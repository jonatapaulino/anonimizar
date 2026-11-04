"""Segurança de borda — identidade por mTLS (header X-Cliente-Orgao).

O certificado de cliente é verificado pelo nginx na rede `borda`
(ssl_verify_client + proxy_set_header). A API confia no header
porque a única rota até ela vem do nginx — compose garante:
`interna` é internal:true e a API não publica porta.

Todo 401 devolve o MESMO corpo opaco (oráculo de enumeração
fechado). O motivo fino fica no log interno, nunca na resposta.
"""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.identidade import hdr
from tests.smoke.dbutil import mk_repo


@pytest.fixture
def ca():
    with TestClient(create_app(
            "tjpa", repo_factory=lambda: mk_repo("a"))) as c:
        yield c


@pytest.fixture
def payload(caso):
    return dict(
        caso_cnj=caso, destino="mpf.pa", modo="pseudonimizacao",
        hash_documento_sha256=hashlib.sha256(b"doc auth").hexdigest(),
        metadados={}, idempotency_key="tjpa-auth-0001")


class TestIdentidadeObrigatoria:
    def test_sem_header_401(self, ca):
        r = ca.get("/v1/tramitacoes/"
                   "00000000-0000-0000-0000-000000000000")
        assert r.status_code == 401
        assert r.json()["erro"]["codigo"] == "nao_autenticado"

    def test_header_vazio_401(self, ca):
        r = ca.post("/v1/recebimentos", json={},
                    headers={"X-Cliente-Orgao": "   "})
        assert r.status_code == 401

    def test_healthz_aberto(self, ca):
        """Probe de liveness não exige identidade (rota pública)."""
        assert ca.get("/healthz").status_code == 200


class TestOpacidade:
    def test_corpos_401_identicos(self, ca):
        """Ausente e vazio => MESMA resposta opaca."""
        r_ausente = ca.post("/v1/tramitacoes", json={})
        r_vazio = ca.post("/v1/tramitacoes", json={},
                          headers={"X-Cliente-Orgao": ""})
        assert {r_ausente.status_code, r_vazio.status_code} == {401}
        corpos = [r_ausente.json()["erro"]["mensagem"],
                  r_vazio.json()["erro"]["mensagem"]]
        assert len(set(corpos)) == 1

    def test_sem_motivo_fino(self, ca):
        r = ca.post("/v1/tramitacoes", json={})
        for frag in ("header", "mtls", "cert", "x-cliente"):
            assert frag.lower() not in str(r.json()).lower()

    def test_identidade_valida_aceita(self, ca, payload):
        r = ca.post("/v1/tramitacoes", json=payload,
                    headers=hdr("tjpa"))
        assert r.status_code == 201
        # origem gravada veio do header autenticado, não do payload
        assert r.json()["origem"] == "tjpa"

    def test_orgao_difere_do_no_409(self, ca, payload):
        """Identidade autenticada de outro órgão: autenticado, mas
        não é este nó — conflito de fluxo, não 401."""
        r = ca.post("/v1/tramitacoes", json=payload,
                    headers=hdr("tre-pa"))
        assert r.status_code == 409
