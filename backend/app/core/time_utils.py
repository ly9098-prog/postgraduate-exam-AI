from datetime import UTC, date, datetime, time, timedelta, timezone


def utcnow() -> datetime:
    """Return naive UTC datetime (compatible with DateTime columns without timezone=True).

    All DB DateTime columns in this project store naive UTC timestamps
    (no ``timezone=True``).  This helper returns a naive datetime so that
    comparisons with DB-loaded values do not raise ``TypeError``.

    When converting to ISO 8601 for API output, use
    :func:`serialize_utc_datetime` instead.
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


def unix_timestamp(value: datetime) -> float:
    """Convert a DB/UTC datetime to Unix epoch seconds without local-TZ leakage.

    Python interprets ``naive_datetime.timestamp()`` in the operating system's
    local timezone.  This project stores naive datetimes as UTC, so always
    attach/convert UTC explicitly before computing epoch seconds.
    """
    if not isinstance(value, datetime):
        raise TypeError("value must be datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.timestamp()


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
    end_shanghai = now_shanghai.replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    start_utc = (start_shanghai - timedelta(hours=8)).replace(tzinfo=None)
    end_utc = (end_shanghai - timedelta(hours=8)).replace(tzinfo=None)
    return start_utc, end_utc


def shanghai_now() -> datetime:
    """Return the current product-local time in Asia/Shanghai (UTC+8)."""
    return datetime.now(_SHANGHAI_TZ)


def shanghai_today() -> date:
    """Return the current calendar date in Asia/Shanghai.

    Use this for product concepts such as "today", streaks, daily reports and
    scheduler target dates.  Never derive those concepts from the server's
    local timezone or from ``utcnow().date()``.
    """
    return shanghai_now().date()


def shanghai_date_utc_range(target_date: date) -> tuple[datetime, datetime]:
    """Return the half-open naive-UTC range for a China calendar date.

    Example: 2026-08-16 China time maps to
    [2026-08-15 16:00:00, 2026-08-16 16:00:00) UTC.
    """
    local_start = datetime.combine(target_date, time.min, tzinfo=_SHANGHAI_TZ)
    start_utc = local_start.astimezone(UTC).replace(tzinfo=None)
    return start_utc, start_utc + timedelta(days=1)


def to_shanghai(value: datetime) -> datetime:
    """Interpret naive datetimes as UTC and convert them to Asia/Shanghai."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_SHANGHAI_TZ)


def shanghai_date_for_utc(value: datetime) -> date:
    """Return the China calendar date for a DB/UTC datetime."""
    return to_shanghai(value).date()


# ── China study-day helpers ──────────────────────────────────────────────
#
# Product timezone is fixed to Asia/Shanghai (UTC+8, no DST).  Sessions are
# stored as naive UTC; all "today / this week / a given day" pomodoro stats are
# computed against China study days.  A study day is a half-open 24h window
# [d + day_start_minute, d+1 + day_start_minute) in China local time, so a user
# with day_start_minute=360 belongs to the *previous* study day before 06:00.
#
# day_start_minute is "minutes past 00:00 of the China calendar day", 0..1439.

_SHANGHAI_OFFSET = timedelta(hours=8)


def study_day_utc_range(
    target_date: date, day_start_minute: int = 0
) -> tuple[datetime, datetime]:
    """Return the half-open naive-UTC range [start_utc, end_utc) of a China study day.

    ``target_date`` is the China calendar date whose study day begins at
    ``day_start_minute`` minutes past its midnight.  Example: day_start_minute=360,
    target_date=2026-08-07 -> (2026-08-06 22:00, 2026-08-07 22:00) UTC.
    """
    local_start = datetime.combine(target_date, time.min) + timedelta(
        minutes=day_start_minute
    )
    start_utc = local_start - _SHANGHAI_OFFSET
    return start_utc, start_utc + timedelta(days=1)


def study_day_for_utc(dt_utc: datetime, day_start_minute: int = 0) -> date:
    """Return the China study day that a naive-UTC datetime belongs to.

    Equivalent to: UTC -> China time, subtract day_start_minute, take the date.
    e.g. 2026-08-07 18:00 UTC (= 08-08 02:00 China) with day_start_minute=360
    returns 2026-08-07.
    """
    china = dt_utc + _SHANGHAI_OFFSET
    return (china - timedelta(minutes=day_start_minute)).date()


def current_study_day(day_start_minute: int = 0) -> date:
    """Return the China study day at this instant, based on the UTC clock (never the server local date)."""
    return study_day_for_utc(utcnow(), day_start_minute)


def study_week_utc_range(day_start_minute: int = 0) -> tuple[datetime, datetime]:
    """Return the half-open naive-UTC range of the current China study week.

    The week is Monday–Sunday in China calendar terms; each day boundary is the
    user's ``day_start_minute``.  e.g. day_start_minute=360 means the week starts
    Monday 06:00 China time.
    """
    current_day = current_study_day(day_start_minute)
    monday = current_day - timedelta(days=current_day.weekday())
    start_utc = study_day_utc_range(monday, day_start_minute)[0]
    return start_utc, start_utc + timedelta(days=7)


def minute_to_time_text(day_start_minute: int) -> str:
    """Format a minutes-past-midnight value as ``HH:MM``. e.g. 360 -> "06:00"."""
    return f"{day_start_minute // 60:02d}:{day_start_minute % 60:02d}"
