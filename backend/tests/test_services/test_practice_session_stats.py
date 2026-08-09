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
- batch_submit 同事务落库 PracticeSession / 旧客户端不携带 session 不受影响
- 单题 used_time 不串题（后置行为记录使用各自题目的 used_time）
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import date, datetime, timedelta
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
    async with isolated_db.async_session() as db:
        from sqlalchemy import delete

        from app.models.pomodoro import (
            PomodoroPauseInterval,
            PomodoroSession,
            UserPomodoroSettings,
        )
        from app.models.practice_record import PracticeRecord
        from app.models.practice_session import PracticeSession
        from app.models.user import User

        await db.execute(delete(PomodoroPauseInterval))
        await db.execute(delete(PomodoroSession))
        await db.execute(delete(PracticeSession))
        await db.execute(delete(PracticeRecord))
        await db.execute(delete(UserPomodoroSettings))
        await db.execute(delete(User))
        await db.commit()


async def _make_user(db, openid: str = "openid_test") -> int:
    from app.models.user import User
    u = User(openid=openid)
    db.add(u)
    await db.flush()
    return u.id


async def _make_subject(db, code: str | None = None, name: str = "高等数学") -> int:
    import uuid

    from app.models.admin import Subject
    code = code or f"math2_{uuid.uuid4().hex[:8]}"
    subj = Subject(code=code, name=name, level=1, path=code, is_active=True, sort_order=0)
    db.add(subj)
    await db.flush()
    return subj.id


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
        knowledge_points=["导数"],
        difficulty=3,
        is_active=True,
    )
    db.add(q)
    await db.flush()
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
            en = await _make_subject(db, code="english_1", name="英语")
            ma = await _make_subject(db, code="math_1", name="高等数学")
            db.add(_make_pomo(uid, en, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            db.add(_make_practice(uid, ma, _utc(2026, 8, 8, 2, 20), _utc(2026, 8, 8, 2, 35), 900))
            await db.commit()

        async with isolated_db.async_session() as db:
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))

        by_code = {s["subject_code"]: s for s in summary["subjects"]}
        assert by_code["english_1"]["duration_sec"] == 1500
        # 刷题只贡献非重叠段 [02:25-02:35) = 600s，不把已计入番茄的 300s 重复计
        assert by_code["math_1"]["duration_sec"] == 600
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


# ── batch-submit 落库 + 幂等 + 旧客户端兼容 + used_time ──────────────

class TestBatchSubmitSession:
    @pytest.mark.asyncio
    async def test_batch_submit_creates_practice_session(self, isolated_db):
        from sqlalchemy import select

        from app.models.practice_session import PracticeSession
        from app.services import practice_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_bs")
            subj = await _make_subject(db)
            q1 = await _make_question(db, subj, answer="A")
            q2 = await _make_question(db, subj, answer="B")
            await db.commit()

        session_meta = {
            "request_id": "req-abc",
            "subject_id": subj,
            "mode": "random",
            "started_at": "2026-08-08T02:00:00.000Z",
            "finished_at": "2026-08-08T02:18:00.000Z",
            "duration_sec": 1080,
            "question_count": 2,
            "answered_count": 2,
            "status": "completed",
        }
        async with isolated_db.async_session() as db:
            result = await svc.batch_submit_answers(
                db, uid, [
                    {"question_id": q1, "user_answer": "A", "used_time": 40, "request_id": "req-abc"},
                    {"question_id": q2, "user_answer": "C", "used_time": 120, "request_id": "req-abc"},
                ],
                session_meta=session_meta,
            )
            await db.commit()
            assert result["total_correct"] == 1
            assert result["total_wrong"] == 1

        async with isolated_db.async_session() as db:
            rows = (await db.execute(
                select(PracticeSession).where(PracticeSession.user_id == uid)
            )).scalars().all()
            assert len(rows) == 1
            s = rows[0]
            assert s.request_id == "req-abc"
            assert s.duration_sec == 1080
            assert s.answered_count == 2
            assert s.correct_count == 1
            assert s.wrong_count == 1
            assert s.status == "completed"

    @pytest.mark.asyncio
    async def test_request_id_idempotent_retry(self, isolated_db):
        from sqlalchemy import select

        from app.models.practice_session import PracticeSession
        from app.services import practice_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_bs_idem")
            subj = await _make_subject(db)
            q1 = await _make_question(db, subj, answer="A")
            await db.commit()

        session_meta = {
            "request_id": "req-idem",
            "subject_id": subj,
            "mode": "random",
            "started_at": "2026-08-08T02:00:00.000Z",
            "finished_at": "2026-08-08T02:10:00.000Z",
            "duration_sec": 600,
        }
        async with isolated_db.async_session() as db:
            await svc.batch_submit_answers(db, uid, [{"question_id": q1, "user_answer": "A"}], session_meta=session_meta)
            await db.commit()

        # 模拟网络重试：同一 request_id 再次提交
        async with isolated_db.async_session() as db:
            await svc.batch_submit_answers(db, uid, [{"question_id": q1, "user_answer": "A"}], session_meta=session_meta)
            await db.commit()

        async with isolated_db.async_session() as db:
            rows = (await db.execute(
                select(PracticeSession).where(PracticeSession.user_id == uid)
            )).scalars().all()
            assert len(rows) == 1, "同 request_id 重试不得新增第二个 PracticeSession"

    @pytest.mark.asyncio
    async def test_old_client_without_session_unaffected(self, isolated_db):
        from sqlalchemy import select

        from app.models.practice_session import PracticeSession
        from app.services import practice_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_bs_old")
            subj = await _make_subject(db)
            q1 = await _make_question(db, subj, answer="A")
            await db.commit()

        async with isolated_db.async_session() as db:
            result = await svc.batch_submit_answers(db, uid, [{"question_id": q1, "user_answer": "A"}])
            await db.commit()
            assert result["total_correct"] == 1

        async with isolated_db.async_session() as db:
            rows = (await db.execute(
                select(PracticeSession).where(PracticeSession.user_id == uid)
            )).scalars().all()
            assert rows == []  # 不携带 session -> 不写 PracticeSession

    @pytest.mark.asyncio
    async def test_used_time_not_serialized_across_questions(self, isolated_db):
        from sqlalchemy import select

        from app.models.answer_behavior import AnswerBehavior
        from app.models.practice_record import PracticeRecord
        from app.services import practice_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_usedtime")
            subj = await _make_subject(db)
            q1 = await _make_question(db, subj, answer="A")
            q2 = await _make_question(db, subj, answer="B")
            await db.commit()

        async with isolated_db.async_session() as db:
            await svc.batch_submit_answers(db, uid, [
                {"question_id": q1, "user_answer": "A", "used_time": 40},
                {"question_id": q2, "user_answer": "C", "used_time": 120},
            ])
            await db.commit()

        async with isolated_db.async_session() as db:
            recs = (await db.execute(
                select(PracticeRecord).where(PracticeRecord.user_id == uid)
            )).scalars().all()
            by_q = {r.question_id: r.used_time for r in recs}
            assert by_q[q1] == 40
            assert by_q[q2] == 120

            behaviors = (await db.execute(
                select(AnswerBehavior).where(AnswerBehavior.user_id == uid)
            )).scalars().all()
            by_q_behav = {b.question_id: b.time_spent_sec for b in behaviors}
            assert by_q_behav[q1] == 40
            assert by_q_behav[q2] == 120


# ── 数据校验 / normalization ─────────────────────────────────────────

class TestSessionNormalization:
    def _meta(self, **overrides):
        base = {
            "request_id": "req-n",
            "subject_id": 1,
            "mode": "random",
            "started_at": "2026-08-08T02:00:00Z",
            "finished_at": "2026-08-08T02:20:00Z",
            "duration_sec": 1200,
        }
        base.update(overrides)
        return base

    def test_absent_meta_returns_none(self):
        from app.services.practice_service import _normalize_practice_session
        assert _normalize_practice_session(None, user_id=1, answered_count=5, total_correct=3, total_wrong=2) is None
        assert _normalize_practice_session({}, user_id=1, answered_count=5, total_correct=3, total_wrong=2) is None

    def test_valid(self):
        from app.services.practice_service import _normalize_practice_session
        out = _normalize_practice_session(
            self._meta(), user_id=1, answered_count=5, total_correct=3, total_wrong=2,
        )
        assert out["duration_sec"] == 1200
        assert out["subject_id"] == 1
        assert out["started_at"] == _utc(2026, 8, 8, 2, 0)
        assert out["finished_at"] == _utc(2026, 8, 8, 2, 20)
        assert out["answered_count"] == 5
        assert out["correct_count"] == 3
        assert out["wrong_count"] == 2
        assert out["status"] == "completed"

    def test_huge_duration_capped(self):
        from app.services import practice_service as svc
        from app.services.practice_service import _normalize_practice_session
        # 墙钟 8h（超出 6h 上限），上报超大 duration -> 被上限裁剪
        out = _normalize_practice_session(
            self._meta(
                duration_sec=999999999,
                started_at="2026-08-08T02:00:00Z",
                finished_at="2026-08-08T10:00:00Z",
            ),
            user_id=1, answered_count=5, total_correct=0, total_wrong=5,
        )
        assert out["duration_sec"] == svc.PRACTICE_SESSION_MAX_DURATION_SEC

    def test_negative_duration_falls_back_to_wall(self):
        from app.services.practice_service import _normalize_practice_session
        out = _normalize_practice_session(
            self._meta(duration_sec=-5), user_id=1, answered_count=5, total_correct=0, total_wrong=5,
        )
        assert out["duration_sec"] == 1200  # 墙钟 20min

    def test_duration_exceeding_wall_clamped(self):
        from app.services.practice_service import _normalize_practice_session
        # 墙钟 1200s，上报 1300（超过 2s 容差）-> clamp 到墙钟
        out = _normalize_practice_session(
            self._meta(duration_sec=1300), user_id=1, answered_count=5, total_correct=0, total_wrong=5,
        )
        assert out["duration_sec"] == 1200

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
                self._meta(
                    started_at="2026-08-08T02:20:00Z",
                    finished_at="2026-08-08T02:00:00Z",
                ),
                user_id=1, answered_count=5, total_correct=0, total_wrong=5,
            )


# ── code-review 修复回归：malformed session 不丢作答 / request_id 截断 / 科目回退 ─

class TestReviewFixes:
    async def _submit(self, isolated_db, openid: str, session_meta):
        from sqlalchemy import select

        from app.models.practice_record import PracticeRecord
        from app.models.practice_session import PracticeSession
        from app.services import practice_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, openid)
            subj = await _make_subject(db)
            q1 = await _make_question(db, subj, answer="A")
            await db.commit()

        async with isolated_db.async_session() as db:
            result = await svc.batch_submit_answers(
                db, uid,
                [{"question_id": q1, "user_answer": "A", "used_time": 40}],
                session_meta=session_meta,
            )
            await db.commit()
            assert result["total_correct"] == 1

        async with isolated_db.async_session() as db:
            recs = (await db.execute(
                select(PracticeRecord).where(PracticeRecord.user_id == uid)
            )).scalars().all()
            sess = (await db.execute(
                select(PracticeSession).where(PracticeSession.user_id == uid)
            )).scalars().all()
        return q1, subj, recs, sess

    @pytest.mark.asyncio
    async def test_malformed_session_keeps_answers(self, isolated_db):
        """session 时间戳非法 → 跳过会话落库，但作答记录照常入库（不 400、不丢答案）。"""
        _, _, recs, sess = await self._submit(isolated_db, "u_rev_malformed", {
            "request_id": "req-bad-ts",
            "subject_id": None,
            "started_at": "not-a-date",  # 结构非法
            "finished_at": "2026-08-08T02:20:00Z",
            "duration_sec": 1200,
        })
        assert len(recs) == 1, "malformed session 不得导致作答记录丢失"
        assert recs[0].is_correct is True
        assert sess == []

    @pytest.mark.asyncio
    async def test_long_request_id_stored_until_255(self, isolated_db):
        """≤255 的 request_id 原样保存（不截断）；超 255 才稳定 hash，避免 DataError。"""
        _, _, recs, sess = await self._submit(isolated_db, "u_rev_longreq", {
            "request_id": "req-" + "x" * 100,  # 103 chars，列内原样保存
            "subject_id": None,
            "started_at": "2026-08-08T02:00:00Z",
            "finished_at": "2026-08-08T02:20:00Z",
            "duration_sec": 1200,
        })
        assert len(recs) == 1
        assert len(sess) == 1
        assert len(sess[0].request_id) == 104
        assert sess[0].request_id == "req-" + "x" * 100

    @pytest.mark.asyncio
    async def test_overlong_request_id_hash_not_truncate_collision(self, isolated_db):
        """两个不同超长 request_id（前 255 位相同）绝不能因截断被当成同一次会话。"""
        from sqlalchemy import select

        from app.models.practice_session import PracticeSession
        from app.services import practice_service as svc

        long_a = "req-" + "a" * 255 + "-one"
        long_b = "req-" + "a" * 255 + "-two"
        assert long_a[:255] == long_b[:255]

        async def _submit(uid, req_id, started):
            async with isolated_db.async_session() as db:
                await svc.batch_submit_answers(
                    db, uid,
                    [{"question_id": qid, "user_answer": "A", "used_time": 40}],
                    session_meta={
                        "request_id": req_id, "subject_id": None,
                        "started_at": started + "Z",
                        "finished_at": (datetime.fromisoformat(started) + timedelta(minutes=20)).isoformat() + "Z",
                        "duration_sec": 1200,
                    },
                )
                await db.commit()
            async with isolated_db.async_session() as db:
                sess = (await db.execute(
                    select(PracticeSession).where(PracticeSession.user_id == uid)
                )).scalars().all()
            return sess

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_rev_hash")
            subj = await _make_subject(db)
            qid = await _make_question(db, subj, answer="A")
            await db.commit()

        sess_a = await _submit(uid, long_a, "2026-08-08T02:00:00")
        assert len(sess_a) == 1
        assert sess_a[0].request_id.startswith("h:")
        # 同一超长 id 重试 → 同一 hash，幂等去重仍生效（仍只有一条会话）
        sess_a2 = await _submit(uid, long_a, "2026-08-08T02:00:00")
        assert len(sess_a2) == 1
        # 不同超长 id → 不同 hash key，绝不能被合并成同一次会话
        sess_ab = await _submit(uid, long_b, "2026-08-08T03:00:00")
        assert len(sess_ab) == 2
        assert sess_ab[0].request_id != sess_ab[1].request_id

    @pytest.mark.asyncio
    async def test_nonexistent_subject_falls_back_to_question_subject(self, isolated_db):
        """客户端 subject_id 指向不存在的科目 → 回退到本组题目的科目，会话正常落库。"""
        _, subj, recs, sess = await self._submit(isolated_db, "u_rev_badsubj", {
            "request_id": "req-bad-subj",
            "subject_id": 999999999,  # 不存在的科目
            "started_at": "2026-08-08T02:00:00Z",
            "finished_at": "2026-08-08T02:20:00Z",
            "duration_sec": 1200,
        })
        assert len(recs) == 1
        assert len(sess) == 1
        assert sess[0].subject_id == subj
