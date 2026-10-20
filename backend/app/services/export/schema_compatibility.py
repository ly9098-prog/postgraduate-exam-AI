"""Preserve legacy export idempotency schema compatibility at startup."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy import Connection
    from sqlalchemy.engine.interfaces import ReflectedIndex, ReflectedUniqueConstraint
    from sqlalchemy.engine.reflection import Inspector
    from sqlalchemy.ext.asyncio import AsyncSession

SessionFactory = Callable[[], AbstractAsyncContextManager["AsyncSession"]]
logger = logging.getLogger("postgraduate-ai")


def _read_sqlite_export_index_state(
    sync_conn: Connection,
    _sa_inspect: Callable[[Connection], Inspector],
) -> tuple[list[ReflectedIndex], list[ReflectedUniqueConstraint], bool] | None:
    _inspector = _sa_inspect(sync_conn)
    if "export_tasks" not in _inspector.get_table_names():
        return None
    _ix_list = _inspector.get_indexes("export_tasks")
    _unique_constraints = _inspector.get_unique_constraints("export_tasks")
    _unique_indexes = [
        _ix
        for _ix in _ix_list
        if _ix.get("column_names", []) == ["idempotency_key"] and _ix.get("unique")
    ]
    _matching_constraints = [
        _constraint
        for _constraint in _unique_constraints
        if _constraint.get("column_names", []) == ["idempotency_key"]
    ]
    _has_plain_index = any(
        (
            _ix.get("column_names", []) == ["idempotency_key"]
            and (not _ix.get("unique"))
            for _ix in _ix_list
        )
    )
    if not _unique_indexes and (not _matching_constraints):
        return None
    return (_unique_indexes, _matching_constraints, _has_plain_index)


def _repair_sqlite_export_idempotency_index(
    sync_conn: Connection,
    _sa_inspect: Callable[[Connection], Inspector],
) -> bool:
    """Inspect/repair SQLite through AsyncConnection.run_sync."""
    state = _read_sqlite_export_index_state(sync_conn, _sa_inspect)
    if state is None:
        return False
    _unique_indexes, _matching_constraints, _has_plain_index = state
    # Batch mode also handles SQLite's table-level UNIQUE constraints.
    from alembic.runtime.migration import MigrationContext

    from alembic import op

    _ctx = MigrationContext.configure(sync_conn)
    _op = op.Operations(_ctx)
    naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    with _op.batch_alter_table(
        "export_tasks", naming_convention=naming_convention
    ) as _batch:
        for _constraint in _matching_constraints:
            _batch.drop_constraint(
                _constraint.get("name") or "uq_export_tasks_idempotency_key",
                type_="unique",
            )
        for _ix in _unique_indexes:
            _batch.drop_index(_ix["name"])
        if not _has_plain_index:
            _batch.create_index("ix_export_tasks_idempotency_key", ["idempotency_key"])
    return True


async def _repair_postgres_export_index(session_factory: SessionFactory) -> None:
    async with session_factory() as _s:
        _row = (
            await _s.execute(
                text(
                    "\n"
                    "                    SELECT conname FROM pg_constraint\n"
                    "                    WHERE conrelid = 'export_tasks'::regclass\n"
                    "                    AND conname LIKE '%idempotency_key%'\n"
                    "                    AND contype = 'u'\n"
                    "                "
                )
            )
        ).scalar_one_or_none()
        if _row:
            _quoted_constraint = str(_row).replace('"', '""')
            await _s.execute(
                text(f'ALTER TABLE export_tasks DROP CONSTRAINT "{_quoted_constraint}"')
            )
            await _s.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_export_tasks_idempotency_key ON "
                    "export_tasks (idempotency_key)"
                )
            )
            await _s.commit()
            logger.info(
                "Fixed residual UNIQUE constraint on export_tasks.idempotency_key (PostgreSQL)"
            )


async def repair_export_idempotency_schema(session_factory: SessionFactory) -> None:
    try:
        from app.core.database import engine as _db_engine

        _dialect = _db_engine.dialect.name
        if _dialect == "sqlite":
            from sqlalchemy import inspect as _sa_inspect

            # Keep reflection and DDL inside the async driver's run_sync adapter.
            async with _db_engine.begin() as _conn:
                _sqlite_index_repaired = await _conn.run_sync(
                    _repair_sqlite_export_idempotency_index, _sa_inspect
                )
            if _sqlite_index_repaired:
                logger.info(
                    "Fixed residual UNIQUE constraint on export_tasks.idempotency_key (SQLite)"
                )
        elif _dialect == "postgresql":
            await _repair_postgres_export_index(session_factory)
    except Exception as _exc:
        logger.warning(
            "Failed to fix idempotency_key UNIQUE constraint (%s: %s) "
            "(non-fatal, application-level fallback active)",
            type(_exc).__name__,
            _exc,
        )
