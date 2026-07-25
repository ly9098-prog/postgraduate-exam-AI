"""Review master/unmaster API 测试 — 使用真实数据库 + TestClient。

覆盖 route 权限、状态往返、调度恢复和幂等性。
"""
import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.core.time_utils import utcnow
from app.main import app
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.user import User
from app.models.wrong_question import WrongQuestion

client = TestClient(app)


# ── DB helpers (real SQLite, same pattern as test_wrong_question_batch) ──


async def _make_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: sync_conn.exec_driver_sql("PRAGMA foreign_keys=OFF"))
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


async def _add_schedule(session, user_id=1, question_id=1, *,
                        mastered=False, next_review_at=None):
    """Create a ReviewSchedule that is already due (past)."""
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


def _make_mock_user(user_id=1):
    user = MagicMock(spec=User)
    user.id = user_id
    return user


class TestMasterUnmasterAPI:
    """Review route master/unmaster — 真实 DB + HTTP TestClient。"""

    @pytest.mark.asyncio
    async def _setup(self, user_id=1):
        self.engine, self.session, self.db_path = await _make_db()
        await _add_user(self.session, user_id)
        self.user = _make_mock_user(user_id)
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.session

    async def _teardown(self):
        app.dependency_overrides.clear()
        await _close_db(self.engine, self.session, self.db_path)

    # ── master → unmaster roundtrip ──

    @pytest.mark.asyncio
    async def test_master_then_unmaster_roundtrip(self):
        """master → unmaster 后 schedule 和 wq 状态正确。"""
        await self._setup()
        try:
            sch = await _add_schedule(self.session, 1, 100)
            wq = await _add_wq(self.session, 1, 100)

            # Master
            resp = client.post(f"/api/v1/review/{sch.id}/master")
            assert resp.status_code == 200
            assert resp.json()["mastered"] is True

            await self.session.refresh(sch)
            assert sch.mastered is True
            await self.session.refresh(wq)
            assert wq.mastered is True
            assert wq.mastered_at is not None

            # Unmaster
            resp = client.post(f"/api/v1/review/{sch.id}/unmaster")
            assert resp.status_code == 200
            assert resp.json()["mastered"] is False

            await self.session.refresh(sch)
            assert sch.mastered is False
            await self.session.refresh(wq)
            assert wq.mastered is False
            assert wq.mastered_at is None
        finally:
            await self._teardown()

    @pytest.mark.asyncio
    async def test_master_idempotent(self):
        """重复 master 返回 200。"""
        await self._setup()
        try:
            sch = await _add_schedule(self.session, 1, 100)

            resp1 = client.post(f"/api/v1/review/{sch.id}/master")
            resp2 = client.post(f"/api/v1/review/{sch.id}/master")
            assert resp1.status_code == 200
            assert resp2.status_code == 200
            assert resp2.json()["mastered"] is True

            await self.session.refresh(sch)
            assert sch.mastered is True
        finally:
            await self._teardown()

    @pytest.mark.asyncio
    async def test_unmaster_idempotent(self):
        """重复 unmaster 返回 200。"""
        await self._setup()
        try:
            sch = await _add_schedule(self.session, 1, 100, mastered=False)

            resp1 = client.post(f"/api/v1/review/{sch.id}/unmaster")
            resp2 = client.post(f"/api/v1/review/{sch.id}/unmaster")
            assert resp1.status_code == 200
            assert resp2.status_code == 200
            assert resp2.json()["mastered"] is False

            await self.session.refresh(sch)
            assert sch.mastered is False
        finally:
            await self._teardown()

    @pytest.mark.asyncio
    async def test_master_unmaster_keeps_review_records(self):
        """master → unmaster 不减少 review_record 数量。"""
        await self._setup()
        try:
            sch = await _add_schedule(self.session, 1, 100)

            # Create a review record
            record = ReviewRecord(
                user_id=1, question_id=100, schedule_id=sch.id,
                rating=4, reviewed_at=utcnow(),
            )
            self.session.add(record)
            await self.session.commit()

            cnt_before = await self.session.execute(
                select(func.count(ReviewRecord.id))
            )
            before = cnt_before.scalar()

            # Master then unmaster
            client.post(f"/api/v1/review/{sch.id}/master")
            client.post(f"/api/v1/review/{sch.id}/unmaster")

            cnt_after = await self.session.execute(
                select(func.count(ReviewRecord.id))
            )
            assert cnt_after.scalar() == before
        finally:
            await self._teardown()

    @pytest.mark.asyncio
    async def test_unmaster_schedule_appears_in_today_review(self):
        """unmaster 后已到期的 schedule 重新出现在今日复习。"""
        await self._setup()
        try:
            # Create schedule that is already due but mastered
            sch = await _add_schedule(self.session, 1, 100, mastered=True)

            # Before unmaster: should NOT appear in review
            cnt1 = await self.session.execute(
                select(func.count(ReviewSchedule.id)).where(
                    ReviewSchedule.user_id == 1,
                    ReviewSchedule.next_review_at <= utcnow(),
                    ReviewSchedule.mastered == False,
                )
            )
            assert cnt1.scalar() == 0

            # Unmaster
            resp = client.post(f"/api/v1/review/{sch.id}/unmaster")
            assert resp.status_code == 200

            # After unmaster: should appear
            cnt2 = await self.session.execute(
                select(func.count(ReviewSchedule.id)).where(
                    ReviewSchedule.user_id == 1,
                    ReviewSchedule.next_review_at <= utcnow(),
                    ReviewSchedule.mastered == False,
                )
            )
            assert cnt2.scalar() == 1
        finally:
            await self._teardown()

    # ── Cross-user ──

    @pytest.mark.asyncio
    async def test_cannot_master_other_user_schedule(self):
        """user2 无法 master user1 的 schedule。"""
        await self._setup(user_id=2)
        try:
            # Schedule belongs to user 1
            sch = await _add_schedule(self.session, 1, 100)

            resp = client.post(f"/api/v1/review/{sch.id}/master")
            assert resp.status_code == 404
        finally:
            await self._teardown()

    @pytest.mark.asyncio
    async def test_cannot_unmaster_other_user_schedule(self):
        """user2 无法 unmaster user1 的 schedule。"""
        await self._setup(user_id=2)
        try:
            sch = await _add_schedule(self.session, 1, 100, mastered=True)

            resp = client.post(f"/api/v1/review/{sch.id}/unmaster")
            assert resp.status_code == 404
        finally:
            await self._teardown()

    # ── Not found ──

    @pytest.mark.asyncio
    async def test_master_not_found_returns_404(self):
        """不存在的 schedule_id 返回 404。"""
        await self._setup()
        try:
            resp = client.post("/api/v1/review/99999/master")
            assert resp.status_code == 404
        finally:
            await self._teardown()

    @pytest.mark.asyncio
    async def test_unmaster_not_found_returns_404(self):
        """不存在的 schedule_id 返回 404。"""
        await self._setup()
        try:
            resp = client.post("/api/v1/review/99999/unmaster")
            assert resp.status_code == 404
        finally:
            await self._teardown()
