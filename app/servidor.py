"""Entrypoint de produção do nó — `uvicorn app.servidor:app`.

Resolve por env: ORGAO (identidade soberana do nó), DATABASE_URL
(postgresql+asyncpg://... — TLS via TLS_CA_BUNDLE), MINIO_URL,
RABBITMQ_URL, VAULT_* e E2E_* (ver deploy/compose.yaml).
"""
from __future__ import annotations

import os

from app.main import create_app


async def _repo_factory():
    """Engine+repo do nó — TLS no link asyncpg quando
    TLS_CA_BUNDLE está definida (rede `interna`, CA privada)."""
    from sqlalchemy.ext.asyncio import (async_sessionmaker,
                                        create_async_engine)
    from app.repository import RepositorioSQL
    from app.tls_interno import ctx_cliente
    kw = {}
    ctx = ctx_cliente()
    if ctx is not None:
        kw["connect_args"] = {"ssl": ctx}
    e = create_async_engine(os.environ["DATABASE_URL"], **kw)
    return e, RepositorioSQL(
        async_sessionmaker(e, expire_on_commit=False))


app = create_app(os.environ.get("ORGAO", "no-local"),
                 repo_factory=_repo_factory)
