"""Shared Pydantic base model with explicit UTC datetime serialization.

Database ``DateTime`` columns in this project are timezone-naive but represent
UTC.  Pydantic's default JSON serializer emits naive values without ``Z``, which
makes JavaScript clients interpret them as device-local time.  All API schema
models that carry datetimes inherit this base so a DB value such as
``2026-08-16 07:12:10`` is emitted as ``2026-08-16T07:12:10Z``.
"""

from datetime import datetime

from pydantic import BaseModel as PydanticBaseModel, ConfigDict

from app.core.time_utils import serialize_utc_datetime


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(json_encoders={datetime: serialize_utc_datetime})
