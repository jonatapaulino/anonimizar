"""Barramento de eventos — handoff assíncrono para a esteira de IA.

Contrato do PublicadorEventos: `publicar` ENFILEIRA, nunca
processa. O NER/anonymizer vive no consumidor, fora do caminho
HTTP — a latência do endpoint não paga o custo da IA por
construção, não por disciplina.

Regra de emissão (NoTramitacao): o evento só sai DEPOIS do commit
da transação (post-commit hook). Rollback => nada publicado —
o consumidor nunca vê evento de um estado que não existe.

O evento carrega SÓ identificadores — documento e PII nunca
viajam no barramento (a esteira busca pelo id no nó soberano).
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol

log = logging.getLogger("tramitacao.eventos")


@dataclass(frozen=True)
class DocumentoProntoParaAnonimizacao:
    """Documento persistido aguardando anonimização LGPD."""
    id_documento: uuid.UUID
    orgao_origem: str
    id_processo: str                       # caso_cnj — escopo HMAC
    emitido_em: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
    evento: str = "DocumentoProntoParaAnonimizacao"


class PublicadorEventos(Protocol):
    """Interface do barramento — implementações devem ser
    O(1)/não-bloqueantes: enfileirar, jamais executar o trabalho."""
    async def publicar(self, evento) -> None: ...


class PublicadorMemoria:
    """Testes: guarda os eventos emitidos para asserção."""
    def __init__(self):
        self.eventos: list = []

    async def publicar(self, evento) -> None:
        self.eventos.append(evento)


class PublicadorLog:
    """Dev local: log estruturado simulando o envio à fila."""
    async def publicar(self, evento) -> None:
        log.info("evento_publicado tipo=%s id_documento=%s "
                 "orgao_origem=%s id_processo=%s",
                 getattr(evento, "evento", type(evento).__name__),
                 getattr(evento, "id_documento", None),
                 getattr(evento, "orgao_origem", None),
                 getattr(evento, "id_processo", None))


class PublicadorRabbitMQ:
    """Adaptador AMQP (aio-pika) — ADR-0013.

    - canal com publisher_confirms: `publish` retorna só após o
      ACK do broker e levanta em nack/timeout — o relay usa isso
      para marcar PROCESSADO só depois do ACK
    - exchange topic `tramitacao`, fila quorum durável, mensagens
      persistentes
    - T12: fila com delivery-limit + DLX — poison messages (PDF
      corrompido, LLM irrecuperável) saem do fluxo após N
      entregas falhas e estacionam em `ia.anonimizacao.dlq`
    """
    EXCHANGE = "tramitacao"
    RK_ANON = "documento.anonimizacao"
    FILA_ANON = "ia.anonimizacao"
    FILA_DLQ = "ia.anonimizacao.dlq"
    EXCHANGE_DLX = "tramitacao.dlx"
    MAX_ENTREGAS = 3
    # quorum obrigatório p/ delivery-limit; args de declare têm
    # que ser IDÊNTICOS em publicador e worker — daí o helper
    # compartilhado abaixo (broker recusa redeclare divergente)
    ARGS_FILA_ANON = {
        "x-queue-type": "quorum",
        "x-delivery-limit": MAX_ENTREGAS,
        "x-dead-letter-exchange": EXCHANGE_DLX,
        "x-dead-letter-routing-key": FILA_DLQ,
    }

    def __init__(self, url: str):
        self.url = url
        self._conn = self._ex = None

    async def conectar(self):
        import aio_pika
        self._conn = await aio_pika.connect_robust(self.url)
        ch = await self._conn.channel(publisher_confirms=True)
        self._ex, _, _ = await declarar_topologia_ia(ch)

    async def publicar(self, evento) -> None:
        """evento: dict (payload da linha outbox) ou dataclass."""
        import aio_pika
        body = evento if isinstance(evento, dict) else asdict(evento)
        msg = aio_pika.Message(
            json.dumps(body, default=str).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
            message_id=str(body.get("id_documento")))
        await self._ex.publish(msg, routing_key=self.RK_ANON)

    async def fechar(self):
        if self._conn:
            await self._conn.close()


async def declarar_topologia_ia(ch):
    """Exchange topic + fila quorum (delivery-limit + DLX) + DLQ —
    declaração idempotente ÚNICA, usada por PublicadorRabbitMQ e
    pelo worker. Se as duas pontas declarassem cada uma a sua
    versão, divergência de args derrubaria o canal (broker exige
    redeclare idêntico). Retorna (exchange, fila, dlq)."""
    import aio_pika
    P = PublicadorRabbitMQ
    ex = await ch.declare_exchange(
        P.EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    dlx = await ch.declare_exchange(
        P.EXCHANGE_DLX, aio_pika.ExchangeType.DIRECT, durable=True)
    q = await ch.declare_queue(
        P.FILA_ANON, durable=True, arguments=P.ARGS_FILA_ANON)
    await q.bind(ex, routing_key=P.RK_ANON)
    dlq = await ch.declare_queue(P.FILA_DLQ, durable=True)
    await dlq.bind(dlx, routing_key=P.FILA_DLQ)
    return ex, q, dlq
