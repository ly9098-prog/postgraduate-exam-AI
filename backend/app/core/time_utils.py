from datetime import UTC, datetime, timedelta, timezone


def utcnow() -> datetime:
    """Return naive UTC datetime (compatible with DateTime columns without timezone=True).

    All DB DateTime columns in this project store naive UTC timestamps
    (no ``timezone=True``).  This helper returns a naive datetime so that
    comparisons with DB-loaded values do not raise ``TypeError``.

    When converting to ISO 8601 for API output, use ``utcnow().isoformat() + "Z"``
    or :func:`utcnow_aware` instead.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """Return aware UTC datetime (``tzinfo=timezone.utc``).

    Use this for API output, JWT claims, and other system boundaries where
    timezone awareness is expected.  Convert to naive before writing to DB
    columns without ``timezone=True``.
    """
    return datetime.now(UTC)


def normalize_to_naive_utc(value: datetime) -> datetime:
    """Convert any datetime to a naive UTC datetime for DB comparison.

    Rules:
    - If *value* is timezone-aware: convert to UTC, then strip tzinfo.
    - If *value* is naive: treat as already UTC (no offset applied).
    - Raises TypeError for non-datetime input.
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def serialize_utc_datetime(value: datetime) -> str:
    """Serialize a datetime to an ISO 8601 string with UTC indicator.

    The returned string always ends with ``Z`` (never ``+00:00``).

    Rules:
    - Naive datetime → treat as UTC → append ``Z``.
    - Aware datetime → convert to UTC → append ``Z``.
    - Never double-append ``Z``.
    """
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    else:
        # Naive — treat as UTC
        value = value.replace(tzinfo=UTC)

    iso = value.isoformat()
    # Remove any trailing "+00:00" to replace with "Z"
    if iso.endswith("+00:00"):
        iso = iso[:-6]
    elif iso.endswith("+00:00Z"):
        iso = iso[:-7] + "Z"
    if not iso.endswith("Z"):
        iso += "Z"
    return iso


# Asia/Shanghai = UTC+8, no DST
_SHANGHAI_TZ = timezone(timedelta(hours=8))


def shanghai_today_boundaries() -> tuple[datetime, datetime]:
    """Return (today_start_utc, today_end_utc) as naive UTC datetimes.

    "Today" is defined in Asia/Shanghai timezone.  The returned values are
    converted to naive UTC for DB column comparison (all DateTime columns
    store naive UTC).
    """
    now_shanghai = datetime.now(_SHANGHAI_TZ)
    start_shanghai = now_shanghai.replace(hour=0, minute=0, second=0, microsecond=0)
    end_shanghai = now_shanghai.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_utc = (start_shanghai - timedelta(hours=8)).replace(tzinfo=None)
    end_utc = (end_shanghai - timedelta(hours=8)).replace(tzinfo=None)
    return start_utc, end_utc
