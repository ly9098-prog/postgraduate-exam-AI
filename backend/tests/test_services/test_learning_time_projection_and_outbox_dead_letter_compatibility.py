"""Pure-function compatibility baseline for learning time projection and dead-letter replay audit.

Pins:
- ``learning_time_projection.today_utc`` / ``date_utc_range`` China-natural-day UTC bounds
- ``learning_time_projection.coerce_date`` SQLite/PostgreSQL date row normalization
- ``outbox_dead_letter.build_dead_letter_replay_audit`` audit payload shape
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.services.learning_time_projection import (
    coerce_date,
    date_utc_range,
    today_utc,
)
from app.services.outbox_dead_letter import build_dead_letter_replay_audit


def _shanghai_now() -> datetime:
    from app.core.time_utils import shanghai_now

    return shanghai_now()


def _shanghai_today() -> date:
    return _shanghai_now().date()


def _today_bounds_naive_utc() -> tuple[datetime, datetime]:
    today = _shanghai_today()
    start_local = datetime.combine(today, time.min, tzinfo=timezone(timedelta(hours=8)))
    start_utc = (start_local - timedelta(hours=8)).replace(tzinfo=None)
    return start_utc, start_utc + timedelta(days=1)


class TestTodayUtc:
    def test_returns_naive_utc_without_tzinfo(self):
        result = today_utc()
        assert result.tzinfo is None

    def test_matches_shanghai_today_start_in_utc(self):
        expected_start, _ = _today_bounds_naive_utc()
        assert today_utc() == expected_start

    def test_is_at_midnight_16_previous_day_utc(self):
        # Shanghai today 00:00 == UTC 16:00 of the previous UTC day.
        result = today_utc()
        assert result.hour == 16
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 0
        # And it equals yesterday's shanghai date boundary in UTC.
        shanghai_today = _shanghai_today()
        expected = datetime.combine(
            shanghai_today, time.min, tzinfo=timezone(timedelta(hours=8))
        ) - timedelta(hours=8)
        assert result == expected.replace(tzinfo=None)


class TestDateUtcRange:
    def test_returns_naive_utc_pair_without_tzinfo(self):
        start, end = date_utc_range(date(2026, 8, 16))
        assert start.tzinfo is None
        assert end.tzinfo is None

    def test_shanghai_date_maps_to_previous_utc_day_16_00(self):
        # 2026-08-16 China time -> [2026-08-15 16:00:00 UTC, 2026-08-16 16:00:00 UTC)
        start, end = date_utc_range(date(2026, 8, 16))
        assert start == datetime(2026, 8, 15, 16, 0, 0)
        assert end == datetime(2026, 8, 16, 16, 0, 0)

    def test_range_is_half_open_exactly_one_day(self):
        start, end = date_utc_range(date(2026, 1, 1))
        assert end - start == timedelta(days=1)

    def test_month_boundary_does_not_loop_around(self):
        # 2026-03-01 Shanghai -> 2026-02-28 16:00 UTC start (non-leap year)
        start, end = date_utc_range(date(2026, 3, 1))
        assert start == datetime(2026, 2, 28, 16, 0, 0)
        assert end == datetime(2026, 3, 1, 16, 0, 0)

    def test_leap_year_february_29_handled(self):
        # 2024 is a leap year; 2024-03-01 Shanghai -> 2024-02-29 16:00 UTC start
        start, _ = date_utc_range(date(2024, 3, 1))
        assert start == datetime(2024, 2, 29, 16, 0, 0)

    def test_year_boundary_maps_back_into_previous_year(self):
        # 2026-01-01 Shanghai -> 2025-12-31 16:00 UTC start
        start, _ = date_utc_range(date(2026, 1, 1))
        assert start == datetime(2025, 12, 31, 16, 0, 0)

    def test_same_date_range_is_deterministic(self):
        # Called twice with same input -> identical pair (no wall-clock bleed).
        a = date_utc_range(date(2026, 7, 4))
        b = date_utc_range(date(2026, 7, 4))
        assert a == b


class TestCoerceDate:
    def test_date_instance_returned_unchanged(self):
        d = date(2026, 8, 16)
        assert coerce_date(d) is d

    def test_datetime_instance_is_a_date_returns_self(self):
        # datetime is a subclass of date -> isinstance check passes -> returned unchanged
        dt = datetime(2026, 8, 16, 12, 0, 0)
        result = coerce_date(dt)
        assert result is dt

    def test_iso_string_parsed_to_date(self):
        assert coerce_date("2026-08-16") == date(2026, 8, 16)

    def test_iso_string_with_time_suffix_uses_first_ten_chars(self):
        # SQLite may return "YYYY-MM-DD HH:MM:SS.ffffff"; only first 10 chars matter.
        assert coerce_date("2026-08-16 12:34:56.789012") == date(2026, 8, 16)

    def test_iso_string_with_t_separator_uses_first_ten_chars(self):
        assert coerce_date("2026-08-16T12:34:56") == date(2026, 8, 16)

    def test_malformed_string_returns_none(self):
        assert coerce_date("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert coerce_date("") is None

    def test_short_string_returns_none(self):
        # Less than 10 chars -> date.fromisoformat raises ValueError
        assert coerce_date("2026-08") is None

    def test_invalid_month_returns_none(self):
        assert coerce_date("2026-13-01") is None

    def test_invalid_day_returns_none(self):
        assert coerce_date("2026-02-30") is None

    def test_none_returns_none(self):
        assert coerce_date(None) is None

    def test_integer_returns_none(self):
        assert coerce_date(20260816) is None

    def test_list_returns_none(self):
        assert coerce_date(["2026-08-16"]) is None

    def test_only_iso_first_ten_chars_used_when_extra_garbage_present(self):
        # "2026-08-16GARBAGE" -> first 10 chars "2026-08-16" parse OK
        assert coerce_date("2026-08-16GARBAGE") == date(2026, 8, 16)


class TestBuildDeadLetterReplayAudit:
    def test_returns_expected_payload_shape(self):
        payload = build_dead_letter_replay_audit(
            actor_id=42, task_id="task-abc", request_id="req-xyz"
        )
        assert payload == {
            "action": "dead_letter_replay",
            "actor_id": 42,
            "resource_type": "task_outbox",
            "resource_id": "task-abc",
            "request_id": "req-xyz",
        }

    def test_keys_are_stable(self):
        payload = build_dead_letter_replay_audit(1, "t", "r")
        assert set(payload.keys()) == {
            "action",
            "actor_id",
            "resource_type",
            "resource_id",
            "request_id",
        }

    def test_action_constant_is_dead_letter_replay(self):
        assert build_dead_letter_replay_audit(0, "", "")["action"] == "dead_letter_replay"

    def test_resource_type_constant_is_task_outbox(self):
        assert build_dead_letter_replay_audit(0, "", "")["resource_type"] == "task_outbox"

    def test_actor_id_preserved_as_int(self):
        # No coercion to str; audit layer expects raw int for actor_id
        payload = build_dead_letter_replay_audit(actor_id=99, task_id="t", request_id="r")
        assert payload["actor_id"] == 99
        assert isinstance(payload["actor_id"], int)

    def test_zero_actor_id_preserved(self):
        # System / anonymous actor (id=0) must not be dropped or coerced
        payload = build_dead_letter_replay_audit(0, "t", "r")
        assert payload["actor_id"] == 0

    def test_negative_actor_id_preserved(self):
        # Defensive: callers should never pass negative, but we pin behavior
        # so future validation changes are explicit, not silent.
        payload = build_dead_letter_replay_audit(-1, "t", "r")
        assert payload["actor_id"] == -1

    def test_task_id_preserved_as_string(self):
        payload = build_dead_letter_replay_audit(1, "task-uuid-123", "req")
        assert payload["resource_id"] == "task-uuid-123"
        assert isinstance(payload["resource_id"], str)

    def test_request_id_preserved_as_string(self):
        payload = build_dead_letter_replay_audit(1, "t", "req-uuid-456")
        assert payload["request_id"] == "req-uuid-456"
        assert isinstance(payload["request_id"], str)

    def test_empty_strings_preserved(self):
        payload = build_dead_letter_replay_audit(0, "", "")
        assert payload["resource_id"] == ""
        assert payload["request_id"] == ""

    def test_distinct_inputs_produce_distinct_payloads(self):
        a = build_dead_letter_replay_audit(1, "t1", "r1")
        b = build_dead_letter_replay_audit(2, "t2", "r2")
        assert a != b
        assert a["actor_id"] == 1 and a["resource_id"] == "t1" and a["request_id"] == "r1"
