"""Conftest raiz — prepara o ambiente JWT offline da suíte.

Importa tests/jwthelper (par RSA transiente + JWT_PUBLIC_KEY no
ambiente) e expõe o emissor como fixture `faz_token`, para testes
que preferem injeção a import direto.
"""
import os

import pytest

from tests.jwthelper import PUBLICA_PEM, token_para  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def _ambiente_jwt():
    """Garante que a chave pública do IdP-teste está no ambiente
    antes de qualquer app subir (o caminho de validação é o de
    produção: env var lida por deps.orgao_atual)."""
    assert os.environ.get("JWT_PUBLIC_KEY") == PUBLICA_PEM
    yield


@pytest.fixture
def faz_token():
    """Emissor de tokens RS256 do IdP local de teste."""
    return token_para
