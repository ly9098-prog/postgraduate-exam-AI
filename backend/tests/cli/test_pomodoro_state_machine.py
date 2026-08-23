"""Focused Pomodoro state-machine regression checks.

This script stubs only the database module's Base class so it can import the real
pomodoro service without requiring an async SQLite driver. It exercises the actual
pure timeline helpers used by the API service.

Usage: python -m app.cli.test_pomodoro_state_machine
"""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta

from sqlalchemy.orm import DeclarativeBase


class _TestBase(DeclarativeBase):
    pass


_fake_database = types.ModuleType("app.core.database")
_fake_database.Base = _TestBase
sys.modules.setdefault("app.core.database", _fake_database)

from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession  # noqa: E402
from app.services import pomodoro_service as svc  # noqa: E402


PASSED = 0


def check(name: str, condition: bool) -> None:
    global PASSED
    if not condition:
        raise AssertionError(name)
    PASSED += 1
    print(f"  ✓ {name}")


def session_at(start: datetime, *, preset: str = "free", work_minutes: int = 0) -> PomodoroSession:
    return PomodoroSession(
        id=1,
        user_id=1,
        subject_id=1,
        preset=preset,
        work_duration=work_minutes,
        break_duration=0,
        start_time=start,
        expected_end_time=(start + timedelta(minutes=work_minutes)) if work_minutes else None,
        status="running",
        notification_enabled=False,
        notification_sent=False,
        total_paused_sec=0,
    )



class _Result:
    def __init__(self, session):
        self.session = session

    def scalar_one_or_none(self):
        return self.session


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeAsyncSession:
    def __init__(self, session):
        self.session = session

    async def execute(self, _query):
        return _Result(self.session)

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None

    def begin_nested(self):
        return _Nested()


async def async_entrypoint_checks(t0: datetime) -> None:
    existing = session_at(t0, preset="standard", work_minutes=25)
    existing.client_start_id = "pstart_entry123"
    existing.chapter_id = None
    existing.notification_enabled = False
    replay = await svc.start_session(
        _FakeAsyncSession(existing),
        1,
        1,
        None,
        "standard",
        25,
        0,
        notification_enabled=False,
        client_start_id="pstart_entry123",
    )
    check("start_session returns the exact existing row for an idempotent retry", replay is existing)

    try:
        await svc.start_session(
            _FakeAsyncSession(existing),
            1,
            1,
            None,
            "standard",
            50,
            0,
            notification_enabled=False,
            client_start_id="pstart_entry123",
        )
    except svc.PomodoroStartIdempotencyConflictError:
        reused_key_rejected = True
    else:
        reused_key_rejected = False
    check("start_session rejects reusing an idempotency key with changed payload", reused_key_rejected)

    s = session_at(t0)
    s.status = "paused"
    s.paused_at = t0 + timedelta(seconds=20)
    s.pause_intervals = [
        PomodoroPauseInterval(session_id=1, started_at=t0 + timedelta(seconds=20), ended_at=None)
    ]
    await svc.pause_session(
        _FakeAsyncSession(s), 1, 1, client_action_at=t0 + timedelta(seconds=5)
    )
    check("pause_session repairs an earlier delayed same-state pause", s.paused_at == t0 + timedelta(seconds=5))
    check("pause_session moves the canonical open interval start", s.pause_intervals[0].started_at == t0 + timedelta(seconds=5))

    s = session_at(t0)
    s.status = "running"
    s.pause_intervals = [
        PomodoroPauseInterval(
            session_id=1,
            started_at=t0 + timedelta(seconds=5),
            ended_at=t0 + timedelta(seconds=20),
        )
    ]
    await svc.resume_session(
        _FakeAsyncSession(s), 1, 1, client_action_at=t0 + timedelta(seconds=10)
    )
    check("resume_session repairs an earlier delayed same-state resume", s.pause_intervals[0].ended_at == t0 + timedelta(seconds=10))
    check("resume_session recomputes canonical paused seconds", s.total_paused_sec == 5)

    s = session_at(t0)
    s.status = "completed"
    s.end_time = t0 + timedelta(seconds=20)
    s.actual_duration = 20
    s.notification_sent = True
    s.pause_intervals = []
    await svc.complete_session(
        _FakeAsyncSession(s), 1, 1, client_action_at=t0 + timedelta(seconds=5)
    )
    check("complete_session accepts an earlier same-terminal timestamp", s.end_time == t0 + timedelta(seconds=5))
    check("complete_session revises free-timer duration to the earlier terminal", s.actual_duration == 5)

    s = session_at(t0)
    s.status = "completed"
    s.end_time = t0 + timedelta(seconds=20)
    s.actual_duration = 20
    s.notification_sent = True
    s.pause_intervals = []
    final_row = await svc.complete_session(
        _FakeAsyncSession(s), 1, 1, client_action_at=t0 + timedelta(hours=3)
    )
    check("terminal retry with a bad client clock still returns canonical final status", final_row.status == "completed")

    s = session_at(t0)
    s.status = "completed"
    s.end_time = t0 + timedelta(seconds=25)
    s.actual_duration = 25
    s.notification_sent = True
    s.pause_intervals = []
    await svc.interrupt_session(
        _FakeAsyncSession(s), 1, 1, client_action_at=t0 + timedelta(seconds=15)
    )
    check("earlier interrupt supersedes a later completed terminal state", s.status == "interrupted")
    check("earlier interrupt becomes the canonical terminal time", s.end_time == t0 + timedelta(seconds=15))

def main() -> None:
    t0 = datetime(2026, 8, 23, 0, 0, 0)

    s = session_at(t0)
    s.pause_intervals = [
        PomodoroPauseInterval(session_id=1, started_at=t0 + timedelta(seconds=5), ended_at=t0 + timedelta(seconds=20))
    ]
    check(
        "paused duration is clipped at an earlier action cutoff",
        svc._effective_paused_sec(s, t0 + timedelta(seconds=10)) == 5,
    )

    s = session_at(t0)
    s.pause_intervals = [
        PomodoroPauseInterval(session_id=1, started_at=t0 + timedelta(seconds=10), ended_at=t0 + timedelta(seconds=20))
    ]
    svc._apply_terminal_state(
        s,
        requested_status="interrupted",
        action_time=t0 + timedelta(seconds=5),
        server_now=t0 + timedelta(seconds=30),
    )
    check("earlier terminal removes pause events that happened after it", len(s.pause_intervals) == 0)
    check("earlier terminal becomes canonical end time", s.end_time == t0 + timedelta(seconds=5))
    check("earlier interrupt keeps only actual focus before it", s.actual_duration == 5)

    s = session_at(t0)
    s.pause_intervals = [
        PomodoroPauseInterval(session_id=1, started_at=t0 + timedelta(seconds=5), ended_at=t0 + timedelta(seconds=20))
    ]
    svc._apply_terminal_state(
        s,
        requested_status="interrupted",
        action_time=t0 + timedelta(seconds=10),
        server_now=t0 + timedelta(seconds=30),
    )
    check("terminal inside a pause truncates the open history at terminal time", s.pause_intervals[0].ended_at == t0 + timedelta(seconds=10))
    check("focus duration excludes the truncated pause segment", s.actual_duration == 5)

    s = session_at(t0, preset="standard", work_minutes=25)
    s.pause_intervals = []
    check("24-minute countdown completion is not ready", not svc._countdown_completion_ready(s, t0 + timedelta(minutes=24)))
    check("25-minute countdown completion is ready", svc._countdown_completion_ready(s, t0 + timedelta(minutes=25)))

    try:
        svc._resolve_client_action_time(
            s,
            t0 - timedelta(seconds=10),
            t0 + timedelta(minutes=1),
        )
    except svc.PomodoroClockSkewError:
        past_skew = True
    else:
        past_skew = False
    check("explicit action far before session start is rejected as clock skew", past_skew)

    try:
        svc._resolve_client_action_time(
            s,
            t0 + timedelta(minutes=2),
            t0 + timedelta(minutes=1),
        )
    except svc.PomodoroClockSkewError:
        future_skew = True
    else:
        future_skew = False
    check("explicit action far ahead of server time is rejected as clock skew", future_skew)

    s.client_start_id = "pstart_demo123"
    s.chapter_id = None
    s.notification_enabled = False
    check(
        "idempotent start payload comparison accepts the original request",
        svc._start_payload_matches(
            s,
            subject_id=1,
            chapter_id=None,
            preset="standard",
            work_duration=25,
            break_duration=0,
            notification_enabled=False,
        ),
    )
    check(
        "idempotent start payload comparison rejects key reuse with changed duration",
        not svc._start_payload_matches(
            s,
            subject_id=1,
            chapter_id=None,
            preset="standard",
            work_duration=50,
            break_duration=0,
            notification_enabled=False,
        ),
    )

    asyncio.run(async_entrypoint_checks(t0))

    print(f"\nPomodoro state-machine checks: {PASSED}/{PASSED} passed")


if __name__ == "__main__":
    main()
