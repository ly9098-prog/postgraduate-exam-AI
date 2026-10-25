"""Contracts for idempotent practice request-id claims."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.practice.batch_claim import (
    claim_practice_request_id,
    load_committed_replay,
)


class Db:
    def __init__(self, *, winner=None, flush_error=None):
        self.winner = winner
        self.flush_error = flush_error
        self.added = []
        self.nested = 0
        self.rolled_back = 0
        self.started = 0

    async def scalar(self, query):
        return self.winner

    def add(self, value):
        self.added.append(value)

    def begin_nested(self):
        self.nested += 1
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def flush(self):
        if self.flush_error is not None:
            raise self.flush_error

    async def rollback(self):
        self.rolled_back += 1


async def start(db):
    db.started += 1


def unique(_exc):
    return True


def not_unique(_exc):
    return False


def replay(session, _payload_hash):
    return {"replayed": session.id}


def unique_error():
    return IntegrityError("duplicate", None, Exception("duplicate"))


@pytest.mark.asyncio
async def test_first_claim_uses_savepoint_and_keeps_transaction_open():
    db = Db()
    session_obj = type("Session", (), {"id": 1})()

    claim = await claim_practice_request_id(
        db,
        user_id=2,
        session_obj=session_obj,
        request_id="request",
        payload_hash="hash",
        start_transaction=start,
        is_unique_violation=unique,
        replay=replay,
    )

    assert claim.claimed
    assert claim.session is session_obj
    assert db.added == [session_obj]
    assert db.nested == 1
    assert db.started == 1
    assert db.rolled_back == 0


@pytest.mark.asyncio
async def test_unique_conflict_replays_winner_without_rollback():
    winner = type("Session", (), {"id": 9})()
    db = Db(winner=winner, flush_error=unique_error())

    claim = await claim_practice_request_id(
        db,
        user_id=2,
        session_obj=type("Session", (), {"id": 1})(),
        request_id="request",
        payload_hash="hash",
        start_transaction=start,
        is_unique_violation=unique,
        replay=replay,
    )

    assert not claim.claimed
    assert claim.replay == {"replayed": 9}
    assert db.rolled_back == 0


@pytest.mark.asyncio
async def test_non_unique_conflict_and_missing_winner_roll_back():
    session_obj = type("Session", (), {"id": 1})()
    for is_unique in (not_unique, unique):
        db = Db(winner=None, flush_error=unique_error())
        with pytest.raises(IntegrityError):
            await claim_practice_request_id(
                db,
                user_id=2,
                session_obj=session_obj,
                request_id="request",
                payload_hash="hash",
                start_transaction=start,
                is_unique_violation=is_unique,
                replay=replay,
            )
        assert db.rolled_back == 1


@pytest.mark.asyncio
async def test_committed_replay_uses_injected_service_semantics():
    existing = type("Session", (), {"id": 8})()
    db = Db(winner=existing)

    assert await load_committed_replay(
        db,
        user_id=2,
        request_id="request",
        payload_hash="hash",
        replay=replay,
    ) == {"replayed": 8}

    db.winner = None
    assert (
        await load_committed_replay(
            db,
            user_id=2,
            request_id="request",
            payload_hash="hash",
            replay=replay,
        )
        is None
    )
