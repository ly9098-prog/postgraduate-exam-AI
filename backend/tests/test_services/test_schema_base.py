"""Shared API datetime serializer behavior without deprecated json_encoders."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.schemas.base import BaseModel


class _Nested(BaseModel):
    occurred_at: datetime


class _Payload(BaseModel):
    occurred_at: datetime
    history: list[datetime]
    nested: _Nested
    metadata: dict[str, Any]


def test_naive_datetimes_remain_utc_in_json_output():
    value = datetime(2026, 7, 4, 12, 30)
    payload = _Payload(
        occurred_at=value,
        history=[value],
        nested=_Nested(occurred_at=value),
        metadata={"recorded_at": value, "label": "ready"},
    )

    assert payload.model_dump(mode="json") == {
        "occurred_at": "2026-07-04T12:30:00Z",
        "history": ["2026-07-04T12:30:00Z"],
        "nested": {"occurred_at": "2026-07-04T12:30:00Z"},
        "metadata": {"recorded_at": "2026-07-04T12:30:00Z", "label": "ready"},
    }
    assert isinstance(payload.model_dump()["occurred_at"], datetime)


def test_aware_datetimes_normalize_to_utc_and_keep_other_values():
    value = datetime(2026, 7, 4, 15, 30, tzinfo=timezone(timedelta(hours=3)))
    payload = _Payload(
        occurred_at=value,
        history=[datetime(2026, 7, 4, 12, 30, tzinfo=UTC)],
        nested=_Nested(occurred_at=value),
        metadata={"number": 5},
    )

    rendered = payload.model_dump(mode="json")
    assert rendered["occurred_at"] == "2026-07-04T12:30:00Z"
    assert rendered["history"] == ["2026-07-04T12:30:00Z"]
    assert rendered["nested"]["occurred_at"] == "2026-07-04T12:30:00Z"
    assert rendered["metadata"] == {"number": 5}


def test_json_schema_keeps_field_types_for_openapi():
    schema = _Payload.model_json_schema(mode="serialization")
    props = schema["properties"]
    assert props["occurred_at"]["format"] == "date-time"
    assert props["history"]["items"]["format"] == "date-time"
    assert props["metadata"]["type"] == "object"


def test_excluded_list_item_keeps_the_remaining_datetime():
    first = datetime(2026, 7, 4, 12, 30)
    second = datetime(2026, 7, 5, 12, 30)
    payload = _Payload(
        occurred_at=first,
        history=[first, second],
        nested=_Nested(occurred_at=first),
        metadata={"dates": [first, second]},
    )
    rendered = payload.model_dump(
        mode="json", exclude={"history": {0}, "metadata": {"dates": {0}}}
    )
    assert rendered["history"] == ["2026-07-05T12:30:00Z"]
    assert rendered["metadata"]["dates"] == ["2026-07-05T12:30:00Z"]
