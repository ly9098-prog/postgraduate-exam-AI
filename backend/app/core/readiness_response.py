"""Readiness response projection; probes and HTTP transport remain at the caller."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReadinessSnapshot:
    database_ok: bool
    redis_ok: bool
    alembic_ok: bool
    staging_ok: bool
    staging_space: dict[str, Any]
    role_ok: bool
    ocr_status: str | None
    queue_status: str | None
    draining: bool
    db_pool: dict[str, Any]
    event_loop_lag_ms: float


def _readiness_checks(
    snapshot: ReadinessSnapshot, *, include_redis: bool,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "database": "ok" if snapshot.database_ok else "unavailable",
        "db_pool": snapshot.db_pool,
        "alembic": "ok" if snapshot.alembic_ok else "stale",
        "staging": "ok" if snapshot.staging_ok else "unavailable",
        "role_deps": "ok" if snapshot.role_ok else "unavailable",
        "event_loop_lag_ms": snapshot.event_loop_lag_ms,
        "draining": "ok" if not snapshot.draining else "draining",
    }
    if include_redis:
        checks["redis"] = "ok" if snapshot.redis_ok else "unavailable"
    if snapshot.ocr_status:
        checks["ocr"] = snapshot.ocr_status
    if snapshot.queue_status:
        checks["queue"] = snapshot.queue_status
    if snapshot.staging_space:
        checks["staging_space"] = snapshot.staging_space
    return checks


def build_readiness_response(
    snapshot: ReadinessSnapshot, *, production_mode: bool, redis_configured: bool,
) -> tuple[int, dict[str, Any]]:
    checks = _readiness_checks(
        snapshot, include_redis=redis_configured or production_mode,
    )
    critical_failures = [
        k
        for k, v in checks.items()
        if v == "unavailable"
        and k
        in (
            "database",
            "redis",
            "alembic",
            "staging",
            "role_deps",
            "ocr",
        )
    ]
    # Preserve the original stale-Alembic behavior; its correction is a separate change.
    if snapshot.draining:
        critical_failures.append("draining")
    all_ok = len(critical_failures) == 0
    content: dict[str, Any] = {
        "status": "ok" if all_ok else "unavailable",
        "degraded": snapshot.ocr_status == "degraded" or snapshot.queue_status == "degraded",
    }
    if not production_mode:
        content["checks"] = checks
    return 200 if all_ok else 503, content
