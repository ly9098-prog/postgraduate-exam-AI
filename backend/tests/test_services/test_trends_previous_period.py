"""stats_service — get_trends + get_dashboard_v2 趋势（含上一周期）回归测试。"""
import os
import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.practice_record import PracticeRecord
from app.services.stats_service import get_dashboard_v2, get_trends

# ── Helpers ──


def _freeze_time(frozen_date: date):
    """Patch utcnow() to return a fixed date."""
    dt = datetime(frozen_date.year, frozen_date.month, frozen_date.day)
    return patch("app.services.stats_service.utcnow", return_value=dt)


async def _make_db():
    """Create a fresh file-based SQLite database with all tables."""
    # Use file-based SQLite to guarantee isolation between tests
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: sync_conn.exec_driver_sql("PRAGMA foreign_keys=OFF"))
        import app.models.question  # noqa: F401
        import app.models.user  # noqa: F401
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


async def _add_records(session: AsyncSession, records: list[PracticeRecord]):
    for r in records:
        session.add(r)
    await session.commit()


def _make_record(user_id: int, answered_at: datetime, is_correct: bool, **kw):
    return PracticeRecord(
        user_id=user_id, question_id=kw.pop("question_id", 1),
        subject="math", question_type="choice", user_answer="A",
        is_correct=is_correct, used_time=30, answered_at=answered_at, **kw,
    )


# ── Tests ──


class TestGetTrendsDualPeriod:
    """Test get_trends() with start_date parameter (backward compatible)."""

    @pytest.mark.asyncio
    async def test_default_still_works(self):
        """Default call (no start_date) returns the most recent N days."""
        engine, session, db_path = await _make_db()
        try:
            today = date(2026, 7, 12)
            with _freeze_time(today):
                await _add_records(session, [
                    _make_record(user_id=1, answered_at=datetime(2026, 7, 6), is_correct=True),
                ])
                points = await get_trends(session, user_id=1, days=7)

            assert len(points) == 7
            assert points[0]["date"] == "2026-07-06"
            assert points[6]["date"] == "2026-07-12"
            assert points[0]["questions"] == 1
            assert points[0]["correct"] == 1
            for p in points[1:]:
                assert p["questions"] == 0 and p["correct"] == 0 and p["accuracy"] == 0.0
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_start_date_shifts_window(self):
        """Passing start_date shifts the window to a custom range."""
        engine, session, db_path = await _make_db()
        try:
            today = date(2026, 7, 12)
            start = today - timedelta(days=14)
            with _freeze_time(today):
                points = await get_trends(session, user_id=1, days=7, start_date=start)

            assert len(points) == 7
            assert points[0]["date"] == (today - timedelta(days=14)).isoformat()
            assert points[6]["date"] == (today - timedelta(days=8)).isoformat()
        finally:
            await _close_db(engine, session, db_path)


class TestDashboardV2PreviousPeriod:
    """Integration tests for previous period data in get_dashboard_v2()."""

    async def _run(self, user_id, frozen_today, trend_days=7, records=None):
        engine, session, db_path = await _make_db()

        # Clear the in-memory cache so prior test results don't leak
        from app.core.cache import cache
        await cache.clear()

        try:
            if records:
                await _add_records(session, records)

            patcher = patch("app.services.stats_service.utcnow")
            mock_utcnow = patcher.start()
            mock_utcnow.return_value = datetime(frozen_today.year, frozen_today.month, frozen_today.day)
            try:
                result = await get_dashboard_v2(session, user_id, trend_days=trend_days)
            finally:
                patcher.stop()

            return result["trends"]
        finally:
            await _close_db(engine, session, db_path)

    @pytest.mark.asyncio
    async def test_both_periods_have_data(self):
        """trend_days=7, both current & previous period have practice records."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today, records=[
            _make_record(user_id=1, answered_at=datetime(2026, 6, 30), is_correct=True, question_id=1),
            _make_record(user_id=1, answered_at=datetime(2026, 6, 30), is_correct=False, question_id=2),
            _make_record(user_id=1, answered_at=datetime(2026, 7, 2), is_correct=True, question_id=3),
            _make_record(user_id=1, answered_at=datetime(2026, 7, 8), is_correct=True, question_id=4),
            _make_record(user_id=1, answered_at=datetime(2026, 7, 8), is_correct=True, question_id=5),
            _make_record(user_id=1, answered_at=datetime(2026, 7, 10), is_correct=False, question_id=6),
        ])

        assert trends["days"] == 7
        assert len(trends["points"]) == 7
        assert len(trends["previous_points"]) == 7
        assert trends["total_questions"] == 3
        assert trends["active_days"] == 2
        assert trends["avg_accuracy"] == pytest.approx(2 / 3, abs=1e-4)
        assert trends["previous_total_questions"] == 3
        assert trends["previous_active_days"] == 2
        assert trends["previous_avg_accuracy"] == pytest.approx(2 / 3, abs=1e-4)

        prev_points = {p["date"]: p for p in trends["previous_points"]}
        assert prev_points["2026-06-30"]["questions"] == 2
        assert prev_points["2026-06-30"]["correct"] == 1
        assert prev_points["2026-06-30"]["accuracy"] == 0.5

        points = {p["date"]: p for p in trends["points"]}
        assert points["2026-07-08"]["questions"] == 2
        assert points["2026-07-08"]["correct"] == 2
        assert points["2026-07-10"]["questions"] == 1
        assert points["2026-07-10"]["correct"] == 0

    @pytest.mark.asyncio
    async def test_current_has_data_previous_empty(self):
        """Previous period should be all zeros when empty."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today, records=[
            _make_record(user_id=1, answered_at=datetime(2026, 7, 8), is_correct=True, question_id=1),
        ])

        assert trends["total_questions"] == 1
        assert trends["active_days"] == 1
        assert trends["avg_accuracy"] == 1.0
        assert trends["previous_total_questions"] == 0
        assert trends["previous_active_days"] == 0
        assert trends["previous_avg_accuracy"] == 0.0
        for pp in trends["previous_points"]:
            assert pp["questions"] == 0 and pp["correct"] == 0 and pp["accuracy"] == 0.0

    @pytest.mark.asyncio
    async def test_previous_has_data_current_empty(self):
        """Current period should be all zeros when empty."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today, records=[
            _make_record(user_id=1, answered_at=datetime(2026, 7, 2), is_correct=True, question_id=1),
        ])

        assert trends["total_questions"] == 0
        assert trends["active_days"] == 0
        assert trends["avg_accuracy"] == 0.0
        assert trends["previous_total_questions"] == 1
        assert trends["previous_active_days"] == 1
        assert trends["previous_avg_accuracy"] == 1.0

    @pytest.mark.asyncio
    async def test_both_periods_empty(self):
        """All counts should be zero when no records exist."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today)

        assert trends["total_questions"] == 0 and trends["active_days"] == 0
        assert trends["avg_accuracy"] == 0.0
        assert trends["previous_total_questions"] == 0 and trends["previous_active_days"] == 0
        assert trends["previous_avg_accuracy"] == 0.0
        assert all(p["questions"] == 0 for p in trends["points"])
        assert all(p["accuracy"] == 0.0 for p in trends["previous_points"])

    @pytest.mark.asyncio
    async def test_missing_dates_zero_filled(self):
        """Days without records are zero-filled in both periods."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today, records=[
            _make_record(user_id=1, answered_at=datetime(2026, 6, 29), is_correct=True, question_id=1),
            _make_record(user_id=1, answered_at=datetime(2026, 7, 6), is_correct=True, question_id=2),
        ])

        assert trends["previous_points"][0]["questions"] == 1
        for i in range(1, 7):
            assert trends["previous_points"][i]["questions"] == 0
            assert trends["previous_points"][i]["accuracy"] == 0.0
        assert trends["points"][0]["questions"] == 1
        for i in range(1, 7):
            assert trends["points"][i]["questions"] == 0

    @pytest.mark.asyncio
    async def test_dates_ascending(self):
        """Dates are sorted in ascending order in both periods."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today, records=[
            _make_record(user_id=1, answered_at=datetime(2026, 7, 10), is_correct=True, question_id=1),
            _make_record(user_id=1, answered_at=datetime(2026, 6, 30), is_correct=True, question_id=2),
        ])

        assert [p["date"] for p in trends["points"]] == sorted(p["date"] for p in trends["points"])
        assert [p["date"] for p in trends["previous_points"]] == sorted(p["date"] for p in trends["previous_points"])

    @pytest.mark.asyncio
    async def test_boundaries_adjacent_non_overlapping(self):
        """Previous period ends 1 day before current period starts; no overlap."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today)

        prev_end = date.fromisoformat(trends["previous_points"][-1]["date"])
        curr_start = date.fromisoformat(trends["points"][0]["date"])
        assert (curr_start - prev_end).days == 1, "periods should be adjacent"

        prev_dates = {p["date"] for p in trends["previous_points"]}
        curr_dates = {p["date"] for p in trends["points"]}
        assert prev_dates.isdisjoint(curr_dates), "periods must not overlap"

    @pytest.mark.asyncio
    async def test_accuracy_zero_when_no_questions(self):
        """Accuracy is 0.0 when questions == 0 (no division errors)."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today)

        assert trends["previous_avg_accuracy"] == 0.0
        assert trends["avg_accuracy"] == 0.0
        for pp in trends["previous_points"]:
            assert pp["accuracy"] == 0.0
        for p in trends["points"]:
            assert p["accuracy"] == 0.0

    @pytest.mark.asyncio
    async def test_previous_avg_accuracy_overall_ratio(self):
        """previous_avg_accuracy uses overall correct/total ratio, not daily average."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today, records=[
            _make_record(user_id=1, answered_at=datetime(2026, 6, 30), is_correct=False, question_id=1),
            _make_record(user_id=1, answered_at=datetime(2026, 6, 30), is_correct=False, question_id=2),
            _make_record(user_id=1, answered_at=datetime(2026, 7, 2), is_correct=True, question_id=3),
        ])

        assert trends["previous_avg_accuracy"] == pytest.approx(1 / 3, abs=1e-4)

    @pytest.mark.parametrize("days", [30, 90])
    @pytest.mark.asyncio
    async def test_trend_days_30_and_90(self, days):
        """Parametrized test for trend_days = 30 and 90."""
        today = date(2026, 7, 12)
        prev_start = today - timedelta(days=2 * days - 1)
        current_start = today - timedelta(days=days - 1)

        trends = await self._run(user_id=1, frozen_today=today, trend_days=days, records=[
            _make_record(user_id=1, answered_at=datetime(prev_start.year, prev_start.month, prev_start.day), is_correct=True, question_id=1),
            _make_record(user_id=1, answered_at=datetime(current_start.year, current_start.month, current_start.day), is_correct=True, question_id=2),
            _make_record(user_id=1, answered_at=datetime(today.year, today.month, today.day), is_correct=True, question_id=3),
        ])

        assert trends["days"] == days
        assert len(trends["points"]) == days
        assert len(trends["previous_points"]) == days
        assert trends["total_questions"] == 2
        assert trends["previous_total_questions"] == 1

    @pytest.mark.asyncio
    async def test_existing_fields_unchanged(self):
        """Existing fields (points, total_questions, etc.) are not affected."""
        today = date(2026, 7, 12)
        trends = await self._run(user_id=1, frozen_today=today, records=[
            _make_record(user_id=1, answered_at=datetime(2026, 7, 8), is_correct=True, question_id=1),
            _make_record(user_id=1, answered_at=datetime(2026, 7, 8), is_correct=True, question_id=2),
            _make_record(user_id=1, answered_at=datetime(2026, 7, 10), is_correct=False, question_id=3),
        ])

        expected_total, expected_active, expected_acc = 3, 2, round(2 / 3, 4)
        assert trends["total_questions"] == expected_total
        assert trends["active_days"] == expected_active
        assert trends["avg_accuracy"] == expected_acc
        assert len(trends["points"]) == 7
        assert trends["points"][0]["date"] == "2026-07-06"
        assert trends["points"][-1]["date"] == "2026-07-12"

    @pytest.mark.asyncio
    async def test_pydantic_serialization(self):
        """DashboardV2Response can properly serialize the new fields."""
        from app.schemas.stats_v2 import DashboardV2Response

        today = date(2026, 7, 12)
        engine, session, db_path = await _make_db()
        try:
            from app.core.cache import cache
            await cache.clear()

            await _add_records(session, [
                _make_record(user_id=1, answered_at=datetime(2026, 7, 2), is_correct=True, question_id=1),
                _make_record(user_id=1, answered_at=datetime(2026, 7, 8), is_correct=True, question_id=2),
            ])
            with _freeze_time(today):
                raw = await get_dashboard_v2(session, user_id=1, trend_days=7)

            response = DashboardV2Response(**raw)

            assert response.trends.previous_total_questions == 1
            assert response.trends.previous_active_days == 1
            assert response.trends.previous_avg_accuracy == 1.0
            assert len(response.trends.previous_points) == 7
            assert len(response.trends.points) == 7

            dumped = response.model_dump(mode="json")
            for key in ("previous_points", "previous_total_questions", "previous_active_days", "previous_avg_accuracy"):
                assert key in dumped["trends"]
            for key in ("points", "total_questions", "active_days", "avg_accuracy"):
                assert key in dumped["trends"]
        finally:
            await _close_db(engine, session, db_path)
