"""Log the existing best-effort runtime-DDL schema divergence diagnostic."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SessionFactory = Callable[[], AbstractAsyncContextManager["AsyncSession"]]
logger = logging.getLogger("postgraduate-ai")


async def _find_missing_runtime_columns(session_factory: SessionFactory) -> list[str]:
    _runtime_ddl_checks: dict[str, list[str]] = {
        "questions": ["question_hash", "sync_uuid", "sync_version"],
        "question_imports": [
            "question_hash",
            "duplicate_status",
            "duplicate_of_question_id",
            "duplicate_of_import_id",
        ],
        "users": ["is_banned", "deleted_at"],
    }
    _divergence: list[str] = []
    async with session_factory() as _s:
        for _tbl, _cols in _runtime_ddl_checks.items():
            try:
                _row = (
                    await _s.execute(
                        text(
                            'SELECT column_name FROM information_schema.columns WHERE '
                            'table_name=:tbl AND column_name=ANY(:cols)'
                        ),
                        {"tbl": _tbl, "cols": _cols},
                    )
                ).all()
                _found = {r[0] for r in _row}
                for _c in _cols:
                    if _c not in _found:
                        _divergence.append(f"{_tbl}.{_c}")
            except Exception:
                pass
    return _divergence


async def log_runtime_schema_divergence(session_factory: SessionFactory) -> None:
    try:
        from app.core.database import engine

        _sync_engine = engine.sync_engine
        if _sync_engine.dialect.name == "postgresql":
            _divergence = await _find_missing_runtime_columns(session_factory)
            if _divergence:
                logger.warning(
                    "Schema divergence (runtime DDL not in Alembic): %s",
                    ", ".join(_divergence),
                )
            else:
                logger.debug("Schema divergence check: all runtime-DDL columns present")
    except Exception:
        logger.debug("Schema divergence check skipped (not PostgreSQL or transient)")
