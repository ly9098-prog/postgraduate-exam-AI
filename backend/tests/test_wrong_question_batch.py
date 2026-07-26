"""wrong_question_service — batch operations, enhanced list, stats, task-flow regression tests."""
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.question import Question
from app.models.review_scheduler import ReviewSchedule
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.services.wrong_question_service import (
    batch_operate,
    get_stats,
    get_task_flow,
    list_wrong_enriched,
    record_wrong,
)

# ── Helpers ──


async def _make_db():
    """Create a fresh file-based SQLite database with all tables."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: sync_conn.exec_driver_sql("PRAGMA foreign_keys=OFF"))
        import app.models.user  # noqa
        import app.models.question  # noqa
        import app.models.admin  # noqa
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = async_session()
    return engine, session, db_path


async def _close_db(engine, session, db_path):
    await session.close()
    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _add_user(session, user_id=1):
    user = User(id=user_id, openid=f"test_{user_id}", nickname=f"user_{user_id}")
    session.add(user)
    await session.commit()
    return user


async def _add_wq(session, user_id=1, question_id=1, **kw):
    wq = WrongQuestion(
        user_id=user_id, question_id=question_id,
        error_type=kw.pop("error_type", "other"),
        wrong_answer=kw.pop("wrong_answer", "B"),
        review_count=kw.pop("review_count", 1),
        mastered=kw.pop("mastered", False),
        last_review_at=kw.pop("last_review_at", datetime(2026, 7, 10)),
        is_active=kw.pop("is_active", True),
        **kw,
    )
    session.add(wq)
    await session.commit()
    await session.refresh(wq)
    return wq


# ── Batch Operations Tests ──


class TestBatchOperate:

    @pytest.mark.asyncio
    async def test_add_to_review_creates_schedule(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100)

            result = await batch_operate(session, user_id=1, action="add_to_review", ids=[wq.id])

            assert result["success"] is True
            assert result["action"] == "add_to_review"
            assert result["updated_count"] == 1
            assert result["skipped_count"] == 0

            from sqlalchemy import func, select
            sch_count = await session.execute(
                select(func.count(ReviewSchedule.id)).where(
                    ReviewSchedule.user_id == 1,
                    ReviewSchedule.question_id == 100,
                )
            )
            assert sch_count.scalar() == 1
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_add_to_review_idempotent(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100)

            # First call creates schedule
            r1 = await batch_operate(session, user_id=1, action="add_to_review", ids=[wq.id])
            assert r1["updated_count"] == 1

            # Second call: schedule already exists and is due today → skipped
            r2 = await batch_operate(session, user_id=1, action="add_to_review", ids=[wq.id])
            assert r2["skipped_count"] == 1
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_mark_mastered_sets_fields(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100)

            result = await batch_operate(session, user_id=1, action="mark_mastered", ids=[wq.id])

            assert result["updated_count"] == 1
            await session.refresh(wq)
            assert wq.mastered is True
            assert wq.mastered_at is not None
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_mark_mastered_idempotent(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100)

            r1 = await batch_operate(session, user_id=1, action="mark_mastered", ids=[wq.id])
            assert r1["updated_count"] == 1

            r2 = await batch_operate(session, user_id=1, action="mark_mastered", ids=[wq.id])
            assert r2["skipped_count"] == 1
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_remove_from_book_soft_delete(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100)

            result = await batch_operate(session, user_id=1, action="remove_from_book", ids=[wq.id])

            assert result["updated_count"] == 1
            await session.refresh(wq)
            assert wq.is_active is False
            assert wq.removed_at is not None
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_remove_from_book_excluded_from_list(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100)

            # Before removal: visible
            items, total = await list_wrong_enriched(session, user_id=1)
            assert total == 1

            # Remove from book
            await batch_operate(session, user_id=1, action="remove_from_book", ids=[wq.id])

            # After removal: not visible
            items, total = await list_wrong_enriched(session, user_id=1)
            assert total == 0
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_delete_permanently_removes_wq(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100)

            result = await batch_operate(session, user_id=1, action="delete", ids=[wq.id])

            assert result["updated_count"] == 1
            from sqlalchemy import func, select
            count = await session.execute(
                select(func.count(WrongQuestion.id)).where(WrongQuestion.user_id == 1)
            )
            assert count.scalar() == 0
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_cross_user_ids_silently_skipped(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            await _add_user(session, 2)
            wq_user1 = await _add_wq(session, user_id=1, question_id=100)

            # user 2 tries to operate on user 1's WQ
            result = await batch_operate(session, user_id=2, action="remove_from_book", ids=[wq_user1.id])

            assert result["skipped_count"] == 1
            assert wq_user1.id in result["skipped_ids"]
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_dedup_preserves_order(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq1 = await _add_wq(session, 1, 100)
            wq2 = await _add_wq(session, 1, 200)

            result = await batch_operate(session, user_id=1, action="remove_from_book", ids=[wq1.id, wq2.id, wq1.id])

            assert result["requested_count"] == 2
            assert result["updated_count"] == 2
        finally:
            await _close_db(engine, session, db_path)


# ── Reactivate Tests ──


class TestReactivateWrongQuestion:

    @pytest.mark.asyncio
    async def test_record_wrong_reactivates_soft_deleted(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100, is_active=False, removed_at=datetime(2026, 7, 5), review_count=3)

            result = await record_wrong(session, user_id=1, question_id=100, wrong_answer="C")

            assert result.id == wq.id
            assert result.is_active is True
            assert result.removed_at is None
            assert result.mastered is False
            assert result.wrong_answer == "C"
            assert result.review_count == 4
        finally:
            await _close_db(engine, session, db_path)


# ── Enhanced Stats Tests ──


class TestEnhancedStats:

    @pytest.mark.asyncio
    async def test_stats_counts_mastered(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            await _add_wq(session, 1, 100, mastered=False)
            await _add_wq(session, 1, 200, mastered=True, mastered_at=datetime(2026, 7, 10))

            stats = await get_stats(session, 1)
            assert stats["total"] == 2
            assert stats["unmastered"] == 1
            assert stats["mastered"] == 1
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_high_frequency_count(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            await _add_wq(session, 1, 100, review_count=1, mastered=False)
            await _add_wq(session, 1, 200, review_count=3, mastered=False)
            await _add_wq(session, 1, 300, review_count=5, mastered=False)

            stats = await get_stats(session, 1)
            assert stats["high_frequency_count"] == 2
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_high_frequency_excludes_mastered(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            await _add_wq(session, 1, 100, review_count=5, mastered=True)

            stats = await get_stats(session, 1)
            assert stats["high_frequency_count"] == 0
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_soft_deleted_excluded_from_stats(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            await _add_wq(session, 1, 100, is_active=True)
            await _add_wq(session, 1, 200, is_active=False, removed_at=datetime(2026, 7, 5))

            stats = await get_stats(session, 1)
            assert stats["total"] == 1
            assert stats["unmastered"] == 1
        finally:
            await _close_db(engine, session, db_path)


# ── Task Flow Tests ──


class TestTaskFlow:

    @pytest.mark.asyncio
    async def test_groups_are_mutually_exclusive(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq1 = await _add_wq(session, 1, 101, review_count=1, mastered=False)
            wq2 = await _add_wq(session, 1, 102, review_count=3, mastered=False)
            wq3 = await _add_wq(session, 1, 103, review_count=1, mastered=True)

            result = await get_task_flow(session, 1, preview_size=3)

            all_item_ids = set()
            for g in result["groups"]:
                for item in g["items"]:
                    all_item_ids.add(item["id"])

            # Each WQ should appear exactly once across groups
            assert len(all_item_ids) == 3
            # Mastered item should be in mastered group
            mastered_ids = {item["id"] for item in result["groups"][4]["items"]}
            assert wq3.id in mastered_ids
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_preview_size_respected(self):
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            for i in range(100, 120):
                await _add_wq(session, 1, i, review_count=1, mastered=True)

            result = await get_task_flow(session, 1, preview_size=2)

            for g in result["groups"]:
                if g["key"] == "mastered":
                    assert len(g["items"]) == 2
                    assert g["total"] == 20
        finally:
            await _close_db(engine, session, db_path)


# ── API-level Tests ──


class TestBatchAPI:

    def _make_mock_user(self, user_id=1):
        user = MagicMock(spec=User)
        user.id = user_id
        return user

    def _make_mock_db(self):
        return AsyncMock(spec=AsyncSession)

    @pytest.mark.asyncio
    async def test_batch_empty_ids(self):
        from fastapi.testclient import TestClient

        from app.api.v1 import wrong_questions as wq_module
        from app.core.security import get_current_user
        from app.main import app

        user = self._make_mock_user(1)
        db = self._make_mock_db()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[wq_module.get_db] = lambda: db

        try:
            client = TestClient(app)
            resp = client.post("/api/v1/wrong-questions/batch", json={
                "action": "add_to_review",
                "ids": [],
            })
            assert resp.status_code == 422  # Pydantic min_length validation
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_batch_too_many_ids(self):
        from fastapi.testclient import TestClient

        from app.api.v1 import wrong_questions as wq_module
        from app.core.security import get_current_user
        from app.main import app

        user = self._make_mock_user(1)
        db = self._make_mock_db()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[wq_module.get_db] = lambda: db

        try:
            client = TestClient(app)
            resp = client.post("/api/v1/wrong-questions/batch", json={
                "action": "add_to_review",
                "ids": list(range(101)),
            })
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_batch_invalid_action(self):
        from fastapi.testclient import TestClient

        from app.api.v1 import wrong_questions as wq_module
        from app.core.security import get_current_user
        from app.main import app

        user = self._make_mock_user(1)
        db = self._make_mock_db()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[wq_module.get_db] = lambda: db

        try:
            client = TestClient(app)
            resp = client.post("/api/v1/wrong-questions/batch", json={
                "action": "invalid_action",
                "ids": [1],
            })
            assert resp.status_code == 422  # Enum validation
        finally:
            app.dependency_overrides.clear()

    def test_unauthorized_returns_401(self):
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        resp = client.post("/api/v1/wrong-questions/batch", json={
            "action": "add_to_review",
            "ids": [1],
        })
        assert resp.status_code == 403  # Missing auth header


# ── Master / Unmaster ──


async def _add_question(session, question_id=1, subject_code="math"):
    """Create a Question + Subject for schedule creation tests."""
    from app.models.admin import Subject
    subj = Subject(code=subject_code, name="数学", path=f"/{subject_code}", level=1)
    session.add(subj)
    await session.flush()
    q = Question(
        id=question_id, subject_id=subj.id,
        question_type="single_choice",
        content={"text": "test"},
        answer="A",
        difficulty=3,
        review_status="approved",
    )
    session.add(q)
    await session.commit()
    return q


async def _add_schedule(session, user_id=1, question_id=1, *,
                        mastered=False, next_review_at=None):
    """Create a ReviewSchedule that is already due (past)."""
    from app.core.time_utils import utcnow
    schedule = ReviewSchedule(
        user_id=user_id,
        question_id=question_id,
        subject="math",
        interval=1,
        ease_factor=2.5,
        repetitions=0,
        next_review_at=next_review_at or (utcnow() - timedelta(hours=1)),
        mastered=mastered,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


class TestMasterUnmaster:

    # ── Basic batch unmark_mastered ──

    @pytest.mark.asyncio
    async def test_batch_unmark_mastered_success(self):
        """batch unmark_mastered 后 wq/schedule mastered=False, mastered_at=None."""
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100, mastered=True,
                               mastered_at=datetime(2026, 7, 12))
            sch = await _add_schedule(session, 1, 100, mastered=True)

            result = await batch_operate(session, user_id=1,
                                         action="unmark_mastered", ids=[wq.id])
            assert result["success"] is True
            assert result["updated_count"] == 1
            assert result["skipped_count"] == 0

            await session.refresh(wq)
            assert wq.mastered is False
            assert wq.mastered_at is None

            await session.refresh(sch)
            assert sch.mastered is False
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_batch_mark_unmark_roundtrip(self):
        """batch mark_mastered → unmark_mastered 状态往返。"""
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100)
            sch = await _add_schedule(session, 1, 100)

            # Mark mastered
            r1 = await batch_operate(session, user_id=1,
                                     action="mark_mastered", ids=[wq.id])
            assert r1["updated_count"] == 1
            await session.refresh(wq)
            assert wq.mastered is True
            assert wq.mastered_at is not None
            await session.refresh(sch)
            assert sch.mastered is True

            # Unmark
            r2 = await batch_operate(session, user_id=1,
                                     action="unmark_mastered", ids=[wq.id])
            assert r2["updated_count"] == 1
            await session.refresh(wq)
            assert wq.mastered is False
            assert wq.mastered_at is None
            await session.refresh(sch)
            assert sch.mastered is False
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_batch_unmark_mastered_idempotent(self):
        """重复 unmark_mastered updated_count=0（skipped）。"""
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100, mastered=False)
            await _add_schedule(session, 1, 100, mastered=False)

            r1 = await batch_operate(session, user_id=1,
                                     action="unmark_mastered", ids=[wq.id])
            assert r1["updated_count"] == 0
            assert r1["skipped_count"] == 1
        finally:
            await _close_db(engine, session, db_path)

    # ── Convergence ──

    @pytest.mark.asyncio
    async def test_batch_unmark_fixes_inconsistent_state(self):
        """wq.mastered=True 但 schedule.mastered=False → unmark 修正两侧为 False。"""
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100, mastered=True,
                               mastered_at=datetime(2026, 7, 12))
            await _add_schedule(session, 1, 100, mastered=False)

            result = await batch_operate(session, user_id=1,
                                         action="unmark_mastered", ids=[wq.id])
            assert result["updated_count"] == 1

            await session.refresh(wq)
            assert wq.mastered is False
            assert wq.mastered_at is None
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_batch_mark_fixes_wq_mastered_at_none(self):
        """wq.mastered=True, mastered_at=None → mark_mastered 补全 mastered_at。"""
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100, mastered=True, mastered_at=None)
            await _add_schedule(session, 1, 100, mastered=True)

            result = await batch_operate(session, user_id=1,
                                         action="mark_mastered", ids=[wq.id])
            assert result["updated_count"] == 1

            await session.refresh(wq)
            assert wq.mastered is True
            assert wq.mastered_at is not None  # 补全
        finally:
            await _close_db(engine, session, db_path)

    # ── Missing schedule ──

    @pytest.mark.asyncio
    async def test_batch_unmark_creates_schedule_if_missing(self):
        """WQ 存在但无 ReviewSchedule → unmark 后创建 schedule 恢复调度资格。"""
        from sqlalchemy import select

        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            await _add_question(session, 200)
            wq = await _add_wq(session, 1, 200, mastered=True,
                               mastered_at=datetime(2026, 7, 12))

            result = await batch_operate(session, user_id=1,
                                         action="unmark_mastered", ids=[wq.id])
            assert result["updated_count"] == 1

            await session.refresh(wq)
            assert wq.mastered is False
            assert wq.mastered_at is None

            # Verify schedule was created
            sch_result = await session.execute(
                select(ReviewSchedule).where(
                    ReviewSchedule.user_id == 1,
                    ReviewSchedule.question_id == 200,
                )
            )
            schedule = sch_result.scalar_one_or_none()
            assert schedule is not None
            assert schedule.mastered is False
            assert schedule.next_review_at is not None
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_batch_unmark_no_duplicate_schedule(self):
        """unmark 不产生重复 schedule（已存在时不重复创建）。"""
        from sqlalchemy import func, select

        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100, mastered=True,
                               mastered_at=datetime(2026, 7, 12))
            await _add_schedule(session, 1, 100, mastered=True)

            # First unmark
            r1 = await batch_operate(session, user_id=1,
                                     action="unmark_mastered", ids=[wq.id])
            assert r1["updated_count"] == 1

            # Count schedules
            cnt = await session.execute(
                select(func.count(ReviewSchedule.id)).where(
                    ReviewSchedule.user_id == 1,
                    ReviewSchedule.question_id == 100,
                )
            )
            assert cnt.scalar() == 1  # still exactly 1
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_batch_unmark_does_not_reactivate_removed(self):
        """已 remove_from_book 的 wq unmark 后不重新激活（不创建新 schedule）。"""
        from sqlalchemy import func, select

        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100, mastered=True,
                               mastered_at=datetime(2026, 7, 12),
                               is_active=False, removed_at=datetime(2026, 7, 10))

            result = await batch_operate(session, user_id=1,
                                         action="unmark_mastered", ids=[wq.id])
            # mastered 字段确实有变化（True→False），所以 updated_count=1
            assert result["updated_count"] == 1
            await session.refresh(wq)
            assert wq.mastered is False

            # 但不应该创建新 schedule
            cnt = await session.execute(
                select(func.count(ReviewSchedule.id)).where(
                    ReviewSchedule.user_id == 1,
                    ReviewSchedule.question_id == 100,
                )
            )
            assert cnt.scalar() == 0
        finally:
            await _close_db(engine, session, db_path)

    # ── Edge cases ──

    @pytest.mark.asyncio
    async def test_batch_unmark_with_duplicate_ids(self):
        """重复 id 去重后只操作一次，updated_count=1。"""
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100, mastered=True,
                               mastered_at=datetime(2026, 7, 12))
            await _add_schedule(session, 1, 100, mastered=True)

            result = await batch_operate(session, user_id=1,
                                         action="unmark_mastered",
                                         ids=[wq.id, wq.id])
            assert result["requested_count"] == 1
            assert result["updated_count"] == 1
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_batch_unmark_cross_user_silently_skipped(self):
        """user2 无法 unmark user1 的错题。"""
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            await _add_user(session, 2)
            wq = await _add_wq(session, 1, 100, mastered=True,
                               mastered_at=datetime(2026, 7, 12))

            result = await batch_operate(session, user_id=2,
                                         action="unmark_mastered", ids=[wq.id])
            assert result["skipped_count"] == 1
            assert result["updated_count"] == 0
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_batch_unmark_not_found_silently_skipped(self):
        """不存在的 id 静默跳过。"""
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)

            result = await batch_operate(session, user_id=1,
                                         action="unmark_mastered", ids=[9999])
            assert result["skipped_count"] == 1
            assert result["updated_count"] == 0
        finally:
            await _close_db(engine, session, db_path)

    # ── backward compatibility ──

    @pytest.mark.asyncio
    async def test_remove_from_book_still_works_and_keeps_history(self):
        """remove_from_book 仍可用，不删错题历史（幂等跳过）。"""
        from sqlalchemy import func, select

        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100)

            result = await batch_operate(session, user_id=1,
                                         action="remove_from_book", ids=[wq.id])
            assert result["updated_count"] == 1
            assert result["success"] is True

            await session.refresh(wq)
            assert wq.is_active is False
            assert wq.removed_at is not None

            # wq still exists (not deleted)
            cnt = await session.execute(
                select(func.count(WrongQuestion.id)).where(WrongQuestion.id == wq.id)
            )
            assert cnt.scalar() == 1

            # Second call idempotent
            r2 = await batch_operate(session, user_id=1,
                                     action="remove_from_book", ids=[wq.id])
            assert r2["skipped_count"] == 1
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_batch_mark_still_works(self):
        """mark_mastered 仍然可用，兼容已有前端调用。"""
        engine, session, db_path = await _make_db()
        try:
            await _add_user(session, 1)
            wq = await _add_wq(session, 1, 100, mastered=False)
            await _add_schedule(session, 1, 100, mastered=False)

            result = await batch_operate(session, user_id=1,
                                         action="mark_mastered", ids=[wq.id])
            assert result["updated_count"] == 1
            assert result["success"] is True

            await session.refresh(wq)
            assert wq.mastered is True
            assert wq.mastered_at is not None
        finally:
            await _close_db(engine, session, db_path)
