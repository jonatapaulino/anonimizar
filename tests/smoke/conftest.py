"""Fixtures da suíte smoke — nós com repositório sqlite + storage
em memória próprios (T9: bytes nunca tocam o banco).

Assinatura: os nós da suíte rodam COM o par Ed25519 de teste
(`assinantes_teste`) — envelope e ack atravessam assinados como
em produção; `fazer_no(com_assinatura=False)` exercita a camada
de bytes sozinha (defesa em profundidade sem chaves)."""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.service import NoTramitacao          # noqa: F401
from app.storage import ArmazenamentoMemoria  # noqa: F401
from tests.smoke.dbutil import mk_repo        # noqa: F401

DOC = b"EXCELENTISSIMO SENHOR DOUTOR JUIZ - processo de teste."
HASH_DOC = hashlib.sha256(DOC).hexdigest()

_ORGS = ("tjpa", "mpf.pa", "prodepa", "tre-pa")


def assinantes_teste() -> dict:
    """Par Ed25519 determinístico por órgão + diretório público
    compartilhado — seeds derivadas de string fixa (teste, não
    produção). O mesmo diretório assina e verifica em todos os
    nós: quem recebe valida a pública de `env.origem`."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    from app.assinatura import AssinanteEd25519
    seeds = {o: hashlib.sha256(
        f"isaci-teste-sign:{o}".encode()).digest() for o in _ORGS}
    pubs = {o: Ed25519PrivateKey.from_private_bytes(s)
            .public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw)
            for o, s in seeds.items()}
    return {o: AssinanteEd25519(seeds[o], pubs) for o in _ORGS}


@pytest.fixture
def assinantes():
    return assinantes_teste()


@pytest.fixture
async def org_a(assinantes):
    e, r = await mk_repo("a")
    yield NoTramitacao("tjpa", r, ArmazenamentoMemoria("tjpa"),
                       assinante=assinantes["tjpa"])
    await e.dispose()


@pytest.fixture
async def org_b(assinantes):
    e, r = await mk_repo("b")
    yield NoTramitacao("mpf.pa", r, ArmazenamentoMemoria("mpf.pa"),
                       assinante=assinantes["mpf.pa"])
    await e.dispose()


@pytest.fixture
async def fazer_no(assinantes):
    """Fábrica de nó soberano — assinatura ligada por padrão;
    `com_assinatura=False` exercita a camada de bytes sozinha
    (a defesa em profundidade para nó sem par de chaves)."""
    engines = []

    async def _f(orgao: str, com_assinatura: bool = True):
        e, r = await mk_repo(f"n{len(engines)}")
        engines.append(e)
        return NoTramitacao(
            orgao, r, ArmazenamentoMemoria(orgao),
            assinante=assinantes[orgao] if com_assinatura else None)

    yield _f
    for e in engines:
        await e.dispose()


@pytest.fixture
def caso():
    return "5614226-41.2021.8.14.2679"


@pytest.fixture
def payload_criacao(caso):
    """T9: a criação é só metadados + hash DECLARADO — o binário
    sobe depois, pelo endpoint de upload."""
    return dict(
        caso_cnj=caso, destino="mpf.pa", modo="pseudonimizacao",
        hash_documento_sha256=HASH_DOC,
        metadados={"assunto": "dano moral", "sigilo": True},
        idempotency_key="tjpa-2026-0001-abcd",
    )
