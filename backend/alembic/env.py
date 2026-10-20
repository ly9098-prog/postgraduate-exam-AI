import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401
from alembic import context
from app.core.orm_base import Base

# Canonical model registry. Keep table registration in one place so Alembic,
# runtime initialization, and schema audits see the same metadata.


def include_object(obj, name, type_, reflected, compare_to):
    """Exclude only the SQL-managed pgvector table from autogenerate.

    ``question_embeddings`` uses PostgreSQL's vector type and is intentionally
    maintained by dedicated migrations/raw SQL rather than an ORM mapping.
    """
    if type_ == "table" and name == "question_embeddings":
        return False
    table = getattr(obj, "table", None)
    if table is not None and table.name == "question_embeddings":
        return False
    return True

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    import os
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    return config.get_main_option("sqlalchemy.url")


def _async_database_url(url: str) -> str:
    """Use an async driver when Alembic is running through the async env."""
    if url.startswith("sqlite+pysqlite://"):
        return url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


def run_migrations_offline() -> None:
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(
        _async_database_url(_get_database_url()),
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
