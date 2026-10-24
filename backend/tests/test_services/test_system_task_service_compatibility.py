"""系统任务服务纯函数兼容基线。

覆盖 system_task_service 中可独立测试的纯规则：
- _serialize_value：运行结果序列化
- _parse_datetime：ISO 时间解析
- _next_run_datetime：下次运行时间计算
- _running_telemetry_is_stale：运行遥测过期判断
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.system_task_service import (
    ScheduledTaskDefinition,
    TaskRunOutcome,
    _next_run_datetime,
    _parse_datetime,
    _running_telemetry_is_stale,
    _serialize_value,
)


class TestSerializeValue:
    """_serialize_value 将运行结果序列化为展示文本。"""

    def test_none_returns_default(self) -> None:
        assert _serialize_value(None) == "执行完成"

    def test_task_run_outcome(self) -> None:
        outcome = TaskRunOutcome(status="success", message="备份成功")
        assert _serialize_value(outcome) == "备份成功"

    def test_string_passthrough(self) -> None:
        assert _serialize_value("自定义消息") == "自定义消息"

    def test_dict_json(self) -> None:
        result = _serialize_value({"key": "value"})
        assert "key" in result
        assert "value" in result

    def test_list_json(self) -> None:
        result = _serialize_value([1, 2, 3])
        assert "1" in result

    def test_int_fallback(self) -> None:
        result = _serialize_value(42)
        assert "42" in result


class TestParseDatetime:
    """_parse_datetime 解析 ISO 格式时间字符串。"""

    def test_none_returns_none(self) -> None:
        assert _parse_datetime(None) is None

    def test_empty_returns_none(self) -> None:
        assert _parse_datetime("") is None

    def test_valid_iso(self) -> None:
        result = _parse_datetime("2026-01-15T10:30:00")
        assert result is not None
        assert result.year == 2026
        assert result.hour == 10

    def test_z_suffix(self) -> None:
        result = _parse_datetime("2026-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2026

    def test_invalid_returns_none(self) -> None:
        assert _parse_datetime("not a date") is None


class TestNextRunDatetime:
    """_next_run_datetime 计算下次确定性运行时间。"""

    def _make_def(self, **kwargs) -> ScheduledTaskDefinition:
        defaults = dict(
            task_id="test_task",
            name="测试任务",
            description="测试",
            schedule_label="每小时",
        )
        defaults.update(kwargs)
        return ScheduledTaskDefinition(**defaults)

    def test_disabled_returns_none(self) -> None:
        d = self._make_def(enabled=False, interval_seconds=60)
        now = datetime(2026, 1, 1, 12, 0, 0)
        assert _next_run_datetime(d, now) is None

    def test_daily_hour_future(self) -> None:
        d = self._make_def(daily_hour_utc=14)
        now = datetime(2026, 1, 1, 12, 0, 0)
        result = _next_run_datetime(d, now)
        assert result is not None
        assert result.hour == 14

    def test_daily_hour_past_rolls_to_next_day(self) -> None:
        d = self._make_def(daily_hour_utc=10)
        now = datetime(2026, 1, 1, 12, 0, 0)
        result = _next_run_datetime(d, now)
        assert result is not None
        assert result.hour == 10
        assert result.day == 2

    def test_interval_seconds(self) -> None:
        d = self._make_def(interval_seconds=300)
        now = datetime(2026, 1, 1, 12, 0, 0)
        result = _next_run_datetime(d, now)
        assert result is not None
        diff = (result - now).total_seconds()
        assert diff == 300

    def test_cron_minute_future(self) -> None:
        d = self._make_def(cron_minute_utc=30)
        now = datetime(2026, 1, 1, 12, 0, 0)
        result = _next_run_datetime(d, now)
        assert result is not None
        assert result.minute == 30

    def test_cron_minute_past_next_hour(self) -> None:
        d = self._make_def(cron_minute_utc=15)
        now = datetime(2026, 1, 1, 12, 30, 0)
        result = _next_run_datetime(d, now)
        assert result is not None
        assert result.hour == 13
        assert result.minute == 15

    def test_no_schedule_returns_none(self) -> None:
        d = self._make_def()
        now = datetime(2026, 1, 1, 12, 0, 0)
        assert _next_run_datetime(d, now) is None


class TestRunningTelemetryIsStale:
    """_running_telemetry_is_stale 判断运行状态是否过期。"""

    def _make_def(self, **kwargs) -> ScheduledTaskDefinition:
        defaults = dict(
            task_id="test_task",
            name="测试",
            description="测试",
            schedule_label="测试",
        )
        defaults.update(kwargs)
        return ScheduledTaskDefinition(**defaults)

    def test_not_running_returns_false(self) -> None:
        d = self._make_def()
        now = datetime(2026, 1, 1, 12, 0, 0)
        assert _running_telemetry_is_stale(d, {"state": "idle"}, now) is False

    def test_running_no_start_time_returns_true(self) -> None:
        d = self._make_def()
        now = datetime(2026, 1, 1, 12, 0, 0)
        assert _running_telemetry_is_stale(d, {"state": "running"}, now) is True

    def test_running_recent_returns_false(self) -> None:
        d = self._make_def()
        now = datetime(2026, 1, 1, 12, 0, 0)
        started = datetime(2026, 1, 1, 11, 30, 0)
        telemetry = {
            "state": "running",
            "last_started_at": started.isoformat(),
        }
        assert _running_telemetry_is_stale(d, telemetry, now) is False

    def test_running_old_returns_true(self) -> None:
        d = self._make_def()
        now = datetime(2026, 1, 1, 12, 0, 0)
        started = datetime(2026, 1, 1, 4, 0, 0)
        telemetry = {
            "state": "running",
            "last_started_at": started.isoformat(),
        }
        assert _running_telemetry_is_stale(d, telemetry, now) is True
