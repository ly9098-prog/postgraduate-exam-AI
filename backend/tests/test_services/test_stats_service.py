"""stats_service — _calc_consecutive_days 回归测试。

确保 func.date().distinct() 的错误写法已修复为正确的 .distinct()。
"""
import asyncio
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.stats_service import _calc_consecutive_days

TODAY = date(2026, 10, 22)


@pytest.fixture(autouse=True)
def freeze_today(monkeypatch):
    monkeypatch.setattr("app.services.stats_service.shanghai_today", lambda: TODAY)


def _make_db_with_dates(dates_list, dialect="sqlite"):
    """构造返回指定日期列表的 mock db。"""
    db = MagicMock()

    # _calc_consecutive_days 的 execute 返回行: (date_value,)
    mock_result = MagicMock()
    mock_result.all.return_value = [(d,) for d in dates_list]
    db.execute = AsyncMock(return_value=mock_result)
    db.connection = AsyncMock(return_value=SimpleNamespace(
        sync_connection=SimpleNamespace(dialect=SimpleNamespace(name=dialect))
    ))
    return db


def _run(coro):
    return asyncio.run(coro)


class TestCalcConsecutiveDays:
    def test_no_records(self):
        db = _make_db_with_dates([])
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 0

    def test_only_today(self):
        db = _make_db_with_dates([TODAY])
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 1

    def test_consecutive_3_days(self):
        today = TODAY
        dates = [today - timedelta(days=i) for i in range(3)]
        db = _make_db_with_dates(dates)
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 3

    def test_gap_breaks_streak(self):
        today = TODAY
        # today and 2 days ago, but not yesterday
        dates = [today, today - timedelta(days=2)]
        db = _make_db_with_dates(dates)
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 1

    def test_only_old_dates(self):
        # no recent dates — streak should be 0
        old = TODAY - timedelta(days=5)
        db = _make_db_with_dates([old])
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 0

    def test_date_objects_and_string_dates_both_work(self):
        """DB 可能返回 date 对象或字符串，应都能处理。"""
        today = TODAY
        # SQLite returns strings, PostgreSQL returns date objects
        db_str = _make_db_with_dates([today.isoformat()])
        db_obj = _make_db_with_dates([today])
        streak_str = _run(_calc_consecutive_days(db_str, user_id=1))
        streak_obj = _run(_calc_consecutive_days(db_obj, user_id=1))
        assert streak_str == streak_obj == 1

    @pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
    def test_bucketing_query_keeps_china_day_user_and_365_day_window(self, dialect):
        from sqlalchemy.dialects import postgresql, sqlite

        from app.core.time_utils import shanghai_date_utc_range

        db = _make_db_with_dates([TODAY], dialect)
        assert _run(_calc_consecutive_days(db, user_id=37)) == 1
        db.connection.assert_awaited_once()
        statement = db.execute.await_args.args[0]
        compiled = statement.compile(
            dialect=sqlite.dialect() if dialect == "sqlite" else postgresql.dialect()
        )
        sql = str(compiled)
        assert "SELECT DISTINCT" in sql
        assert "practice_records.user_id =" in sql
        assert "practice_records.answered_at >=" in sql
        assert 37 in compiled.params.values()
        assert shanghai_date_utc_range(TODAY - timedelta(days=364))[0] in compiled.params.values()
        if dialect == "sqlite":
            assert "date(practice_records.answered_at," in sql
            assert "+8 hours" in compiled.params.values()
        else:
            assert "INTERVAL '8 hours' AS DATE" in sql
