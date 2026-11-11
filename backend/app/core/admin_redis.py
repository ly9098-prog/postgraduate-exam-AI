"""Admin Redis helpers: online presence, rate limiting, idempotency, bypass.

Implements the planned ``admin:online:*``, ``admin:ratelimit:*``,
``admin:idempotency:*`` and ``admin:bypass:*`` namespaces from
``docs/admin/REDIS_PLAN.md``.

Failure semantics follow the plan's degradation matrix:

- online presence — best-effort, Redis down changes nothing
- rate limiting — best-effort, Redis down means "no limit" (skip)
- idempotency — strict, Redis down means 503 for the wrapped write
- bypass — strict read, Redis down means "no exemption"
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.core.cache import CacheUnavailableError, cache
from app.core.runtime_paths import API_ADMIN_V1_PREFIX
from app.core.time_utils import unix_timestamp, utcnow

logger = logging.getLogger("postgraduate-ai.admin_redis")

_ONLINE_TTL_SEC = 5 * 60
_RATELIMIT_TTL_SEC = 60
_RATELIMIT_ENDPOINTS: dict[str, int] = {
    # endpoint suffix → requests per minute (plan §3.9)
    "batch": 10,
    "stats": 30,
}
_RATELIMIT_DEFAULT_LIMIT = 60
_BYPASS_ALLOWED_PATHS = frozenset(
    {
        f"{API_ADMIN_V1_PREFIX}/dashboard/overview",
        f"{API_ADMIN_V1_PREFIX}/dashboard/daily",
        f"{API_ADMIN_V1_PREFIX}/redis/online",
    }
)
_RATELIMIT_SUPER_ADMIN_MULTIPLIER = 2
_IDEMPOTENCY_TTL_SEC = 10 * 60
_IDEMPOTENCY_PENDING_TTL_SEC = 60 * 60


class AdminOnlinePresence:
    """Records per-admin liveness markers (``admin:online:{userId}``)."""

    async def record(
        self, user_id: int, *, ip: str | None = None, user_agent: str | None = None
    ) -> None:
        try:
            await cache.set(
                f"admin:online:{user_id}",
                {
                    "last_active_at": unix_timestamp(utcnow()),
                    "ip": ip,
                    "user_agent": user_agent,
                },
                ttl=_ONLINE_TTL_SEC,
            )
        except Exception:
            pass  # observability only — never fail the request

    async def snapshot(self) -> list[dict[str, Any]]:
        """Return currently-online admins (best-effort, SCAN based).

        When Redis is disabled/unavailable, falls back to this process's
        local cache so single-instance deployments and tests still work.
        """
        import time as _time

        try:
            client = await cache._ensure_client()  # noqa: SLF001
            if client is not None:
                keys: list[str] = []
                cursor = 0
                while True:
                    cursor, batch = await client.scan(
                        cursor=cursor, match="admin:online:*", count=200
                    )
                    if batch:
                        keys.extend(
                            k.decode() if isinstance(k, bytes) else k for k in batch
                        )
                    if cursor == 0:
                        break
            else:
                now = _time.time()
                keys = [
                    key
                    for key, (exp, _) in cache._local.items()  # noqa: SLF001
                    if key.startswith("admin:online:") and (exp is None or exp > now)
                ]

            items: list[dict[str, Any]] = []
            for key in keys:
                raw = await cache.get(key)
                if raw is None:
                    continue
                user_id = key.rsplit(":", 1)[-1]
                items.append(
                    {"user_id": int(user_id), **(raw if isinstance(raw, dict) else {})}
                )
            items.sort(key=lambda item: item.get("last_active_at", 0), reverse=True)
            return items
        except Exception:
            return []


online_presence = AdminOnlinePresence()


def _endpoint_class(path: str) -> str:
    if "batch" in path or "bulk" in path:
        return "batch"
    if "stats" in path or "overview" in path or "daily" in path:
        return "stats"
    return "default"


async def check_admin_ratelimit(
    user_id: int,
    path: str,
    *,
    is_super_admin: bool = False,
    bypass_token: str | None = None,
) -> bool:
    """Fixed-window per-user rate limit (``admin:ratelimit:{userId}:{class}``).

    Returns True when allowed. Best-effort: Redis unavailable → allow.
    """
    if path in _BYPASS_ALLOWED_PATHS and await is_bypass_allowed(bypass_token):
        return True
    endpoint_class = _endpoint_class(path)
    limit = _RATELIMIT_ENDPOINTS.get(endpoint_class, _RATELIMIT_DEFAULT_LIMIT)
    if is_super_admin:
        limit *= _RATELIMIT_SUPER_ADMIN_MULTIPLIER
    key = f"admin:ratelimit:{user_id}:{endpoint_class}"
    try:
        count = await cache.increment_strict(key, ttl=_RATELIMIT_TTL_SEC)
    except CacheUnavailableError:
        return True
    except Exception:
        return True
    return count <= limit


class IdempotencyConflictError(ValueError):
    """A caller reused a key for a different request."""


class IdempotencyInProgressError(ValueError):
    """The original request has not finished yet."""


@dataclass(frozen=True)
class IdempotencyClaim:
    redis_key: str
    fingerprint: str
    pending_value: str | None
    response: dict[str, Any] | None = None


async def reserve_idempotent_request(
    user_id: int, idem_key: str, fingerprint: str
) -> IdempotencyClaim:
    """Atomically reserve a request before executing a critical batch write.

    A pending claim survives a worker crash long enough to avoid immediately
    repeating a possibly committed operation. Completed responses live for 10m.
    """
    redis_key = f"admin:idempotency:{user_id}:{idem_key}"
    pending_value = json.dumps(
        {"fingerprint": fingerprint, "state": "pending", "owner": uuid4().hex},
        sort_keys=True,
    )
    for _ in range(2):
        reserved = await cache.acquire_lock_strict(
            redis_key, pending_value, ttl=_IDEMPOTENCY_PENDING_TTL_SEC
        )
        if reserved:
            return IdempotencyClaim(redis_key, fingerprint, pending_value)
        stored = await cache.get_strict(redis_key)
        if stored is None:
            continue  # An existing claim expired between SET NX and GET.
        if isinstance(stored, str):
            # The local cache stores the raw SET NX value; Redis parses JSON.
            try:
                stored = json.loads(stored)
            except ValueError:
                raise IdempotencyConflictError(
                    "Invalid existing idempotency state"
                ) from None
        if not isinstance(stored, dict) or stored.get("fingerprint") != fingerprint:
            raise IdempotencyConflictError("Idempotency-Key belongs to another request")
        if stored.get("state") == "pending":
            raise IdempotencyInProgressError("Request with this key is in progress")
        if stored.get("state") == "complete" and isinstance(
            stored.get("response"), dict
        ):
            return IdempotencyClaim(redis_key, fingerprint, None, stored["response"])
        raise IdempotencyConflictError("Invalid existing idempotency state")
    raise CacheUnavailableError("Idempotency reservation changed during lookup")


async def complete_idempotent_request(
    claim: IdempotencyClaim, response: dict[str, Any]
) -> None:
    """Publish a response only when the original reservation is still owned."""
    if claim.pending_value is None:
        return
    saved = await cache.compare_and_set_strict(
        claim.redis_key,
        claim.pending_value,
        {"fingerprint": claim.fingerprint, "state": "complete", "response": response},
        ttl=_IDEMPOTENCY_TTL_SEC,
    )
    if not saved:
        raise CacheUnavailableError("Idempotency reservation expired or changed")


async def release_idempotent_request(claim: IdempotencyClaim) -> None:
    """Free an uncommitted operation so a caller can retry after an error."""
    if claim.pending_value is not None:
        await cache.release_lock(claim.redis_key, claim.pending_value)


@dataclass(frozen=True)
class BypassToken:
    token_hash: str
    type: str
    note: str | None


def _bypass_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_bypass_token(
    token: str,
    *,
    type_: str = "monitor",
    note: str | None = None,
    ttl: int | None = None,
) -> None:
    """Register a bypass token (critical op — caller must write audit_log)."""
    value = {"type": type_, "note": note, "created_at": unix_timestamp(utcnow())}
    if ttl is not None:
        await cache.set_strict(
            f"admin:bypass:{_bypass_token_hash(token)}", value, ttl=ttl
        )
    else:
        # No TTL requested — use a long-but-finite marker (30d) so abandoned
        # tokens cannot accumulate forever; renewal is just a re-create.
        await cache.set_strict(
            f"admin:bypass:{_bypass_token_hash(token)}", value, ttl=30 * 24 * 60 * 60
        )


async def delete_bypass_token(token: str) -> bool:
    try:
        return bool(
            await cache.delete_strict(f"admin:bypass:{_bypass_token_hash(token)}")
        )
    except CacheUnavailableError:
        return False


async def is_bypass_allowed(token: str | None) -> bool:
    """True when the presented token is a registered bypass token.

    Strict: Redis unavailable → no exemption (fail-closed).
    """
    if not token:
        return False
    try:
        entry = await cache.get_strict(f"admin:bypass:{_bypass_token_hash(token)}")
    except CacheUnavailableError:
        return False
    return isinstance(entry, dict) and entry.get("type") in {"monitor", "internal"}


def hash_bypass_token(token: str) -> str:
    """Expose the hash for audit-log detail without leaking the raw token."""
    return _bypass_token_hash(token)


def now_unix() -> int:
    return int(time.time())


def dumps_safe(value: Any) -> str:
    try:
        return json.dumps(value, default=str)
    except Exception:
        return "{}"
