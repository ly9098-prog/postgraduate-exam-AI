"""Lightweight runtime policy helpers for the transactional outbox.

Kept separate from ``outbox_service`` so role/backoff policy can be unit-tested
without importing SQLAlchemy models or initializing the database engine.
"""
from __future__ import annotations

from app.core.config import settings

REDIS_BACKOFF_INITIAL_SEC = max(1.0, float(settings.OUTBOX_REDIS_BACKOFF_INITIAL_SEC))
REDIS_BACKOFF_MAX_SEC = max(
    REDIS_BACKOFF_INITIAL_SEC,
    float(settings.OUTBOX_REDIS_BACKOFF_MAX_SEC),
)


def next_redis_backoff(current: float) -> float:
    """Return the next bounded exponential Redis infrastructure backoff."""
    return min(
        REDIS_BACKOFF_MAX_SEC,
        max(REDIS_BACKOFF_INITIAL_SEC, current * 2.0),
    )


def is_redis_infrastructure_exception(exc: BaseException) -> bool:
    """Best-effort classification for Redis connection/timeout exceptions."""
    exc_type = type(exc)
    module = (getattr(exc_type, "__module__", "") or "").lower()
    name = (getattr(exc_type, "__name__", "") or "").lower()
    if module.startswith("redis") and name in {"connectionerror", "timeouterror"}:
        return True
    text = str(exc).lower()
    return "redis" in text and any(
        token in text for token in ("connection", "timeout", "unavailable")
    )
