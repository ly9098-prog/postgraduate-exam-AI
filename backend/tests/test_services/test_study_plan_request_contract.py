"""Direct contracts for study-plan activity dates, snapshots and settings writes."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError

from app.schemas.study_plan import StudyPlanUpsertRequest
from app.services import study_plan_service as service


@pytest.fixture
def db():
    return SimpleNamespace(
        scalar=AsyncMock(),
        scalars=AsyncMock(),
        execute=AsyncMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        get_bind=Mock(return_value=None),
    )


def _db_rows(rows):
    result = SimpleNamespace(all=Mock(return_value=rows))
    result.scalars = Mock(return_value=SimpleNamespace(all=Mock(return_value=rows)))
    return result


def _db_scalars(rows):
    return SimpleNamespace(all=Mock(return_value=rows))


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_activity_date_boundary_and_source_split(db, monkeypatch, reverse):
    rows = {
        "review_records": _db_rows([datetime(2026, 10, 27, 16), None]),
        "practice_sessions": SimpleNamespace(
            all=Mock(
                return_value=[
                    SimpleNamespace(
                        started_at=datetime(2026, 10, 28, 15),
                        finished_at=datetime(2026, 10, 29, 1),
                        duration_sec=36000,
                    )
                ]
            )
        ),
        "pomodoro_sessions": SimpleNamespace(
            scalars=Mock(return_value=SimpleNamespace(all=Mock(return_value=[])))
        ),
        "exam_attempts": SimpleNamespace(
            all=Mock(
                return_value=[
                    SimpleNamespace(
                        started_at=datetime(2026, 10, 30, 1),
                        submitted_at=datetime(2026, 10, 30, 3),
                        duration_sec=7200,
                    )
                ]
            )
        ),
    }

    order = [
        "review_records",
        "practice_sessions",
        "pomodoro_sessions",
        "exam_attempts",
    ]
    if reverse:
        # Empty scope IDs exercise the query guards; only exams are queried.
        order = ["exam_attempts"]

    async def execute(statement, *args, **kwargs):
        # SQLAlchemy compiles model names into FROM/JOIN clauses.
        text = " ".join(str(statement).split())
        expected = next(
            (source for source in order if source in text),
            None,
        )
        assert expected is not None, text
        return rows[expected]

    execute = AsyncMock(side_effect=execute)
    db.execute = execute
    db.scalars = AsyncMock(return_value=_db_scalars([datetime(2026, 10, 27, 16), None]))

    def split_session_duration_by_study_day(session, intervals, day_start):
        assert day_start == 0
        return {}

    monkeypatch.setattr(
        service,
        "split_session_duration_by_study_day",
        split_session_duration_by_study_day,
    )

    result = await service._load_activity_dates(
        db,
        7,
        start_date=date(2026, 10, 27),
        end_date=date(2026, 10, 30),
        all_408_ids=[] if reverse else [1],
        core_408_ids=[] if reverse else [1],
        day_start_minute=0,
    )

    expected = (
        {date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)}
        if not reverse
        else {date(2026, 10, 30)}
    )
    assert result == expected
    if reverse:
        db.scalars.assert_not_awaited()
    else:
        db.scalars.assert_awaited_once()
    assert execute.await_count == (3 if not reverse else 1)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_activity_dates_return_early_without_queries(db):
    result = await service._load_activity_dates(
        db,
        7,
        start_date=date(2026, 10, 30),
        end_date=date(2026, 10, 29),
        all_408_ids=[1],
        core_408_ids=[1],
        day_start_minute=60,
    )
    assert result == set()
    db.scalar.assert_not_awaited()
    db.scalars.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_current_snapshot_reuse_does_not_write(db, monkeypatch):
    row = SimpleNamespace(
        plan_revision=4,
        basis_json={"day_start_minute": 60},
    )
    db.scalar = AsyncMock(return_value=row)
    build = Mock(side_effect=AssertionError("must not rebuild"))
    monkeypatch.setattr(service, "_build_snapshot_payload", build)
    result = await service._ensure_day_snapshot(
        db,
        plan=SimpleNamespace(id=2, revision=4),
        today=date(2026, 10, 30),
        hub={},
        exam_suggestion=None,
        prior_active_days=0,
        day_start_minute=60,
    )
    assert result is row
    db.commit.assert_not_awaited()
    db.refresh.assert_not_awaited()
    build.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_conflict_returns_winner_without_second_commit(db, monkeypatch):
    db.scalar = AsyncMock(return_value=None)
    payload = (45, False, {"review": 45}, {"day_start_minute": 0})
    monkeypatch.setattr(service, "_build_snapshot_payload", Mock(return_value=payload))
    monkeypatch.setattr(service, "_start_explicit_transaction", AsyncMock())
    winner = SimpleNamespace(winner=True)

    calls = {"begin_nested": 0, "winner": 0}

    async def scalar(statement, *args, **kwargs):
        calls["winner"] += 1
        return None if calls["winner"] == 1 else winner

    db.scalar = AsyncMock(side_effect=scalar)

    class Savepoint:
        async def __aenter__(self):
            calls["begin_nested"] += 1
            db.add = Mock()
            return self

        async def __aexit__(self, exc_type, exc, tb):
            assert exc_type is IntegrityError
            return False

    db.begin_nested = Mock(return_value=Savepoint())

    async def flush():
        raise IntegrityError("stmt", {}, Exception("UNIQUE constraint failed"))

    db.flush = AsyncMock(side_effect=flush)
    result = await service._ensure_day_snapshot(
        db,
        plan=SimpleNamespace(id=2, revision=4),
        today=date(2026, 10, 30),
        hub={},
        exam_suggestion=None,
        prior_active_days=0,
        day_start_minute=0,
    )
    assert result is winner
    # The first scalar reads the missing day; the second reloads the winner.
    assert calls == {"begin_nested": 1, "winner": 2}
    db.commit.assert_not_awaited()
    db.refresh.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["plan_revision", "day_start_minute"])
async def test_stale_snapshot_updates_existing_row_and_commits(db, monkeypatch, field):
    row = SimpleNamespace(
        plan_revision=3 if field == "plan_revision" else 4,
        basis_json={"day_start_minute": 0 if field == "day_start_minute" else 60},
    )
    db.scalar.return_value = row
    payload = (90, True, {"review": 90}, {"day_start_minute": 60})
    monkeypatch.setattr(service, "_build_snapshot_payload", Mock(return_value=payload))
    result = await service._ensure_day_snapshot(
        db,
        plan=SimpleNamespace(id=2, revision=4),
        today=date(2026, 10, 30),
        hub={},
        exam_suggestion=None,
        prior_active_days=0,
        day_start_minute=60,
    )
    assert result is row
    assert (row.plan_revision, row.target_minutes, row.is_rest_day) == (4, 90, True)
    assert row.allocation_json is payload[2] and row.basis_json is payload[3]
    db.commit.assert_awaited_once()
    db.refresh.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["same", "changed", "inactive", "missing_revision"])
async def test_upsert_revision_and_commit_refresh_order(db, monkeypatch, mode):
    events = []
    data = StudyPlanUpsertRequest(
        target_date=date(2026, 12, 20),
        daily_minutes=90,
        weekly_days=6,
        priority_mode="balanced",
    )
    plan = SimpleNamespace(
        target_date=data.target_date,
        daily_minutes=60 if mode == "changed" else 90,
        weekly_days=6,
        priority_mode="balanced",
        revision=None if mode == "missing_revision" else 4,
        is_active=mode not in {"inactive", "missing_revision"},
    )
    db.scalar.return_value = plan
    monkeypatch.setattr(service, "shanghai_today", lambda: date(2026, 10, 30))

    async def commit():
        events.append(("commit", plan.revision, plan.is_active, plan.daily_minutes))

    async def refresh(value):
        assert value is plan
        events.append(("refresh",))

    db.commit.side_effect = commit
    db.refresh.side_effect = refresh
    assert await service.upsert_study_plan(db, 7, data) is plan
    expected = 4 if mode == "same" else 2 if mode == "missing_revision" else 5
    assert events == [("commit", expected, True, 90), ("refresh",)]


@pytest.mark.asyncio
async def test_upsert_create_race_reloads_locked_winner(db, monkeypatch):
    data = StudyPlanUpsertRequest(
        target_date=date(2026, 10, 30),
        daily_minutes=90,
        weekly_days=6,
        priority_mode="balanced",
    )
    winner = SimpleNamespace(
        id=8,
        target_date=date(2026, 10, 30),
        daily_minutes=90,
        weekly_days=6,
        priority_mode="balanced",
        revision=1,
        is_active=True,
    )
    db.scalar = AsyncMock(side_effect=[None, winner])
    monkeypatch.setattr(service, "shanghai_today", lambda: date(2026, 10, 30))
    monkeypatch.setattr(service, "_start_explicit_transaction", AsyncMock())

    class Savepoint:
        async def __aenter__(self):
            db.add = Mock()
            return self

        async def __aexit__(self, exc_type, exc, tb):
            assert exc_type is IntegrityError
            return False

    db.begin_nested = Mock(return_value=Savepoint())

    async def flush():
        raise IntegrityError("stmt", {}, Exception("duplicate key"))

    db.flush = AsyncMock(side_effect=flush)
    # Losing the create race returns the reloaded winner, not the failed candidate.
    result = await service.upsert_study_plan(db, 7, data)
    assert result is winner
    assert db.scalar.await_count == 2
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(winner)


@pytest.mark.asyncio
@pytest.mark.parametrize("active", [True, False])
async def test_deactivate_only_writes_when_active_plan_exists(db, active):
    plan = SimpleNamespace(is_active=active, revision=1)
    db.scalar = AsyncMock(return_value=plan)
    await service.deactivate_study_plan(db, 7)
    if active:
        assert plan.is_active is False and plan.revision == 2
        db.commit.assert_awaited_once()
    else:
        assert plan.is_active is active and plan.revision == 1
        db.commit.assert_not_awaited()
    db.refresh.assert_not_awaited()
