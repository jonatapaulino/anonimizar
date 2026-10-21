"""Autorização por participação no caso — correção do bug em que
download e upload verificavam só existência, não pertencimento.

Regra: só origem ou destino do caso podem upar/baixar. Órgão
terceiro recebe 404 (não revela nem que a tramitação existe) —
a mesma política já aplicada em `consultar`/`abrir_anonimizado`.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import ArmazenamentoMemoria
from tests.jwthelper import hdr
from tests.smoke.conftest import DOC, HASH_DOC
from tests.smoke.dbutil import mk_repo

CASO = "5614226-41.2021.8.14.2679"


@pytest.fixture
def ca():
    with TestClient(create_app(
            "tjpa", repo_factory=lambda: mk_repo("a"),
            storage=ArmazenamentoMemoria("tjpa"))) as c:
        yield c


@pytest.fixture
def cb():
    """Nó B (PRODEPA) — precisa existir para receber/confirmar."""
    with TestClient(create_app(
            "prodepa", repo_factory=lambda: mk_repo("b"),
            storage=ArmazenamentoMemoria("prodepa"))) as c:
        yield c


@pytest.fixture
def payload():
    return dict(
        caso_cnj=CASO, destino="prodepa", modo="pseudonimizacao",
        hash_documento_sha256=HASH_DOC,
        metadados={"assunto": "dano moral"},
        idempotency_key="tjpa-auth-doc-001")


def _criar(ca, payload):
    r = ca.post("/v1/tramitacoes", json=payload, headers=hdr("tjpa"))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _up(ca, tid, org="tjpa", doc=DOC):
    return ca.post(f"/v1/documentos/{tid}/upload",
                   files={"arquivo": ("peca.pdf", doc,
                                      "application/pdf")},
                   headers=hdr(org))


class TestAutorizacaoDocumento:
    def test_download_terceiro_negado(self, ca, payload):
        """BUG: hoje qualquer órgão autenticado baixa o doc de
        outro — basta conhecer o tid."""
        tid = _criar(ca, payload)
        assert _up(ca, tid).status_code == 201
        r = ca.get(f"/v1/documentos/{tid}/download",
                   headers=hdr("tre-pa"))         # fora do caso
        assert r.status_code == 404               # não 200

    def test_upload_terceiro_negado(self, ca, payload):
        """Terceiro não pode nem tentar upar no doc alheio."""
        tid = _criar(ca, payload)
        r = _up(ca, tid, org="tre-pa")
        assert r.status_code == 404               # não 201

    def test_download_origem_e_destino_ok(self, ca, payload):
        """Origem e destino do caso seguem autorizados."""
        tid = _criar(ca, payload)
        assert _up(ca, tid).status_code == 201
        for org in ("tjpa", "prodepa"):
            r = ca.get(f"/v1/documentos/{tid}/download",
                       headers=hdr(org))
            assert r.status_code == 200
            assert r.content == DOC

    def test_download_anon_terceiro_ja_negado(self, ca, payload):
        """Regressão: abrir_anonimizado JÁ tinha o check —
        garante que a política é uniforme nas três rotas."""
        tid = _criar(ca, payload)
        assert _up(ca, tid).status_code == 201
        r = ca.get(f"/v1/documentos/{tid}/download-anonimizado",
                   headers=hdr("tre-pa"))
        assert r.status_code == 404

    def test_tid_inexistente_404_para_todos(self, ca):
        import uuid
        tid = uuid.uuid4()
        for org in ("tjpa", "tre-pa"):
            r = ca.get(f"/v1/documentos/{tid}/download",
                       headers=hdr(org))
            assert r.status_code == 404


def _ate_recebida(ca, cb, payload):
    """Fluxo feliz até RECEBIDA no nó B — ponto de partida dos
    testes de confirmação/ack."""
    tid = _criar(ca, payload)
    assert _up(ca, tid).status_code == 201
    env = ca.post(f"/v1/tramitacoes/{tid}/envio",
                  headers=hdr("tjpa"))
    assert env.status_code == 200, env.text
    rec = cb.post("/v1/recebimentos", json=env.json(),
                  headers=hdr("prodepa"))
    assert rec.status_code == 200, rec.text
    return tid, env.json()


class TestAutorizacaoConfirmacao:
    """confirmar: só o DESTINO do caso decide. Terceiro -> 404;
    a origem (participante, mas papel errado) -> 409."""

    def _post(self, cb, tid, org, hash_ok=True, hash_doc=None):
        return cb.post(
            f"/v1/tramitacoes/{tid}/confirmacao",
            headers=hdr(org),
            json=dict(tramitacao_id=tid, decisao="aceita",
                      hash_documento_recebido=(
                          hash_doc or HASH_DOC)))

    def test_terceiro_nao_confirma(self, ca, cb, payload):
        tid, env = _ate_recebida(ca, cb, payload)
        r = self._post(cb, tid, "tre-pa")
        assert r.status_code == 404          # não 200

    def test_origem_nao_confirma(self, ca, cb, payload):
        """A origem participa do caso mas o papel de decidir é
        do destino — 404 opaco (papel não vira oráculo)."""
        tid, env = _ate_recebida(ca, cb, payload)
        r = self._post(cb, tid, "tjpa")
        assert r.status_code == 404

    def test_destino_confirma_ok(self, ca, cb, payload):
        tid, env = _ate_recebida(ca, cb, payload)
        r = self._post(cb, tid, "prodepa")
        assert r.status_code == 200


class TestAutorizacaoAcks:
    """acks: o ack é a decisão do DESTINO chegando ao nó da
    origem — caller tem que ser o destino. Origem forçando a
    própria transição -> 409; terceiro -> 404."""

    def _ate_confirmada(self, ca, cb, payload):
        tid, env = _ate_recebida(ca, cb, payload)
        conf = cb.post(
            f"/v1/tramitacoes/{tid}/confirmacao",
            headers=hdr("prodepa"),
            json=dict(tramitacao_id=tid, decisao="aceita",
                      hash_documento_recebido=HASH_DOC))
        assert conf.status_code == 200, conf.text
        return tid, conf.json()

    def test_terceiro_nao_aplica_ack(self, ca, cb, payload):
        tid, conf = self._ate_confirmada(ca, cb, payload)
        r = ca.post(f"/v1/tramitacoes/{tid}/acks",
                    headers=hdr("tre-pa"), json=conf)
        assert r.status_code == 404

    def test_origem_nao_forca_ack(self, ca, cb, payload):
        """A origem não pode empurrar um ack sozinha — a decisão
        tem que vir do destino."""
        tid, conf = self._ate_confirmada(ca, cb, payload)
        r = ca.post(f"/v1/tramitacoes/{tid}/acks",
                    headers=hdr("tjpa"), json=conf)
        assert r.status_code == 404

    def test_destino_entrega_ack_ok(self, ca, cb, payload):
        tid, conf = self._ate_confirmada(ca, cb, payload)
        r = ca.post(f"/v1/tramitacoes/{tid}/acks",
                    headers=hdr("prodepa"), json=conf)
        assert r.status_code == 200
        assert r.json()["status"] == "confirmada"


class TestAutorizacaoEnvio:
    """enviar: participante do caso + origem == nó. Destino é
    participante mas não pode enviar a tramitação alheia."""

    def test_terceiro_nao_envia(self, ca, payload):
        tid = _criar(ca, payload)
        assert _up(ca, tid).status_code == 201
        r = ca.post(f"/v1/tramitacoes/{tid}/envio",
                    headers=hdr("tre-pa"))
        assert r.status_code == 404

    def test_destino_nao_envia(self, ca, payload):
        tid = _criar(ca, payload)
        assert _up(ca, tid).status_code == 201
        r = ca.post(f"/v1/tramitacoes/{tid}/envio",
                    headers=hdr("prodepa"))
        assert r.status_code == 404

    def test_origem_envia_ok(self, ca, payload):
        tid = _criar(ca, payload)
        assert _up(ca, tid).status_code == 201
        r = ca.post(f"/v1/tramitacoes/{tid}/envio",
                    headers=hdr("tjpa"))
        assert r.status_code == 200
