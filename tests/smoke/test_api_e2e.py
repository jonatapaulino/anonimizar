"""Smoke E2E sobre HTTP: o mesmo fluxo A->B rodando contra o app
FastAPI real (TestClient), uma instância por órgão — cada nó com
repo + storage próprios (T9: binário sobe via multipart, envelope
é só metadados).

Repete os cenários do nível de contrato + cobre o que só HTTP pega:
401 sem identidade, 422 sanitizado, OpenAPI gerada.
"""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import ArmazenamentoMemoria
from tests.jwthelper import hdr
from tests.smoke.dbutil import mk_repo

DOC = b"EXCELENTISSIMO SENHOR DOUTOR JUIZ - processo via HTTP."
HASH_DOC = hashlib.sha256(DOC).hexdigest()


@pytest.fixture
def ca():
    # `with` roda o lifespan: o engine nasce no loop do TestClient
    # (portal), que é onde as rotas executam — exigência do asyncpg.
    with TestClient(create_app(
            "tjpa", repo_factory=lambda: mk_repo("a"),
            storage=ArmazenamentoMemoria("tjpa"))) as c:
        yield c


@pytest.fixture
def cb():
    with TestClient(create_app(
            "mpf.pa", repo_factory=lambda: mk_repo("b"),
            storage=ArmazenamentoMemoria("mpf.pa"))) as c:
        yield c


@pytest.fixture
def payload(caso):
    return dict(
        caso_cnj=caso, destino="mpf.pa", modo="pseudonimizacao",
        hash_documento_sha256=HASH_DOC,
        metadados={"assunto": "dano moral"},
        idempotency_key="tjpa-2026-http-0001")


def fluxo_http(ca, cb, payload):
    """T9: cria (metadados) -> upload multipart -> envia (só
    metadados) -> recebe -> confirma -> ack."""
    r = ca.post("/v1/tramitacoes", json=payload, headers=hdr("tjpa"))
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    up = ca.post(f"/v1/documentos/{tid}/upload",
                 files={"arquivo": ("peca.pdf", DOC,
                                    "application/pdf")},
                 headers=hdr("tjpa"))
    assert up.status_code == 201, up.text
    env = ca.post(f"/v1/tramitacoes/{tid}/envio", headers=hdr("tjpa")).json()
    rec = cb.post("/v1/recebimentos", json=env, headers=hdr("mpf.pa"))
    assert rec.status_code == 200 and rec.json()["recebido"] is True
    conf = cb.post(f"/v1/tramitacoes/{tid}/confirmacao", headers=hdr("mpf.pa"),
                   json=dict(tramitacao_id=tid, decisao="aceita",
                             hash_documento_recebido=
                             env["hash_documento_sha256"]))
    assert conf.status_code == 200
    fin = ca.post(f"/v1/tramitacoes/{tid}/acks", headers=hdr("mpf.pa"),
                  json=conf.json())
    return tid, env, rec.json(), conf.json(), fin


class TestFluxoHTTP:
    def test_caminho_feliz_completo(self, ca, cb, payload):
        tid, env, rec, conf, fin = fluxo_http(ca, cb, payload)
        assert fin.status_code == 200
        assert fin.json()["status"] == "confirmada"
        # hash atravessa a fronteira JSON intacto
        assert env["hash_documento_sha256"] == \
            fin.json()["hash_documento_sha256"]
        # o envelope não carrega bytes (T9)
        assert "documento_b64" not in env
        # e o arquivo é baixável do storage do órgão A
        dl = ca.get(f"/v1/documentos/{tid}/download",
                    headers=hdr("tjpa"))
        assert dl.status_code == 200 and dl.content == DOC

    def test_resposta_nao_contem_documento(self, ca, cb, payload):
        tid, env, rec, conf, fin = fluxo_http(ca, cb, payload)
        st = ca.get(f"/v1/tramitacoes/{tid}", headers=hdr("tjpa")).json()
        assert "documento" not in st and "documento_b64" not in st
        assert b"EXCELENTISSIMO" not in str(st).encode()

    def test_envio_sem_upload_409(self, ca, payload):
        """Gate físico T9: sem arquivo no storage, não há envio."""
        r = ca.post("/v1/tramitacoes", json=payload,
                    headers=hdr("tjpa"))
        tid = r.json()["id"]
        env = ca.post(f"/v1/tramitacoes/{tid}/envio",
                      headers=hdr("tjpa"))
        assert env.status_code == 409

    def test_adulteracao_do_hash_pega_na_confirmacao(
            self, ca, cb, payload):
        """Envelope adulterado (hash trocado): recebido como
        metadado, mas a confirmação com o hash REAL explode."""
        r = ca.post("/v1/tramitacoes", json=payload,
                    headers=hdr("tjpa"))
        tid = r.json()["id"]
        ca.post(f"/v1/documentos/{tid}/upload",
                files={"arquivo": ("p.pdf", DOC)}, headers=hdr("tjpa"))
        env = ca.post(f"/v1/tramitacoes/{tid}/envio",
                      headers=hdr("tjpa")).json()
        env["hash_documento_sha256"] = "0" * 64      # MITM
        rec = cb.post("/v1/recebimentos", json=env,
                      headers=hdr("mpf.pa")).json()
        assert rec["recebido"] is True
        conf = cb.post(f"/v1/tramitacoes/{tid}/confirmacao",
                       headers=hdr("mpf.pa"),
                       json=dict(tramitacao_id=tid, decisao="aceita",
                                 hash_documento_recebido=payload[
                                     "hash_documento_sha256"]))
        assert conf.status_code == 409

    def test_idempotencia_http(self, ca, payload):
        a = ca.post("/v1/tramitacoes", json=payload, headers=hdr("tjpa"))
        b = ca.post("/v1/tramitacoes", json=payload, headers=hdr("tjpa"))
        assert a.json()["id"] == b.json()["id"]


class TestErrosHTTP:
    def test_sem_identidade_401(self, ca, payload):
        r = ca.post("/v1/tramitacoes", json=payload)
        assert r.status_code == 401
        assert r.json()["erro"]["codigo"] == "nao_autenticado"

    def test_orgao_errado_no_no_409(self, ca, payload):
        r = ca.post("/v1/tramitacoes", json=payload,
                    headers=hdr("tre-pa"))   # outro órgão
        assert r.status_code == 409

    def test_validacao_sanitizada_nao_ecoa_documento(self, ca, payload):
        payload["metadados"] = {"obs": "CPF 123.456.789-00 aqui"}
        r = ca.post("/v1/tramitacoes", json=payload, headers=hdr("tjpa"))
        assert r.status_code == 422
        corpo = r.text
        assert "123.456.789-00" not in corpo   # PII não volta no erro
        assert r.json()["erro"]["codigo"] == "payload_invalido"

    def test_confirmacao_sem_recebimento_404(self, ca, cb, payload):
        tid_fake = "00000000-0000-0000-0000-000000000000"
        r = cb.post(f"/v1/tramitacoes/{tid_fake}/confirmacao",
                    headers=hdr("mpf.pa"),
                    json=dict(tramitacao_id=tid_fake, decisao="aceita",
                              hash_documento_recebido="a" * 64))
        assert r.status_code == 404

    def test_confirmar_duas_vezes_409(self, ca, cb, payload):
        tid, env, rec, conf, fin = fluxo_http(ca, cb, payload)
        r = cb.post(f"/v1/tramitacoes/{tid}/confirmacao", headers=hdr("mpf.pa"),
                    json=dict(tramitacao_id=tid, decisao="aceita",
                              hash_documento_recebido=
                              env["hash_documento_sha256"]))
        assert r.status_code == 409


class TestContratoHTTP:
    def test_openapi_gerada_e_cobre_rotas(self, ca):
        spec = ca.get("/openapi.json").json()
        for rota in ("/v1/tramitacoes", "/v1/recebimentos",
                     "/v1/tramitacoes/{tid}/confirmacao",
                     "/v1/documentos/{did}/upload",
                     "/v1/documentos/{did}/download"):
            assert rota in spec["paths"]
        # schemas do contrato aparecem na OpenAPI (ADR-0003)
        assert "TramitacaoCreate" in spec["components"]["schemas"]

    def test_healthz(self, ca):
        assert ca.get("/healthz").json()["orgao"] == "tjpa"
