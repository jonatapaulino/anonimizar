"""Segurança de borda — Bearer JWT offline (RS256).

Todo 401 devolve o MESMO corpo opaco (oráculo de enumeração
fechado) + WWW-Authenticate: Bearer. Os motivos finos ficam no
log interno, nunca na resposta.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.jwthelper import hdr, token_chave_errada
from tests.smoke.dbutil import mk_repo


@pytest.fixture
def ca():
    with TestClient(create_app(
            "tjpa", repo_factory=lambda: mk_repo("a"))) as c:
        yield c


@pytest.fixture
def payload(caso):
    import hashlib
    return dict(
        caso_cnj=caso, destino="mpf.pa", modo="pseudonimizacao",
        hash_documento_sha256=hashlib.sha256(b"doc auth").hexdigest(),
        metadados={}, idempotency_key="tjpa-auth-0001")


def _corpos_iguais(*rs):
    corpos = [r.json()["erro"]["mensagem"] for r in rs]
    assert len(set(corpos)) == 1, corpos


class TestBearerObrigatorio:
    def test_sem_header_401(self, ca):
        r = ca.get("/v1/tramitacoes/"
                   "00000000-0000-0000-0000-000000000000")
        assert r.status_code == 401
        assert r.headers["WWW-Authenticate"] == "Bearer"
        assert r.json()["erro"]["codigo"] == "nao_autenticado"

    def test_scheme_errado_401(self, ca):
        r = ca.get("/healthz")          # rota aberta — sanidade
        assert r.status_code == 200
        r = ca.post("/v1/recebimentos", json={},
                    headers={"Authorization": "Basic dGpwYTp4"})
        assert r.status_code == 401

    def test_token_lixo_401(self, ca):
        r = ca.post("/v1/recebimentos", json={},
                    headers={"Authorization": "Bearer nao-e-jwt"})
        assert r.status_code == 401


class TestValidacaoCriptografica:
    def test_token_falso_outra_chave_401(self, ca):
        """Token bem-formado mas assinado por par RSA estranho."""
        r = ca.post("/v1/tramitacoes", json={},
                    headers={"Authorization":
                             f"Bearer {token_chave_errada('tjpa')}"})
        assert r.status_code == 401

    def test_token_expirado_401(self, ca):
        r = ca.post("/v1/tramitacoes", json={},
                    headers=hdr("tjpa", ttl=-60))
        assert r.status_code == 401

    def test_token_sem_claim_orgao_401(self, ca):
        """exp válido, assinatura válida, mas sem orgao_id nem sub."""
        import time
        import jwt
        from tests.jwthelper import PRIVADA_PEM
        agora = int(time.time())
        tok = jwt.encode({"exp": agora + 300, "iat": agora},
                         PRIVADA_PEM, algorithm="RS256")
        r = ca.post("/v1/tramitacoes", json={},
                    headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401

    def test_sub_como_fallback_funciona(self, ca, payload):
        """orgao_id ausente -> sub carrega a identidade (ADR-0006:
        issuer-agnóstico, tolera IdPs que só põem sub)."""
        import time
        import jwt
        from tests.jwthelper import PRIVADA_PEM
        agora = int(time.time())
        tok = jwt.encode({"sub": "tjpa", "iat": agora,
                          "exp": agora + 300},
                         PRIVADA_PEM, algorithm="RS256")
        r = ca.post("/v1/tramitacoes", json=payload,
                    headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 201


class TestOpacidade:
    def test_corpos_401_identicos(self, ca):
        """Ausente, forjado, expirado e sem claim => MESMA resposta."""
        r_ausente = ca.post("/v1/tramitacoes", json={})
        r_falso = ca.post(
            "/v1/tramitacoes", json={},
            headers={"Authorization":
                     f"Bearer {token_chave_errada('tjpa')}"})
        r_expirado = ca.post("/v1/tramitacoes", json={},
                             headers=hdr("tjpa", ttl=-1))
        _corpos_iguais(r_ausente, r_falso, r_expirado)
        # nada de motivo fino na resposta
        for frag in ("expirad", "assinatura", "signature", "claim",
                     "exp", "key", "RS256"):
            assert frag.lower() not in str(
                r_expirado.json()).lower()

    def test_token_valido_identidade_aceita(self, ca, payload):
        r = ca.post("/v1/tramitacoes", json=payload,
                    headers=hdr("tjpa"))
        assert r.status_code == 201
        # origem gravada veio da claim, não do payload
        assert r.json()["origem"] == "tjpa"

    def test_orgao_do_token_difere_do_no_409(self, ca, payload):
        """Token VÁLIDO de outro órgão: autenticado, mas não é este
        nó — conflito de fluxo, não 401 (a separação 401/409 está
        correta: autenticação ≠ autorização de nó)."""
        r = ca.post("/v1/tramitacoes", json=payload,
                    headers=hdr("tre-pa"))
        assert r.status_code == 409
