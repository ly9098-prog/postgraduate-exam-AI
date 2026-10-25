"""Request-id claim contract for idempotent practice batch submissions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.practice_session import PracticeSession


@dataclass(slots=True)
class BatchClaimResult:
    session: PracticeSession
    replay: dict | None = None

    @property
    def claimed(self) -> bool:
        return self.replay is None


async def load_committed_replay(
    db: AsyncSession,
    *,
    user_id: int,
    request_id: str,
    payload_hash: str,
    replay: Callable[[Any, str], dict],
) -> dict | None:
    existing = await db.scalar(
        select(PracticeSession).where(
            PracticeSession.user_id == user_id,
            PracticeSession.request_id == request_id,
        )
    )
    if existing is None:
        return None
    return replay(existing, payload_hash)


async def claim_practice_request_id(
    db: AsyncSession,
    *,
    user_id: int,
    session_obj: PracticeSession,
    request_id: str,
    payload_hash: str,
    start_transaction: Callable[[AsyncSession], Awaitable[None]],
    is_unique_violation: Callable[[Exception], bool],
    replay: Callable[[Any, str], dict],
) -> BatchClaimResult:
    await start_transaction(db)
    try:
        # Claim the request id in a savepoint. A concurrent winner must not
        # poison the caller's transaction before we replay its committed result.
        async with db.begin_nested():
            db.add(session_obj)
            await db.flush()
        return BatchClaimResult(session_obj)
    except IntegrityError as exc:
        if not is_unique_violation(exc):
            await db.rollback()
            raise
        winner = await db.scalar(
            select(PracticeSession).where(
                PracticeSession.user_id == user_id,
                PracticeSession.request_id == request_id,
            )
        )
        if winner is None:
            await db.rollback()
            raise
        return BatchClaimResult(winner, replay(winner, payload_hash))
