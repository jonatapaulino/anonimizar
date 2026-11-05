"""Endurecimento B/C — a camada de custódia criptográfica e os
gates físicos, cada um provado onde ele morre.

Camadas testadas aqui (ordem das fronteiras):

  1) Assinatura Ed25519 — envelope e ack carregam prova do
     emissor: campo adulterado, assinatura ausente, chave errada
     ou signatário diverso da origem declarada => 409 no INGRESSO,
     antes do banco. Fail-closed onde o par de chaves existe.
  2) `destino` endereçado — envelope para outro nó não vira
     registro aqui (mal-endereçado != mal-autenticado).
  3) Confirmação verificável — B só confirma recomputando o
     SHA-256 dos bytes no SEU storage; declarar não prova.
  4) Upload com estado + formato — bytes só sobem em CRIADA/
     RECEBIDA; magic bytes barra executáveis/scripts.
  5) Replay compartilhado — `replay_nonces` no Postgres: o nonce
     de um quadro válido só entra UMA vez, em qualquer réplica.
  6) Ingresso E2E streaming — multi-quadro e corpos grandes sem
     materialização; `x-e2e-ct` é allowlist.
  7) Verificação autônoma da hash-chain — linha adulterada no
     banco é detectada pelo replay elo a elo, não pelo topo.
  8) Fail-closed de operação — worker sem IA_ENGINE/DATABASE_URL,
     Vault sem credencial, identidade malformada e segredo de
     borda divergente não sobem/atuam.
"""
import hashlib
import io
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.cofre import FonteVaultKV, fonte_de_env
from app.crypto_e2e import (CT_E2E, ErroCripto, FluxoSelador,
                            abrir, selar)
from app.errors import ErroNaoEncontrado
from app.main import create_app
from app.schemas.comum import StatusTramitacao
from app.schemas.tramitacao import (ConfirmacaoOut,
                                    EnvelopeRecebimento)
from app.service import ErroFluxo
from app.storage import ArmazenamentoMemoria
from tests.identidade import hdr
from tests.smoke.conftest import DOC, assinantes_teste
from tests.smoke.dbutil import FakeUpload, mk_repo

CHAVE = bytes(range(32))


def _abre(r) -> dict:
    """A resposta sai selada (E2E no egresso) — abre antes do
    parse, como o ClienteE2E faz."""
    return json.loads(abrir(CHAVE, r.content))


# ---------- helpers ----------

async def _ate_recebida_alvo(no_a, payload):
    """A cria/sobe/envia e devolve (out, env_dict assinado) —
    sem receber: os testes de adulteração controlam o ingresso."""
    out = await no_a.criar(payload)
    await no_a.upload_documento(out.id, FakeUpload(DOC), no_a.orgao)
    env = (await no_a.enviar(out.id, no_a.orgao)
           ).model_dump(mode="json")
    return out, env


async def _ate_recebida(no_a, no_b, payload):
    """Idem + recebimento em B. Devolve (out, env_dict)."""
    out, env = await _ate_recebida_alvo(no_a, payload)
    await no_b.receber(env, "tjpa")
    return out, env


# ---------- 1) assinatura do envelope ----------

class TestAssinaturaEnvelope:
    async def test_campo_adulterado_quebra_assinatura(
            self, org_a, org_b, payload_criacao):
        """MITM no `caso_cnj` (não só no hash): qualquer campo
        coberto invalida a assinatura no ingresso."""
        _out, env = await _ate_recebida_alvo(org_a, payload_criacao)
        env["caso_cnj"] = env["caso_cnj"].replace("2679", "0001")
        with pytest.raises(ErroFluxo, match="assinatura"):
            await org_b.receber(env, "tjpa")

    async def test_envelope_sem_assinatura_rejeitado(
            self, org_a, org_b, payload_criacao):
        """Nó com chaves configuradas não aceita envelope nu —
        downgrade de protocolo é rejeitado, não tolerado."""
        _out, env = await _ate_recebida_alvo(org_a, payload_criacao)
        env["assinatura"] = None
        with pytest.raises(ErroFluxo, match="assinatura"):
            await org_b.receber(env, "tjpa")

    async def test_envelope_assinado_por_outro_orgao(
            self, fazer_no, org_a, org_b, payload_criacao):
        """A forja sutil: terceiro assina um envelope VÁLIDO com
        a PRÓPRIA chave declarando origem alheia — bem-formado
        Ed25519, verificação falha: a pública conferida é a de
        `env.origem`, não a do signatário."""
        no_c = await fazer_no("prodepa")          # nó terceiro
        _out, env = await _ate_recebida_alvo(org_a, payload_criacao)
        # re-assina o envelope de A com a chave de C
        env["assinatura"] = no_c.assinante.assinar(
            EnvelopeRecebimento(**env))
        with pytest.raises(ErroFluxo, match="assinatura"):
            await org_b.receber(env, "tjpa")

    async def test_envelope_valido_aceito(
            self, org_a, org_b, payload_criacao):
        """Controle positivo: envelope íntegro segue abrindo —
        a camada não virou denial-of-service próprio."""
        _out, env = await _ate_recebida_alvo(org_a, payload_criacao)
        rec = await org_b.receber(env, "tjpa")
        assert rec.recebido is True


# ---------- 2) destino endereçado ----------

class TestDestinoEnderecado:
    async def test_envelope_para_outro_no_rejeitado(
            self, fazer_no, org_a, payload_criacao):
        """O nó C recebe um envelope que não lhe é endereçado —
        `env.destino != self.orgao` => 409 antes de gravar."""
        no_c = await fazer_no("prodepa")
        out, env = await _ate_recebida_alvo(org_a, payload_criacao)
        assert env["destino"] == "mpf.pa"       # não é prodepa
        with pytest.raises(ErroFluxo, match="endereçado"):
            await no_c.receber(env, "tjpa")
        with pytest.raises(ErroNaoEncontrado):
            await no_c.obter(out.id)            # nada gravou


# ---------- 3) assinatura do ack ----------

class TestAssinaturaAck:
    async def _ack_valido(self, org_a, org_b, payload):
        out, _env = await _ate_recebida(org_a, org_b, payload)
        await org_b.upload_documento(
            out.id, FakeUpload(DOC), org_b.orgao)
        conf = await org_b.confirmar(dict(
            tramitacao_id=out.id, decisao="aceita",
            hash_documento_recebido=out.hash_documento_sha256),
            org_b.orgao)
        return out, conf

    async def test_ack_valido_aceito(self, org_a, org_b,
                                     payload_criacao):
        out, conf = await self._ack_valido(org_a, org_b,
                                           payload_criacao)
        assert conf.assinatura                   # saiu assinado
        fin = await org_a.aplicar_confirmacao(out.id, conf, "mpf.pa")
        assert fin.status == StatusTramitacao.CONFIRMADA

    async def test_ack_sem_assinatura_rejeitado(
            self, org_a, org_b, payload_criacao):
        """Ack nu num nó com chaves => não aplica (downgrade)."""
        out, conf = await self._ack_valido(org_a, org_b,
                                           payload_criacao)
        conf_nu = conf.model_copy(update={"assinatura": None})
        with pytest.raises(ErroFluxo, match="ack"):
            await org_a.aplicar_confirmacao(out.id, conf_nu,
                                            "mpf.pa")

    async def test_ack_falsificado_rejeitado(
            self, fazer_no, org_a, org_b, payload_criacao):
        """Ack assinado por terceiro passa no papel (org=
        destino) mas morre na assinatura — a chave conferida é a
        do DESTINO DO CASO, não a do chamador."""
        out, _conf = await self._ack_valido(org_a, org_b,
                                            payload_criacao)
        no_c = await fazer_no("prodepa")
        forja = ConfirmacaoOut(
            tramitacao_id=out.id, status="confirmada",
            confirmado_em=datetime.now(timezone.utc),
            hash_cadeia="0" * 64)
        forja = forja.model_copy(
            update={"assinatura": no_c.assinante.assinar(forja)})
        with pytest.raises(ErroFluxo, match="ack"):
            await org_a.aplicar_confirmacao(out.id, forja, "mpf.pa")
        # nada transitou — a origem segue aguardando a decisão
        assert (await org_a.obter(out.id)).status == \
            StatusTramitacao.EM_TRANSITO

    async def test_ack_campo_adulterado_rejeitado(
            self, org_a, org_b, payload_criacao):
        """Trocar `status` de um ack válido invalida a assinatura
        — a decisão entregue é a decisão assinada."""
        out, conf = await self._ack_valido(org_a, org_b,
                                           payload_criacao)
        mau = conf.model_copy(update={"status": "recusada"})
        with pytest.raises(ErroFluxo, match="ack"):
            await org_a.aplicar_confirmacao(out.id, mau, "mpf.pa")


# ---------- 4) confirmação verificável ----------

class TestConfirmacaoVerificavel:
    async def test_confirmar_sem_bytes_no_storage(
            self, org_a, org_b, payload_criacao):
        """Declarar o hash certo não fecha o caso: sem os bytes
        no storage de B, confirmar é 409 — "dizer que recebeu"
        não é evidência."""
        out, _env = await _ate_recebida(org_a, org_b,
                                        payload_criacao)
        with pytest.raises(ErroFluxo, match="não está no storage"):
            await org_b.confirmar(dict(
                tramitacao_id=out.id, decisao="aceita",
                hash_documento_recebido=out.hash_documento_sha256),
                org_b.orgao)

    async def test_confirmar_bytes_adulterados_no_storage(
            self, org_a, org_b, payload_criacao):
        """Storage de B adulterado/corrompido: a recomputação do
        SHA-256 diverge do registrado => 409. O hash declarado
        não salva bytes errados."""
        out, _env = await _ate_recebida(org_a, org_b,
                                        payload_criacao)
        await org_b.storage.garantir()
        await org_b.storage.guardar(
            str(out.id), io.BytesIO(b"bytes adulterados no bucket"))
        with pytest.raises(ErroFluxo, match="diverge"):
            await org_b.confirmar(dict(
                tramitacao_id=out.id, decisao="aceita",
                hash_documento_recebido=out.hash_documento_sha256),
                org_b.orgao)
        # e o caso NÃO transitou — segue RECEBIDA
        assert (await org_b.obter(out.id)).status == \
            StatusTramitacao.RECEBIDA


# ---------- 5) gate de estado + formato no upload ----------

class TestUploadGates:
    async def test_upload_em_transito_rejeitado(
            self, org_a, payload_criacao):
        """EM_TRANSITO já tem o objeto como pré-condição — bytes
        novos após o envio são anomalia, não update."""
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC),
                                     org_a.orgao)
        await org_a.enviar(out.id, org_a.orgao)
        with pytest.raises(ErroFluxo, match="CRIADA ou RECEBIDA"):
            await org_a.upload_documento(out.id, FakeUpload(DOC),
                                         org_a.orgao)

    async def test_upload_apos_confirmada_rejeitado(
            self, org_a, org_b, payload_criacao):
        out, _env = await _ate_recebida(org_a, org_b,
                                        payload_criacao)
        await org_b.upload_documento(out.id, FakeUpload(DOC),
                                     org_b.orgao)
        conf = await org_b.confirmar(dict(
            tramitacao_id=out.id, decisao="aceita",
            hash_documento_recebido=out.hash_documento_sha256),
            org_b.orgao)
        await org_a.aplicar_confirmacao(out.id, conf, "mpf.pa")
        # caso fechado: nenhum byte novo entra, em nenhum nó
        for no, papel in ((org_a, "tjpa"), (org_b, "mpf.pa")):
            with pytest.raises(ErroFluxo, match="CRIADA ou RECEBIDA"):
                await no.upload_documento(
                    out.id, FakeUpload(DOC), papel)

    @pytest.mark.parametrize("doc", [
        b"MZ\x90\x00 executavel de teste",        # PE/DOS
        b"\x7fELF\x02\x01\x01 binario linux",     # ELF
        b"#!/bin/sh\nrm -rf /\n",                 # script
    ])
    async def test_magic_bytes_rejeitado(self, fazer_no,
                                         payload_criacao, doc):
        """Executáveis/scripts não entram na esteira mesmo com o
        hash declarado casando — o formato é gate de conteúdo."""
        no = await fazer_no("tjpa")
        payload = dict(
            payload_criacao,
            hash_documento_sha256=hashlib.sha256(doc).hexdigest(),
            idempotency_key="tjpa-magic-0001")
        out = await no.criar(payload)
        with pytest.raises(ErroFluxo, match="formato"):
            await no.upload_documento(out.id, FakeUpload(doc),
                                      no.orgao)
        assert not await no.storage.existe(str(out.id))

    @pytest.mark.parametrize("doc", [
        b"%PDF-1.4 conteudo do processo",         # pdf
        b"PK\x03\x04 zip office",                 # office/zip
        b"\x89PNG\r\n\x1a\n imagem",              # png
        b"\xff\xd8\xff\xe0 jpeg",                 # jpeg
        b"texto utf-8 simples do documento",      # texto
    ])
    async def test_formatos_documentais_aceitos(
            self, fazer_no, payload_criacao, doc):
        """Controle: os formatos do corpus seguem entrando — o
        gate não virou deny-all."""
        no = await fazer_no("tjpa")
        payload = dict(
            payload_criacao,
            hash_documento_sha256=hashlib.sha256(doc).hexdigest(),
            idempotency_key="tjpa-fmt-0001")
        out = await no.criar(payload)
        r = await no.upload_documento(out.id, FakeUpload(doc),
                                      no.orgao)
        assert r["sha256"] == hashlib.sha256(doc).hexdigest()


# ---------- 6) replay compartilhado ----------

class TestReplayCompartilhado:
    async def test_replay_visto_atomic_insert(self):
        """Claim por PK: primeira vez False (novo), segunda True
        (replay) — o banco serializa, não o processo."""
        e, repo = await mk_repo("r1")
        nonce = "ab" * 12
        assert await repo.replay_visto(nonce, 1_000_000) is False
        assert await repo.replay_visto(nonce, 1_000_000) is True
        await e.dispose()

    async def test_varredura_de_expirados_oportunista(self):
        """O insert carrega a limpeza: nonces de janela passada
        somem no próximo claim (sem sweeper dedicado)."""
        from sqlalchemy import text
        e, repo = await mk_repo("r2")
        assert await repo.replay_visto("cc" * 12, 1) is False
        # próximo claim com expira_ms alto varre a linha morta
        assert await repo.replay_visto("dd" * 12, 9_999_999) is False
        async with e.connect() as c:
            n = (await c.execute(
                text("SELECT count(*) FROM replay_nonces"))
                ).scalar()
        assert n == 1                        # só o dd*12 sobrou
        await e.dispose()

    def test_replay_http_compartilhado_400(self, monkeypatch,
                                           payload_criacao):
        """Mesmo quadro E2E POSTado duas vezes: a segunda morre
        no anti-replay — com o store no Postgres (app.state.
        replay_db), vale para qualquer réplica do nó."""
        monkeypatch.setenv("E2E_CHAVE", CHAVE.hex())
        monkeypatch.setenv("E2E_OBRIGATORIO", "1")
        with TestClient(create_app(
                "tjpa", repo_factory=lambda: mk_repo("re"),
                storage=ArmazenamentoMemoria("tjpa"))) as c:
            corpo = selar(CHAVE, json.dumps(payload_criacao).encode())
            hs = {"content-type": CT_E2E,
                  "x-e2e-ct": "application/json", **hdr("tjpa")}
            r1 = c.post("/v1/tramitacoes", content=corpo, headers=hs)
            assert r1.status_code == 201
            r2 = c.post("/v1/tramitacoes", content=corpo, headers=hs)
            assert r2.status_code == 400


# ---------- 7) ingresso E2E streaming + allowlist ----------

class TestIngressoStreaming:
    @pytest.fixture
    def ca_e2e(self, monkeypatch):
        monkeypatch.setenv("E2E_CHAVE", CHAVE.hex())
        monkeypatch.setenv("E2E_OBRIGATORIO", "1")
        with TestClient(create_app(
                "tjpa", repo_factory=lambda: mk_repo("st"),
                storage=ArmazenamentoMemoria("tjpa"))) as c:
            yield c

    def test_x_e2e_ct_fora_da_allowlist_415(self, ca_e2e):
        """x-e2e-ct declarado fora da lista (json/multipart) =>
        415 — o roteador não vê content-types arbitrários."""
        corpo = selar(CHAVE, b'{"x":1}')
        r = ca_e2e.post("/v1/tramitacoes", content=corpo, headers={
            "content-type": CT_E2E,
            "x-e2e-ct": "application/x-msdownload", **hdr("tjpa")})
        assert r.status_code == 415

    def test_multi_quadro_decifra_e_roteia(
            self, ca_e2e, payload_criacao):
        """Corpo claro fatiado em VÁRIOS quadros E2E: o ingresso
        recompõe o stream e o roteador recebe o JSON inteiro —
        sem materialização do ciphertext."""
        claro = json.dumps(payload_criacao).encode()
        s = FluxoSelador(CHAVE)
        metade = len(claro) // 2
        corpo = (s.selar_bloco(claro[:metade])
                 + s.selar_bloco(claro[metade:]) + s.terminador())
        r = ca_e2e.post("/v1/tramitacoes", content=corpo, headers={
            "content-type": CT_E2E,
            "x-e2e-ct": "application/json", **hdr("tjpa")})
        assert r.status_code == 201
        assert _abre(r)["origem"] == "tjpa"

    def test_corpo_grande_atravessa_streaming(
            self, ca_e2e, payload_criacao):
        """Upload multipart grande (~1 MiB) em muitos quadros:
        o cifrado atravessa quadro a quadro e a aplicação recebe
        o multipart inteiro — 201 com digest conferido."""
        doc = b"%PDF-1.4 " + b"x" * (1024 * 1024)    # ~1 MiB
        hash_doc = hashlib.sha256(doc).hexdigest()
        payload_criacao["hash_documento_sha256"] = hash_doc
        r = ca_e2e.post(
            "/v1/tramitacoes",
            content=selar(CHAVE,
                          json.dumps(payload_criacao).encode()),
            headers={"content-type": CT_E2E,
                     "x-e2e-ct": "application/json", **hdr("tjpa")})
        tid = _abre(r)["id"]
        bnd = "----borda-streaming-test"
        mp = (f"--{bnd}\r\nContent-Disposition: form-data; "
              f'name="arquivo"; filename="d.pdf"\r\n'
              f"Content-Type: application/pdf\r\n\r\n").encode() \
            + doc + f"\r\n--{bnd}--\r\n".encode()
        # fatia o multipart em quadros de ~256 KiB
        s = FluxoSelador(CHAVE)
        partes = [mp[i:i + 262144]
                  for i in range(0, len(mp), 262144)]
        corpo = b"".join(s.selar_bloco(p) for p in partes) \
            + s.terminador()
        up = ca_e2e.post(f"/v1/documentos/{tid}/upload",
                         content=corpo, headers={
                             "content-type": CT_E2E,
                             "x-e2e-ct": "multipart/form-data; "
                                         f"boundary={bnd}",
                             **hdr("tjpa")})
        assert up.status_code == 201
        assert _abre(up)["sha256"] == hash_doc


# ---------- 8) verificação autônoma da hash-chain ----------

class TestVerificacaoTrilha:
    async def test_cadeia_integra_replay_ok(
            self, org_a, org_b, payload_criacao):
        out, _env = await _ate_recebida(org_a, org_b,
                                        payload_criacao)
        v = await org_a.verificar_trilha(str(out.id), "tjpa")
        assert v.integro is True and v.linhas >= 2
        v_b = await org_b.verificar_trilha(str(out.id), "mpf.pa")
        assert v_b.integro is True

    async def test_linha_adulterada_detectada(
            self, org_a, payload_criacao):
        """UPDATE direto no banco (adm malicioso/corrupção):
          - Postgres: o trigger append-only BARRE o update —
            prova mais forte, a linha nem muda;
          - sqlite (sem trigger): o update passa e o replay
            elo a elo aponta a primeira linha divergente —
            o topo denormalizado não é prova, a matemática é."""
        from sqlalchemy import text
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC),
                                     org_a.orgao)
        adulterado = True
        try:
            async with org_a.repo._engine.begin() as c:
                await c.execute(text(
                    "UPDATE trilha_auditoria SET evento='forjado' "
                    "WHERE seq = (SELECT min(seq) FROM "
                    "trilha_auditoria)"))
        except Exception:
            adulterado = False        # trigger PG: append-only real
        if adulterado:
            v = await org_a.verificar_trilha(str(out.id), "tjpa")
            assert v.integro is False
            assert v.divergencia_seq is not None

    async def test_verificar_terceiro_404(
            self, org_a, payload_criacao):
        """Auditoria é privilégio de participante — terceiro
        recebe o 404 opaco de sempre (existência não vaza)."""
        out = await org_a.criar(payload_criacao)
        with pytest.raises(ErroNaoEncontrado):
            await org_a.verificar_trilha(str(out.id), "tre-pa")

    def test_rota_verificar_http(self, payload_criacao):
        """GET /v1/tramitacoes/{id}/verificar — auditoria pela
        API, mesma autorização da consulta."""
        ass = assinantes_teste()
        with TestClient(create_app(
                "tjpa", repo_factory=lambda: mk_repo("vf"),
                storage=ArmazenamentoMemoria("tjpa"),
                assinante=ass["tjpa"])) as c:
            r = c.post("/v1/tramitacoes", json=payload_criacao,
                       headers=hdr("tjpa"))
            tid = r.json()["id"]
            v = c.get(f"/v1/tramitacoes/{tid}/verificar",
                      headers=hdr("tjpa"))
            assert v.status_code == 200
            assert v.json()["integro"] is True
            assert v.json()["linhas"] == 1


# ---------- 9) dedup de efeito na esteira ----------

class TestDedupEfeito:
    async def test_encadear_uma_vez_nao_duplica(
            self, org_a, payload_criacao):
        """A tx do consumidor deduplica o evento: mesma linha
        duas vezes na mesma trilha = no-op (None), não bifurca."""
        out = await org_a.criar(payload_criacao)
        async with org_a.repo.transacao() as tx:
            h1 = await tx.encadear_uma_vez(out.id, "evt:teste")
            h2 = await tx.encadear_uma_vez(out.id, "evt:teste")
        assert h1 and h2 is None
        eventos = [t["evento"]
                   for t in await org_a.repo.trilha(out.id)]
        assert eventos.count("evt:teste") == 1

    async def test_worker_redelivery_nao_duplica_trilha(
            self, org_a, payload_criacao):
        """At-least-once real: processar_evento 2x (redelivery
        AMQP) reescreve o objeto mas NÃO duplica
        `doc_anonimizado:` na trilha."""
        from app.worker import StubMotorIA, processar_evento
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC),
                                     org_a.orgao)
        st_dst = ArmazenamentoMemoria(
            "tjpa", nome_bucket="tjpa-docs-anonimizados")
        doc = str(out.id)
        ev = {"id_documento": doc, "orgao_origem": "tjpa",
              "id_processo": out.caso_cnj}
        motor = StubMotorIA(atraso=0)
        await processar_evento(ev, org_a.storage, st_dst, motor,
                               repo=org_a.repo)
        await processar_evento(ev, org_a.storage, st_dst, motor,
                               repo=org_a.repo)      # re-entrega
        eventos = [t["evento"]
                   for t in await org_a.repo.trilha(out.id)]
        assert eventos.count(f"doc_anonimizado:{doc}") == 1


# ---------- 10) fail-closed de operação ----------

class TestFailClosed:
    def test_worker_sem_ia_engine_aborta(self, monkeypatch):
        """IA_ENGINE ausente não cai no stub — o stub devolve o
        doc em claro e subir silencioso anonimizaria nada."""
        from app.worker import motor_de_env
        monkeypatch.delenv("IA_ENGINE", raising=False)
        with pytest.raises(SystemExit, match="IA_ENGINE"):
            motor_de_env()

    def test_worker_engine_desconhecida_aborta(self, monkeypatch):
        from app.worker import motor_de_env
        monkeypatch.setenv("IA_ENGINE", "motor_que_nao_existe")
        with pytest.raises(SystemExit, match="desconhecida"):
            motor_de_env()

    def test_vault_sem_credencial_fail_closed(self, monkeypatch):
        """E2E_FONTE=vault sem credencial utilizável => erro no
        boot — a API não sobe com a fonte de chaves cega."""
        monkeypatch.setenv("E2E_FONTE", "vault")
        monkeypatch.setenv("VAULT_ADDR", "https://vault:8200")
        for v in ("VAULT_TOKEN", "VAULT_TOKEN_FILE",
                  "VAULT_ROLE_ID", "VAULT_SECRET_ID",
                  "VAULT_ROLE_ID_FILE", "VAULT_SECRET_ID_FILE"):
            monkeypatch.delenv(v, raising=False)
        with pytest.raises(ErroCripto, match="autentica"):
            fonte_de_env()

    def test_vault_approle_login_e_leitura(self, monkeypatch):
        """AppRole: POST auth/approle/login devolve client_token
        curto; a leitura do KV vai com ELE (não com root)."""
        import httpx
        posts, gets = [], []

        class R:
            def __init__(s, j): s._j = j
            def raise_for_status(s): pass
            def json(s): return s._j

        def _post(url, **kw):
            posts.append((url, kw))
            return R({"auth": {"client_token": "tok-curto",
                               "lease_duration": 60}})

        def _get(url, **kw):
            gets.append((url, kw))
            return R({"data": {"data": {"atual": CHAVE.hex()}}})

        monkeypatch.setattr(httpx, "post", _post)
        monkeypatch.setattr(httpx, "get", _get)
        f = FonteVaultKV("https://vault:8200", "isaci/e2e", None,
                         role_id="r-id", secret_id="s-id")
        c = f.chaves()
        assert c.atual == CHAVE
        assert posts[0][0].endswith("/v1/auth/approle/login")
        assert posts[0][1]["json"] == {"role_id": "r-id",
                                       "secret_id": "s-id"}
        # a leitura do KV usa o token do AppRole, não estático
        assert gets[0][1]["headers"]["X-Vault-Token"] == "tok-curto"
        assert gets[0][1]["verify"] is not False    # TLS sempre


# ---------- 11) borda: identidade + segredo compartilhado ----------

def _req(hs):
    """Request mínima com a cara de starlette para orgao_atual."""
    return type("Req", (), {
        "headers": hs,
        "url": type("U", (), {"path": "/v1/x"})()})()


class TestBordaIdentidade:
    def test_identidade_malformada_401(self):
        """CN fora do formato OrgaoID (caminho que injete o
        header sem o mapa do nginx) => 401 opaco."""
        from app.deps import ErroAuth, orgao_atual
        with pytest.raises(ErroAuth):
            orgao_atual(_req({}))
        with pytest.raises(ErroAuth):
            orgao_atual(_req({"x-cliente-orgao": "x; DROP TABLE"}))
        with pytest.raises(ErroAuth):
            orgao_atual(_req({"x-cliente-orgao": "TJPA"}))  # caso
        assert orgao_atual(
            _req({"x-cliente-orgao": "tjpa"})) == "tjpa"

    def test_segredo_de_borda(self, monkeypatch):
        """BORDA_SEGREDO configurado => header exigido e comparado
        em tempo constante: quem injetar X-Cliente-Orgao por
        outro caminho não fala em nome de órgão."""
        from app.deps import ErroAuth, orgao_atual
        monkeypatch.setenv("BORDA_SEGREDO", "segredo-par-nginx")
        with pytest.raises(ErroAuth):
            orgao_atual(_req({"x-cliente-orgao": "tjpa"}))
        with pytest.raises(ErroAuth):
            orgao_atual(_req({"x-cliente-orgao": "tjpa",
                              "x-borda-segredo": "errado"}))
        assert orgao_atual(_req(
            {"x-cliente-orgao": "tjpa",
             "x-borda-segredo": "segredo-par-nginx"})) == "tjpa"
