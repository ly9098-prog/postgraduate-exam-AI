"""刷题会话（PracticeSession）纳入番茄钟学习统计的回归测试。

覆盖 current_task.md 第 23 节后端用例：
- 只有 Pomodoro：原有统计不变
- 只有 PracticeSession：今日/每日/趋势/科目时长 += duration_sec
- Pomodoro + Practice 无重叠：总时长求和
- 跨统计日刷题（自定义 day_start）：时长正确拆分，贡献总和守恒
- history 混排：统一按开始时间倒序
- history total：等于两来源总数
- history 日期过滤：遵守 day_start_minute
- request_id 幂等：重试不新增第二个 PracticeSession
- overlap 去重：Pomodoro 与刷题并行时不 double count
- 科目级 sessions 含刷题、顶层 sessions 保持番茄次数
- 签名 batch_submit 同事务落库 PracticeSession/records/outbox，缺失协议拒绝且无残留
- 单题 used_time 不串题（真实后置投影使用各自题目的 used_time）
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def isolated_db(monkeypatch_module):
    tmp = tempfile.NamedTemporaryFile(prefix="prac_session_stats_", suffix=".db", delete=False)
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
    # This fixture owns a temporary SQLite database. Reset derived/outbox rows as
    # well as source rows because SQLite here does not enforce FK cascades.
    async with isolated_db.async_session() as db:
        for table in reversed(list(isolated_db.Base.metadata.tables.values())):
            await db.execute(table.delete())
        await db.commit()


async def _make_user(db, openid: str = "openid_test") -> int:
    from app.models.user import User
    u = User(openid=openid)
    db.add(u)
    await db.flush()
    return u.id


async def _make_subject(db, code: str = "advanced_math", name: str = "高等数学") -> int:
    from sqlalchemy import select

    from app.models.admin import Subject

    existing = await db.scalar(select(Subject).where(Subject.code == code))
    if existing is not None:
        return existing.id
    subject = Subject(code=code, name=name, level=1, path=code, is_active=True, sort_order=0)
    db.add(subject)
    await db.flush()
    return subject.id


def _utc(*parts):
    return datetime(*parts)


def _make_pomo(uid, subj, start, end, actual, preset="standard", status="completed"):
    from app.models.pomodoro import PomodoroSession
    return PomodoroSession(
        user_id=uid, subject_id=subj, preset=preset,
        work_duration=25, break_duration=5,
        start_time=start, end_time=end,
        actual_duration=actual, status=status,
    )


def _make_practice(uid, subj, started, finished, duration, request_id="r1", status="completed"):
    from app.models.practice_session import PracticeSession
    return PracticeSession(
        user_id=uid, subject_id=subj, request_id=request_id, mode="random",
        started_at=started, finished_at=finished, duration_sec=duration,
        question_count=5, answered_count=5, correct_count=4, wrong_count=1,
        status=status,
    )


async def _make_question(db, subj, *, id_override=None, answer="A", question_type="single_choice"):
    from app.models.question import Question
    q = Question(
        id=id_override,
        subject_id=subj,
        question_type=question_type,
        content={"stem": "q?"},
        options={"A": "a", "B": "b", "C": "c", "D": "d"},
        answer=answer,
        analysis="解析",
        difficulty=3,
        is_active=True,
    )
    db.add(q)
    await db.flush()
    from app.services.knowledge_point_service import sync_question_knowledge_points
    await sync_question_knowledge_points(db, q, ["导数"], source="test")
    from app.services.question_revision_service import ensure_question_revision
    await ensure_question_revision(db, q, change_source="test")
    return q.id


# ── 统计口径：时长并入 + sessions 语义 ───────────────────────────────

class TestStatisticsMerge:
    @pytest.mark.asyncio
    async def test_pomodoro_only_unchanged(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_pomo_only")
            subj = await _make_subject(db)
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))
            trends = await svc.get_trends(db, uid, days=7)

        assert stats["today_duration_sec"] == 1500
        assert stats["today_sessions"] == 1
        assert summary["duration_sec"] == 1500
        assert summary["sessions"] == 1
        assert summary["subjects"][0]["duration_sec"] == 1500
        assert summary["subjects"][0]["sessions"] == 1
        by_date = {t["date"]: t for t in trends}
        assert by_date["2026-08-08"]["duration_sec"] == 1500
        assert by_date["2026-08-08"]["sessions"] == 1

    @pytest.mark.asyncio
    async def test_practice_only(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_prac_only")
            subj = await _make_subject(db, name="高等数学")
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 20), 1200))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))
            trends = await svc.get_trends(db, uid, days=7)

        assert stats["today_duration_sec"] == 1200
        # 顶层 sessions 保持番茄次数：纯刷题日为 0
        assert stats["today_sessions"] == 0
        assert summary["duration_sec"] == 1200
        assert summary["sessions"] == 0
        assert summary["subjects"][0]["duration_sec"] == 1200
        assert summary["subjects"][0]["sessions"] == 1  # 科目级 sessions 含刷题
        by_date = {t["date"]: t for t in trends}
        assert by_date["2026-08-08"]["duration_sec"] == 1200
        assert by_date["2026-08-08"]["sessions"] == 0

    @pytest.mark.asyncio
    async def test_pomodoro_plus_practice_no_overlap(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_mixed")
            subj = await _make_subject(db)
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 3, 0), _utc(2026, 8, 8, 3, 20), 1200))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        assert stats["today_duration_sec"] == 2700  # 1500 + 1200
        assert stats["today_sessions"] == 1  # 仅番茄
        assert summary["duration_sec"] == 2700
        assert summary["subjects"][0]["duration_sec"] == 2700
        assert summary["subjects"][0]["sessions"] == 2  # 1 番茄 + 1 刷题

    @pytest.mark.asyncio
    async def test_cross_day_practice_custom_day_start(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_cross")
            subj = await _make_subject(db)
            await svc.update_pomodoro_settings(db, uid, 360)  # 06:00
            # 中国 05:50 -> 06:10 == UTC 21:50 -> 22:10 (前一日)
            db.add(_make_practice(uid, subj, _utc(2026, 8, 7, 21, 50), _utc(2026, 8, 7, 22, 10), 1200))
            await db.commit()

        async with isolated_db.async_session() as db:
            d7 = await svc.get_daily_summary(db, uid, date(2026, 8, 7))
            d8 = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        assert d7["duration_sec"] == 600
        assert d7["subjects"][0]["sessions"] == 1  # 开始于 08-07
        assert d8["duration_sec"] == 600
        assert d8["sessions"] == 0  # 顶层 sessions 不含跨日贡献
        assert d8["subjects"][0]["sessions"] == 0  # 跨日渗透科目切片 sessions=0
        assert d7["duration_sec"] + d8["duration_sec"] == 1200  # 守恒

    @pytest.mark.asyncio
    async def test_overlap_dedup_partial(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_overlap")
            subj = await _make_subject(db)
            # Pomodoro [10:00-10:20] 无暂停 -> active 1200s
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 20), 1200))
            # Practice [10:10-10:25] duration 900；与番茄 active 重叠 600s -> 净增 300s
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 2, 10), _utc(2026, 8, 8, 2, 25), 900))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        assert stats["today_duration_sec"] == 1500  # 1200 番茄 + 300 刷题净增，非 2100
        assert summary["duration_sec"] == 1500
        assert summary["subjects"][0]["duration_sec"] == 1500

    @pytest.mark.asyncio
    async def test_overlap_dedup_fully_covered(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_covered")
            subj = await _make_subject(db)
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 20), 1200))
            # Practice 完全落在番茄窗口内 -> 不 double count
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 2, 5), _utc(2026, 8, 8, 2, 15), 600))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)

        assert stats["today_duration_sec"] == 1200  # 刷题不额外贡献

    @pytest.mark.asyncio
    async def test_practice_during_pomodoro_pause_counts(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_pause")
            subj = await _make_subject(db)
            from app.models.pomodoro import PomodoroPauseInterval
            pomo = _make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 20), 900)
            db.add(pomo)
            await db.flush()
            # 暂停 [10:05-10:10]：active = [10:00-10:05]+[10:10-10:20] = 900s
            db.add(PomodoroPauseInterval(session_id=pomo.id, started_at=_utc(2026, 8, 8, 2, 5), ended_at=_utc(2026, 8, 8, 2, 10)))
            # Practice [10:10-10:25] 与 active 重叠 600s -> 净增 300s
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 2, 10), _utc(2026, 8, 8, 2, 25), 900))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)

        assert stats["today_duration_sec"] == 1200  # 900 番茄 active + 300 刷题净增


# ── 上线前生产审查：跨统计日+overlap / 多番茄 union / invariant / 同秒分页 / 零时长 ──

class TestProductionReviewMath:
    @pytest.mark.asyncio
    async def test_cross_day_plus_overlap_conserved(self, isolated_db):
        """跨统计日 + overlap 同时发生：只扣对应统计日真正重叠部分，总贡献守恒、无负值。"""
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_cd_overlap")
            subj = await _make_subject(db)
            await svc.update_pomodoro_settings(db, uid, 360)  # 06:00
            # China 05:45-06:15 == UTC 21:45-22:15（前一日），active 1800s
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 7, 21, 45), _utc(2026, 8, 7, 22, 15), 1800))
            # China 05:55-06:25 == UTC 21:55-22:25；与番茄重叠 [21:55-22:15)
            db.add(_make_practice(uid, subj, _utc(2026, 8, 7, 21, 55), _utc(2026, 8, 7, 22, 25), 1800))
            await db.commit()

        async with isolated_db.async_session() as db:
            d7 = await svc.get_daily_summary(db, uid, date(2026, 8, 7))
            d8 = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        # 番茄按日拆分：900 + 900；刷题只在未重叠段 [22:15-22:25) 贡献 600 给 08-08
        assert d7["duration_sec"] == 900
        assert d8["duration_sec"] == 1500
        assert d7["duration_sec"] >= 0 and d8["duration_sec"] >= 0
        # 守恒：union = 番茄 1800 + 刷题尾部 600 = 2400
        assert d7["duration_sec"] + d8["duration_sec"] == 2400

    @pytest.mark.asyncio
    async def test_multi_pomodoro_overlap_unions_before_practice_exclusion(self, isolated_db, monkeypatch):
        """多个互相重叠的番茄对同一刷题：先 union 再排除，不能重复扣减。"""
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_multi_pomo")
            subj = await _make_subject(db)
            # Practice 10:00-11:00（wall 3600），Pomodoro A 10:05-10:25，B 10:20-10:40
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 3, 0), 3600))
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 5), _utc(2026, 8, 8, 2, 25), 1200))
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 20), _utc(2026, 8, 8, 2, 40), 1200))
            await db.commit()

        async with isolated_db.async_session() as db:
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        # union(A,B) = [02:05,02:40) = 2100s；刷题非覆盖段 1500s 全部计入
        # 若按"每个番茄单独减"会重复减 300s → 刷题只剩 1200，total 3600
        assert summary["duration_sec"] == 3900  # 1200 + 1200 + 1500
        assert summary["subjects"][0]["duration_sec"] == 3900

    @pytest.mark.asyncio
    async def test_subject_duration_sum_equals_total(self, isolated_db, monkeypatch):
        """科目时长之和 == 当日总学习时长（Pomodoro 英语 + 刷题数学重叠不双计）。"""
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_invariant")
            en = await _make_subject(db, code="english", name="英语")
            ma = await _make_subject(db, code="advanced_math", name="高等数学")
            db.add(_make_pomo(uid, en, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            db.add(_make_practice(uid, ma, _utc(2026, 8, 8, 2, 20), _utc(2026, 8, 8, 2, 35), 900))
            await db.commit()

        async with isolated_db.async_session() as db:
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        by_code = {s["subject_code"]: s for s in summary["subjects"]}
        assert by_code["english"]["duration_sec"] == 1500
        # 刷题只贡献非重叠段 [02:25-02:35) = 600s，不把已计入番茄的 300s 重复计
        assert by_code["advanced_math"]["duration_sec"] == 600
        assert sum(s["duration_sec"] for s in summary["subjects"]) == summary["duration_sec"]

    @pytest.mark.asyncio
    async def test_practice_duration_less_than_wall_not_over_excluded(self, isolated_db, monkeypatch):
        """Practice duration_sec < wall span（前台计时）与番茄重叠：按比例排除，不欠计。"""
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_fg_dur")
            subj = await _make_subject(db)
            # 番茄 10:00-10:25 active 1500s
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            # 刷题 wall 10:00-10:55（后台挂起 50min），前台有效仅 300s
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 55), 300))
            await db.commit()

        async with isolated_db.async_session() as db:
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        # 非覆盖段 [02:25-02:55) = 1800s / wall 3300s → 300 * 1800/3300 ≈ 163s
        # 旧算法（墙钟差）会把 300 - 1500 = 0，欠计为纯番茄 1500
        assert summary["duration_sec"] == 1663  # 1500 + 163
        assert summary["subjects"][0]["duration_sec"] == 1663

    @pytest.mark.asyncio
    async def test_zero_duration_practice_session(self, isolated_db, monkeypatch):
        """零时长刷题：会话落库、history 可见、不增加总时长、不生成科目切片。"""
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_zero_dur")
            subj = await _make_subject(db)
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 10), 0))
            await db.commit()

        async with isolated_db.async_session() as db:
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))
            items, total = await svc.get_history(db, uid, page=1, page_size=20)

        assert summary["duration_sec"] == 0
        assert summary["sessions"] == 0
        assert summary["subjects"] == []
        assert total == 1
        assert items[0]["record_type"] == "practice"
        assert items[0]["actual_duration"] == 0


# ── history 混排 / total / 日期过滤 / 分页 ──────────────────────────

class TestHistoryMerge:
    @pytest.mark.asyncio
    async def test_history_mixed_desc_order(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_hist_mix")
            subj = await _make_subject(db)
            # 10:00 Pomo, 10:10 Practice, 10:30 Pomo
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 2, 10), _utc(2026, 8, 8, 2, 28), 1080))
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 30), _utc(2026, 8, 8, 3, 0), 1800))
            await db.commit()

        async with isolated_db.async_session() as db:
            items, total = await svc.get_history(db, uid, page=1, page_size=20)

        assert total == 3
        assert [i["record_type"] for i in items] == ["pomodoro", "practice", "pomodoro"]
        assert [i["record_key"] for i in items] == ["pomodoro:2", "practice:1", "pomodoro:1"]
        assert items[1]["subject_name"] == "高等数学"
        assert items[1]["actual_duration"] == 1080

    @pytest.mark.asyncio
    async def test_history_total_equals_both_sources(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_hist_total")
            subj = await _make_subject(db)
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 3, 0), _utc(2026, 8, 8, 3, 20), 1200, request_id="r1"))
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 4, 0), _utc(2026, 8, 8, 4, 20), 1200, request_id="r2"))
            await db.commit()

        async with isolated_db.async_session() as db:
            _, total = await svc.get_history(db, uid, page=1, page_size=20)

        assert total == 3  # 1 番茄 + 2 刷题

    @pytest.mark.asyncio
    async def test_history_date_filter_day_start(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_hist_date")
            subj = await _make_subject(db)
            await svc.update_pomodoro_settings(db, uid, 360)
            # 08-07 23:50 中国 (UTC 15:50) 属于 08-07 统计日（06:00 边界）
            db.add(_make_practice(uid, subj, _utc(2026, 8, 7, 15, 50), _utc(2026, 8, 7, 16, 10), 1200, request_id="r1"))
            # 08-08 05:00 中国 (UTC 08-07 21:00) 属于 08-07 统计日
            db.add(_make_practice(uid, subj, _utc(2026, 8, 7, 21, 0), _utc(2026, 8, 7, 21, 20), 1200, request_id="r2"))
            await db.commit()

        async with isolated_db.async_session() as db:
            day7, total7 = await svc.get_history(db, uid, filter_date=date(2026, 8, 7))
            day8, total8 = await svc.get_history(db, uid, filter_date=date(2026, 8, 8))

        assert total7 == 2
        assert total8 == 0

    @pytest.mark.asyncio
    async def test_history_pagination_no_lost_records(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_hist_page")
            subj = await _make_subject(db)
            for i in range(6):
                base = _utc(2026, 8, 8, 2, 0) + timedelta(minutes=i * 30)
                if i % 2 == 0:
                    db.add(_make_pomo(uid, subj, base, base + timedelta(minutes=25), 1500))
                else:
                    db.add(_make_practice(uid, subj, base, base + timedelta(minutes=20), 1200, request_id=f"r{i}"))
            await db.commit()

        async with isolated_db.async_session() as db:
            p1, t1 = await svc.get_history(db, uid, page=1, page_size=2)
            p2, t2 = await svc.get_history(db, uid, page=2, page_size=2)
            p3, t3 = await svc.get_history(db, uid, page=3, page_size=2)

        assert t1 == 6
        keys = [i["record_key"] for i in p1] + [i["record_key"] for i in p2] + [i["record_key"] for i in p3]
        assert len(keys) == 6
        assert len(set(keys)) == 6, "分页不能丢记录或重复"
        # 顺序严格倒序
        starts = [i["start_time"] for i in p1 + p2 + p3]
        assert starts == sorted(starts, reverse=True)

    @pytest.mark.asyncio
    async def test_history_same_second_stable_sort(self, isolated_db):
        """番茄与刷题同秒开始时，secondary sort（record_type, id）保证分页稳定不重不漏。"""
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_hist_same_sec")
            subj = await _make_subject(db)
            # 同秒：pomodoro 与 practice 的 start_time 完全一致
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 20), 1200, request_id="r1"))
            # 更晚的一条用于制造翻页
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 30), _utc(2026, 8, 8, 3, 0), 1800))
            await db.commit()

        async with isolated_db.async_session() as db:
            p1, t1 = await svc.get_history(db, uid, page=1, page_size=1)
            p2, t2 = await svc.get_history(db, uid, page=2, page_size=1)
            p3, t3 = await svc.get_history(db, uid, page=3, page_size=1)

        assert t1 == t2 == t3 == 3
        # page1 = 最新 02:30 番茄；page2/page3 = 两个同秒记录，次序由 record_type DESC 决定
        assert p1[0]["start_time"] == _utc(2026, 8, 8, 2, 30)
        assert p2[0]["record_type"] == "practice"
        assert p3[0]["record_type"] == "pomodoro"
        all_keys = [p1[0]["record_key"], p2[0]["record_key"], p3[0]["record_key"]]
        assert len(set(all_keys)) == 3, "同秒分页不得重复或丢失"


# Signed submissions and asynchronous per-answer projection.

async def _signed_submission(db, uid, subj, answers, request_id="req-stats"):
    from app.core.time_utils import utcnow
    from app.models.question import Question
    from app.services import practice_service as svc
    from app.services.practice import batch_token
    from app.services.question_revision_service import load_latest_question_revision_ids

    finished = utcnow()
    started = finished - timedelta(minutes=20)
    questions = [await db.get(Question, answer["question_id"]) for answer in answers]
    revisions = await load_latest_question_revision_ids(db, [q.id for q in questions])
    # Issue at the session's start, retaining the real HMAC and expiry validator.
    with patch.object(
        batch_token.time,
        "time",
        return_value=started.replace(tzinfo=UTC).timestamp(),
    ):
        token, _, signed_id = svc.create_practice_batch_token(
            user_id=uid, subject_id=subj, mode="random", questions=questions,
            revision_ids=revisions, submission_request_id=request_id,
        )
    assert token and signed_id == request_id
    return {
        "answers": answers,
        "session_meta": {
            "request_id": request_id, "subject_id": subj, "mode": "random",
            "started_at": started.isoformat() + "Z",
            "finished_at": finished.isoformat() + "Z", "duration_sec": 1200,
            "question_count": len(answers), "answered_count": len(answers),
        },
        "skipped_question_ids": [], "batch_token": token,
    }


async def _seed_submission(isolated_db, answers=("A",), request_id="req-stats"):
    async with isolated_db.async_session() as db:
        uid = await _make_user(db)
        subj = await _make_subject(db)
        qids = [await _make_question(db, subj, answer=value) for value in answers]
        await db.commit()
        payload = await _signed_submission(
            db, uid, subj,
            [{"question_id": qid, "user_answer": value} for qid, value in zip(qids, answers)],
            request_id=request_id,
        )
    return uid, subj, qids, payload


async def _assert_no_submission(isolated_db):
    from sqlalchemy import func, select

    from app.models.practice_record import PracticeRecord
    from app.models.practice_session import PracticeSession
    from app.models.task_outbox import TaskOutbox

    async with isolated_db.async_session() as db:
        for model in (PracticeSession, PracticeRecord, TaskOutbox):
            assert await db.scalar(select(func.count()).select_from(model)) == 0


class TestBatchSubmitSession:
    @pytest.mark.asyncio
    async def test_batch_submit_creates_practice_session(self, isolated_db):
        from sqlalchemy import select

        from app.models.practice_record import PracticeRecord
        from app.models.practice_session import PracticeSession
        from app.models.task_outbox import TaskOutbox
        from app.services import practice_service as svc

        uid, _, _, payload = await _seed_submission(isolated_db, ("A", "B"), "req-abc")
        payload["answers"][0]["used_time"] = 40
        payload["answers"][1].update(user_answer="C", used_time=120)
        async with isolated_db.async_session() as db:
            result = await svc.batch_submit_answers(db, uid, **payload)
        assert (result["total_correct"], result["total_wrong"]) == (1, 1)
        async with isolated_db.async_session() as db:
            session = (await db.scalars(select(PracticeSession))).one()
            records = list((await db.scalars(select(PracticeRecord))).all())
            outboxes = list((await db.scalars(select(TaskOutbox))).all())
            assert session.request_id == "req-abc"
            assert session.duration_sec == 1200 and session.answered_count == 2
            assert session.correct_count == session.wrong_count == 1
            assert session.status == "completed" and session.submission_response == result
            assert len(records) == len(outboxes) == 2
            assert {row.projection_state for row in records} == {"pending"}
            assert {row.task_type for row in outboxes} == {"answer_projection"}
            assert {row.payload["practice_record_id"] for row in outboxes} == {
                row.id for row in records
            }

    @pytest.mark.asyncio
    async def test_request_id_idempotent_retry(self, isolated_db):
        from sqlalchemy import func, select

        from app.models.practice_record import PracticeRecord
        from app.models.practice_session import PracticeSession
        from app.models.task_outbox import TaskOutbox
        from app.services import practice_service as svc

        uid, _, _, payload = await _seed_submission(isolated_db, request_id="req-idem")
        responses = []
        for _ in range(2):
            async with isolated_db.async_session() as db:
                responses.append(await svc.batch_submit_answers(db, uid, **payload))
        assert responses[0] == responses[1]
        async with isolated_db.async_session() as db:
            for model in (PracticeSession, PracticeRecord, TaskOutbox):
                assert await db.scalar(select(func.count()).select_from(model)) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing", ["session_meta", "batch_token", "skipped_question_ids"])
    async def test_incomplete_client_protocol_rejected_without_writes(self, isolated_db, missing):
        from app.services import practice_service as svc

        uid, _, _, payload = await _seed_submission(isolated_db)
        payload[missing] = None if missing != "batch_token" else ""
        with pytest.raises(svc.PracticeBatchTokenError):
            async with isolated_db.async_session() as db:
                await svc.batch_submit_answers(db, uid, **payload)
        await _assert_no_submission(isolated_db)

    @pytest.mark.asyncio
    async def test_used_time_preserved_until_and_after_projection(self, isolated_db):
        from sqlalchemy import select

        from app.models.answer_behavior import AnswerBehavior
        from app.models.practice_record import PracticeRecord
        from app.services import practice_service as svc
        from app.services.practice.answer_projection_service import (
            project_practice_answer,
        )

        uid, _, qids, payload = await _seed_submission(isolated_db, ("A", "B"))
        payload["answers"][0]["used_time"] = 40
        payload["answers"][1].update(user_answer="C", used_time=120)
        async with isolated_db.async_session() as db:
            await svc.batch_submit_answers(db, uid, **payload)
        async with isolated_db.async_session() as db:
            records = list((await db.scalars(select(PracticeRecord))).all())
            assert {row.question_id: row.used_time for row in records} == dict(zip(qids, [40, 120]))
            assert list((await db.scalars(select(AnswerBehavior))).all()) == []
        for record in records:
            async with isolated_db.async_session() as db:
                projected = await project_practice_answer(db, practice_record_id=record.id)
                assert projected["processed"] is True
        async with isolated_db.async_session() as db:
            behaviors = list((await db.scalars(select(AnswerBehavior))).all())
            assert len(behaviors) == 2
            assert {row.question_id: row.time_spent_sec for row in behaviors} == dict(zip(qids, [40, 120]))
            assert {row.practice_record_id for row in behaviors} == {row.id for row in records}


class TestSessionNormalization:
    def _meta(self, **overrides):
        base = {
            "request_id": "req-n", "subject_id": 1, "mode": "random",
            "started_at": "2026-08-08T02:00:00Z", "finished_at": "2026-08-08T02:20:00Z",
            "duration_sec": 1200, "question_count": 5, "answered_count": 5,
        }
        base.update(overrides)
        return base

    @pytest.mark.parametrize("meta", [None, {}])
    def test_absent_meta_is_rejected(self, meta):
        from app.services.practice_service import _normalize_practice_session
        with pytest.raises(ValueError, match="session 不能为空"):
            _normalize_practice_session(meta, user_id=1, answered_count=5, total_correct=3, total_wrong=2)

    def test_valid(self):
        from app.services.practice_service import _normalize_practice_session
        out = _normalize_practice_session(
            self._meta(), user_id=1, answered_count=5, total_correct=3, total_wrong=2,
        )
        assert out == {
            "user_id": 1, "subject_id": 1, "request_id": "req-n", "mode": "random",
            "started_at": _utc(2026, 8, 8, 2, 0), "finished_at": _utc(2026, 8, 8, 2, 20),
            "duration_sec": 1200, "question_count": 5, "answered_count": 5,
            "correct_count": 3, "wrong_count": 2, "status": "completed",
        }

    def test_huge_duration_is_rejected_instead_of_capped(self):
        from app.services.practice_service import _normalize_practice_session
        with pytest.raises(ValueError, match="墙钟"):
            _normalize_practice_session(
                self._meta(duration_sec=999999999, finished_at="2026-08-08T10:00:00Z"),
                user_id=1, answered_count=5, total_correct=0, total_wrong=5,
            )

    def test_duration_within_wall_but_above_session_limit_is_rejected(self):
        from app.services.practice_service import (
            PRACTICE_SESSION_MAX_DURATION_SEC,
            _normalize_practice_session,
        )
        with pytest.raises(ValueError, match="允许上限"):
            _normalize_practice_session(
                self._meta(duration_sec=PRACTICE_SESSION_MAX_DURATION_SEC + 1,
                           finished_at="2026-08-09T02:00:00Z"),
                user_id=1, answered_count=5, total_correct=0, total_wrong=5,
            )

    @pytest.mark.parametrize("duration", [-5, None])
    def test_missing_or_negative_duration_falls_back_to_wall(self, duration):
        from app.services.practice_service import _normalize_practice_session
        out = _normalize_practice_session(
            self._meta(duration_sec=duration), user_id=1, answered_count=5, total_correct=0, total_wrong=5,
        )
        assert out["duration_sec"] == 1200

    def test_duration_exceeding_wall_is_rejected(self):
        from app.services.practice_service import _normalize_practice_session
        with pytest.raises(ValueError, match="墙钟"):
            _normalize_practice_session(
                self._meta(duration_sec=1300), user_id=1, answered_count=5, total_correct=0, total_wrong=5,
            )

    @pytest.mark.parametrize("count", [None, 4, 6])
    def test_answered_count_is_mandatory_and_matches_answers(self, count):
        from app.services.practice_service import _normalize_practice_session
        with pytest.raises(ValueError, match="answered_count"):
            _normalize_practice_session(
                self._meta(answered_count=count), user_id=1, answered_count=5, total_correct=3, total_wrong=2,
            )

    def test_malformed_datetime_rejected(self):
        from app.services.practice_service import _normalize_practice_session
        with pytest.raises(ValueError, match="ISO"):
            _normalize_practice_session(
                self._meta(started_at="not-a-date"), user_id=1, answered_count=5, total_correct=0, total_wrong=5,
            )

    def test_finished_before_started_rejected(self):
        from app.services.practice_service import _normalize_practice_session
        with pytest.raises(ValueError, match="finished_at"):
            _normalize_practice_session(
                self._meta(started_at="2026-08-08T02:20:00Z", finished_at="2026-08-08T02:00:00Z"),
                user_id=1, answered_count=5, total_correct=0, total_wrong=5,
            )


class TestSubmitValidation:
    @pytest.mark.asyncio
    async def test_malformed_session_rejected_without_partial_answers(self, isolated_db):
        from app.services import practice_service as svc

        uid, _, _, payload = await _seed_submission(isolated_db)
        payload["session_meta"]["started_at"] = "not-a-date"
        with pytest.raises(ValueError, match="ISO"):
            async with isolated_db.async_session() as db:
                await svc.batch_submit_answers(db, uid, **payload)
        await _assert_no_submission(isolated_db)


    @pytest.mark.asyncio
    @pytest.mark.parametrize("length", [104, 128])
    async def test_request_id_within_protocol_limit_is_stored_exactly(self, isolated_db, length):
        from sqlalchemy import select

        from app.models.practice_session import PracticeSession
        from app.services import practice_service as svc

        request_id = "req-" + "x" * (length - 4)
        uid, _, _, payload = await _seed_submission(isolated_db, request_id=request_id)
        async with isolated_db.async_session() as db:
            await svc.batch_submit_answers(db, uid, **payload)
        async with isolated_db.async_session() as db:
            session = (await db.scalars(select(PracticeSession))).one()
            assert session.request_id == request_id and len(session.request_id) == length

    @pytest.mark.asyncio
    @pytest.mark.parametrize("length", [129, 255, 263])
    async def test_overlong_request_id_rejected_without_hash_or_writes(self, isolated_db, length):
        from app.services import practice_service as svc

        uid, _, _, payload = await _seed_submission(isolated_db)
        payload["session_meta"]["request_id"] = "r" * length
        with pytest.raises(ValueError, match="128"):
            async with isolated_db.async_session() as db:
                await svc.batch_submit_answers(db, uid, **payload)
        await _assert_no_submission(isolated_db)

    @pytest.mark.asyncio
    async def test_nonexistent_subject_is_rejected_instead_of_reassigned(self, isolated_db):
        from app.services import practice_service as svc

        uid, _, _, payload = await _seed_submission(isolated_db)
        payload["session_meta"]["subject_id"] = 999999999
        with pytest.raises(svc.PracticeBatchTokenError, match="科目"):
            async with isolated_db.async_session() as db:
                await svc.batch_submit_answers(db, uid, **payload)
        await _assert_no_submission(isolated_db)


class TestChinaDateAggregation:
    @pytest.mark.asyncio
    async def test_real_sqlite_buckets_midnight_and_keeps_users_isolated(self, isolated_db, monkeypatch):
        from sqlalchemy import select

        from app.models.practice_record import PracticeRecord
        from app.services import practice_service, stats_service, study_report_service

        uid, subj, qids, payload = await _seed_submission(isolated_db, ("A", "B"))
        payload["answers"][1]["user_answer"] = "C"
        async with isolated_db.async_session() as db:
            await practice_service.batch_submit_answers(db, uid, **payload)
        async with isolated_db.async_session() as db:
            records = list((await db.scalars(select(PracticeRecord).order_by(PracticeRecord.id))).all())
            records[0].answered_at = _utc(2026, 10, 21, 15, 59, 59)
            records[1].answered_at = _utc(2026, 10, 21, 16, 0, 0)
            other_uid = await _make_user(db, "other-date-user")
            db.add(PracticeRecord(
                user_id=other_uid, question_id=qids[0],
                question_version_id=records[0].question_version_id, subject_id=subj,
                question_type="single_choice", user_answer="A", is_correct=True,
                answered_at=_utc(2026, 10, 21, 16, 0, 0),
            ))
            await db.commit()
        for service in (stats_service, study_report_service):
            monkeypatch.setattr(service, "shanghai_today", lambda: date(2026, 10, 22))
        async with isolated_db.async_session() as db:
            assert await stats_service._calc_consecutive_days(db, uid) == 2
            assert await stats_service._calc_consecutive_days(db, other_uid) == 1
            trend = await study_report_service.get_study_trend(db, uid, subject_id=subj, days=3)
            other = await study_report_service.get_study_trend(db, other_uid, days=3)
        assert [item["date"] for item in trend["items"]] == ["2026-10-20", "2026-10-21", "2026-10-22"]
        assert [item["answer_count"] for item in trend["items"]] == [0, 1, 1]
        assert [item["accuracy"] for item in trend["items"]] == [0.0, 100.0, 0.0]
        assert [item["answer_count"] for item in other["items"]] == [0, 0, 1]
