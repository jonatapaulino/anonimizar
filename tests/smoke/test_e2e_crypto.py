"""Blindagem E2E — envelope AEAD na entrada e na saída.

Prova as três regras da arquitetura:
1. o que sai do app é ciphertext (a rede nunca vê o claro);
2. o que chega cifrado é aberto ANTES do handler (regra de
   negócio só vê plaintext em memória);
3. adulteração/reuso de envelope quebra o selo => 400 opaco.
"""
import io
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.crypto_e2e import (CT_E2E, ErroCripto, FluxoSelador,
                            ReplayCache, abrir, abrir_stream_async,
                            agora_ms, eh_e2e, selar)
from app.main import create_app
from app.storage import ArmazenamentoCifrado, ArmazenamentoMemoria
from tests.identidade import hdr
from tests.smoke.dbutil import mk_repo

CHAVE = bytes(range(32))          # chave de teste determinística


@pytest.fixture
def ca(monkeypatch):
    monkeypatch.setenv("E2E_CHAVE", CHAVE.hex())
    monkeypatch.setenv("E2E_OBRIGATORIO", "1")
    with TestClient(create_app(
            "tjpa", repo_factory=lambda: mk_repo("a"))) as c:
        yield c


def _e2e_post(c, path, payload, orgao="tjpa"):
    """POST já no formato de rede: corpo cifrado + ct E2E."""
    claro = json.dumps(payload).encode()
    return c.post(path, content=selar(CHAVE, claro), headers={
        "Content-Type": CT_E2E, "X-E2E-CT": "application/json",
        **hdr(orgao)})


def _abre_resp(r):
    assert r.headers["content-type"] == CT_E2E
    assert eh_e2e(r.content)
    return json.loads(abrir(CHAVE, r.content))


class TestCanalProtegido:
    def test_request_em_claro_recusado_415(self, ca):
        """E2E_OBRIGATORIO=1: plaintext em rota /v1/ => 415 opaco."""
        r = ca.post("/v1/tramitacoes", json={}, headers=hdr("tjpa"))
        assert r.status_code == 415
        # recusa de transporte é JSON opaco (o par nem falou E2E)
        assert r.json()["erro"]["codigo"] == "payload_protegido"

    def test_roundtrip_cifrado(self, ca, caso):
        """Request E2E chega, handler vê o JSON claro, response
        sai cifrada e decifra no par."""
        import hashlib
        p = dict(caso_cnj=caso, destino="mpf.pa",
                 modo="pseudonimizacao",
                 hash_documento_sha256=hashlib.sha256(
                     b"doc e2e").hexdigest(),
                 metadados={}, idempotency_key="tjpa-e2e-0001")
        r = _e2e_post(ca, "/v1/tramitacoes", p)
        assert r.status_code == 201
        body = _abre_resp(r)
        assert body["origem"] == "tjpa"
        # o claro do request NÃO aparece no ciphertext da resposta
        assert caso.encode() not in r.content

    def test_selo_adulterado_400(self, ca):
        env = bytearray(selar(CHAVE, b'{"x":1}'))
        env[40] ^= 0xFF                    # bit-flip no ciphertext
        r = ca.post("/v1/recebimentos", content=bytes(env),
                    headers={"Content-Type": CT_E2E, **hdr("tjpa")})
        assert r.status_code == 400

    def test_chave_errada_400(self, ca):
        """Envelope selado com outra chave => selo inválido."""
        env = selar(b"\xAA" * 32, b"{}")
        r = ca.post("/v1/recebimentos", content=env,
                    headers={"Content-Type": CT_E2E, **hdr("tjpa")})
        assert r.status_code == 400

    def test_sem_e2e_no_auth_401_antes_415(self, ca):
        """Sem identidade + sem envelope: o middleware recusa o
        canal antes da auth — 415 (camada de transporte primeiro)."""
        r = ca.post("/v1/tramitacoes", json={})
        assert r.status_code == 415


class TestStorageCifrado:
    async def test_objeto_persiste_só_cifrado(self):
        """Backend só vê quadros; abrir devolve o claro."""
        inner = ArmazenamentoMemoria("tjpa")
        st = ArmazenamentoCifrado(inner, CHAVE)
        await st.guardar("doc1", io.BytesIO(b"conteudo sigiloso"))
        bruto = inner._objs["doc1"]
        assert eh_e2e(bruto)
        assert b"sigiloso" not in bruto
        claro = b"".join([c async for c in st.abrir("doc1")])
        assert claro == b"conteudo sigiloso"

    async def test_objeto_adulterado_falha(self):
        inner = ArmazenamentoMemoria("tjpa")
        st = ArmazenamentoCifrado(inner, CHAVE)
        await st.guardar("doc2", io.BytesIO(b"abcdef" * 100))
        bruto = bytearray(inner._objs["doc2"])
        bruto[40] ^= 0x01
        inner._objs["doc2"] = bytes(bruto)
        with pytest.raises(ErroCripto):
            async for _ in st.abrir("doc2"):
                pass

    async def test_stream_multiquadro(self):
        """Doc > CHUNK vira N quadros — termina no terminador e
        truncamento é detectado."""
        inner = ArmazenamentoMemoria("tjpa")
        st = ArmazenamentoCifrado(inner, CHAVE)
        dados = os.urandom(200 * 1024)
        await st.guardar("grande", io.BytesIO(dados))
        claro = b"".join([c async for c in st.abrir("grande")])
        assert claro == dados
        inner._objs["grande"] = inner._objs["grande"][:-26]
        with pytest.raises(ErroCripto):
            async for _ in st.abrir("grande"):
                pass


class TestQuadro:
    def test_selar_abrir(self):
        assert abrir(CHAVE, selar(CHAVE, b"payload")) == b"payload"

    def test_quadros_sequenciais_nao_reordenam(self):
        s = FluxoSelador(CHAVE)
        q1, q2 = s.selar_bloco(b"a"), s.selar_bloco(b"b")
        env = q2 + q1 + s.terminador()   # reordenado
        with pytest.raises(ErroCripto):
            abrir(CHAVE, env)

    def test_terminador_ausente_falha(self):
        s = FluxoSelador(CHAVE)
        with pytest.raises(ErroCripto):
            abrir(CHAVE, s.selar_bloco(b"x"))   # sem terminador


class TestReplay:
    """v2: ts_ms no AAD + janela de frescura + nonce-cache."""

    def test_envelope_velho_recusado(self):
        env = selar(CHAVE, b"{}", ts_ms=agora_ms() - 120_000)
        with pytest.raises(ErroCripto):
            abrir(CHAVE, env, janela_ms=60_000)

    def test_envelope_futuro_recusado(self):
        env = selar(CHAVE, b"{}", ts_ms=agora_ms() + 120_000)
        with pytest.raises(ErroCripto):
            abrir(CHAVE, env, janela_ms=60_000)

    def test_dentro_da_janela_abre(self):
        env = selar(CHAVE, b"{}", ts_ms=agora_ms() - 30_000)
        assert abrir(CHAVE, env, janela_ms=60_000) == b"{}"

    def test_reenvio_bloqueia_no_cache(self):
        cache = ReplayCache()
        env = selar(CHAVE, b"{}")
        assert abrir(CHAVE, env, janela_ms=60_000,
                     replay=cache) == b"{}"
        with pytest.raises(ErroCripto):
            abrir(CHAVE, env, janela_ms=60_000, replay=cache)

    def test_ts_adulterado_quebra_selo(self):
        env = bytearray(selar(CHAVE, b"{}"))
        env[20] ^= 0x01                  # byte do ts — AAD o cobre
        with pytest.raises(ErroCripto):
            abrir(CHAVE, env)

    def test_sem_janela_envelope_antigo_abre(self):
        """Storage/DLQ: dado em repouso não expira."""
        env = selar(CHAVE, b"doc",
                    ts_ms=agora_ms() - 86_400_000)
        assert abrir(CHAVE, env) == b"doc"

    async def test_stream_async_frescura(self):
        async def _ait(b):
            yield b
        env = selar(CHAVE, b"x", ts_ms=agora_ms() - 120_000)
        with pytest.raises(ErroCripto):
            [_ async for _ in abrir_stream_async(
                CHAVE, _ait(env), janela_ms=60_000)]

    def test_middleware_replay_400(self, ca, caso):
        """Mesmo envelope reenviado no canal HTTP => 400 do
        middleware (idempotência ecoaria 201 — o nonce-cache é
        camada de transporte, anterior ao negócio)."""
        import hashlib
        p = dict(caso_cnj=caso, destino="mpf.pa",
                 modo="pseudonimizacao",
                 hash_documento_sha256=hashlib.sha256(
                     b"doc replay").hexdigest(),
                 metadados={}, idempotency_key="tjpa-replay-0001")
        env = selar(CHAVE, json.dumps(p).encode())
        hd = {"Content-Type": CT_E2E, "X-E2E-CT": "application/json",
              **hdr("tjpa")}
        r1 = ca.post("/v1/tramitacoes", content=env, headers=hd)
        assert r1.status_code == 201
        r2 = ca.post("/v1/tramitacoes", content=env, headers=hd)
        assert r2.status_code == 400
