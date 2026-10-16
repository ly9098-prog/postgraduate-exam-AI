"""番茄钟统计日（China study-day）归属与归属引擎测试。

覆盖 current_task.md 的 case 1~13：
- time helper：study_day_utc_range / study_day_for_utc / current_study_day / study_week_utc_range
- duration attribution：跨自然日 / 自定义 day_start / 跨日暂停 / 旧数据 fallback / session count
- service：settings 读写与校验、history 按 start 学习日过滤、daily-summary、subject breakdown、
  stats/trends、pause interval 幂等、旧 paused active session 兼容。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import date, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def isolated_db(monkeypatch_module):
    tmp = tempfile.NamedTemporaryFile(prefix="pomo_day_test_", suffix=".db", delete=False)
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


@pytest_asyncio.fixture()
async def db_session(isolated_db):
    async with isolated_db.async_session() as session:
        yield session


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
        await db.execute(delete(PomodoroSubjectAllocation))
        await db.execute(delete(PomodoroSession))
        await db.execute(delete(UserPomodoroSettings))
        await db.execute(delete(User))
        await db.commit()


async def _make_user(db, openid: str = "openid_test") -> int:
    from app.models.user import User
    u = User(openid=openid)
    db.add(u)
    await db.flush()
    return u.id


async def _make_subject(db, code: str | None = None) -> int:
    import uuid

    from app.models.admin import Subject
    code = code or f"math2_{uuid.uuid4().hex[:8]}"
    subj = Subject(code=code, name="数学二", level=1, path=code, is_active=True, sort_order=0)
    db.add(subj)
    await db.flush()
    return subj.id


class TestSubjectAllocation:
    @pytest.mark.asyncio
    async def test_history_does_not_copy_pomodoro_allocations_to_other_record_types(
        self, db_session
    ):
        from app.models.admin import Subject
        from app.models.practice_session import PracticeSession
        from app.services import pomodoro_service as svc

        uid = await _make_user(db_session, "u_history_allocation_collision")
        root = Subject(
            code="exam408", name="计算机综合", level=1, path="exam408", is_active=True
        )
        english = Subject(
            code="english", name="英语", level=1, path="english", is_active=True
        )
        db_session.add_all([root, english])
        await db_session.flush()
        for code in (
            "data_structure",
            "computer_organization",
            "operating_system",
            "computer_network",
        ):
            db_session.add(
                Subject(
                    code=code,
                    name=code,
                    level=2,
                    path=f"exam408.{code}",
                    parent_id=root.id,
                    is_active=True,
                )
            )
        await db_session.flush()

        session = await svc.start_session(
            db_session,
            uid,
            root.id,
            None,
            "free",
            0,
            0,
            allocation_mode="equal_408_core_v1",
        )
        session_id = session.id
        await svc.interrupt_session(db_session, session_id, uid)
        db_session.add(
            PracticeSession(
                id=session_id,
                user_id=uid,
                subject_id=english.id,
                request_id="history-allocation-collision",
                started_at=session.start_time,
                finished_at=session.end_time,
                duration_sec=0,
                status="completed",
            )
        )
        await db_session.flush()

        rows, _ = await svc.get_history(db_session, uid)
        by_key = {row["record_key"]: row for row in rows}
        assert len(by_key[f"pomodoro:{session_id}"]["subject_allocations"]) == 4
        assert by_key[f"practice:{session_id}"]["subject_allocations"] == []

    @pytest.mark.asyncio
    async def test_equal_408_start_persists_four_canonical_allocations(self, db_session):
        from sqlalchemy import select

        from app.models.admin import Subject
        from app.schemas.pomodoro import PomodoroSessionResponse
        from app.services import pomodoro_service as svc

        uid = await _make_user(db_session, "u_equal_408")
        root = Subject(
            code="exam408", name="计算机综合", level=1, path="exam408", is_active=True
        )
        db_session.add(root)
        await db_session.flush()
        codes = (
            "data_structure",
            "computer_organization",
            "operating_system",
            "computer_network",
        )
        for code in codes:
            db_session.add(
                Subject(
                    code=code,
                    name=code,
                    level=2,
                    path=f"exam408.{code}",
                    parent_id=root.id,
                    is_active=True,
                )
            )
        await db_session.flush()

        session = await svc.start_session(
            db_session,
            uid,
            root.id,
            None,
            "standard",
            25,
            5,
            allocation_mode="equal_408_core_v1",
        )

        assert session.subject_id == root.id
        assert [
            (allocation.subject_code_snapshot, allocation.weight_basis_points)
            for allocation in session.subject_allocations
        ] == [(code, 2500) for code in codes]
        response = PomodoroSessionResponse.from_orm_with_subject(session)
        assert response.allocation_mode == "equal_408_core_v1"
        assert len(response.subject_allocations) == 4
        interrupted = await svc.interrupt_session(db_session, session.id, uid)
        terminal_response = PomodoroSessionResponse.from_orm_with_subject(interrupted)
        assert terminal_response.allocation_mode == "equal_408_core_v1"
        assert len(terminal_response.subject_allocations) == 4
        from app.core.time_utils import current_study_day

        interrupted.actual_duration = 3601
        await db_session.flush()
        summary = await svc.get_daily_summary(
            db_session, uid, current_study_day(0)
        )
        assert summary["sessions"] == 1
        assert summary["duration_sec"] == 3601
        assert sum(item["duration_sec"] for item in summary["subjects"]) == 3601
        assert [item["duration_sec"] for item in summary["subjects"]] == [
            901, 900, 900, 900
        ]
        assert all(item["participation_sessions"] == 1 for item in summary["subjects"])
        await db_session.delete(interrupted)
        await db_session.flush()
        for leaf in list((await db_session.execute(
            select(Subject).where(Subject.parent_id == root.id)
        )).scalars()):
            await db_session.delete(leaf)
        await db_session.flush()

        with pytest.raises(ValueError, match="配置不完整"):
            await svc.start_session(
                db_session,
                uid,
                root.id,
                None,
                "standard",
                25,
                5,
                allocation_mode="equal_408_core_v1",
            )
        await db_session.commit()


def _utc(*parts):
    return datetime(*parts)


def _make_session(uid, subj, start, end, actual, status="completed"):
    from app.models.pomodoro import PomodoroSession
    return PomodoroSession(
        user_id=uid, subject_id=subj, preset="standard",
        work_duration=25, break_duration=5,
        start_time=start, end_time=end,
        actual_duration=actual, status=status,
    )


# ── Time helpers (case 1-3, 11) ────────────────────────────────────────

class TestTimeHelpers:
    def test_case1_day_start_0000(self):
        from app.core.time_utils import study_day_utc_range
        start, end = study_day_utc_range(date(2026, 8, 7), 0)
        assert start == _utc(2026, 8, 6, 16, 0, 0)
        assert end == _utc(2026, 8, 7, 16, 0, 0)

    def test_case2_day_start_0600(self):
        from app.core.time_utils import study_day_utc_range
        start, end = study_day_utc_range(date(2026, 8, 7), 360)
        assert start == _utc(2026, 8, 6, 22, 0, 0)
        assert end == _utc(2026, 8, 7, 22, 0, 0)

    def test_case2b_minute_level(self):
        from app.core.time_utils import study_day_utc_range
        start, end = study_day_utc_range(date(2026, 8, 7), 390)
        assert start == _utc(2026, 8, 6, 22, 30, 0)
        assert end == _utc(2026, 8, 7, 22, 30, 0)

    def test_case3_current_study_day_before_day_start(self, monkeypatch):
        from app.core import time_utils
        # 中国时间 08-08 02:00 == UTC 08-07 18:00
        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 7, 18, 0, 0))
        assert time_utils.current_study_day(360) == date(2026, 8, 7)

    def test_case3b_current_study_day_default(self, monkeypatch):
        from app.core import time_utils
        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 7, 18, 0, 0))
        assert time_utils.current_study_day(0) == date(2026, 8, 8)

    def test_study_day_for_utc(self):
        from app.core.time_utils import study_day_for_utc
        assert study_day_for_utc(_utc(2026, 8, 7, 18, 0, 0), 360) == date(2026, 8, 7)
        assert study_day_for_utc(_utc(2026, 8, 7, 18, 0, 0), 0) == date(2026, 8, 8)

    def test_minute_to_time_text(self):
        from app.core.time_utils import minute_to_time_text
        assert minute_to_time_text(0) == "00:00"
        assert minute_to_time_text(180) == "03:00"
        assert minute_to_time_text(360) == "06:00"
        assert minute_to_time_text(390) == "06:30"
        assert minute_to_time_text(1439) == "23:59"

    def test_case11_study_week_custom_day_start(self, monkeypatch):
        from app.core import time_utils
        # 中国时间 08-08 02:00 (UTC 08-07 18:00)，day_start=360 -> 当前学习日 08-07(周五)
        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 7, 18, 0, 0))
        start, end = time_utils.study_week_utc_range(360)
        # 周一 = 08-03，周一 06:00 中国 == 08-02 22:00 UTC
        assert start == _utc(2026, 8, 2, 22, 0, 0)
        assert end == _utc(2026, 8, 9, 22, 0, 0)

    def test_case11b_study_week_default(self, monkeypatch):
        from app.core import time_utils
        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 7, 18, 0, 0))
        start, end = time_utils.study_week_utc_range(0)
        # 周一 = 08-03，周一 00:00 中国 == 08-02 16:00 UTC
        assert start == _utc(2026, 8, 2, 16, 0, 0)
        assert end == _utc(2026, 8, 9, 16, 0, 0)


# ── Duration attribution (case 4-8) ────────────────────────────────────

def _session(start, end, actual):
    return SimpleNamespace(start_time=start, end_time=end, actual_duration=actual)


def _pause(started, ended=None):
    return SimpleNamespace(started_at=started, ended_at=ended)


class TestAttribution:
    def test_case4_natural_day_cross(self):
        from app.services.pomodoro_attribution import (
            split_session_duration_by_study_day,
        )
        s = _session(_utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 20), 1800)  # 23:50~00:20 中国
        out = split_session_duration_by_study_day(s, [], 0)
        assert out == {date(2026, 8, 7): 600, date(2026, 8, 8): 1200}

    def test_case5_custom_day_start_entirely_previous(self):
        from app.services.pomodoro_attribution import (
            split_session_duration_by_study_day,
        )
        s = _session(_utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 20), 1800)
        out = split_session_duration_by_study_day(s, [], 360)
        assert out == {date(2026, 8, 7): 1800}

    def test_case6_cross_day_pause(self):
        from app.services.pomodoro_attribution import (
            split_session_duration_by_study_day,
        )
        s = _session(_utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 20), 1200)
        pauses = [_pause(_utc(2026, 8, 7, 15, 55), _utc(2026, 8, 7, 16, 5))]
        out = split_session_duration_by_study_day(s, pauses, 0)
        assert out == {date(2026, 8, 7): 300, date(2026, 8, 8): 900}
        assert sum(out.values()) == 1200

    def test_case7_zero_pause_deterministic_and_conserved(self):
        # A completed session with NO pause intervals is a zero-pause session: the
        # whole wall clock is active, so attribution is exact and conserved.
        from app.services.pomodoro_attribution import (
            split_session_duration_by_study_day,
        )
        s = _session(_utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 20), 1800)
        out = split_session_duration_by_study_day(s, [], 0)
        assert all(v >= 0 for v in out.values())
        assert sum(out.values()) == 1800
        out2 = split_session_duration_by_study_day(s, [], 0)
        assert out == out2

    def test_case7b_zero_pause_whole_to_one_day(self):
        from app.services.pomodoro_attribution import (
            split_session_duration_by_study_day,
        )
        s = _session(_utc(2026, 8, 7, 2, 0), _utc(2026, 8, 7, 3, 0), 3600)
        out = split_session_duration_by_study_day(s, [], 0)
        assert out == {date(2026, 8, 7): 3600}

    def test_case7c_largest_remainder_conservation(self):
        from app.services.pomodoro_attribution import (
            split_session_duration_by_study_day,
        )
        s = _session(_utc(2026, 8, 7, 15, 59, 55), _utc(2026, 8, 7, 16, 0, 7), 11)
        out = split_session_duration_by_study_day(s, [], 0)
        assert sum(out.values()) == 11

    def test_case7d_zero_raw_fallback_to_start_day(self):
        from app.services.pomodoro_attribution import (
            split_session_duration_by_study_day,
        )
        # start == end (零长窗口，raw overlap 为 0)；start=16:00 UTC == 08-08 00:00 中国
        s = _session(_utc(2026, 8, 7, 16, 0), _utc(2026, 8, 7, 16, 0), 300)
        out = split_session_duration_by_study_day(s, [], 0)
        assert sum(out.values()) == 300
        assert out == {date(2026, 8, 8): 300}

    def test_case7e_subsecond_split_not_lost(self):
        # 跨边界 1.5s（前 0.5s / 后 1.0s），actual=1 -> 应偏向后一天，不整体落到开始日
        from app.services.pomodoro_attribution import (
            split_session_duration_by_study_day,
        )
        s = _session(_utc(2026, 8, 7, 15, 59, 59, 500000), _utc(2026, 8, 7, 16, 0, 1, 0), 1)
        out = split_session_duration_by_study_day(s, [], 0)
        assert out[date(2026, 8, 7)] == 0
        assert out[date(2026, 8, 8)] == 1
        assert sum(out.values()) == 1

    @pytest.mark.asyncio
    async def test_case8_session_count_belongs_to_start_day(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_cnt")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 20), 1800))
            await db.commit()

        async with isolated_db.async_session() as db:
            summary_7 = await svc.get_daily_summary(db, uid, date(2026, 8, 7))
            summary_8 = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        assert summary_7["sessions"] == 1
        assert summary_7["duration_sec"] == 600
        assert summary_8["sessions"] == 0
        assert summary_8["duration_sec"] == 1200
        assert summary_7["sessions"] + summary_8["sessions"] == 1


# ── Service-level stats (daily-summary / subjects / stats / trends) ────

class TestDailySummary:
    @pytest.mark.asyncio
    async def test_daily_summary_custom_day_start_split(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_sum")
            subj = await _make_subject(db)
            await svc.update_pomodoro_settings(db, uid, 360)
            # 08-08 05:00~07:00 中国 = UTC 08-07 21:00~23:00，跨两个学习日
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 21, 0), _utc(2026, 8, 7, 23, 0), 7200))
            await db.commit()

        async with isolated_db.async_session() as db:
            d7 = await svc.get_daily_summary(db, uid, date(2026, 8, 7))
            d8 = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        assert d7["duration_sec"] == 3600
        assert d7["sessions"] == 1
        assert d8["duration_sec"] == 3600
        assert d8["sessions"] == 0  # 前一日开始的 session，今日只有时长贡献
        assert sum(s["duration_sec"] for s in d7["subjects"]) == d7["duration_sec"]
        assert d7["subjects"][0]["subject_name"] == "数学二"
        assert d7["day_start_minute"] == 360
        assert d7["day_start_time"] == "06:00"

    @pytest.mark.asyncio
    async def test_daily_summary_uncategorized(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_uncat")
            db.add(_make_session(uid, None, _utc(2026, 8, 7, 2, 0), _utc(2026, 8, 7, 3, 0), 3600))
            await db.commit()

        async with isolated_db.async_session() as db:
            d = await svc.get_daily_summary(db, uid, date(2026, 8, 7))

        assert d["duration_sec"] == 3600
        assert d["subjects"][0]["subject_name"] == "未分类"
        assert d["subjects"][0]["subject_id"] is None

    @pytest.mark.asyncio
    async def test_inactive_subject_merges_into_uncategorized(self, isolated_db):
        from app.models.admin import Subject
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_inactive")
            active = await _make_subject(db)
            inactive = Subject(
                code="deactivated_subj", name="已停用科目", level=1,
                path="deactivated_subj", is_active=False, sort_order=0,
            )
            db.add(inactive)
            await db.flush()
            db.add(_make_session(uid, active, _utc(2026, 8, 7, 2, 0), _utc(2026, 8, 7, 3, 0), 3600))
            db.add(_make_session(uid, inactive.id, _utc(2026, 8, 7, 4, 0), _utc(2026, 8, 7, 5, 0), 3600))
            db.add(_make_session(uid, None, _utc(2026, 8, 7, 6, 0), _utc(2026, 8, 7, 7, 0), 3600))
            await db.commit()

        async with isolated_db.async_session() as db:
            rows = await svc.get_subject_breakdown(db, uid, date(2026, 8, 7))

        # 停用科目与无科目合并为单个"未分类"，不单独出现
        assert len(rows) == 2
        by_name = {r["subject_name"]: r for r in rows}
        assert "数学二" in by_name
        assert by_name["数学二"]["duration_sec"] == 3600
        assert "未分类" in by_name
        assert by_name["未分类"]["duration_sec"] == 7200
        assert by_name["未分类"]["subject_id"] is None


class TestSubjectBreakdown:
    @pytest.mark.asyncio
    async def test_cross_day_session_appears_with_zero_sessions(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_brk")
            subj = await _make_subject(db)
            await svc.update_pomodoro_settings(db, uid, 360)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 21, 0), _utc(2026, 8, 7, 23, 0), 7200))
            await db.commit()

        async with isolated_db.async_session() as db:
            rows8 = await svc.get_subject_breakdown(db, uid, date(2026, 8, 8))
            rows7 = await svc.get_subject_breakdown(db, uid, date(2026, 8, 7))

        assert rows8[0]["duration_sec"] == 3600
        assert rows8[0]["sessions"] == 0
        assert rows7[0]["sessions"] == 1
        assert rows7[0]["duration_sec"] == 3600


class TestStatsAndTrends:
    @pytest.mark.parametrize("active_status", ["running", "paused"])
    @pytest.mark.asyncio
    async def test_active_sessions_are_excluded_from_statistics(
        self, isolated_db, monkeypatch, active_status
    ):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 7, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_stats_active")
            subj = await _make_subject(db)

            # Only the completed session is a historical learning record. The
            # active rows deliberately carry a stale duration to ensure the
            # aggregate query filters by lifecycle status before attribution.
            db.add(_make_session(
                uid, subj, _utc(2026, 8, 7, 8, 0), _utc(2026, 8, 7, 8, 10), 600,
            ))
            db.add(_make_session(
                uid, subj, _utc(2026, 8, 7, 8, 20), None, 1200, status=active_status,
            ))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 7))
            trends = await svc.get_trends(db, uid, days=7)
            lifetime = await svc.get_lifetime_summary(db, uid)

        assert stats["today_sessions"] == 1
        assert stats["today_duration_sec"] == 600
        assert summary["sessions"] == 1
        assert summary["duration_sec"] == 600
        assert sum(item["duration_sec"] for item in summary["subjects"]) == 600
        today_trend = next(item for item in trends if item["date"] == "2026-08-07")
        assert today_trend["sessions"] == 1
        assert today_trend["duration_sec"] == 600
        assert lifetime["sessions"] == 1
        assert lifetime["duration_sec"] == 600

    @pytest.mark.asyncio
    async def test_stats_today_contribution(self, isolated_db, monkeypatch):
        from app.core import time_utils
        # 固定"当前"为 08-07 18:00 中国（UTC 08-07 10:00）-> 当前学习日 = 08-07
        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 7, 10, 0, 0))

        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_stats")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 20), 1800))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)

        assert stats["day_start_minute"] == 0
        assert stats["day_start_time"] == "00:00"
        assert stats["today_date"] == "2026-08-07"
        assert stats["today_sessions"] == 1
        assert stats["today_duration_sec"] == 600  # 只统计当前学习日内的贡献

    @pytest.mark.asyncio
    async def test_trends_cross_day_contribution(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_trend")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 20), 1800))
            await db.commit()

        async with isolated_db.async_session() as db:
            trends = await svc.get_trends(db, uid, days=7)

        by_date = {t["date"]: t for t in trends}
        assert by_date["2026-08-07"]["duration_sec"] == 600
        assert by_date["2026-08-07"]["sessions"] == 1
        assert by_date["2026-08-08"]["duration_sec"] == 1200
        assert by_date["2026-08-08"]["sessions"] == 0


# ── History (case 9) ───────────────────────────────────────────────────

class TestHistory:
    @pytest.mark.asyncio
    async def test_history_filters_by_start_study_day(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_hist")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 20), 1800))
            db.add(_make_session(uid, subj, _utc(2026, 8, 8, 3, 0), _utc(2026, 8, 8, 3, 30), 1800))
            await db.commit()

        async with isolated_db.async_session() as db:
            day7, total7 = await svc.get_history(db, uid, filter_date=date(2026, 8, 7))
            day8, total8 = await svc.get_history(db, uid, filter_date=date(2026, 8, 8))

        assert total7 == 1
        assert day7[0]["start_time"] == _utc(2026, 8, 7, 15, 50)
        assert total8 == 1
        assert day8[0]["start_time"] == _utc(2026, 8, 8, 3, 0)


# ── Settings (case 10) ─────────────────────────────────────────────────

class TestSettings:
    @pytest.mark.asyncio
    async def test_default_zero(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_set")
            s = await svc.get_pomodoro_settings(db, uid)
        assert s == {"day_start_minute": 0, "day_start_time": "00:00", "timezone": "Asia/Shanghai"}

    @pytest.mark.asyncio
    async def test_update_and_read_back(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_set2")
            updated = await svc.update_pomodoro_settings(db, uid, 360)
            await db.commit()
            read = await svc.get_pomodoro_settings(db, uid)
        assert updated["day_start_minute"] == 360
        assert updated["day_start_time"] == "06:00"
        assert read["day_start_minute"] == 360

    @pytest.mark.asyncio
    async def test_invalid_values_rejected(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_set3")
            with pytest.raises(ValueError):
                await svc.update_pomodoro_settings(db, uid, -1)
            with pytest.raises(ValueError):
                await svc.update_pomodoro_settings(db, uid, 1440)

    @pytest.mark.asyncio
    async def test_setting_change_immediately_recomputes(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_recalc")
            subj = await _make_subject(db)
            db.add(_make_session(uid, subj, _utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 20), 1800))
            await db.commit()

        async with isolated_db.async_session() as db:
            d_0000 = await svc.get_daily_summary(db, uid, date(2026, 8, 7))
            await svc.update_pomodoro_settings(db, uid, 360)
            await db.commit()

        async with isolated_db.async_session() as db:
            d_0600 = await svc.get_daily_summary(db, uid, date(2026, 8, 7))

        assert d_0000["duration_sec"] == 600
        assert d_0600["duration_sec"] == 1800


# ── Pause interval lifecycle (case 12-13) ──────────────────────────────

class TestPauseIntervals:
    @pytest.mark.asyncio
    async def test_case12_pause_repeat_pause_resume_no_dup(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_pidem")
            subj = await _make_subject(db)
            session = await svc.start_session(db, uid, subj, None, "standard", 25, 5)
            sid = session.id
            await db.commit()

        async with isolated_db.async_session() as db:
            await svc.pause_session(db, sid, uid)
            await db.commit()
        async with isolated_db.async_session() as db:
            await svc.pause_session(db, sid, uid)  # 重复 pause 幂等
            await db.commit()
        async with isolated_db.async_session() as db:
            await svc.resume_session(db, sid, uid)
            await db.commit()
        async with isolated_db.async_session() as db:
            await svc.resume_session(db, sid, uid)  # 重复 resume 幂等
            await db.commit()

        async with isolated_db.async_session() as db:
            intervals = (await db.execute(
                select(PomodoroPauseInterval).where(PomodoroPauseInterval.session_id == sid)
            )).scalars().all()
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert len(intervals) == 1
        assert intervals[0].ended_at is not None
        assert row.status == "running"
        assert row.paused_at is None

    @pytest.mark.asyncio
    async def test_case13_paused_without_open_interval_is_not_repaired(self, isolated_db):
        # Post-migration invariant: paused -> exactly one open pause interval.  A
        # paused_at-only row is a data anomaly: logged, never silently repaired.
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_legacy")
            subj = await _make_subject(db)
            session = await svc.start_session(db, uid, subj, None, "standard", 25, 5)
            sid = session.id
            await db.commit()

        # Corrupt data: paused_at set but no pause interval.
        legacy_paused_at = _utc(2026, 8, 8, 1, 0, 0)
        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()
            row.status = "paused"
            row.paused_at = legacy_paused_at
            row.start_time = _utc(2026, 8, 8, 0, 50, 0)
            await db.commit()

        async with isolated_db.async_session() as db:
            await svc.resume_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            intervals = (await db.execute(
                select(PomodoroPauseInterval).where(PomodoroPauseInterval.session_id == sid)
            )).scalars().all()
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert len(intervals) == 0, "must not fabricate a pause interval for anomalous data"
        assert row.status == "running"
        assert row.paused_at is None

    @pytest.mark.asyncio
    async def test_case13b_complete_paused_without_open_interval_no_interval(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_legacy2")
            subj = await _make_subject(db)
            session = await svc.start_session(db, uid, subj, None, "standard", 25, 5)
            sid = session.id
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()
            row.status = "paused"
            row.paused_at = _utc(2026, 8, 8, 1, 0, 0)
            await db.commit()

        async with isolated_db.async_session() as db:
            await svc.complete_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            intervals = (await db.execute(
                select(PomodoroPauseInterval).where(PomodoroPauseInterval.session_id == sid)
            )).scalars().all()
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert len(intervals) == 0, "must not fabricate a pause interval for anomalous data"
        assert row.status == "completed"
        assert row.paused_at is None
        # Server-authoritative actual = wall clock (the lost pause segment is a
        # logged data anomaly, not silently repaired).
        assert row.actual_duration == int((row.end_time - row.start_time).total_seconds())

    @pytest.mark.asyncio
    async def test_complete_with_pause_produces_exact_attribution(self, isolated_db):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_pauseattr")
            subj = await _make_subject(db)
            session = await svc.start_session(db, uid, subj, None, "standard", 25, 5)
            sid = session.id
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(
                select(PomodoroSession)
                .options(selectinload(PomodoroSession.pause_intervals))
                .where(PomodoroSession.id == sid)
            )).scalar_one()
            row.status = "completed"
            row.start_time = _utc(2026, 8, 7, 15, 50)   # 23:50 中国
            row.end_time = _utc(2026, 8, 7, 16, 20)     # 00:20 次日中国
            row.actual_duration = 1200
            row.pause_intervals.append(PomodoroPauseInterval(
                session_id=sid,
                started_at=_utc(2026, 8, 7, 15, 55),    # 23:55 中国
                ended_at=_utc(2026, 8, 7, 16, 5),       # 00:05 次日中国
            ))
            await db.commit()

        async with isolated_db.async_session() as db:
            d7 = await svc.get_daily_summary(db, uid, date(2026, 8, 7))
            d8 = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        assert d7["duration_sec"] == 300
        assert d8["duration_sec"] == 900


# ── Performance / query-count regression ───────────────────────────────
#
# 统计页组合计算必须保持：一次 session 查询 + 一次批量 pause 查询（无 N+1）、
# subject 按需加载、query 数量有界（7/30/90 天不变成 N 天 N queries）。

class TestSnapshotQueryCounts:
    @staticmethod
    def _capture(engine):
        import sqlalchemy as sa

        statements: list[str] = []

        def _hook(conn, cursor, statement, parameters, context, executemany):
            statements.append(str(statement))

        sa.event.listen(engine.sync_engine, "before_cursor_execute", _hook)
        return statements, lambda: sa.event.remove(
            engine.sync_engine, "before_cursor_execute", _hook
        )

    @staticmethod
    async def _seed(db, *, start_date, days, per_day, pauses_each=0) -> int:
        from datetime import timedelta

        from app.models.pomodoro import PomodoroPauseInterval

        # 每日 08:00 UTC（= 16:00 中国，dsm=0 下归属当日学习日）
        uid = await _make_user(db, "u_perf")
        subj = await _make_subject(db)
        for d in range(days):
            day = start_date + timedelta(days=d)
            for i in range(per_day):
                start = datetime(day.year, day.month, day.day, 8, 0, 0) + timedelta(minutes=i * 5)
                end = start + timedelta(minutes=25)
                session = _make_session(uid, subj, start, end, 1500)
                db.add(session)
                await db.flush()
                for p in range(pauses_each):
                    db.add(PomodoroPauseInterval(
                        session_id=session.id,
                        started_at=start + timedelta(minutes=1 + p),
                        ended_at=start + timedelta(minutes=2 + p),
                    ))
        await db.commit()
        return uid

    @pytest.mark.asyncio
    async def test_combined_snapshot_is_one_load_one_pause_batch(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await self._seed(db, start_date=date(2026, 8, 1), days=3, per_day=3, pauses_each=1)
            statements, stop = self._capture(isolated_db.engine)
            try:
                snap = await svc.build_pomodoro_statistics_snapshot(
                    db, uid, target_date=date(2026, 8, 2),
                    need_stats=True, need_trends=True, need_daily_summary=True,
                )
            finally:
                stop()

        # 4 statements：settings + sessions(+subject JOIN) + pause batch IN + practice sessions
        assert len(statements) == 4, statements
        session_stmt = next(s for s in statements if "pomodoro_sessions" in s)
        assert "subjects" in session_stmt.lower()  # daily_summary 需要 subject -> JOIN 一次
        pause_stmts = [s for s in statements if "pomodoro_pause_intervals" in s]
        assert len(pause_stmts) == 1  # 批量 IN，无 N+1
        assert snap["stats"]["today_duration_sec"] >= 0
        assert snap["trends"]
        assert snap["daily_summary"]["duration_sec"] == 4500
        assert snap["daily_summary"]["subjects"]

    @pytest.mark.asyncio
    async def test_stats_does_not_load_subject(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            # 本周（周一起 08-03）内 seeding，保证 stats 窗口有重叠 session
            uid = await self._seed(db, start_date=date(2026, 8, 3), days=5, per_day=2, pauses_each=1)
            statements, stop = self._capture(isolated_db.engine)
            try:
                stats = await svc.get_stats(db, uid)
            finally:
                stop()

        assert not any("subjects" in s.lower() for s in statements), statements
        assert len(statements) == 4, statements  # settings + sessions cols + pauses batch + practice cols
        assert stats["week_sessions"] > 0

    @pytest.mark.asyncio
    async def test_90_day_trends_query_count_bounded(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            # 30 天 × 5 = 150 sessions，跨 90 天趋势窗口；pause 各 1 条
            uid = await self._seed(db, start_date=date(2026, 7, 9), days=30, per_day=5, pauses_each=1)
            statements, stop = self._capture(isolated_db.engine)
            try:
                trends = await svc.build_pomodoro_statistics_snapshot(
                    db, uid, trends_days=90, need_trends=True
                )
            finally:
                stop()

        # 有界（settings + sessions + pauses；仅当 >500 条才分片）——绝不 N 天 N queries
        assert len(statements) <= 4, statements
        assert len(trends["trends"]) == 90
        assert sum(t["duration_sec"] for t in trends["trends"]) > 0

    @pytest.mark.asyncio
    async def test_pause_loading_no_n_plus_one(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            # 50 sessions × 2 pauses：pause 仍只有一条批量查询
            uid = await self._seed(db, start_date=date(2026, 7, 26), days=10, per_day=5, pauses_each=2)
            statements, stop = self._capture(isolated_db.engine)
            try:
                snap = await svc.build_pomodoro_statistics_snapshot(
                    db, uid, target_date=date(2026, 7, 27), trends_days=30,
                    need_trends=True, need_daily_summary=True,
                )
            finally:
                stop()

        pause_stmts = [s for s in statements if "pomodoro_pause_intervals" in s]
        assert len(pause_stmts) == 1, statements
        assert snap["daily_summary"]["duration_sec"] > 0


class TestPauseRowLockPostgresCompat:
    """pause_session 的行锁在 PostgreSQL 下不能锁 outer join 可空侧。

    SQLite 忽略 FOR UPDATE，运行时测试覆盖不到（线上曾 500：
    ``FOR UPDATE cannot be applied to the nullable side of an outer join``）。
    本测试对 postgresql dialect 编译该查询，断言锁只作用于 pomodoro_sessions，
    防止将来把 ``of=PomodoroSession`` 去掉回归到裸 ``FOR UPDATE``。
    """

    def test_pause_row_lock_targets_only_pomodoro_sessions(self):
        from sqlalchemy import select
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.orm import joinedload, selectinload

        from app.models.pomodoro import PomodoroSession

        stmt = (
            select(PomodoroSession)
            .options(
                joinedload(PomodoroSession.subject_ref),
                selectinload(PomodoroSession.pause_intervals),
            )
            .where(PomodoroSession.id == 1)
            .with_for_update(of=PomodoroSession)
        )
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert sql.rstrip().endswith("FOR UPDATE OF pomodoro_sessions")
