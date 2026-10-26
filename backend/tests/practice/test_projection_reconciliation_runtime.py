"""Characterize reconciler polling, lock ownership and cancellation cleanup."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.practice import projection_reconciliation_service as service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["held", "unheld", "failure", "cancel", "initial-cancel"]
)
async def test_runner_preserves_poll_lease_session_and_logger_order(monkeypatch, mode):
    from app.core import database, distributed_lock

    events = []
    cancel = asyncio.CancelledError("stop")
    db = object()
    logger = Mock()

    class Session:
        async def __aenter__(self):
            events.append("session-enter")
            return db

        async def __aexit__(self, *error):
            events.append(("session-exit", error[0]))

    class Lease:
        async def __aenter__(self):
            events.append("lease-enter")
            return SimpleNamespace(is_still_held=lambda: mode != "unheld")

        async def __aexit__(self, *error):
            events.append(("lease-exit", error[0]))

    class Lock:
        def __init__(self, name):
            events.append(("lock", name))

        def acquire_and_renew(self, **kwargs):
            events.append(("acquire", kwargs))
            return Lease()

    async def sleep(seconds):
        events.append(("sleep", seconds))
        if seconds == 40 or mode == "initial-cancel":
            raise cancel

    async def reconcile(session, **kwargs):
        assert session is db
        events.append(("reconcile", kwargs))
        if mode == "failure":
            raise RuntimeError("one cycle")
        if mode == "cancel":
            raise cancel
        return {"checked": 1, "errors": 0}

    monkeypatch.setattr(database, "async_session", Session)
    monkeypatch.setattr(distributed_lock, "DistributedLock", Lock)
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    monkeypatch.setattr(service, "reconcile_answer_projections", reconcile)
    monkeypatch.setattr(service, "logger", logger)

    # Use 80s so the initial sleep (60) differs from the cycle sleep (80).
    async def stop_after_cycle(seconds):
        if seconds == 80:
            events.append(("sleep", seconds))
            raise cancel
        await sleep(seconds)

    monkeypatch.setattr(service.asyncio, "sleep", stop_after_cycle)
    with pytest.raises(asyncio.CancelledError) as caught:
        await service.run_answer_projection_reconciler(
            poll_interval=80,
            grace_sec=5,
            batch_size=7,
        )
    assert caught.value is cancel
    assert events[:2] == [("lock", "answer-projection-reconcile"), ("sleep", 60)]
    if mode == "initial-cancel":
        assert len(events) == 2
    else:
        assert events[2:4] == [
            ("acquire", {"ttl": 72, "renew_interval": 24}),
            "lease-enter",
        ]
        if mode == "unheld":
            assert events[4:] == [("lease-exit", None), ("sleep", 80)]
        else:
            error_type = {
                "held": None,
                "failure": RuntimeError,
                "cancel": asyncio.CancelledError,
            }[mode]
            assert events[4:8] == [
                "session-enter",
                ("reconcile", {"batch_size": 7, "grace_sec": 5}),
                ("session-exit", error_type),
                ("lease-exit", error_type),
            ]
            assert events[8:] == ([] if mode == "cancel" else [("sleep", 80)])
    logger.info.assert_any_call("Answer projection reconciler cancelled")
    assert logger.exception.call_count == (1 if mode == "failure" else 0)


@pytest.mark.asyncio
async def test_backlog_retains_pending_cutoff_and_time_serialization():
    from datetime import datetime, timedelta

    now = datetime(2026, 10, 26, 12)
    oldest = now - timedelta(seconds=12)
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                one=lambda: (2, oldest),
            )
        )
    )
    result = await service.get_projection_backlog_metrics(db, grace_sec=5, now=now)
    assert result == {
        "unprojected": 2,
        "oldest_age_sec": 12,
        "oldest_answered_at": service.serialize_utc_datetime(oldest),
    }
    assert db.execute.await_args.args[0].compile().params == {
        "projection_state_1": "pending",
        "answered_at_1": now - timedelta(seconds=5),
    }
