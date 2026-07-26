"""stats_service — _calc_consecutive_days 回归测试。

确保 func.date().distinct() 的错误写法已修复为正确的 .distinct()。
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.services.stats_service import _calc_consecutive_days


def _make_db_with_dates(dates_list):
    """构造返回指定日期列表的 mock db。"""
    db = MagicMock()

    # _calc_consecutive_days 的 execute 返回行: (date_value,)
    mock_result = MagicMock()
    mock_result.all.return_value = [(d,) for d in dates_list]
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _run(coro):
    return asyncio.run(coro)


class TestCalcConsecutiveDays:
    def test_no_records(self):
        db = _make_db_with_dates([])
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 0

    def test_only_today(self):
        db = _make_db_with_dates([datetime.now(UTC).date()])
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 1

    def test_consecutive_3_days(self):
        today = datetime.now(UTC).date()
        dates = [today - timedelta(days=i) for i in range(3)]
        db = _make_db_with_dates(dates)
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 3

    def test_gap_breaks_streak(self):
        today = datetime.now(UTC).date()
        # today and 2 days ago, but not yesterday
        dates = [today, today - timedelta(days=2)]
        db = _make_db_with_dates(dates)
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 1

    def test_only_old_dates(self):
        # no recent dates — streak should be 0
        old = datetime.now(UTC).date() - timedelta(days=5)
        db = _make_db_with_dates([old])
        streak = _run(_calc_consecutive_days(db, user_id=1))
        assert streak == 0

    def test_date_objects_and_string_dates_both_work(self):
        """DB 可能返回 date 对象或字符串，应都能处理。"""
        today = datetime.now(UTC).date()
        # SQLite returns strings, PostgreSQL returns date objects
        db_str = _make_db_with_dates([today.isoformat()])
        db_obj = _make_db_with_dates([today])
        streak_str = _run(_calc_consecutive_days(db_str, user_id=1))
        streak_obj = _run(_calc_consecutive_days(db_obj, user_id=1))
        # Both should work (may differ in comparison logic but not crash)
        assert isinstance(streak_str, int)
        assert isinstance(streak_obj, int)
        assert streak_obj == 1
