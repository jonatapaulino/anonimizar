"""Worker da esteira de IA — processo consumidor independente
(`python -m app.worker`, sem HTTP).

Consome `ia.anonimizacao` (fila durável, declarada pelo
PublicadorRabbitMQ — ADR-0013). Pipeline por mensagem:

  payload {id_documento, orgao_origem, id_processo}
    → download de <org>-docs        (MinIO do órgão de origem)
    → MotorIA.anonimizar(bytes)
    → upload em <org>-docs-anonimizados
    → ACK   (só aqui — sucesso completo)
    qualquer falha → NACK + requeue (a mensagem volta à fila)

At-least-once no lado consumidor espelha o relay no produtor.
Idempotente por construção: a chave de destino é o próprio
id_documento — reprocessar reescreve o mesmo objeto, sem efeito
colateral adicional.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os

from app.events import PublicadorRabbitMQ, declarar_topologia_ia
from app.storage import ArmazenamentoMinIO, bucket_para

log = logging.getLogger("tramitacao.worker")

NOME_BRUTOS = "docs"
NOME_ANONIMIZADOS = "docs-anonimizados"


class StubMotorIA:
    """Stub do modelo NER/anonimização — a interface (async,
    bytes -> bytes) é a definitiva; trocar pelo modelo real não
    toca o worker. `chamados` registra invocações p/ teste."""
    def __init__(self, atraso: float = 1.0):
        self.atraso = atraso
        self.chamados: list[int] = []

    async def anonimizar(self, conteudo: bytes) -> bytes:
        self.chamados.append(len(conteudo))
        await asyncio.sleep(self.atraso)
        log.info("documento simulado anonimizado (%d bytes)",
                 len(conteudo))
        return conteudo


class DemoMotorIA(StubMotorIA):
    """Motor determinístico de demonstração (IA_ENGINE=demo):
    anonimização real, mas local — regex de formatos LGPD (CPF,
    e-mail, telefone) e valores após rótulos usuais de petição
    (Outorgante:, Requerente:...). Zero tokens, mesma saída
    sempre — é um stand-in do NER, não o modelo."""
    TAG = "[ANONIMIZADO_LGPD]"
    PADROES = (
        r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",                    # CPF
        r"\b[\w.+-]+@[\w-]+\.[\w.]+\b",                     # e-mail
        r"\(?\d{2}\)?\s?9?\d{4}-\d{4}\b",                   # telefone
        r"(?im)(?<=: )[^\n,]+(?=,?\s*(?:cpf|rg)\b)",        # nome: rotulo
    )

    async def anonimizar(self, conteudo: bytes) -> bytes:
        import re
        await asyncio.sleep(self.atraso)
        txt = conteudo.decode("utf-8", errors="replace")
        for p in self.PADROES:
            txt = re.sub(p, self.TAG, txt)
        log.info("demo: %d bytes anonimizados (regex LGPD)",
                 len(conteudo))
        return txt.encode()


def motor_de_env():
    """IA_ENGINE=stub (padrão, zero tokens) | demo (regex LGPD
    local) | langchain (LLM real via app/motor_langchain.py) |
    ollama (LLM local soberano via app/motor_ollama.py)."""
    engine = os.environ.get("IA_ENGINE", "stub")
    if engine == "langchain":
        from app.motor_langchain import LangChainMotorIA
        return LangChainMotorIA.de_env()
    if engine == "ollama":
        from app.motor_ollama import MotorOllama
        return MotorOllama.de_env()
    if engine == "demo":
        return DemoMotorIA(atraso=0.5)
    return StubMotorIA()


class FabricaStorages:
    """Cache de pares de storage por órgão — um client S3 por
    bucket, reutilizado entre mensagens. `fazer(orgao, bucket)`
    é injetável: produção passa MinIO, testes passam memória."""
    def __init__(self, fazer):
        self._fazer = fazer
        self._cache: dict[str, tuple] = {}

    async def par(self, orgao: str):
        if orgao not in self._cache:
            o = self._fazer(orgao, bucket_para(orgao, NOME_BRUTOS))
            d = self._fazer(orgao, bucket_para(orgao,
                                               NOME_ANONIMIZADOS))
            await o.garantir()
            await d.garantir()
            self._cache[orgao] = (o, d)
        return self._cache[orgao]

    async def fechar(self):
        for o, d in self._cache.values():
            await o.fechar()
            await d.fechar()
        self._cache.clear()


def fabrica_minio(endpoint: str, user: str, pw: str):
    return lambda orgao, bucket: ArmazenamentoMinIO(
        orgao, endpoint, user, pw, nome_bucket=bucket)


async def processar_evento(payload: dict, st_origem, st_dest,
                           motor, repo=None) -> str:
    """Um evento -> download, IA, upload e FEEDBACK: grava
    `doc_anonimizado:{id}` na trilha (hash-chain) da tramitação —
    o ciclo se fecha observável no banco do nó. Levanta em
    qualquer falha — o chamador decide ack/nack."""
    import uuid as _uuid
    from app import metricas, pii_residual
    doc = payload["id_documento"]
    dados = b"".join([c async for c in st_origem.abrir(doc)])
    anonimizado = await motor.anonimizar(dados)
    m = metricas.medir(doc, dados, anonimizado)
    if m.get("saida_legivel") is False:
        # saída ilegível NÃO é anonimizado — falha determinística
        # (reprocessar corrompe igual): ACK + falha na trilha,
        # sem requeue/DLQ. doc_anonimizado seria registro falso.
        if repo is not None:
            async with repo.transacao() as tx:
                await tx.encadear(
                    _uuid.UUID(doc),
                    f"falha_anonimizacao:{doc}:saida_ilegivel")
        log.warning("worker: %s saída ilegível — "
                    "falha_anonimizacao (sem retry)", doc)
        return doc
    # gate de residual (POC): PII ainda visível na saída NÃO vai
    # para o bucket anonimizado — falha determinística na trilha.
    # O log carrega contagens por tipo, nunca os valores.
    total_res, por_tipo = pii_residual.residuo_bytes(anonimizado)
    if total_res:
        if repo is not None:
            async with repo.transacao() as tx:
                await tx.encadear(
                    _uuid.UUID(doc),
                    f"falha_anonimizacao:{doc}:residual_pii")
        log.warning("worker: %s residual_pii %s — "
                    "falha_anonimizacao (sem retry)", doc, por_tipo)
        return doc
    await st_dest.guardar(doc, io.BytesIO(anonimizado))
    if repo is not None:
        async with repo.transacao() as tx:
            await tx.encadear(_uuid.UUID(doc),
                              f"doc_anonimizado:{doc}")
    log.info("worker: %s anonimizado (%d bytes) de %s",
             doc, len(anonimizado), payload.get("orgao_origem"))
    return doc


async def processar_mensagem(m, fabrica: FabricaStorages,
                             motor, repo=None) -> None:
    """ack/nack em torno do pipeline — usado pelo loop infinito
    e pelo ciclo único dos testes."""
    payload = json.loads(m.body)
    st_org, st_dest = await fabrica.par(payload["orgao_origem"])
    await processar_evento(payload, st_org, st_dest, motor, repo)


async def um_ciclo(queue, fabrica: FabricaStorages, motor,
                  repo=None) -> bool:
    """Consome UMA mensagem (gancho de teste). ACK no sucesso;
    NACK+requeue na falha. Retorna False se a fila estava vazia."""
    m = await queue.get(fail=False)
    if m is None:
        return False
    try:
        await processar_mensagem(m, fabrica, motor, repo)
    except Exception as e:
        log.warning("worker: falha no ciclo (%s) — nack/requeue",
                    e)
        await m.nack(requeue=True)
        raise
    await m.ack()
    return True


# ---------- DLQ (T12) ----------
async def registrar_falha(payload: dict, repo) -> None:
    """Mensagem morta: grava `falha_anonimizacao:{id}` na trilha —
    o incidente fica auditável no nó, não só numa fila escura."""
    import uuid as _uuid
    doc = payload["id_documento"]
    async with repo.transacao() as tx:
        await tx.encadear(_uuid.UUID(doc),
                          f"falha_anonimizacao:{doc}")


async def um_ciclo_dlq(dlq, repo) -> bool:
    """Drena UMA mensagem morta → trilha → ACK. Falha na gravação
    (ex.: tramitação inexistente — FK): NACK sem requeue — a DLQ
    não pode virar ela mesma um hot-loop de poison."""
    m = await dlq.get(fail=False)
    if m is None:
        return False
    payload = json.loads(m.body)
    try:
        await registrar_falha(payload, repo)
    except Exception as e:
        log.error("dlq: não registrou trilha p/ %s (%s) — drop",
                  payload.get("id_documento"), e)
        await m.nack(requeue=False)
        raise
    await m.ack()
    log.warning("dlq: falha_anonimizacao registrada p/ %s",
                payload.get("id_documento"))
    return True


async def main():
    import aio_pika
    url_amqp = os.environ.get("RABBITMQ_URL")
    if not url_amqp:
        raise SystemExit("RABBITMQ_URL não definida")
    url_minio = os.environ.get("MINIO_URL")
    if not url_minio:
        raise SystemExit("MINIO_URL não definida")

    conn = await aio_pika.connect_robust(url_amqp)
    ch = await conn.channel()
    await ch.set_qos(prefetch_count=1)     # uma mensagem por vez
    _, queue, dlq = await declarar_topologia_ia(ch)

    fabrica = FabricaStorages(fabrica_minio(
        url_minio,
        os.environ.get("MINIO_USER", "edvar"),
        os.environ.get("MINIO_PASS", "")))
    motor = motor_de_env()                      # IA_ENGINE
    # feedback: trilha no banco do nó — opcional p/ dev sem DB
    repo = None
    url_db = os.environ.get("DATABASE_URL")
    if url_db:
        from app.repository import repo_from_url
        repo = repo_from_url(url_db)
    else:
        log.warning("worker: DATABASE_URL ausente — sem trilha")

    async def _drenar_dlq():
        """Mensagens mortas pela delivery-limit: registra a falha
        na trilha e ACKa. Não derruba o processo em hipótese
        alguma — invariante do DoD."""
        async with dlq.iterator() as it:
            async for m in it:
                try:
                    await registrar_falha(json.loads(m.body), repo)
                    await m.ack()
                    log.warning("dlq: falha_anonimizacao -> %s",
                                json.loads(m.body)["id_documento"])
                except Exception as e:
                    log.error("dlq: %s — drop (sem requeue)", e)
                    await m.nack(requeue=False)

    task_dlq = (asyncio.create_task(_drenar_dlq())
                if repo is not None else None)
    if task_dlq is None:
        log.warning("worker: sem repo — DLQ acumula p/ inspeção")
    log.info("worker: escutando %s (prefetch=1, DLX ativo)",
             queue.name)
    try:
        async with queue.iterator() as it:
            async for m in it:
                try:
                    await processar_mensagem(m, fabrica, motor,
                                             repo)
                    await m.ack()
                except Exception as e:
                    log.warning("worker: %s — nack/requeue", e)
                    await m.nack(requeue=True)
    finally:
        if task_dlq is not None:
            task_dlq.cancel()
        await fabrica.fechar()
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
