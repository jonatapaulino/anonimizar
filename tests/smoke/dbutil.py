"""Fábrica de repositório para testes.

Padrão (TDD rápido): sqlite em memória por nó — cada nó é uma
instância soberana com seu próprio engine (StaticPool mantém a
conexão única viva entre sessions).

Com TEST_DB_URL (ex.: postgresql+asyncpg://...): usa o banco real —
o schema deve existir (alembic upgrade head) e as linhas são
limpas a cada fixture para isolamento entre testes.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (async_sessionmaker,
                                    create_async_engine)

from app.repository import (RepositorioSQL, criar_tabelas,
                            repo_sqlite_memoria)

# ordem respeita FKs (filhas primeiro)
_TABELAS = ("outbox_eventos", "idempotencia",
            "trilha_auditoria", "tramitacoes")


class FakeUpload:
    """Async-readable com a cara de UploadFile — para testar o
    upload no nível serviço sem multipart."""
    def __init__(self, b: bytes):
        import io
        self._f = io.BytesIO(b)

    async def read(self, n=-1):
        return self._f.read(n)


async def _limpar(e):
    async with e.begin() as c:
        for t in _TABELAS:
            await c.execute(text(f"DELETE FROM {t}"))


def _url_para(no: str) -> str | None:
    """Soberania por nó: TEST_DB_URL_A/_B explícitas, senão
    TEST_DB_URL para o nó A e TEST_DB_URL+'_b' para o B (o script
    de integração cria o database tramitacao_b)."""
    url = os.environ.get(f"TEST_DB_URL_{no.upper()}")
    if url:
        return url
    base = os.environ.get("TEST_DB_URL")
    if not base:
        return None
    return base if no == "a" else base + "_b"


async def mk_repo(no: str = "a"):
    """Retorna (engine, repo) pronto. SQLite: cria o schema em
    memória. Postgres (TEST_DB_URL*): schema via alembic — só limpa
    as linhas, para exercitar o schema migrado de verdade.
    O repo ganha `._engine` — backdoor de teste para asserções
    SQL diretas (contagem em tabelas, outbox etc.)."""
    url = _url_para(no)
    if url:
        e = create_async_engine(url)
        await _limpar(e)
        r = RepositorioSQL(
            async_sessionmaker(e, expire_on_commit=False))
        r._engine = e
        return e, r
    e, r = repo_sqlite_memoria()
    await criar_tabelas(e)
    r._engine = e
    return e, r
