"""今日复习时长（ReviewSession）纳入番茄钟学习统计「刷题时长」的回归测试。

- 纯复习：今日/每日/趋势/科目时长 += duration_sec，顶层 sessions 仍为番茄次数
- 与 Pomodoro 重叠：不 double count
- history 混排 review 记录（record_key = review:<id>）
- lifetime 起点包含首条复习
- _record_review_session：按科目拆分时长守恒、request_id 幂等、失败题不计时、
  非法计时元数据静默丢弃
- grade_batch_review 把 session_meta 传递给计时记录
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


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def isolated_db(monkeypatch_module):
    tmp = tempfile.NamedTemporaryFile(prefix="review_session_stats_", suffix=".db", delete=False)
    tmp.close()
    monkeypatch_module.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    monkeypatch_module.setenv("REDIS_URL", "")

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

    yield SimpleNamespace(engine=engine, async_session=session_factory)

    try:
        await engine.dispose()
        os.unlink(tmp.name)
    except Exception:
        pass


@pytest_asyncio.fixture(autouse=True)
async def reset_tables(isolated_db):
    from sqlalchemy import delete

    from app.models.admin import Subject
    from app.models.pomodoro import (
        PomodoroPauseInterval,
        PomodoroSession,
        UserPomodoroSettings,
    )
    from app.models.practice_session import PracticeSession
    from app.models.question import Question
    from app.models.review_scheduler import ReviewSchedule, ReviewSession
    from app.models.user import User

    async with isolated_db.async_session() as db:
        for model in (
            ReviewSession, ReviewSchedule, PomodoroPauseInterval, PomodoroSession,
            PracticeSession, UserPomodoroSettings, Question, Subject, User,
        ):
            await db.execute(delete(model))
        await db.commit()


def _utc(*parts):
    return datetime(*parts)


async def _make_user(db, openid: str) -> int:
    from app.models.user import User

    u = User(openid=openid)
    db.add(u)
    await db.flush()
    return u.id


async def _make_subject(db, code: str, name: str) -> int:
    from app.models.admin import Subject

    subj = Subject(code=code, name=name, level=1, path=code, is_active=True, sort_order=0)
    db.add(subj)
    await db.flush()
    return subj.id


def _make_review(uid, subj, started, finished, duration, request_id="seg1:1"):
    from app.models.review_scheduler import ReviewSession

    return ReviewSession(
        user_id=uid, subject_id=subj, request_id=request_id,
        started_at=started, finished_at=finished, duration_sec=duration,
        question_count=5, correct_count=4, wrong_count=1, status="completed",
    )


def _make_pomo(uid, subj, start, end, actual):
    from app.models.pomodoro import PomodoroSession

    return PomodoroSession(
        user_id=uid, subject_id=subj, preset="standard",
        work_duration=25, break_duration=5,
        start_time=start, end_time=end, actual_duration=actual, status="completed",
    )


async def _make_schedule(db, uid, subject_id, *, schedule_subject=True) -> int:
    """Question + ReviewSchedule; schedule_subject=False 模拟 subject_id 为空的旧数据。"""
    from app.models.question import Question
    from app.models.review_scheduler import ReviewSchedule

    q = Question(
        subject_id=subject_id, question_type="single_choice", content={"stem": "q"},
        options={"A": "a", "B": "b"}, answer="A", difficulty=3, is_active=True,
    )
    db.add(q)
    await db.flush()
    sch = ReviewSchedule(
        user_id=uid, question_id=q.id, question_version_id=1,
        subject_id=subject_id if schedule_subject else None,
        next_review_at=_utc(2026, 8, 8, 0, 0),
    )
    db.add(sch)
    await db.flush()
    return sch.id


def _ok(schedule_id, is_correct=True):
    return {"schedule_id": schedule_id, "success": True, "is_correct": is_correct}


async def _review_rows(isolated_db, uid):
    from sqlalchemy import select

    from app.models.review_scheduler import ReviewSession

    async with isolated_db.async_session() as db:
        return (
            await db.execute(
                select(ReviewSession)
                .where(ReviewSession.user_id == uid)
                .order_by(ReviewSession.request_id)
            )
        ).scalars().all()


# ── 统计口径 ─────────────────────────────────────────────────────────

class TestReviewStatisticsMerge:
    @pytest.mark.asyncio
    async def test_review_only_counts_as_duration(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))
        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_review_only")
            subj = await _make_subject(db, "math2_r1", "高等数学")
            db.add(_make_review(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 10), 600))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)
            summary = await svc.get_daily_summary(db, uid, date(2026, 8, 8))
            trends = await svc.get_trends(db, uid, days=7)
            range_summary = await svc.get_range_summary(db, uid, date(2026, 8, 8), date(2026, 8, 8))

        assert stats["today_duration_sec"] == 600
        assert stats["today_sessions"] == 0  # 顶层 sessions 保持番茄次数
        assert summary["duration_sec"] == 600
        assert summary["sessions"] == 0
        assert summary["subjects"][0]["subject_name"] == "高等数学"
        assert summary["subjects"][0]["duration_sec"] == 600
        assert summary["subjects"][0]["sessions"] == 1
        assert {t["date"]: t for t in trends}["2026-08-08"]["duration_sec"] == 600
        assert range_summary["duration_sec"] == 600
        assert range_summary["active_days"] == 1

    @pytest.mark.asyncio
    async def test_review_practice_pomodoro_sum_and_overlap_dedup(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.models.practice_session import PracticeSession
        from app.services import pomodoro_service as svc

        def _make_practice(uid, subj, started, finished, duration):
            return PracticeSession(
                user_id=uid, subject_id=subj, request_id="p1", mode="random",
                started_at=started, finished_at=finished, duration_sec=duration,
                question_count=5, answered_count=5, correct_count=5, wrong_count=0,
                status="completed",
            )

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))
        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_review_mix")
            subj = await _make_subject(db, "math2_r2", "高等数学")
            # 番茄 02:00-02:25；复习 02:20-02:30（后 5 分钟未被番茄覆盖）；刷题 03:00-03:20
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            db.add(_make_review(uid, subj, _utc(2026, 8, 8, 2, 20), _utc(2026, 8, 8, 2, 30), 600))
            db.add(_make_practice(uid, subj, _utc(2026, 8, 8, 3, 0), _utc(2026, 8, 8, 3, 20), 1200))
            await db.commit()

        async with isolated_db.async_session() as db:
            stats = await svc.get_stats(db, uid)

        assert stats["today_duration_sec"] == 1500 + 300 + 1200
        assert stats["today_sessions"] == 1

    @pytest.mark.asyncio
    async def test_history_includes_review_records(self, isolated_db):
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_review_hist")
            subj = await _make_subject(db, "math2_r3", "高等数学")
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            db.add(_make_review(uid, subj, _utc(2026, 8, 8, 3, 0), _utc(2026, 8, 8, 3, 10), 540))
            db.add(_make_review(uid, None, _utc(2026, 8, 7, 3, 0), _utc(2026, 8, 7, 3, 10), 60, "seg0:none"))
            await db.commit()

        async with isolated_db.async_session() as db:
            items, total = await svc.get_history(db, uid, page=1, page_size=20)
            day_items, day_total = await svc.get_history(
                db, uid, page=1, page_size=20, filter_date=date(2026, 8, 8)
            )

        assert total == 3
        assert [i["record_type"] for i in items] == ["review", "pomodoro", "review"]
        assert items[0]["record_key"].startswith("review:")
        assert items[0]["subject_name"] == "高等数学"
        assert items[0]["actual_duration"] == 540
        assert items[2]["subject_name"] == "未分类"
        assert day_total == 2
        assert {i["record_type"] for i in day_items} == {"review", "pomodoro"}

    @pytest.mark.asyncio
    async def test_lifetime_starts_from_first_review(self, isolated_db, monkeypatch):
        from app.core import time_utils
        from app.services import pomodoro_service as svc

        monkeypatch.setattr(time_utils, "utcnow", lambda: _utc(2026, 8, 8, 10, 0, 0))
        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_review_life")
            subj = await _make_subject(db, "math2_r4", "高等数学")
            db.add(_make_review(uid, subj, _utc(2026, 8, 5, 2, 0), _utc(2026, 8, 5, 2, 10), 600))
            db.add(_make_pomo(uid, subj, _utc(2026, 8, 8, 2, 0), _utc(2026, 8, 8, 2, 25), 1500))
            await db.commit()

        async with isolated_db.async_session() as db:
            lifetime = await svc.get_lifetime_summary(db, uid)

        assert lifetime["start_date"] == "2026-08-05"
        assert lifetime["duration_sec"] == 2100
        assert lifetime["active_days"] == 2


# ── grade-batch 计时记录 ──────────────────────────────────────────────

def _meta(request_id="seg_abcdef12", minutes_ago=10, duration=300):
    from app.core.time_utils import utcnow

    finished = utcnow() - timedelta(seconds=1)
    started = finished - timedelta(minutes=minutes_ago)
    return {
        "request_id": request_id,
        "started_at": started.isoformat() + "Z",
        "finished_at": finished.isoformat() + "Z",
        "duration_sec": duration,
    }


class TestRecordReviewSession:
    @pytest.mark.asyncio
    async def test_split_by_subject_conserves_duration(self, isolated_db):
        from app.services.review_scheduler import _record_review_session

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_rec_split")
            math = await _make_subject(db, "math2_s1", "高等数学")
            ds = await _make_subject(db, "ds_s1", "数据结构")
            m1 = await _make_schedule(db, uid, math)
            m2 = await _make_schedule(db, uid, math, schedule_subject=False)  # 回退 question.subject_id
            d1 = await _make_schedule(db, uid, ds)
            failed = await _make_schedule(db, uid, ds)
            await db.commit()

            results = [
                _ok(m1), _ok(m2, is_correct=False), _ok(d1),
                {"schedule_id": failed, "success": False, "is_correct": False},
            ]
            await _record_review_session(db, uid, _meta(duration=301), results)

        rows = await _review_rows(isolated_db, uid)
        by_subject = {r.subject_id: r for r in rows}
        assert set(by_subject) == {math, ds}
        assert sum(r.duration_sec for r in rows) == 301
        assert by_subject[math].duration_sec == 201  # 2/3，余数给题数多的科目
        assert by_subject[ds].duration_sec == 100
        assert by_subject[math].question_count == 2
        assert by_subject[math].correct_count == 1
        assert by_subject[math].wrong_count == 1
        assert by_subject[ds].question_count == 1  # 失败题不计入
        assert all(r.request_id.startswith("seg_abcdef12:") for r in rows)
        assert all(r.finished_at >= r.started_at for r in rows)

    @pytest.mark.asyncio
    async def test_replay_same_segment_is_noop(self, isolated_db):
        from app.services.review_scheduler import _record_review_session

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_rec_replay")
            math = await _make_subject(db, "math2_s2", "高等数学")
            s1 = await _make_schedule(db, uid, math)
            await db.commit()
            await _record_review_session(db, uid, _meta(duration=120), [_ok(s1)])
            # 网络重试：同一分段 id、更长时长，也不重复计时
            await _record_review_session(db, uid, _meta(duration=180), [_ok(s1)])
            await _record_review_session(db, uid, _meta("seg_other_1", duration=60), [_ok(s1)])

        rows = await _review_rows(isolated_db, uid)
        assert sorted(r.duration_sec for r in rows) == [60, 120]

    @pytest.mark.asyncio
    async def test_invalid_or_missing_meta_records_nothing(self, isolated_db):
        from app.services.review_scheduler import _record_review_session

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_rec_invalid")
            math = await _make_subject(db, "math2_s3", "高等数学")
            s1 = await _make_schedule(db, uid, math)
            await db.commit()
            await _record_review_session(db, uid, None, [_ok(s1)])
            await _record_review_session(db, uid, _meta("seg_zero_01", duration=0), [_ok(s1)])
            await _record_review_session(db, uid, {"request_id": "seg_bad_001", "duration_sec": "x"}, [_ok(s1)])
            await _record_review_session(
                db, uid, _meta("seg_fail_01"), [{"schedule_id": s1, "success": False}]
            )

        assert await _review_rows(isolated_db, uid) == []

    def test_normalize_clamps_clock_and_duration(self):
        from app.core.time_utils import utcnow
        from app.services.review_scheduler import (
            REVIEW_SESSION_MAX_DURATION_SEC,
            _normalize_review_session,
        )

        future = (utcnow() + timedelta(hours=2)).isoformat() + "Z"
        w = _normalize_review_session({
            "request_id": "seg_clock_1", "started_at": future, "finished_at": future,
            "duration_sec": 90,
        })
        assert w["finished_at"] <= utcnow()
        assert w["duration_sec"] == 90
        assert (w["finished_at"] - w["started_at"]).total_seconds() == 90

        # 前台时长超出墙钟窗口：扩展起点，不丢时长
        meta = _meta("seg_clock_2", minutes_ago=1, duration=200)
        w = _normalize_review_session(meta)
        assert (w["finished_at"] - w["started_at"]).total_seconds() >= 200

        huge = _normalize_review_session({"request_id": "seg_clock_3", "duration_sec": 10**9})
        assert huge["duration_sec"] == REVIEW_SESSION_MAX_DURATION_SEC

    @pytest.mark.asyncio
    async def test_grade_batch_review_forwards_session_meta(self, monkeypatch):
        from app.services import review_scheduler as rs

        captured = {}

        async def fake_load_revision_views(db, version_ids):
            return {}

        async def fake_record(db, user_id, session_meta, results):
            captured["args"] = (user_id, session_meta, results)

        class _DB:
            async def commit(self):
                pass

        monkeypatch.setattr(rs, "load_revision_views", fake_load_revision_views)
        monkeypatch.setattr(rs, "_record_review_session", fake_record)
        meta = {"request_id": "seg_fwd_001", "duration_sec": 30}
        item = {
            "schedule_id": 1, "question_id": 1, "question_version_id": 9,
            "occurrence_seq": 0, "request_id": "req_item_01", "user_answer": "A",
        }
        out = await rs.grade_batch_review(_DB(), 7, [item], session_meta=meta)

        assert out["total"] == 1
        user_id, forwarded, results = captured["args"]
        assert user_id == 7
        assert forwarded == meta
        assert results[0]["success"] is False  # 版本缺失 → 不会被计时
