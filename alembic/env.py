"""Alembic env — async (asyncpg) em produção, sync/SQLite ok em teste.

URL: DATABASE_URL > sqlalchemy.url do ini.
"""
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get(
        "DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def do_migrations(connection):
    context.configure(connection=connection,
                      target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_online():
    url = _url()
    if "+" not in url.split("://")[0]:       # url simples -> driver async
        raise RuntimeError(
            "DATABASE_URL deve declarar driver async "
            "(postgresql+asyncpg://... | sqlite+aiosqlite://...)")
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(do_migrations)
    await engine.dispose()


def run_offline():
    context.configure(url=_url(), target_metadata=target_metadata,
                      literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
