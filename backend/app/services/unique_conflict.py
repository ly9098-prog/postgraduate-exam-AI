"""Shared transaction helpers for first-write races and SQLite serialization."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def is_unique_violation(exc: IntegrityError) -> bool:
    """Return True only for a database unique-constraint conflict."""
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if code == "23505":
        return True
    message = str(orig)
    return "UNIQUE constraint failed" in message or "duplicate key" in message


async def start_explicit_transaction(db: AsyncSession) -> None:
    """Start SQLite's outer transaction before a savepoint claim.

    SQLite defers BEGIN until the first write. Releasing a savepoint in that
    state can persist the claim even if the caller later rolls back; PostgreSQL
    already provides an outer transaction.
    """
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return
    connection = await db.connection()
    raw_connection = await connection.get_raw_connection()
    if not raw_connection.driver_connection.in_transaction:
        await db.execute(text("BEGIN"))


async def start_sqlite_write_transaction(db: AsyncSession) -> None:
    """Acquire SQLite's writer lock before a read-then-write sequence.

    A deferred ``BEGIN`` still lets concurrent readers observe the same stale
    state. ``BEGIN IMMEDIATE`` serializes the complete sequence at the database
    boundary without changing callers that already own a transaction.
    """
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return
    connection = await db.connection()
    raw_connection = await connection.get_raw_connection()
    if not raw_connection.driver_connection.in_transaction:
        await db.execute(text("BEGIN IMMEDIATE"))
