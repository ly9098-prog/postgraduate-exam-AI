"""Pomodoro V2 canonical migration tests (spec §17): normalization, backfill,
idempotency, and the post-migration verifier.

Covers:
- deterministic centered pause reconstruction (23:00→01:00 actual 5400 -> pause 1800)
- zero-pause / rounding clamp / invalid-skip / --repair-invalid
- active (running/paused) session reconstruction
- idempotency (second run changes 0 rows)
- verifier pass on canonical data and fail on broken intervals
- runtime interpretation: no pause intervals == zero pause (not legacy)
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.time_utils import utcnow


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def isolated_db(monkeypatch_module):
    tmp = tempfile.NamedTemporaryFile(prefix="pomo_migr_test_", suffix=".db", delete=False)
    tmp.close()

    monkeypatch_module.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    monkeypatch_module.setenv("REDIS_URL", "")

    import importlib

    from app.core import config as config_mod
    importlib.reload(config_mod)

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import app.models  # noqa: F401 — registers all models on Base
    from app.core.database import Base

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp.name}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield SimpleNamespace(engine=engine, async_session=session_factory, Base=Base)

    try:
        await engine.dispose()
        os.unlink(tmp.name)
    except Exception:
        pass


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest_asyncio.fixture(autouse=True)
async def reset_tables(isolated_db):
    async with isolated_db.async_session() as db:
        from sqlalchemy import delete

        from app.models.pomodoro import (
            PomodoroPauseInterval,
            PomodoroSession,
            PomodoroSubjectAllocation,
            UserPomodoroSettings,
        )
        from app.models.user import User

        await db.execute(delete(PomodoroPauseInterval))
        # This SQLite fixture does not enable FK cascades; clear child rows explicitly.
        await db.execute(delete(PomodoroSubjectAllocation))
        await db.execute(delete(PomodoroSession))
        await db.execute(delete(UserPomodoroSettings))
        await db.execute(delete(User))
        await db.commit()


async def _make_user(db, openid: str = "openid_migr") -> int:
    from app.models.user import User
    u = User(openid=openid)
    db.add(u)
    await db.flush()
    return u.id


async def _make_subject(db) -> int:
    from sqlalchemy import select

    from app.models.admin import Subject
    subj = await db.scalar(select(Subject).where(Subject.code == "advanced_math"))
    if subj is not None:
        return subj.id
    subj = Subject(
        code="advanced_math", name="高等数学", level=1, path="advanced_math",
        is_active=True, sort_order=0,
    )
    db.add(subj)
    await db.flush()
    return subj.id


def _utc(*parts):
    return datetime(*parts)


def _make_session(uid, subj, start, end, actual, status="completed", total_paused_sec=0):
    from app.models.pomodoro import PomodoroSession
    return PomodoroSession(
        user_id=uid, subject_id=subj, preset="standard",
        work_duration=25, break_duration=5,
        start_time=start, end_time=end,
        actual_duration=actual, status=status,
        total_paused_sec=total_paused_sec,
    )


# ── Normalization pure functions ─────────────────────────────────────────

class TestNormalization:
    def test_backfill_spec_example_centered(self):
        # 23:00 -> 01:00 (next day) = 7200s wall, actual 5400 -> pause 1800
        from app.services.pomodoro_normalization import normalize_completed
        start = _utc(2026, 8, 7, 23, 0, 0)
        end = _utc(2026, 8, 8, 1, 0, 0)
        n = normalize_completed(start, end, 5400)
        assert n.action == "create_pause"
        iv = n.interval
        pause_sec = int((iv[1] - iv[0]).total_seconds())
        assert pause_sec == 1800
        wall = int((end - start).total_seconds())
        assert wall - pause_sec == 5400

    def test_zero_pause_noop(self):
        from app.services.pomodoro_normalization import normalize_completed
        start = _utc(2026, 8, 7, 23, 0, 0)
        end = _utc(2026, 8, 8, 1, 0, 0)
        n = normalize_completed(start, end, 7200)
        assert n.action == "noop"
        assert n.interval is None

    def test_rounding_clamp_within_2s(self):
        from app.services.pomodoro_normalization import normalize_completed
        start = _utc(2026, 8, 7, 23, 0, 0)
        end = _utc(2026, 8, 8, 1, 0, 0)  # wall 7200
        n = normalize_completed(start, end, 7201)
        assert n.action == "clamp_rounding"
        assert n.corrected_actual == 7200
        assert n.interval is None

    def test_invalid_excess_over_2s(self):
        from app.services.pomodoro_normalization import normalize_completed
        start = _utc(2026, 8, 7, 23, 0, 0)
        end = _utc(2026, 8, 8, 1, 0, 0)
        assert normalize_completed(start, end, 7200 + 100).action == "invalid"
        n = normalize_completed(start, end, 7200 + 100, repair_invalid=True)
        assert n.action == "repair"
        assert n.corrected_actual == 7200

    def test_negative_actual(self):
        from app.services.pomodoro_normalization import normalize_completed
        start = _utc(2026, 8, 7, 23, 0, 0)
        end = _utc(2026, 8, 8, 1, 0, 0)
        assert normalize_completed(start, end, -5).action == "invalid"
        n = normalize_completed(start, end, -5, repair_invalid=True)
        assert n.action == "repair"
        assert n.corrected_actual == 0
        assert n.interval == (start, end)  # full wall as pause keeps invariant

    def test_missing_end_time_invalid(self):
        from app.services.pomodoro_normalization import normalize_completed
        assert normalize_completed(_utc(2026, 8, 7, 23, 0), None, 100).action == "invalid"

    def test_end_before_start_invalid(self):
        from app.services.pomodoro_normalization import normalize_completed
        n = normalize_completed(_utc(2026, 8, 8, 1, 0), _utc(2026, 8, 7, 23, 0), 100)
        assert n.action == "invalid"

    def test_active_past_pause_centered(self):
        from app.services.pomodoro_normalization import active_past_pause_interval
        start = _utc(2026, 8, 8, 0, 0, 0)
        now = _utc(2026, 8, 8, 1, 0, 0)  # elapsed 3600
        iv = active_past_pause_interval(start, now, 600)
        assert iv is not None
        assert int((iv[1] - iv[0]).total_seconds()) == 600
        assert start <= iv[0] < iv[1] <= now

    def test_active_past_pause_zero(self):
        from app.services.pomodoro_normalization import active_past_pause_interval
        assert active_past_pause_interval(_utc(2026, 8, 8, 0, 0), _utc(2026, 8, 8, 1, 0), 0) is None


# ── Backfill (script) ────────────────────────────────────────────────────

class TestBackfill:
    @pytest.mark.asyncio
    async def test_backfill_creates_centered_interval(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_legacy")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 5400))
            await db.commit()

        summary = await run_migration(apply=True, session_factory=isolated_db.async_session)
        assert summary["created_pause_intervals"] == 1
        assert summary["total_rows_changed"] == 1

        async with isolated_db.async_session() as db:
            ivs = (await db.execute(
                select(PomodoroPauseInterval).join(PomodoroSession)
            )).scalars().all()
            row = (await db.execute(select(PomodoroSession))).scalar_one()
        assert len(ivs) == 1
        pause_sec = int((ivs[0].ended_at - ivs[0].started_at).total_seconds())
        assert pause_sec == 1800
        wall = int((row.end_time - row.start_time).total_seconds())
        assert wall - pause_sec == row.actual_duration == 5400

    @pytest.mark.asyncio
    async def test_backfill_zero_pause_no_change(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_zero")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 7200))
            await db.commit()

        summary = await run_migration(apply=True, session_factory=isolated_db.async_session)
        assert summary["created_pause_intervals"] == 0
        assert summary["total_rows_changed"] == 0

        async with isolated_db.async_session() as db:
            count = (await db.execute(select(PomodoroPauseInterval))).scalars().all()
            row = (await db.execute(select(PomodoroSession))).scalar_one()
        assert len(count) == 0
        assert row.actual_duration == 7200

    @pytest.mark.asyncio
    async def test_backfill_clamps_rounding(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_round")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 7201))
            await db.commit()

        summary = await run_migration(apply=True, session_factory=isolated_db.async_session)
        assert summary["clamped_rounding"] == 1

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession))).scalar_one()
            ivs = (await db.execute(select(PomodoroPauseInterval))).scalars().all()
        assert row.actual_duration == 7200
        assert len(ivs) == 0

    @pytest.mark.asyncio
    async def test_backfill_invalid_excess_skip_then_repair(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroSession
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_excess")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 7200 + 100))
            await db.commit()

        summary = await run_migration(apply=True, session_factory=isolated_db.async_session)
        assert summary["invalid_skipped"] == 1
        assert summary["repaired"] == 0

        # --repair-invalid clamps actual to wall (zero pause)
        summary2 = await run_migration(apply=True, repair_invalid=True, session_factory=isolated_db.async_session)
        assert summary2["repaired"] == 1

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession))).scalar_one()
        assert row.actual_duration == 7200

    @pytest.mark.asyncio
    async def test_backfill_negative_repair(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_neg")
            subj = await _make_subject(db)
            # Insert a negative-actual completed session (would violate the CHECK
            # constraint, so bypass it — SQLite only).
            await db.execute(text("PRAGMA ignore_check_constraints = ON"))
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), -5))
            await db.commit()

        summary = await run_migration(apply=True, session_factory=isolated_db.async_session)
        assert summary["invalid_skipped"] == 1
        assert summary["repaired"] == 0

        summary2 = await run_migration(apply=True, repair_invalid=True, session_factory=isolated_db.async_session)
        assert summary2["repaired"] == 1

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession))).scalar_one()
            ivs = (await db.execute(select(PomodoroPauseInterval))).scalars().all()
        assert row.actual_duration == 0
        assert len(ivs) == 1
        # full wall as pause -> wall - pause == 0 == actual
        wall = int((row.end_time - row.start_time).total_seconds())
        assert wall - int((ivs[0].ended_at - ivs[0].started_at).total_seconds()) == 0

    @pytest.mark.asyncio
    async def test_backfill_running_past_pause(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_running")
            subj = await _make_subject(db)
            db.add(_make_session(
                uid, subj, utcnow() - timedelta(hours=1), None, None,
                status="running", total_paused_sec=600,
            ))
            await db.commit()

        summary = await run_migration(apply=True, session_factory=isolated_db.async_session)
        assert summary["active_past_pause_intervals"] == 1

        async with isolated_db.async_session() as db:
            ivs = (await db.execute(select(PomodoroPauseInterval))).scalars().all()
        assert len(ivs) == 1
        assert int((ivs[0].ended_at - ivs[0].started_at).total_seconds()) == 600

    @pytest.mark.asyncio
    async def test_backfill_paused_creates_open_interval(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_paused")
            subj = await _make_subject(db)
            row = _make_session(uid, subj, _utc(2026, 8, 8, 0, 0), None, None, status="paused")
            row.paused_at = _utc(2026, 8, 8, 0, 10, 0)
            db.add(row)
            await db.commit()

        summary = await run_migration(apply=True, session_factory=isolated_db.async_session)
        assert summary["active_open_intervals"] == 1

        async with isolated_db.async_session() as db:
            ivs = (await db.execute(select(PomodoroPauseInterval))).scalars().all()
        assert len(ivs) == 1
        assert ivs[0].ended_at is None
        assert ivs[0].started_at == _utc(2026, 8, 8, 0, 10, 0)

    @pytest.mark.asyncio
    async def test_backfill_idempotent_second_run_zero_changes(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_idem")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 5400))
            db.add(_make_session(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 3, 0), 3600))
            running = _make_session(uid, subj, utcnow() - timedelta(hours=1), None, None, status="running", total_paused_sec=300)
            db.add(running)
            await db.commit()

        s1 = await run_migration(apply=True, session_factory=isolated_db.async_session)
        assert s1["total_rows_changed"] > 0

        s2 = await run_migration(apply=True, session_factory=isolated_db.async_session)
        assert s2["total_rows_changed"] == 0, "second run must change 0 rows"

        async with isolated_db.async_session() as db:
            total = len((await db.execute(select(PomodoroSession))).scalars().all())
            iv_count = len((await db.execute(select(PomodoroPauseInterval))).scalars().all())
        assert total == 3
        assert iv_count == 2  # 1 completed pause + 1 running past-pause

    @pytest.mark.asyncio
    async def test_backfill_dry_run_makes_no_writes(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_dry")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 5400))
            await db.commit()

        summary = await run_migration(apply=False, session_factory=isolated_db.async_session)
        assert summary["mode"] == "dry-run"
        assert summary["created_pause_intervals"] == 1  # would create

        async with isolated_db.async_session() as db:
            ivs = (await db.execute(select(PomodoroPauseInterval))).scalars().all()
            row = (await db.execute(select(PomodoroSession))).scalar_one()
        assert len(ivs) == 0, "dry-run must not write"
        assert row.actual_duration == 5400

    @pytest.mark.asyncio
    async def test_backfill_cutoff_respects_created_at(self, isolated_db):
        from sqlalchemy import select, update

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from scripts.migrate_pomodoro_sessions_v2 import run_migration

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "m_cut")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 5400))
            await db.commit()

        cutoff = _utc(2026, 8, 8, 0, 0, 0)
        async with isolated_db.async_session() as db:
            await db.execute(
                update(PomodoroSession).values(created_at=_utc(2026, 8, 8, 2, 0, 0))
            )
            await db.commit()

        summary = await run_migration(apply=True, cutoff=cutoff, session_factory=isolated_db.async_session)
        assert summary["completed_processed"] == 0, "created after cutoff -> untouched"
        assert summary["total_rows_changed"] == 0

        async with isolated_db.async_session() as db:
            ivs = (await db.execute(select(PomodoroPauseInterval))).scalars().all()
        assert len(ivs) == 0


# ── Verifier ─────────────────────────────────────────────────────────────

class TestVerify:
    @pytest.mark.asyncio
    async def test_verify_passes_on_canonical_db(self, isolated_db):

        from scripts.migrate_pomodoro_sessions_v2 import run_migration
        from scripts.verify_pomodoro_v2_migration import verify

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "v_ok")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 5400))
            db.add(_make_session(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 3, 0), 3600))
            await db.commit()

        await run_migration(apply=True, session_factory=isolated_db.async_session)

        ok = await verify(session_factory=isolated_db.async_session)
        assert ok is True

    @pytest.mark.asyncio
    async def test_verify_fails_on_mismatched_interval(self, isolated_db):

        from app.models.pomodoro import PomodoroPauseInterval
        from scripts.verify_pomodoro_v2_migration import verify

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "v_bad")
            subj = await _make_subject(db)
            row = _make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 5400)
            db.add(row)
            await db.flush()
            db.add(PomodoroPauseInterval(
                session_id=row.id,
                started_at=_utc(2026, 8, 7, 23, 30, 0),
                ended_at=_utc(2026, 8, 7, 23, 40, 0),  # only 600s pause, actual needs 1800
            ))
            await db.commit()

        ok = await verify(session_factory=isolated_db.async_session)
        assert ok is False

    @pytest.mark.asyncio
    async def test_verify_fails_on_open_interval_on_completed(self, isolated_db):

        from app.models.pomodoro import PomodoroPauseInterval
        from scripts.verify_pomodoro_v2_migration import verify

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "v_open")
            subj = await _make_subject(db)
            row = _make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 7200)
            db.add(row)
            await db.flush()
            db.add(PomodoroPauseInterval(
                session_id=row.id, started_at=_utc(2026, 8, 7, 23, 30, 0), ended_at=None,
            ))
            await db.commit()

        ok = await verify(session_factory=isolated_db.async_session)
        assert ok is False

    @pytest.mark.asyncio
    async def test_verify_fails_on_legacy_fallback_need(self, isolated_db):
        # completed session with a pause gap but no intervals -> needs legacy fallback
        from scripts.verify_pomodoro_v2_migration import verify

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "v_legacy")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 23, 0), _utc(2026, 8, 8, 1, 0), 5400))
            await db.commit()

        ok = await verify(session_factory=isolated_db.async_session)
        assert ok is False


# ── Runtime: no pause intervals == zero pause ────────────────────────────

class TestRuntimeCanonical:
    @pytest.mark.asyncio
    async def test_complete_is_server_authoritative_no_client_override(self, isolated_db, monkeypatch):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroSession
        from app.services import pomodoro_service as svc

        start = _utc(2026, 8, 7, 10, 0)
        clock = {"now": start}
        monkeypatch.setattr(svc, "utcnow", lambda: clock["now"])
        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "r_authority")
            subj = await _make_subject(db)
            session = await svc.start_session(db, uid, subj, None, "standard", 25, 5)
            sid = session.id
            await db.commit()

        async with isolated_db.async_session() as db:
            with pytest.raises(svc.PomodoroNotReadyError, match="POMODORO_NOT_READY"):
                await svc.complete_session(db, sid, uid)
            await db.rollback()

        clock["now"] = start + timedelta(minutes=25)
        async with isolated_db.async_session() as db:
            await svc.complete_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.status == "completed"
        # no intervals -> zero pause -> actual == wall clock
        wall = int((row.end_time - row.start_time).total_seconds())
        assert row.actual_duration == wall
        assert wall == 1500
        assert row.total_paused_sec == 0

    @pytest.mark.asyncio
    async def test_pause_then_complete_uses_interval_seconds(self, isolated_db, monkeypatch):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from app.services import pomodoro_service as svc

        start = _utc(2026, 8, 7, 11, 0)
        clock = {"now": start}
        monkeypatch.setattr(svc, "utcnow", lambda: clock["now"])
        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "r_pause")
            subj = await _make_subject(db)
            session = await svc.start_session(db, uid, subj, None, "standard", 25, 5)
            sid = session.id
            await db.commit()

        clock["now"] = start + timedelta(minutes=25)
        async with isolated_db.async_session() as db:
            await svc.pause_session(db, sid, uid)
            interval = (await db.execute(
                select(PomodoroPauseInterval).where(
                    PomodoroPauseInterval.session_id == sid,
                    PomodoroPauseInterval.ended_at.is_(None),
                )
            )).scalar_one()
            assert interval.started_at == clock["now"]
            await db.commit()

        clock["now"] = start + timedelta(minutes=29)
        async with isolated_db.async_session() as db:
            await svc.complete_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()
        wall = int((row.end_time - row.start_time).total_seconds())
        assert wall == 1740
        assert row.total_paused_sec == 240
        # canonical invariant holds exactly: wall - pause == actual
        assert row.actual_duration == wall - row.total_paused_sec
        assert row.actual_duration == 1500
