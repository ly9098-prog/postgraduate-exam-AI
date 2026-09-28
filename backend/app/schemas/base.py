"""Shared Pydantic base model with explicit UTC datetime serialization.

Database ``DateTime`` columns in this project are timezone-naive but represent
UTC. Pydantic's default JSON serializer emits naive values without ``Z``, which
makes JavaScript clients interpret them as device-local time. All API schema
models that carry datetimes inherit this base so a DB value such as
``2026-08-16 07:12:10`` is emitted as ``2026-08-16T07:12:10Z``.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel as PydanticBaseModel
from pydantic import SerializationInfo, SerializerFunctionWrapHandler, field_serializer

from app.core.time_utils import serialize_utc_datetime


def _nested_selector(selector: Any, key: Any) -> Any:
    if isinstance(selector, dict):
        child = selector.get(key, selector.get("__all__"))
        return None if child is True or child is ... else child
    return None


def _utc_datetimes(
    value: Any, serialized: Any, *, include: Any = None, exclude: Any = None
) -> Any:
    """Keep Pydantic's JSON handling, overriding only datetime values."""
    if isinstance(value, datetime):
        return serialize_utc_datetime(value)
    if isinstance(value, dict) and isinstance(serialized, dict):
        return {
            key: (
                _utc_datetimes(
                    value[key],
                    rendered,
                    include=_nested_selector(include, key),
                    exclude=_nested_selector(exclude, key),
                )
                if key in value
                else rendered
            )
            for key, rendered in serialized.items()
        }
    if isinstance(value, (tuple, list)) and isinstance(serialized, list):
        indices = range(len(value))
        if isinstance(include, (set, dict)) and "__all__" not in include:
            indices = [index for index in indices if index in include]
        if isinstance(exclude, (set, dict)):
            indices = [
                index
                for index in indices
                if index not in exclude
                or (isinstance(exclude, dict) and exclude[index] not in (True, ...))
            ]
        originals = [(index, value[index]) for index in indices]
        if len(originals) != len(serialized):
            # Avoid pairing a filtered JSON element with the wrong original.
            return serialized
        return [
            _utc_datetimes(
                original,
                rendered,
                include=_nested_selector(include, index),
                exclude=_nested_selector(exclude, index),
            )
            for (index, original), rendered in zip(originals, serialized, strict=True)
        ]
    return serialized


class BaseModel(PydanticBaseModel):
    @field_serializer("*", mode="wrap", check_fields=False, when_used="json")
    def serialize_utc_fields(
        self,
        value: Any,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ):
        if isinstance(value, datetime):
            return serialize_utc_datetime(value)
        return _utc_datetimes(
            value, handler(value), include=info.include, exclude=info.exclude
        )
