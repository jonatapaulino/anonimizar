"""Serviço de tramitação — lógica do nó edge (MVP, async + repo).

Estado via Repositorio injetado (app/repository.py) — Postgres em
produção, sqlite em teste; a interface é a mesma. Escritas de
status + trilha acontecem dentro de `transacao()` = atômicas.

T9 — separação de payload: o binário NUNCA passa pelo banco nem
pelo envelope. Fluxo: criar (metadados + hash declarado) →
upload multipart → hash conferido → arquivo no object storage do
órgão → SÓ ENTÃO o evento de IA entra na outbox. `enviar` exige
o arquivo físico presente — não se tramita o que não existe.
"""
import hashlib
import tempfile
import uuid

from app.errors import (ErroConflitoIdempotencia, ErroFluxo,  # noqa: F401
                        ErroLimiteDocumento, ErroNaoEncontrado)
from app.repository import Repositorio
from app.schemas.comum import (MAX_DOC_BYTES, TRANSICOES,
                               StatusTramitacao)
from app.schemas.tramitacao import (
    ConfirmacaoCreate, ConfirmacaoOut, ConsultaTramitacaoOut,
    EnvelopeRecebimento, EventoTrilhaOut, RecebimentoOut,
    TramitacaoCreate, TramitacaoOut,
)


def _agora():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


class NoTramitacao:
    """Um nó por órgão; origem e destino são o mesmo serviço em
    papéis diferentes — cada órgão roda a sua instância soberana."""

    def __init__(self, orgao: str, repo: Repositorio,
                 storage=None, storage_anon=None,
                 ttl_reenvio_s: float = 3600):
        self.orgao, self.repo = orgao, repo
        self.storage, self.storage_anon = storage, storage_anon
        self.ttl_reenvio_s = ttl_reenvio_s

    @staticmethod
    def _envelope(rec: dict, tid: uuid.UUID) -> EnvelopeRecebimento:
        """Envelope de trânsito — só metadados + hash (T9)."""
        return EnvelopeRecebimento(
            tramitacao_id=tid, origem=rec["origem"],
            caso_cnj=rec["caso_cnj"], modo=rec["modo"],
            hash_documento_sha256=rec["hash_doc"],
            enviado_em=_agora(),
            requer_anonimizacao_lgpd=rec["requer_anonimizacao_lgpd"])

    @staticmethod
    def _ev_lgpd(rec: dict) -> tuple[str, dict]:
        """Payload do evento — só ids (documento/PII nunca saem
        no barramento; a esteira busca pelo id no nó soberano)."""
        return ("DocumentoProntoParaAnonimizacao", dict(
            id_documento=str(rec["id"]), orgao_origem=rec["origem"],
            id_processo=rec["caso_cnj"]))

    def _transitar(self, rec: dict, novo: StatusTramitacao):
        if novo not in TRANSICOES[rec["status"]]:
            raise ErroFluxo(
                f"transição ilegal: {rec['status']} -> {novo}")
        rec["status"] = novo
        rec["atualizado_em"] = _agora()

    async def _commit(self, rec, tid, evento) -> str:
        """status + trilha numa única tx."""
        async with self.repo.transacao() as tx:
            await tx.salvar(rec)
            h = await tx.encadear(tid, evento)
            rec["hash_cadeia"] = h
            await tx.salvar(rec)
        return h

    async def _carregar(self, tid: uuid.UUID) -> dict:
        rec = await self.repo.carregar(tid)
        if rec is None:
            raise ErroNaoEncontrado("tramitação desconhecida")
        return rec

    # ---------- origem (Órgão A) ----------
    async def criar(self, payload, origem: str | None = None
                    ) -> TramitacaoOut:
        origem = origem or self.orgao
        if origem != self.orgao:
            raise ErroFluxo("identidade autenticada não é este nó")
        c = (payload if isinstance(payload, TramitacaoCreate)
             else TramitacaoCreate(**payload))
        tid_ant = await self.repo.tid_por_idem(
            origem, c.idempotency_key)
        if tid_ant:
            return await self.obter(tid_ant)
        tid = uuid.uuid4()
        rec = dict(
            id=tid, caso_cnj=c.caso_cnj, origem=origem,
            destino=c.destino, modo=c.modo,
            status=StatusTramitacao.CRIADA,
            hash_doc=c.hash_documento_sha256,   # declarado — o
            hash_cadeia="", metadados=c.metadados,  # upload prova
            requer_anonimizacao_lgpd=c.requer_anonimizacao_lgpd,
            criado_em=_agora(), atualizado_em=_agora())
        async with self.repo.transacao() as tx:
            await tx.salvar(rec)
            rec["hash_cadeia"] = await tx.encadear(tid, f"criada:{tid}")
            await tx.salvar(rec)
            await tx.idem(origem, c.idempotency_key, tid)
        return self._out(rec)

    async def enviar(self, tid: uuid.UUID,
                     org: str) -> EnvelopeRecebimento:
        rec = await self._carregar(tid)
        self._checar_participacao(rec, org)          # 404 terceiro
        self._checar_papel(rec, org, "origem")       # 404 destino
        if org != self.orgao:
            raise ErroFluxo("identidade autenticada não é este nó")
        self._transitar(rec, StatusTramitacao.EM_TRANSITO)
        # sem arquivo físico não se tramita: o envelope é só
        # metadados — quem recebe precisa de um hash que de fato
        # aponte para bytes verificados no storage da origem
        if self.storage is None:
            raise ErroFluxo("armazenamento não configurado")
        if not await self.storage.existe(str(tid)):
            raise ErroFluxo(
                "documento não está no storage — faça o upload")
        await self._commit(rec, tid, f"em_transito:{tid}")
        return self._envelope(rec, tid)

    async def reenviar(self, tid: uuid.UUID,
                       org: str) -> EnvelopeRecebimento:
        """Reemissão do envelope — reconciliação da perda A->B.

        Só de EM_TRANSITO e só depois de `ttl_reenvio_s` desde a
        última transição (checagem passiva — sem sweeper). Usa a
        aresta já declarada EM_TRANSITO->CRIADA ("reenvio") e
        reemite por CRIADA->EM_TRANSITO numa única tx: duas linhas
        honestas na trilha, estado final inalterado — reenvio é
        reemissão de mensagem, não mudança de fase. Idempotente
        por construção: o envelope é rederivado do registro."""
        rec = await self._carregar(tid)
        self._checar_participacao(rec, org)          # 404 terceiro
        self._checar_papel(rec, org, "origem")       # 404 destino
        if org != self.orgao:
            raise ErroFluxo("identidade autenticada não é este nó")
        if rec["status"] is not StatusTramitacao.EM_TRANSITO:
            raise ErroFluxo(
                f"reenvio exige EM_TRANSITO, estado={rec['status']}")
        atu = rec["atualizado_em"]
        if atu.tzinfo is None:              # sqlite devolve naive
            from datetime import timezone
            atu = atu.replace(tzinfo=timezone.utc)
        decorrido = (_agora() - atu).total_seconds()
        if decorrido < self.ttl_reenvio_s:
            raise ErroFluxo(
                f"reenvio exige {self.ttl_reenvio_s}s em "
                f"EM_TRANSITO (decorridos {decorrido:.0f}s)")
        if self.storage is None:
            raise ErroFluxo("armazenamento não configurado")
        if not await self.storage.existe(str(tid)):
            raise ErroFluxo(
                "documento não está no storage — faça o upload")
        async with self.repo.transacao() as tx:
            self._transitar(rec, StatusTramitacao.CRIADA)
            await tx.encadear(tid, f"reenvio:{tid}")
            self._transitar(rec, StatusTramitacao.EM_TRANSITO)
            rec["hash_cadeia"] = await tx.encadear(
                tid, f"em_transito:{tid}")
            await tx.salvar(rec)
        return self._envelope(rec, tid)

    async def aplicar_confirmacao(self, tid: uuid.UUID,
                                  conf: ConfirmacaoOut,
                                  org: str) -> TramitacaoOut:
        """O nó da origem RECEBE a decisão — quem a entrega é o
        destino. Qualquer outro (inclusive a própria origem)
        -> 404 opaco."""
        rec = await self._carregar(tid)
        self._checar_participacao(rec, org)          # 404 terceiro
        self._checar_papel(rec, org, "destino")      # 404 origem
        if conf.tramitacao_id != tid:
            raise ErroFluxo("ack refere outra tramitação")
        self._transitar(rec, StatusTramitacao(conf.status))
        await self._commit(rec, tid, f"conf:{tid}:{conf.status}")
        return self._out(rec)

    # ---------- destino (Órgão B) ----------
    async def receber(self, envelope, org: str) -> RecebimentoOut:
        """Envelope é só metadados (T9): o hash declarado é a âncora
        que o upload/download vai conferir depois — aqui não há
        bytes para verificar.

        Duplicata de canal (reentrega at-least-once ou reenvio do
        item 1): tid já conhecido => eco idempotente via
        `_eco_recebimento` — não regride estado nem duplica
        trilha."""
        env = (envelope if isinstance(envelope, EnvelopeRecebimento)
               else EnvelopeRecebimento(**envelope))
        tid = env.tramitacao_id
        ant = await self.repo.carregar(tid)
        if ant is not None:
            return self._eco_recebimento(ant, env, org)
        rec = dict(
            id=tid, caso_cnj=env.caso_cnj, origem=env.origem,
            destino=self.orgao, modo=env.modo,
            status=StatusTramitacao.RECEBIDA,
            hash_doc=env.hash_documento_sha256, hash_cadeia="",
            metadados={},
            requer_anonimizacao_lgpd=env.requer_anonimizacao_lgpd,
            criado_em=_agora(), atualizado_em=_agora())
        async with self.repo.transacao() as tx:
            await tx.salvar(rec)
            rec["hash_cadeia"] = await tx.encadear(
                tid, f"recebida:{tid}")
            await tx.salvar(rec)
        return RecebimentoOut(
            tramitacao_id=tid, recebido=True,
            status=StatusTramitacao.RECEBIDA,
            recebido_em=_agora(),
            motivo=None, hash_cadeia=rec["hash_cadeia"])

    def _eco_recebimento(self, rec: dict, env,
                         org: str) -> RecebimentoOut:
        """Resposta mínima à reentrega de envelope conhecido.

        Campos no eco e por que cada um sai:
          tramitacao_id — correlação com o pedido; é o id que o
            chamador mesmo apresentou (nada novo revelado);
          recebido=True — a resposta semântica do endpoint;
          status — permite à origem descobrir o estado terminal
            (CONFIRMADA/RECUSADA) após reenvio — é a reconciliação;
          recebido_em — o instante real do PRIMEIRO ingresso:
            distingue eco de recebimento novo e já é visível a
            participantes via GET /v1/tramitacoes/{id}.
        Fora do eco: motivo (inaplicável) e hash_cadeia (prova
        interna da trilha — não é insumo do chamador). Terceiro
        recebe 404 antes de qualquer resposta: o eco não vira
        oráculo de existência/status para quem não participa."""
        self._checar_participacao(rec, org)
        if env.hash_documento_sha256 != rec["hash_doc"]:
            raise ErroFluxo(
                "envelope diverge da tramitação registrada")
        return RecebimentoOut(
            tramitacao_id=rec["id"], recebido=True,
            status=rec["status"], recebido_em=rec["criado_em"],
            motivo=None, hash_cadeia=None)

    def _checar_papel(self, rec: dict, org: str, papel: str):
        """Papel exigido (origem/destino): qualquer outro — mesmo
        participante com papel errado — recebe o MESMO 404 opaco
        do terceiro. Papel não vira oráculo."""
        if org != rec[papel]:
            raise ErroNaoEncontrado("tramitação desconhecida")

    async def confirmar(self, payload, org: str) -> ConfirmacaoOut:
        c = (payload if isinstance(payload, ConfirmacaoCreate)
             else ConfirmacaoCreate(**payload))
        rec = await self._carregar(c.tramitacao_id)
        self._checar_participacao(rec, org)          # 404 terceiro
        self._checar_papel(rec, org, "destino")      # 404 origem
        if rec["status"] is not StatusTramitacao.RECEBIDA:
            raise ErroFluxo(
                f"confirmação exige RECEBIDA, estado={rec['status']}")
        if c.hash_documento_recebido != rec["hash_doc"]:
            raise ErroFluxo("hash declarado difere do recebido")
        novo = (StatusTramitacao.CONFIRMADA
                if c.decisao.value == "aceita"
                else StatusTramitacao.RECUSADA)
        self._transitar(rec, novo)
        h = await self._commit(
            rec, c.tramitacao_id,
            f"confirma:{c.tramitacao_id}:{novo}")
        return ConfirmacaoOut(
            tramitacao_id=c.tramitacao_id, status=novo,
            confirmado_em=_agora(), hash_cadeia=h)

    async def obter(self, tid: uuid.UUID) -> TramitacaoOut:
        return self._out(await self._carregar(tid))

    # ---------- consulta (T12) ----------
    async def consultar(self, ident: str,
                        org: str) -> ConsultaTramitacaoOut:
        """Uma rota, dois identificadores: `ident` parseando como
        UUID busca por id; caso contrário é id_processo (CNJ).
        Isolamento: só origem/destino enxergam — terceiro leva 404
        (não revela nem a existência do caso)."""
        try:
            tid = uuid.UUID(str(ident))
        except (ValueError, AttributeError, TypeError):
            tid = None
        rec = (await self.repo.carregar(tid) if tid is not None
               else await self.repo.por_caso(org, str(ident)))
        if rec is None or org not in (rec["origem"], rec["destino"]):
            raise ErroNaoEncontrado("tramitação desconhecida")
        trilha = await self.repo.trilha(rec["id"])
        evs = [t["evento"] for t in trilha]
        return ConsultaTramitacaoOut(
            id=rec["id"], caso_cnj=rec["caso_cnj"],
            origem=rec["origem"], destino=rec["destino"],
            modo=rec["modo"], status=rec["status"],
            hash_documento_sha256=rec["hash_doc"],
            criado_em=rec["criado_em"],
            atualizado_em=rec["atualizado_em"],
            hash_cadeia=rec["hash_cadeia"],
            metadados=rec["metadados"],
            requer_anonimizacao_lgpd=rec["requer_anonimizacao_lgpd"],
            anonimizacao_concluida=any(
                e.startswith("doc_anonimizado:") for e in evs),
            anonimizacao_falhou=any(
                e.startswith(("falha_anonimizacao:",
                              "falha_outbox:")) for e in evs),
            trilha=[EventoTrilhaOut(**t) for t in trilha])

    # ---------- storage físico (T8) ----------
    def _checar_participacao(self, rec: dict, org: str):
        """Isolamento por caso: só origem/destino tocam no doc.
        Terceiro -> 404 (existência não vaza), mesma regra de
        `consultar`. `org` é OBRIGATÓRIO: a identidade vem do
        JWT na fronteira HTTP; chamadas internas declaram o nó."""
        if org not in (rec["origem"], rec["destino"]):
            raise ErroNaoEncontrado("tramitação desconhecida")

    async def upload_documento(self, tid: uuid.UUID,
                               arquivo, org: str) -> dict:
        """Integridade estrita: a tramitação deve existir e o
        SHA-256 do upload deve bater com o registrado. Stream:
        chunks alimentam o hash e um spool em disco — nunca o
        arquivo inteiro em RAM."""
        rec = await self._carregar(tid)
        self._checar_participacao(rec, org)   # 404 antes do spool
        if self.storage is None:
            raise ErroFluxo("armazenamento não configurado")
        h = hashlib.sha256()
        tmp = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        total = 0
        while chunk := await arquivo.read(64 * 1024):
            total += len(chunk)
            if total > MAX_DOC_BYTES:      # 413 — corta o stream
                raise ErroLimiteDocumento( # antes de spoolar tudo
                    "documento excede o limite de tamanho")
            h.update(chunk)
            tmp.write(chunk)
        tmp.seek(0)
        digest = h.hexdigest()
        if digest != rec["hash_doc"]:
            raise ErroFluxo("hash do upload difere do registrado")
        await self.storage.garantir()
        chave = str(tid)
        # Duplicata exige arquivo + evento commitado: o órfão
        # (guardou, tx falhou) NÃO é duplicata — o re-upload repara
        # trilha e outbox sem regravar o binário. Sob corrida dois
        # uploads podem ver arquivado=False e gravar dois eventos —
        # mesma tolerância at-least-once já documentada da esteira.
        arquivado = any(
            t["evento"] == f"doc_arquivado:{tid}"
            for t in await self.repo.trilha(tid))
        if await self.storage.existe(chave):
            if arquivado:
                return {"id_documento": chave, "sha256": digest,
                        "tamanho": total, "duplicado": True}
            # órfão: re-hash dos bytes guardados — se divergirem da
            # declaração é anomalia (storage corrompido/adulterado);
            # não se escreve doc_arquivado sobre bytes errados
            h_st = hashlib.sha256()
            async for c in self.storage.abrir(chave):
                h_st.update(c)
            if h_st.hexdigest() != rec["hash_doc"]:
                raise ErroFluxo(
                    "objeto em storage diverge do declarado")
        else:
            await self.storage.guardar(chave, tmp)
        # Evento de IA SÓ depois do arquivo existir fisicamente
        # (T9): trilha + outbox numa tx — se falhar, o arquivo
        # fica órfão no storage, mas o re-upload o repara (a IA
        # jamais é notificada de um documento que não pôde ser
        # marcado).
        rec["atualizado_em"] = _agora()
        async with self.repo.transacao() as tx:
            rec["hash_cadeia"] = await tx.encadear(
                tid, f"doc_arquivado:{tid}")
            await tx.salvar(rec)
            if rec["requer_anonimizacao_lgpd"]:
                await tx.outbox(*self._ev_lgpd(rec))
        return {"id_documento": chave, "sha256": digest,
                "tamanho": total}

    async def abrir_documento(self, tid: uuid.UUID,
                              org: str):
        """Devolve iterador async de chunks para StreamingResponse."""
        rec = await self._carregar(tid)
        self._checar_participacao(rec, org)
        if self.storage is None:
            raise ErroFluxo("armazenamento não configurado")
        if not await self.storage.existe(str(tid)):
            raise ErroNaoEncontrado("documento não está no storage")
        return self.storage.abrir(str(tid))

    async def abrir_anonimizado(self, tid: uuid.UUID, org: str):
        """Versão sanitizada — bucket `*-docs-anonimizados` do nó
        que rodou a esteira (a origem do documento). Mesma regra
        de isolamento da consulta."""
        rec = await self._carregar(tid)
        self._checar_participacao(rec, org)   # antes do storage:
        if self.storage_anon is None:         # config não vaza
            raise ErroFluxo("storage anonimizado não configurado")
        if not await self.storage_anon.existe(str(tid)):
            raise ErroNaoEncontrado(
                "documento anonimizado não disponível")
        return self.storage_anon.abrir(str(tid))

    def _out(self, rec: dict) -> TramitacaoOut:
        return TramitacaoOut(
            id=rec["id"], caso_cnj=rec["caso_cnj"], origem=rec["origem"],
            destino=rec["destino"], modo=rec["modo"],
            status=rec["status"], hash_documento_sha256=rec["hash_doc"],
            criado_em=rec["criado_em"],
            atualizado_em=rec["atualizado_em"],
            hash_cadeia=rec["hash_cadeia"])
