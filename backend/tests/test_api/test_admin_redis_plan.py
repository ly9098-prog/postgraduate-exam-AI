"""Regression tests for the REDIS_PLAN.md admin key implementation.

Covers: role-version permission cache, online presence, per-user rate limit,
atomic idempotency guard, bypass tokens, dashboard daily stats cache and
refresh-consumed marker lifetime. All Redis interaction goes through the
``cache`` client, which falls back to an in-process store when ``REDIS_URL``
is unset — the default in unit tests.
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.core import admin_guards, admin_security
from app.core.admin_guards import admin_rate_limit, require_idempotency
from app.core.admin_redis import (
    IdempotencyClaim,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    check_admin_ratelimit,
    complete_idempotent_request,
    create_bypass_token,
    delete_bypass_token,
    is_bypass_allowed,
    online_presence,
    release_idempotent_request,
    reserve_idempotent_request,
)
from app.core.admin_security import (
    _get_permission_names,
    bump_role_version,
)
from app.core.cache import CacheUnavailableError, cache
from app.core.config import settings
from app.core.time_utils import unix_timestamp, utcnow
from app.models.admin import AdminUser, Role


@pytest.fixture(autouse=True)
def _clean_local_cache():
    cache._local.clear()
    yield
    cache._local.clear()


@pytest.fixture
def _cache_enabled(monkeypatch):
    """Simulate a configured Redis so role-version caching activates."""
    monkeypatch.setattr(cache, "_enabled", True)
    yield
    monkeypatch.setattr(cache, "_enabled", bool(settings.REDIS_URL))


# ── Role version + permission cache ──────────────────────────────


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _Result:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _Scalars(self._values)


class _FakeDb:
    def __init__(self, values):
        self._values = values
        self.calls = 0

    async def execute(self, _statement):
        self.calls += 1
        return _Result(self._values)


@pytest.mark.asyncio
async def test_permission_cache_hit_avoids_db():
    db = _FakeDb(["question:read", "role:read"])
    first = await _get_permission_names(db, role_id=7)
    assert first == {"question:read", "role:read"}
    # Second call must be served from cache — no further DB queries.
    second = await _get_permission_names(_FakeDb([]), role_id=7)
    assert second == first
    assert db.calls == 1
    # The version marker must outlive the 15-minute permissions entry.
    assert cache._local["admin:role:version:7"][0] is None


@pytest.mark.asyncio
async def test_bump_role_version_invalidates_cache():
    db = _FakeDb(["perm:a"])
    await _get_permission_names(db, role_id=8)
    await bump_role_version(None, 8)
    fresh_db = _FakeDb(["perm:b"])
    result = await _get_permission_names(fresh_db, role_id=8)
    assert result == {"perm:b"}
    assert fresh_db.calls == 1


# ── Online presence ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_online_presence_record_and_snapshot():
    await online_presence.record(42, ip="10.0.0.1", user_agent="ua")
    snapshot = await online_presence.snapshot()
    assert any(item["user_id"] == 42 for item in snapshot)


# ── Rate limit ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ratelimit_blocks_after_limit():
    allowed = True
    for _ in range(10):
        allowed = await check_admin_ratelimit(9, "/api/admin/v1/imports/x/approve")
    assert allowed  # default class is 60/min; 10 calls fine

    # batch class limit is 10/min — the 11th must be rejected
    for _ in range(10):
        await check_admin_ratelimit(10, "/api/admin/v1/imports/batch")
    assert not await check_admin_ratelimit(10, "/api/admin/v1/imports/batch")


@pytest.mark.asyncio
async def test_ratelimit_super_admin_doubled():
    for _ in range(20):
        assert await check_admin_ratelimit(
            11, "/api/admin/v1/imports/batch", is_super_admin=True
        )
    assert not await check_admin_ratelimit(
        11, "/api/admin/v1/imports/batch", is_super_admin=True
    )


@pytest.mark.asyncio
async def test_ratelimit_allows_when_redis_unavailable(monkeypatch):
    from app.core.cache import CacheUnavailableError

    async def boom(*args, **kwargs):
        raise CacheUnavailableError("down")

    monkeypatch.setattr(cache, "increment_strict", boom)
    assert await check_admin_ratelimit(12, "/any/path") is True


@pytest.mark.asyncio
async def test_admin_rate_limit_dependency_raises_429(monkeypatch):
    request = MagicMock()
    request.url.path = "/api/admin/v1/imports/batch"
    request.headers = {}
    user = MagicMock()
    user.role = None
    principal = admin_security.AdminPrincipal.__new__(admin_security.AdminPrincipal)
    object.__setattr__(principal, "user", user)
    object.__setattr__(principal, "token_payload", {})
    principal.user.role_id = 2  # non-super_admin → base limits apply
    principal.user.id = 13

    # exhaust the batch bucket for user 13
    for _ in range(10):
        await check_admin_ratelimit(13, "/api/admin/v1/imports/batch")

    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: "operator")
    )
    with pytest.raises(HTTPException) as exc_info:
        await admin_rate_limit(request, current_admin=principal, db=db)
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role_id", "role_name", "is_super"),
    [(1, "super_admin", True), (2, "operator", False), (3, "super_admin", True)],
)
async def test_admin_rate_limit_unloaded_role_does_not_lazy_load(
    monkeypatch, role_id, role_name, is_super
):
    """An authenticated admin has an unloaded role in get_current_admin."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Role.__table__.create)
            await conn.run_sync(AdminUser.__table__.create)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as db:
            db.add_all(
                [
                    Role(id=role_id, name=role_name, display_name=role_name),
                    AdminUser(
                        id=42,
                        username="rate-limit-admin",
                        password_hash="test-only",
                        role_id=role_id,
                    ),
                ]
            )
            await db.commit()
        async with session_maker() as db:
            user = (
                await db.execute(select(AdminUser).where(AdminUser.id == 42))
            ).scalar_one()
            assert "role" in inspect(user).unloaded
            checker = AsyncMock(return_value=True)
            monkeypatch.setattr(admin_guards, "check_admin_ratelimit", checker)

            await admin_rate_limit(
                make_admin_request(path="/api/admin/v1/dashboard/daily"),
                current_admin=admin_security.AdminPrincipal(user, {}),
                db=db,
            )

            checker.assert_awaited_once_with(
                42,
                "/api/admin/v1/dashboard/daily",
                is_super_admin=is_super,
                bypass_token=None,
            )
            assert "role" in inspect(user).unloaded
    finally:
        await engine.dispose()


# ── Idempotency ──────────────────────────────────────────────────


def make_admin_request(
    path: str = "/api/admin/v1/imports/batch-a/approve",
    *,
    key: str | None = "key-1",
    body: bytes = b"",
    bypass_token: str | None = None,
) -> Request:
    headers = []
    if key is not None:
        headers.append((b"idempotency-key", key.encode()))
    if bypass_token is not None:
        headers.append((b"x-admin-bypass-token", bypass_token.encode()))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": headers,
        },
        receive=receive,
    )


@pytest.mark.asyncio
async def test_idempotency_reservation_replays_only_after_completion():
    claim = await reserve_idempotent_request(21, "key-1", "fingerprint")
    with pytest.raises(IdempotencyInProgressError):
        await reserve_idempotent_request(21, "key-1", "fingerprint")
    await complete_idempotent_request(claim, {"affected": 3})
    repeated = await reserve_idempotent_request(21, "key-1", "fingerprint")
    assert repeated.response == {"affected": 3}
    assert repeated.pending_value is None


@pytest.mark.asyncio
async def test_concurrent_same_key_reserves_only_once():
    results = await asyncio.gather(
        reserve_idempotent_request(21, "same-key", "same-request"),
        reserve_idempotent_request(21, "same-key", "same-request"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, IdempotencyClaim) for result in results) == 1
    assert sum(isinstance(result, IdempotencyInProgressError) for result in results) == 1


@pytest.mark.asyncio
async def test_idempotency_fingerprint_conflict_and_uncommitted_release():
    claim = await reserve_idempotent_request(21, "key-1", "fingerprint-1")
    with pytest.raises(IdempotencyConflictError):
        await reserve_idempotent_request(21, "key-1", "fingerprint-2")
    await release_idempotent_request(claim)
    assert (
        await reserve_idempotent_request(21, "key-1", "fingerprint-2")
    ).pending_value


@pytest.mark.asyncio
async def test_require_idempotency_missing_header_400():
    with pytest.raises(HTTPException) as exc_info:
        await require_idempotency(
            make_admin_request(key=None), current_admin=MagicMock()
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_require_idempotency_rejects_other_action_and_body():
    principal = MagicMock(id=21)
    request = make_admin_request(body=b'{"reason":"a"}')
    claim = await require_idempotency(request, current_admin=principal)
    await complete_idempotent_request(claim, {"status": "approved"})
    repeated = await require_idempotency(
        make_admin_request(body=b'{"reason":"a"}'), current_admin=principal
    )
    assert repeated.response == {"status": "approved"}
    for other in (
        make_admin_request(
            path="/api/admin/v1/imports/batch-b/approve", body=b'{"reason":"a"}'
        ),
        make_admin_request(body=b'{"reason":"b"}'),
    ):
        with pytest.raises(HTTPException) as error:
            await require_idempotency(other, current_admin=principal)
        assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_idempotency_completion_error_preserves_pending_claim(monkeypatch):
    claim = await reserve_idempotent_request(21, "key-1", "fingerprint")

    async def unavailable(*args, **kwargs):
        raise CacheUnavailableError("down")

    monkeypatch.setattr(cache, "compare_and_set_strict", unavailable)
    with pytest.raises(CacheUnavailableError):
        await complete_idempotent_request(claim, {"affected": 1})
    with pytest.raises(IdempotencyInProgressError):
        await reserve_idempotent_request(21, "key-1", "fingerprint")


@pytest.mark.asyncio
async def test_batch_delete_commits_once_then_replays(monkeypatch):
    from app.api.v1 import admin_questions
    from app.schemas.admin_questions import (
        AdminQuestionBatchRequest,
        AdminQuestionBatchResult,
    )

    principal = MagicMock(id=21)
    path = "/api/admin/v1/questions/batch-delete"
    body = b'{"ids":[1]}'
    request = make_admin_request(path=path, body=body)
    claim = await require_idempotency(request, current_admin=principal)
    db = MagicMock()
    db.commit = AsyncMock()
    result = AdminQuestionBatchResult(success_ids=[1], failed_items=[])
    delete = AsyncMock(return_value=result)
    monkeypatch.setattr(admin_questions, "batch_delete_admin_questions", delete)

    first = await admin_questions.batch_delete_questions(
        AdminQuestionBatchRequest(ids=[1]), request, principal, None, claim, db
    )
    replay_request = make_admin_request(path=path, body=body)
    replay_claim = await require_idempotency(replay_request, current_admin=principal)
    replay = await admin_questions.batch_delete_questions(
        AdminQuestionBatchRequest(ids=[1]),
        replay_request,
        principal,
        None,
        replay_claim,
        db,
    )
    assert first.success_ids == replay.success_ids == [1]
    delete.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_approve_replays_without_duplicate_commit(monkeypatch):
    from app.api.v1 import admin_imports

    path = "/api/admin/v1/imports/batch-a/approve"
    principal = MagicMock(id=21)
    request = make_admin_request(path=path)
    claim = await require_idempotency(request, current_admin=principal)
    db = MagicMock()
    db.commit = AsyncMock()
    approve = AsyncMock(return_value=3)
    monkeypatch.setattr(admin_imports, "approve_import_batch", approve)

    first = await admin_imports.approve_import_batch_items(
        "batch-a", request, principal, None, claim, db
    )
    repeated_request = make_admin_request(path=path)
    repeated = await admin_imports.approve_import_batch_items(
        "batch-a",
        repeated_request,
        principal,
        None,
        await require_idempotency(repeated_request, current_admin=principal),
        db,
    )
    assert first.affected_count == repeated.affected_count == 3
    approve.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_after_commit_redis_failure_preserves_claim(monkeypatch):
    from app.api.v1 import admin_questions
    from app.schemas.admin_questions import (
        AdminQuestionBatchRequest,
        AdminQuestionBatchResult,
    )

    principal = MagicMock(id=21)
    request = make_admin_request(
        path="/api/admin/v1/questions/batch-delete", body=b'{"ids":[1]}'
    )
    claim = await require_idempotency(request, current_admin=principal)
    db = MagicMock()
    db.commit = AsyncMock()
    delete = AsyncMock(
        return_value=AdminQuestionBatchResult(success_ids=[1], failed_items=[])
    )
    monkeypatch.setattr(admin_questions, "batch_delete_admin_questions", delete)

    async def unavailable(*args, **kwargs):
        raise CacheUnavailableError("down")

    monkeypatch.setattr(cache, "compare_and_set_strict", unavailable)
    with pytest.raises(HTTPException) as error:
        await admin_questions.batch_delete_questions(
            AdminQuestionBatchRequest(ids=[1]), request, principal, None, claim, db
        )
    assert error.value.status_code == 503
    db.commit.assert_awaited_once()
    with pytest.raises(HTTPException) as retry_error:
        await require_idempotency(
            make_admin_request(
                path="/api/admin/v1/questions/batch-delete", body=b'{"ids":[1]}'
            ),
            current_admin=principal,
        )
    assert retry_error.value.status_code == 409
    delete.assert_awaited_once()


# ── Bypass tokens ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bypass_token_lifecycle():
    token = "raw-token-abc"
    assert await is_bypass_allowed(token) is False
    await create_bypass_token(token, type_="monitor", note="nagios")
    assert await is_bypass_allowed(token) is True
    assert await is_bypass_allowed("other-token") is False
    assert await delete_bypass_token(token) is True
    assert await is_bypass_allowed(token) is False


@pytest.mark.asyncio
async def test_bypass_header_skips_only_allowlisted_observability_rate_limit():
    token = "monitor-test-token"
    principal = MagicMock()
    principal.id = 10
    principal.role_id = 2
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: "operator")
    )
    stats_path = "/api/admin/v1/dashboard/daily"
    request = make_admin_request(path=stats_path)
    for _ in range(30):
        await admin_rate_limit(request, current_admin=principal, db=db)
    with pytest.raises(HTTPException) as error:
        await admin_rate_limit(request, current_admin=principal, db=db)
    assert error.value.status_code == 429
    await create_bypass_token(token, type_="monitor")
    bypass_request = make_admin_request(path=stats_path, bypass_token=token)
    await admin_rate_limit(bypass_request, current_admin=principal, db=db)
    # A monitoring token must not bypass limits on critical batch writes.
    batch_path = "/api/admin/v1/imports/batch"
    for _ in range(10):
        await check_admin_ratelimit(10, batch_path)
    with pytest.raises(HTTPException) as error:
        await admin_rate_limit(
            make_admin_request(path=batch_path, bypass_token=token),
            current_admin=principal,
            db=db,
        )
    assert error.value.status_code == 429


@pytest.mark.asyncio
async def test_role_version_bumped_only_after_commit(monkeypatch):
    from app.api.v1 import admin_rbac

    events = []
    db = MagicMock()

    async def committed():
        events.append("commit")

    async def invalidated(_db, role_id):
        assert role_id == 7
        events.append("bump")

    async def updated(*args, **kwargs):
        events.append("update")
        return MagicMock()

    db.commit = committed
    db.refresh = AsyncMock()
    monkeypatch.setattr(admin_rbac, "update_role_permissions", updated)
    monkeypatch.setattr(admin_rbac, "bump_role_version", invalidated)
    await admin_rbac.replace_role_permissions(
        7,
        admin_rbac.RolePermissionsUpdateRequest(permission_ids=[]),
        MagicMock(),
        current_admin=MagicMock(id=1),
        db=db,
    )
    assert events == ["update", "commit", "bump"]


@pytest.mark.asyncio
async def test_ocr_snapshot_falls_back_to_database_after_cache_miss():
    from app.api.v1.admin_redis import get_ocr_task_snapshot

    db = MagicMock()
    db.get = AsyncMock(
        return_value=MagicMock(
            id="job-42",
            status="completed",
            last_error_message=None,
            last_error_code=None,
            updated_at=None,
        )
    )
    snapshot = await get_ocr_task_snapshot("job-42", db=db)
    assert snapshot.status == "completed"
    assert snapshot.progress == 100
    assert snapshot.source == "database"
    db.get.assert_awaited_once()


# ── Dashboard daily stats cache ──────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_daily_cache_roundtrip():
    from app.services.admin_dashboard_service import get_dashboard_daily

    start = date(2026, 9, 1)
    end = date(2026, 9, 3)
    key = f"admin:stats:daily:{start.isoformat()}:{end.isoformat()}"
    payload = [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "users_new": i,
            "questions_new": 0,
            "imports_new": 0,
            "audits_total": 0,
        }
        for i in range(3)
    ]
    await cache.set(key, payload, ttl=60)

    db = MagicMock()
    db.connection = AsyncMock()
    items = await get_dashboard_daily(db, start, end)
    assert [item["users_new"] for item in items] == [0, 1, 2]
    assert all(isinstance(item["date"], date) for item in items)
    db.connection.assert_not_awaited()


# ── Refresh-consumed marker lifetime ──────────────────────────────


@pytest.mark.asyncio
async def test_consume_refresh_marker_lives_until_token_expiration(monkeypatch):
    """A used 7-day refresh token must not become reusable after 24 hours."""
    captured = {}

    async def fake_acquire(key, value, ttl=10):
        captured["ttl"] = ttl
        return True

    async def fake_get_strict(key):
        return None

    async def fake_db_exec(_stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    monkeypatch.setattr(cache, "acquire_lock_strict", fake_acquire)
    monkeypatch.setattr(cache, "get_strict", fake_get_strict)

    class _Db:
        execute = staticmethod(fake_db_exec)

    payload = {
        "sub": "1",
        "iat": int(unix_timestamp(utcnow())) - 10,
        "exp": int(unix_timestamp(utcnow())) + 7 * 24 * 60 * 60,
        "jti": "jti-ttl-test",
    }
    with pytest.raises(HTTPException):
        await admin_security.consume_admin_refresh_token(payload, _Db())
    # User lookup fails (user None), but the TTL was already recorded.
    assert 7 * 24 * 60 * 60 - 3 <= captured["ttl"] <= 7 * 24 * 60 * 60
