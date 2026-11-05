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
import hmac
import tempfile
import uuid

from app.constantes import (PREFS_FALHA_ESTEIRA,
                            PREF_DOC_ANONIMIZADO, chave_objeto,
                            ev_ack, ev_confirma, ev_criada,
                            ev_doc_arquivado, ev_em_transito,
                            ev_recebida, ev_reenvio)
from app.errors import (ErroConflitoIdempotencia, ErroFluxo,  # noqa: F401
                        ErroLimiteDocumento, ErroNaoEncontrado)
from app.repository import Repositorio
from app.schemas.comum import (MAX_DOC_BYTES, TRANSICOES,
                               StatusTramitacao)
from app.schemas.tramitacao import (
    ConfirmacaoCreate, ConfirmacaoOut, ConsultaTramitacaoOut,
    EnvelopeRecebimento, EventoTrilhaOut, RecebimentoOut,
    TramitacaoCreate, TramitacaoOut, VerificacaoOut,
)


def _agora():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _formato_documento_ok(cabeca: bytes) -> bool:
    """Magic bytes do formato documental — executáveis e binários
    arbitrários não entram na esteira. Cobre os formatos do
    corpus (pdf/office/imagem) e texto puro; não é antivírus —
    o parser hostil continua sendo dívida de sandbox própria."""
    if cabeca.startswith((b"%PDF-", b"PK\x03\x04",
                         b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
        return True     # pdf, office(zip), png, jpeg
    if cabeca.startswith((b"MZ", b"\x7fELF", b"#!")):
        return False    # executáveis e scripts
    try:
        cabeca.decode("utf-8")
        return True     # texto puro (txt/md/json do corpus real)
    except UnicodeDecodeError:
        return False


class NoTramitacao:
    """Um nó por órgão; origem e destino são o mesmo serviço em
    papéis diferentes — cada órgão roda a sua instância soberana.

    `assinante`: par Ed25519 + diretório de públicas dos pares
    (app/assinatura.py). Configurado, envelope e ack são
    assinados na emissão e verificados na recepção — fail-closed;
    ausente (dev/teste), o nó não assina nem verifica."""

    def __init__(self, orgao: str, repo: Repositorio,
                 storage=None, storage_anon=None,
                 ttl_reenvio_s: float = 3600, assinante=None):
        self.orgao, self.repo = orgao, repo
        self.storage, self.storage_anon = storage, storage_anon
        self.ttl_reenvio_s = ttl_reenvio_s
        self.assinante = assinante

    def _envelope(self, rec: dict, tid: uuid.UUID) -> EnvelopeRecebimento:
        """Envelope de trânsito — só metadados + hash (T9), com
        `destino` endereçado ao nó e `assinatura` Ed25519 sobre
        todos os campos quando o par de chaves está configurado."""
        env = EnvelopeRecebimento(
            tramitacao_id=tid, origem=rec["origem"],
            destino=rec["destino"],
            caso_cnj=rec["caso_cnj"], modo=rec["modo"],
            hash_documento_sha256=rec["hash_doc"],
            enviado_em=_agora(),
            requer_anonimizacao_lgpd=rec["requer_anonimizacao_lgpd"])
        if self.assinante is not None:
            env = env.model_copy(
                update={"assinatura": self.assinante.assinar(env)})
        return env

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
            rec["hash_cadeia"] = await tx.encadear(
                tid, ev_criada(tid))
            await tx.salvar(rec)
            await tx.idem(origem, c.idempotency_key, tid)
        return self._out(rec)

    async def enviar(self, tid: uuid.UUID,
                     org: str) -> EnvelopeRecebimento:
        rec = await self._carregar(tid)
        self._autorizar(rec, org, "origem", exige_no=True)
        # sem arquivo físico não se tramita: o envelope é só
        # metadados — quem recebe precisa de um hash que de fato
        # aponte para bytes verificados no storage da origem.
        # Valida ANTES de transitar: mutação sempre por último.
        if self.storage is None:
            raise ErroFluxo("armazenamento não configurado")
        if not await self.storage.existe(chave_objeto(tid)):
            raise ErroFluxo(
                "documento não está no storage — faça o upload")
        self._transitar(rec, StatusTramitacao.EM_TRANSITO)
        await self._commit(rec, tid, ev_em_transito(tid))
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
        self._autorizar(rec, org, "origem", exige_no=True)
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
        if not await self.storage.existe(chave_objeto(tid)):
            raise ErroFluxo(
                "documento não está no storage — faça o upload")
        async with self.repo.transacao() as tx:
            self._transitar(rec, StatusTramitacao.CRIADA)
            await tx.encadear(tid, ev_reenvio(tid))
            self._transitar(rec, StatusTramitacao.EM_TRANSITO)
            rec["hash_cadeia"] = await tx.encadear(
                tid, ev_em_transito(tid))
            await tx.salvar(rec)
        return self._envelope(rec, tid)

    async def aplicar_confirmacao(self, tid: uuid.UUID,
                                  conf: ConfirmacaoOut,
                                  org: str) -> TramitacaoOut:
        """O nó da origem RECEBE a decisão — quem a entrega é o
        destino. Qualquer outro (inclusive a própria origem)
        -> 404 opaco."""
        rec = await self._carregar(tid)
        self._autorizar(rec, org, "destino")         # 404 terceiro/origem
        if conf.tramitacao_id != tid:
            raise ErroFluxo("ack refere outra tramitação")
        # ack assinado pelo DESTINO do caso: quando o par de
        # chaves está configurado, a decisão só vale com a
        # assinatura dele — re-entrega ou forja não autoriza.
        if self.assinante is not None and \
                not self.assinante.verificar(rec["destino"], conf):
            raise ErroFluxo("assinatura do ack inválida — "
                            "decisão não é do destino do caso")
        self._transitar(rec, StatusTramitacao(conf.status))
        await self._commit(rec, tid, ev_ack(tid, conf.status))
        return self._out(rec)

    # ---------- destino (Órgão B) ----------
    async def receber(self, envelope, org: str) -> RecebimentoOut:
        """Envelope é só metadados (T9): o hash declarado é a âncora
        que o upload/download vai conferir depois — aqui não há
        bytes para verificar.

        Duplicata de canal (reentrega at-least-once ou reenvio do
        item 1): tid já conhecido => eco idempotente via
        `_eco_recebimento` — não regride estado nem duplica
        trilha.

        A origem declarada É a origem autenticada (o contrato do
        envelope — ADR-0007 — já previa a conferência): quem posta
        é o nó emissor, com o cert mTLS DO REMETENTE, não do
        destino — a rota abaixa em B mas quem fala é A.

        Amarras antes de qualquer consulta ao banco — o 409 é
        uniforme e não vaza existência do tid:
          1) identidade do canal == origem declarada;
          2) `env.destino` == ESTE nó — envelope mal-endereçado
             (ou re-direcionado) não vira registro;
          3) assinatura Ed25519 válida para `env.origem` quando o
             par de chaves está configurado — envelope adulterado
             (qualquer campo) é rejeitado como inválido."""
        env = (envelope if isinstance(envelope, EnvelopeRecebimento)
               else EnvelopeRecebimento(**envelope))
        tid = env.tramitacao_id
        if org != env.origem:
            raise ErroFluxo(
                "identidade autenticada diverge da origem "
                "declarada no envelope")
        if env.destino != self.orgao:
            raise ErroFluxo(
                "envelope não é endereçado a este nó")
        if self.assinante is not None and \
                not self.assinante.verificar(env.origem, env):
            raise ErroFluxo("assinatura do envelope inválida")
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
                tid, ev_recebida(tid))
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
        self._autorizar(rec, org)
        if not hmac.compare_digest(env.hash_documento_sha256,
                                   rec["hash_doc"]):
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

    def _autorizar(self, rec: dict, org: str,
                   papel: str | None = None,
                   exige_no: bool = False) -> None:
        """Autorização ordenada — a SEQUÊNCIA é propriedade de
        segurança: participação (404) → papel (404) → identidade
        do nó (409). Terceiro e participante-com-papel-errado
        recebem o MESMO 404 — existência e papel não viram
        oráculo. Centralizada aqui por mecanismo: antes vivia por
        convenção de escrita e reordenar um call site vazava
        estado a terceiros."""
        self._checar_participacao(rec, org)
        if papel is not None:
            self._checar_papel(rec, org, papel)
        if exige_no and org != self.orgao:
            raise ErroFluxo("identidade autenticada não é este nó")

    async def confirmar(self, payload, org: str) -> ConfirmacaoOut:
        """Destino fecha o caso — a integridade NÃO se amarra ao
        declarado: o nó recomputa SHA-256 dos bytes no PRÓPRIO
        storage e exige que confiram com o hash registrado E com
        o `hash_documento_recebido` declarado. Sem os bytes
        verificados no bucket, confirmar é 409 — "dizer que
        recebeu" não é evidência de recebimento. A verificação
        precede `_transitar` (mesma disciplina do enviar:
        valida antes, muta por último). O ack sai assinado
        quando o par de chaves está configurado."""
        c = (payload if isinstance(payload, ConfirmacaoCreate)
             else ConfirmacaoCreate(**payload))
        rec = await self._carregar(c.tramitacao_id)
        self._autorizar(rec, org, "destino")         # 404 terceiro/origem
        novo = (StatusTramitacao.CONFIRMADA
                if c.decisao.value == "aceita"
                else StatusTramitacao.RECUSADA)
        if not hmac.compare_digest(rec["hash_doc"],
                                  c.hash_documento_recebido):
            raise ErroFluxo("hash declarado difere do recebido")
        if self.storage is None:
            raise ErroFluxo("armazenamento não configurado")
        chave = chave_objeto(c.tramitacao_id)
        if not await self.storage.existe(chave):
            raise ErroFluxo(
                "documento não está no storage do nó — "
                "confirmação exige os bytes verificados")
        h_doc = hashlib.sha256()
        async for parte in self.storage.abrir(chave):
            h_doc.update(parte)
        if not hmac.compare_digest(h_doc.hexdigest(),
                                  rec["hash_doc"]):
            raise ErroFluxo(
                "hash dos bytes em storage diverge do "
                "registrado — transporte adulterado?")
        self._transitar(rec, novo)
        h = await self._commit(
            rec, c.tramitacao_id,
            ev_confirma(c.tramitacao_id, novo))
        out = ConfirmacaoOut(
            tramitacao_id=c.tramitacao_id, status=novo,
            confirmado_em=_agora(), hash_cadeia=h)
        if self.assinante is not None:
            out = out.model_copy(
                update={"assinatura": self.assinante.assinar(out)})
        return out

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
        if rec is None:
            raise ErroNaoEncontrado("tramitação desconhecida")
        self._autorizar(rec, org)
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
                e.startswith(PREF_DOC_ANONIMIZADO) for e in evs),
            anonimizacao_falhou=any(
                e.startswith(PREFS_FALHA_ESTEIRA) for e in evs),
            trilha=[EventoTrilhaOut(**t) for t in trilha])

    async def verificar_trilha(self, ident: str,
                               org: str) -> VerificacaoOut:
        """Rejoga a hash-chain do nó (mesmo `ident` de
        `consultar`, mesma autorização 404→papel→nó). `integro`
        False + `divergencia_seq` aponta a primeira linha
        adulterada — auditoria autônoma, sem confiar no topo
        denormalizado. A cadeia é global por nó: a divergência
        num caso invalida a evidência dos demais."""
        try:
            tid = uuid.UUID(str(ident))
        except (ValueError, AttributeError, TypeError):
            tid = None
        rec = (await self.repo.carregar(tid) if tid is not None
               else await self.repo.por_caso(org, str(ident)))
        if rec is None:
            raise ErroNaoEncontrado("tramitação desconhecida")
        self._autorizar(rec, org)
        v = await self.repo.verificar()
        return VerificacaoOut(**v)

    # ---------- storage físico (T8) ----------
    def _checar_participacao(self, rec: dict, org: str):
        """Isolamento por caso: só origem/destino tocam no doc.
        Terceiro -> 404 (existência não vaza), mesma regra de
        `consultar`. `org` é OBRIGATÓRIO: a identidade vem do
        mTLS na fronteira HTTP; chamadas internas declaram o nó."""
        if org not in (rec["origem"], rec["destino"]):
            raise ErroNaoEncontrado("tramitação desconhecida")

    async def upload_documento(self, tid: uuid.UUID,
                               arquivo, org: str) -> dict:
        """Integridade estrita: a tramitação deve existir e o
        SHA-256 do upload deve bater com o registrado. Stream:
        chunks alimentam o hash e um spool em disco — nunca o
        arquivo inteiro em RAM."""
        rec = await self._carregar(tid)
        self._autorizar(rec, org)             # 404 antes do spool
        # Gate de estado: bytes só sobem onde ainda são
        # necessários — CRIADA (origem arquivando) e RECEBIDA
        # (destino arquivando o que recebeu). EM_TRANSITO já tem
        # o objeto como pré-condição; terminais recusam — upload
        # após CONFIRMADA não passa.
        if rec["status"] not in (StatusTramitacao.CRIADA,
                                StatusTramitacao.RECEBIDA):
            raise ErroFluxo(
                f"upload exige CRIADA ou RECEBIDA, "
                f"estado={rec['status']}")
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
        if not hmac.compare_digest(digest, rec["hash_doc"]):
            raise ErroFluxo("hash do upload difere do registrado")
        # Gate de formato — magic bytes do cabeçalho: executáveis
        # e binários não-documentais não entram na esteira.
        cabeca = tmp.read(512)
        tmp.seek(0)
        if not _formato_documento_ok(cabeca):
            raise ErroFluxo("formato de documento não permitido")
        await self.storage.garantir()
        chave = chave_objeto(tid)
        # Duplicata exige arquivo + evento commitado: o órfão
        # (guardou, tx falhou) NÃO é duplicata — o re-upload repara
        # trilha e outbox sem regravar o binário. Sob corrida dois
        # uploads podem ver arquivado=False e gravar dois eventos —
        # mesma tolerância at-least-once já documentada da esteira.
        arquivado = any(
            t["evento"] == ev_doc_arquivado(tid)
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
            if not hmac.compare_digest(h_st.hexdigest(),
                                       rec["hash_doc"]):
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
                tid, ev_doc_arquivado(tid))
            await tx.salvar(rec)
            if rec["requer_anonimizacao_lgpd"]:
                await tx.outbox(*self._ev_lgpd(rec))
        return {"id_documento": chave, "sha256": digest,
                "tamanho": total}

    async def abrir_documento(self, tid: uuid.UUID,
                              org: str):
        """Devolve iterador async de chunks para StreamingResponse."""
        rec = await self._carregar(tid)
        self._autorizar(rec, org)
        if self.storage is None:
            raise ErroFluxo("armazenamento não configurado")
        if not await self.storage.existe(chave_objeto(tid)):
            raise ErroNaoEncontrado("documento não está no storage")
        return self.storage.abrir(chave_objeto(tid))

    async def abrir_anonimizado(self, tid: uuid.UUID, org: str):
        """Versão sanitizada — bucket `*-docs-anonimizados` do nó
        que rodou a esteira (a origem do documento). Mesma regra
        de isolamento da consulta."""
        rec = await self._carregar(tid)
        self._autorizar(rec, org)             # antes do storage:
        if self.storage_anon is None:         # config não vaza
            raise ErroFluxo("storage anonimizado não configurado")
        if not await self.storage_anon.existe(chave_objeto(tid)):
            raise ErroNaoEncontrado(
                "documento anonimizado não disponível")
        return self.storage_anon.abrir(chave_objeto(tid))

    def _out(self, rec: dict) -> TramitacaoOut:
        return TramitacaoOut(
            id=rec["id"], caso_cnj=rec["caso_cnj"], origem=rec["origem"],
            destino=rec["destino"], modo=rec["modo"],
            status=rec["status"], hash_documento_sha256=rec["hash_doc"],
            criado_em=rec["criado_em"],
            atualizado_em=rec["atualizado_em"],
            hash_cadeia=rec["hash_cadeia"])
