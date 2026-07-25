"""Tests for time_utils: UTC serialization, naive/aware handling, date range."""
from datetime import UTC, datetime, timezone, timedelta

import pytest

from app.core.time_utils import (
    normalize_to_naive_utc,
    serialize_utc_datetime,
    utcnow,
)


class TestSerializeUtcDatetime:
    """API 输出的 UTC 序列化必须带 Z 后缀。"""

    def test_naive_datetime_gets_z(self):
        dt = datetime(2026, 7, 4, 12, 30, 0)
        assert serialize_utc_datetime(dt) == "2026-07-04T12:30:00Z"

    def test_aware_utc_datetime_gets_z(self):
        dt = datetime(2026, 7, 4, 12, 30, 0, tzinfo=timezone.utc)
        assert serialize_utc_datetime(dt) == "2026-07-04T12:30:00Z"

    def test_aware_positive_offset_converts_to_utc(self):
        dt = datetime(2026, 7, 4, 15, 30, 0, tzinfo=timezone(timedelta(hours=3)))
        result = serialize_utc_datetime(dt)
        assert result == "2026-07-04T12:30:00Z"

    def test_aware_negative_offset_converts_to_utc(self):
        dt = datetime(2026, 7, 4, 6, 30, 0, tzinfo=timezone(timedelta(hours=-5)))
        result = serialize_utc_datetime(dt)
        assert result == "2026-07-04T11:30:00Z"

    def test_with_microseconds(self):
        dt = datetime(2026, 7, 4, 12, 30, 0, 123456)
        result = serialize_utc_datetime(dt)
        assert result == "2026-07-04T12:30:00.123456Z"

    def test_winter_time(self):
        """冬令时（UTC+2）也能正确转换为 UTC。"""
        dt = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        result = serialize_utc_datetime(dt)
        assert result == "2026-01-15T12:00:00Z"


class TestNormalizeToNaiveUtc:
    """输入参数归一化：always→naive UTC。"""

    def test_naive_stays_unchanged(self):
        dt = datetime(2026, 7, 4, 12, 30, 0)
        result = normalize_to_naive_utc(dt)
        assert result == dt
        assert result.tzinfo is None

    def test_aware_utc_strips_tz(self):
        dt = datetime(2026, 7, 4, 12, 30, 0, tzinfo=timezone.utc)
        result = normalize_to_naive_utc(dt)
        assert result == datetime(2026, 7, 4, 12, 30, 0)
        assert result.tzinfo is None

    def test_aware_positive_offset_converts(self):
        dt = datetime(2026, 7, 4, 15, 30, 0, tzinfo=timezone(timedelta(hours=3)))
        result = normalize_to_naive_utc(dt)
        assert result == datetime(2026, 7, 4, 12, 30, 0)

    def test_z_suffix_string_parsed_and_normalized(self):
        """Simulates what happens when FastAPI parses 2026-07-04T12:30:00Z"""
        from pydantic import TypeAdapter
        ta = TypeAdapter(datetime)
        dt = ta.validate_python("2026-07-04T12:30:00Z")
        result = normalize_to_naive_utc(dt)
        assert result == datetime(2026, 7, 4, 12, 30, 0)
        assert result.tzinfo is None

    def test_positive_offset_string_parsed(self):
        """FastAPI 解析 +03:00 时间后也能正确归一化。"""
        from pydantic import TypeAdapter
        ta = TypeAdapter(datetime)
        dt = ta.validate_python("2026-07-04T15:30:00+03:00")
        result = normalize_to_naive_utc(dt)
        assert result == datetime(2026, 7, 4, 12, 30, 0)


class TestUtcnow:
    """utcnow 返回 naive datetime。"""

    def test_returns_naive(self):
        now = utcnow()
        assert now.tzinfo is None

    def test_close_to_aware_utc(self):
        """与 aware UTC 的差值应在合理范围内。"""
        now_naive = utcnow()
        now_aware = datetime.now(timezone.utc)
        diff = abs((now_aware.replace(tzinfo=None) - now_naive).total_seconds())
        assert diff < 2  # within 2 seconds
