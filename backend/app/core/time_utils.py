from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return naive UTC datetime (compatible with DateTime columns without timezone=True).

    All DB DateTime columns in this project store naive UTC timestamps
    (no ``timezone=True``).  This helper returns a naive datetime so that
    comparisons with DB-loaded values do not raise ``TypeError``.

    When converting to ISO 8601 for API output, use ``utcnow().isoformat() + "Z"``
    or :func:`utcnow_aware` instead.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """Return aware UTC datetime (``tzinfo=timezone.utc``).

    Use this for API output, JWT claims, and other system boundaries where
    timezone awareness is expected.  Convert to naive before writing to DB
    columns without ``timezone=True``.
    """
    return datetime.now(timezone.utc)
