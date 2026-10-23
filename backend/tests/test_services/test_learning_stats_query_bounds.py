from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.core.time_utils import shanghai_date_utc_range
from app.services import stats_service, study_report_service


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.connection = AsyncMock(
        return_value=SimpleNamespace(
            sync_connection=SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
        )
    )
    result = MagicMock()
    result.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dialect", "params"),
    [
        (sqlite.dialect(), shanghai_date_utc_range(date(2026, 7, 6))),
        (postgresql.dialect(), shanghai_date_utc_range(date(2026, 7, 6))),
    ],
)
async def test_stats_trends_query_is_bounded_to_requested_window(dialect, params):
    db = _mock_db()
    start = date(2026, 7, 6)

    points = await stats_service.get_trends(db, user_id=7, days=3, start_date=start)

    assert len(points) == 3
    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=dialect)
    assert "practice_records.answered_at <" in str(compiled)
    assert params[0] in compiled.params.values()
    assert shanghai_date_utc_range(date(2026, 7, 9))[0] in compiled.params.values()


@pytest.mark.asyncio
async def test_study_report_trend_query_is_bounded_to_today(monkeypatch):
    today = date(2026, 7, 12)
    monkeypatch.setattr(study_report_service, "shanghai_today", lambda: today)
    db = _mock_db()

    result = await study_report_service.get_study_trend(db, user_id=7, days=3)

    assert len(result["items"]) == 3
    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=sqlite.dialect())
    assert "practice_records.answered_at <" in str(compiled)
    assert shanghai_date_utc_range(date(2026, 7, 10))[0] in compiled.params.values()
    assert shanghai_date_utc_range(date(2026, 7, 13))[0] in compiled.params.values()
