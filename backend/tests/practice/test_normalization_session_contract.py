"""Characterize session validation order, coercion and output ownership."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.practice import normalization as rules


def session_meta(**overrides):
    values = {
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:01:00Z",
        "duration_sec": 60,
        "request_id": "  request  ",
        "subject_id": "7",
        "mode": "smart",
        "answered_count": 3,
        "question_count": 5,
    }
    values.update(overrides)
    return values


def normalize(meta, **overrides):
    counts = dict(user_id=4, answered_count=3, total_correct=2, total_wrong=1)
    counts.update(overrides)
    return rules.normalize_practice_session(meta, **counts)


@pytest.mark.parametrize("meta", [None, {}, [], "", False, 0])
def test_falsy_session_precedes_any_field_access(meta):
    with pytest.raises(ValueError, match="^session 不能为空$"):
        normalize(meta)


@pytest.mark.parametrize(
    ("changes", "message", "chained"),
    [
        (
            dict(started_at="bad", finished_at="bad", duration_sec="bad"),
            "session.start_at / session.finished_at 必须为合法 ISO 时间",
            False,
        ),
        (
            dict(finished_at="2025-12-31T23:59:59Z", duration_sec="bad"),
            "session.finished_at 不得早于 session.started_at",
            False,
        ),
        (
            dict(duration_sec="bad", request_id="x" * 129, subject_id="bad"),
            "session.duration_sec 必须为整数",
            False,
        ),
        (
            dict(duration_sec=21601, subject_id="bad"),
            "session.duration_sec 不得超过 started_at/finished_at 墙钟时长",
            False,
        ),
        (
            dict(finished_at="2026-01-02T00:00:00Z", duration_sec=21601, mode="bad"),
            "session.duration_sec 超过允许上限",
            False,
        ),
        (
            dict(request_id="x" * 129, subject_id="bad", mode="bad"),
            "request_id 长度不得超过 128",
            False,
        ),
        (
            dict(subject_id="bad", mode="bad", answered_count=None),
            "session.subject_id 必须为整数",
            False,
        ),
        (
            dict(mode="SMART", answered_count=None),
            "session.mode 无效",
            False,
        ),
        (
            dict(answered_count=None, question_count="bad"),
            "session.answered_count 必须为整数",
            True,
        ),
        (
            dict(answered_count="bad"),
            "session.answered_count 必须为整数",
            True,
        ),
        (
            dict(answered_count=4, question_count="bad"),
            "session.answered_count 与 answers 数量不一致",
            False,
        ),
    ],
)
def test_first_invalid_field_and_explicit_exception_cause(changes, message, chained):
    with pytest.raises(ValueError) as caught:
        normalize(session_meta(**changes))
    assert str(caught.value) == message
    assert (caught.value.__cause__ is not None) is chained
    if chained:
        assert caught.value.__cause__ is caught.value.__context__
        assert caught.value.__suppress_context__ is True


@pytest.mark.parametrize(
    ("duration", "expected"),
    [(None, 60), (-1, 60), (-0.5, 0), (True, 1), ("61", 61), (62, 62), (0, 0)],
)
def test_duration_fallback_integer_truncation_and_rounding_allowance(duration, expected):
    result = normalize(session_meta(duration_sec=duration))
    assert result["duration_sec"] == expected
    assert type(result["duration_sec"]) is int


def test_wall_clock_truncates_before_tolerance_and_limit_is_inclusive():
    result = normalize(
        session_meta(finished_at="2026-01-01T00:01:00.999999Z", duration_sec=62)
    )
    assert result["duration_sec"] == 62
    with pytest.raises(ValueError, match="墙钟"):
        normalize(
            session_meta(finished_at="2026-01-01T00:01:00.999999Z", duration_sec=63)
        )
    result = normalize(
        session_meta(finished_at="2026-01-01T06:00:00Z", duration_sec=21600)
    )
    assert result["duration_sec"] == 21600


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 3), ("bad", 3), ([], 3), (-2, 0), (False, 0), (4.9, 4), ("9", 9)],
)
def test_question_count_falls_back_without_being_capped_to_answers(value, expected):
    assert normalize(session_meta(question_count=value))["question_count"] == expected


@pytest.mark.parametrize("field", ["duration_sec", "subject_id", "answered_count", "question_count"])
def test_overflow_is_not_wrapped_or_treated_as_a_fallback(field):
    with pytest.raises(OverflowError):
        normalize(session_meta(**{field: float("inf")}))


@pytest.mark.parametrize("field", ["duration_sec", "subject_id", "answered_count", "question_count"])
def test_nan_uses_each_fields_existing_value_error_policy(field):
    if field == "question_count":
        assert normalize(session_meta(question_count=float("nan")))["question_count"] == 3
    else:
        with pytest.raises(ValueError, match=field):
            normalize(session_meta(**{field: float("nan")}))


@pytest.mark.parametrize("mode", [None, "", False, 0])
def test_falsy_mode_defaults_to_random(mode):
    assert normalize(session_meta(mode=mode))["mode"] == "random"


def test_payload_order_ownership_and_no_input_mutation():
    started = datetime(2026, 1, 1)
    finished = datetime(2026, 1, 1, 0, 1)
    user = object()
    meta = session_meta(started_at=started, finished_at=finished, extra={"keep": []})
    before = dict(meta)
    first = normalize(meta, user_id=user)
    second = normalize(meta, user_id=user)
    assert first == second and first is not second
    assert first["started_at"] is started and first["finished_at"] is finished
    assert first["user_id"] is user
    assert meta == before and meta["extra"] is before["extra"]
    assert list(first) == [
        "user_id", "subject_id", "request_id", "mode", "started_at", "finished_at",
        "duration_sec", "question_count", "answered_count", "correct_count",
        "wrong_count", "status",
    ]
    assert first["request_id"] == "request" and first["status"] == "completed"


def test_negative_counts_are_clipped_independently_without_reconciling_totals():
    result = normalize(
        session_meta(answered_count=-3, question_count=None),
        answered_count=-3, total_correct=9, total_wrong=-5,
    )
    assert [result[key] for key in (
        "question_count", "answered_count", "correct_count", "wrong_count",
    )] == [0, 0, 9, 0]


def test_nonnegative_count_objects_are_preserved_without_reconversion():
    class Count(int):
        pass

    answered, correct, wrong = Count(3), Count(2), Count(1)
    result = normalize(
        session_meta(question_count=None), answered_count=answered,
        total_correct=correct, total_wrong=wrong,
    )
    assert result["question_count"] is result["answered_count"] is answered
    assert result["correct_count"] is correct and result["wrong_count"] is wrong


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-01T00:30:00+08:00", datetime(2025, 12, 31, 16, 30)),
        ("2026-01-01T00:30:00-03:30", datetime(2026, 1, 1, 4)),
        ("2026-01-01T00:30:00.123456Z", datetime(2026, 1, 1, 0, 30, 0, 123456)),
        ("2026-01-01", datetime(2026, 1, 1)),
        (" invalid ", None),
    ],
)
def test_datetime_utc_conversion_and_invalid_text(value, expected):
    assert rules.parse_session_datetime(value) == expected


def test_session_compares_instants_after_converting_both_offsets():
    result = normalize(session_meta(
        started_at="2026-01-01T08:00:00+08:00",
        finished_at="2025-12-31T21:01:00-03:00",
    ))
    assert result["started_at"] == datetime(2026, 1, 1)
    assert result["finished_at"] == datetime(2026, 1, 1, 0, 1)
    aware = datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))
    assert rules.parse_session_datetime(aware) == result["started_at"]
