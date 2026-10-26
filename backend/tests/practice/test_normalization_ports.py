"""Exercise live historical patch ports at observable evaluation boundaries."""

import asyncio
import inspect
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.practice import normalization as rules
from tests.practice.test_normalization_session_contract import normalize, session_meta


class ObservedSession(dict):
    def __init__(self, events, hook=lambda _key: None, **overrides):
        super().__init__(session_meta(**overrides))
        self.events = events
        self.hook = hook

    def __bool__(self):
        self.events.append("bool")
        return dict.__len__(self) > 0

    def get(self, key, default=None):
        self.events.append(key)
        self.hook(key)
        return super().get(key, default)


def test_session_reads_once_in_order_without_eager_snapshot():
    events = []
    normalize(ObservedSession(events))
    assert events == [
        "bool", "started_at", "finished_at", "duration_sec", "request_id",
        "subject_id", "mode", "answered_count", "question_count",
    ]


@pytest.mark.parametrize(
    "field",
    ["started_at", "finished_at", "duration_sec", "request_id", "subject_id",
     "mode", "answered_count", "question_count"],
)
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
def test_get_failure_preserves_identity_and_stops_later_reads(field, failure_type):
    events = []
    failure = failure_type("sentinel")

    def hook(key):
        if key == field:
            raise failure

    with pytest.raises(failure_type) as caught:
        normalize(ObservedSession(events, hook))
    assert caught.value is failure
    assert events[-1] == field
    assert len(events) == len(set(events))


def test_both_dates_are_parsed_before_invalid_date_rejection(monkeypatch):
    events = []
    monkeypatch.setattr(rules, "parse_session_datetime", lambda value: events.append(value))
    with pytest.raises(ValueError, match="ISO"):
        normalize(session_meta())
    assert events == ["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"]


def test_parser_is_loaded_before_get_and_reloaded_for_the_second_date(monkeypatch):
    events = []
    first = datetime(2026, 1, 1)
    second = datetime(2026, 1, 1, 0, 1)

    def replacement(value):
        events.append(("replacement", value))
        return second

    def initial(value):
        events.append(("initial", value))
        return first

    def hook(key):
        if key == "started_at":
            monkeypatch.setattr(rules, "parse_session_datetime", replacement)

    monkeypatch.setattr(rules, "parse_session_datetime", initial)
    result = normalize(ObservedSession(events, hook))
    assert events[:5] == [
        "bool", "started_at", ("initial", "2026-01-01T00:00:00Z"),
        "finished_at", ("replacement", "2026-01-01T00:01:00Z"),
    ]
    assert result["started_at"] is first and result["finished_at"] is second


def test_request_port_load_precedes_get_and_mode_port_stays_live(monkeypatch):
    token = object()
    events = []

    def initial(value):
        events.append(("initial-request", value))
        monkeypatch.setattr(rules, "PRACTICE_ALLOWED_MODES", {"patched"})
        return token

    def hook(key):
        if key == "request_id":
            monkeypatch.setattr(
                rules, "normalize_practice_request_id",
                lambda _value: pytest.fail("request callee was already loaded"),
            )

    monkeypatch.setattr(rules, "normalize_practice_request_id", initial)
    result = normalize(ObservedSession(events, hook, mode="patched"))
    assert result["request_id"] is token
    assert ("initial-request", "  request  ") in events


@pytest.mark.parametrize(
    ("target", "replacement", "duration", "message"),
    [
        ("_PRACTICE_DURATION_ROUNDING_TOLERANCE", -1, 60, "墙钟"),
        ("PRACTICE_SESSION_MAX_DURATION_SEC", 59, 60, "允许上限"),
    ],
)
def test_duration_limits_are_read_after_duration_conversion(
    monkeypatch, target, replacement, duration, message,
):
    class Duration:
        def __int__(self):
            monkeypatch.setattr(rules, target, replacement)
            return duration

    with pytest.raises(ValueError, match=message):
        normalize(session_meta(duration_sec=Duration()))


def test_original_module_builtin_overrides_remain_live_during_session(monkeypatch):
    events = []

    def later_int(value):
        events.append(("later-int", value))
        return int(value)

    def initial_int(value):
        events.append(("initial-int", value))
        monkeypatch.setattr(rules, "int", later_int)
        return int(value)

    def observed_max(*values):
        events.append(("max", values))
        return max(*values)

    monkeypatch.setattr(rules, "int", initial_int, raising=False)
    monkeypatch.setattr(rules, "max", observed_max, raising=False)
    normalize(session_meta())
    assert events == [
        ("initial-int", 60), ("later-int", 60.0), ("max", (0, 60)),
        ("later-int", "7"), ("later-int", 3), ("later-int", 5), ("max", (0, 5)),
        ("max", (0, 3)), ("max", (0, 2)), ("max", (0, 1)),
    ]


@pytest.mark.parametrize(
    ("name", "last_read"),
    [
        ("parse_session_datetime", "bool"),
        ("_PRACTICE_DURATION_ROUNDING_TOLERANCE", "duration_sec"),
        ("PRACTICE_SESSION_MAX_DURATION_SEC", "duration_sec"),
        ("normalize_practice_request_id", "duration_sec"),
        ("PRACTICE_ALLOWED_MODES", "mode"),
    ],
)
def test_missing_historical_port_has_name_error_and_original_read_position(
    monkeypatch, name, last_read,
):
    events = []
    monkeypatch.delattr(rules, name)
    with pytest.raises(NameError) as caught:
        normalize(ObservedSession(events))
    assert str(caught.value) == f"name '{name}' is not defined"
    assert caught.value.name == name
    assert caught.value.__context__ is None
    assert events[-1] == last_read


@pytest.mark.parametrize("field", ["duration_sec", "subject_id", "answered_count", "question_count"])
def test_int_conversion_errors_preserve_existing_cause_policy(field):
    failure = TypeError("sentinel")

    class BadInt:
        def __int__(self):
            raise failure

    if field == "question_count":
        assert normalize(session_meta(question_count=BadInt()))["question_count"] == 3
        return
    with pytest.raises(ValueError) as caught:
        normalize(session_meta(**{field: BadInt()}))
    assert caught.value.__context__ is failure
    assert caught.value.__cause__ is (failure if field == "answered_count" else None)
    assert caught.value.__suppress_context__ is (field == "answered_count")


@pytest.mark.parametrize("as_text", [False, True])
def test_naive_datetime_warning_precedes_dynamic_utc_conversion(monkeypatch, as_text):
    events = []
    value = "2026-01-01T00:00:00" if as_text else datetime(2026, 1, 1)
    sentinel = object()

    def warning(*args):
        events.append(args)
        monkeypatch.setattr(rules, "normalize_to_naive_utc", lambda _value: sentinel)

    monkeypatch.setattr(rules, "logger", SimpleNamespace(warning=warning))
    assert rules.parse_session_datetime(value) is sentinel
    assert events == [(
        "practice session datetime 缺少时区信息，按 UTC 处理（若为北京时间将偏移 8h）: %s"
        if as_text else "practice session datetime 缺少时区信息，按 UTC 处理: %s",
        value,
    )]


def test_warning_exception_is_not_swallowed_or_followed_by_conversion(monkeypatch):
    failure = RuntimeError("warning failed")

    def warning(*_args):
        raise failure

    monkeypatch.setattr(rules, "logger", SimpleNamespace(warning=warning))
    monkeypatch.setattr(
        rules, "normalize_to_naive_utc",
        lambda _value: pytest.fail("conversion must follow a successful warning"),
    )
    with pytest.raises(RuntimeError) as caught:
        rules.parse_session_datetime(datetime(2026, 1, 1))
    assert caught.value is failure


def test_entry_signature_metadata_and_consumer_import_identity():
    from app.services import practice_service
    from app.services.practice import batch_submission_flow, batch_token

    entry = rules.normalize_practice_session
    assert entry is practice_service._normalize_practice_session
    assert entry is batch_submission_flow.normalize_practice_session
    assert rules.parse_session_datetime is batch_token.parse_session_datetime
    assert entry.__globals__ is vars(rules)
    assert entry.__module__ == rules.__name__
    assert entry.__name__ == entry.__qualname__ == "normalize_practice_session"
    assert entry.__doc__ == "Validate the mandatory server-issued practice session metadata."
    assert str(inspect.signature(entry)) == (
        "(session_meta: 'dict', *, user_id: 'int', answered_count: 'int', "
        "total_correct: 'int', total_wrong: 'int') -> 'dict'"
    )
