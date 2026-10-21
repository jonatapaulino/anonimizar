"""Fixtures da suíte smoke — nós com repositório sqlite + storage
em memória próprios (T9: bytes nunca tocam o banco)."""
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


@pytest.fixture
async def org_a():
    e, r = await mk_repo("a")
    yield NoTramitacao("tjpa", r, ArmazenamentoMemoria("tjpa"))
    await e.dispose()


@pytest.fixture
async def org_b():
    e, r = await mk_repo("b")
    yield NoTramitacao("mpf.pa", r, ArmazenamentoMemoria("mpf.pa"))
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
