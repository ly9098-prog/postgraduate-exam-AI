"""Cross-domain identity and auth dependency compatibility matrix."""

import asyncio

import pytest
from fastapi import HTTPException

from app.core.admin_security import (
    AdminPrincipal,
    create_admin_refresh_token,
    create_admin_token,
    get_current_admin,
    require_permissions,
)
from app.core.cache import CacheUnavailableError, cache
from app.core.database import get_db
from app.core.security import (
    authenticate_user_token,
    create_token,
    decode_token_payload,
)
from app.main import app
from app.models.admin import AdminUser


def _admin_user():
    return AdminUser(id=41, username="matrix", password_hash="hash", role_id=7)


def _principal(token):
    return AdminPrincipal(_admin_user(), token)


class _PermissionResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        values = self.values

        class _Scalars:
            def all(self):
                return values

        return _Scalars()


class _PermissionDb:
    def __init__(self, values):
        self.values = values
        self.calls = 0

    async def execute(self, _statement):
        self.calls += 1
        return _PermissionResult(self.values)


def test_user_and_admin_jwt_domains_reject_each_other():
    admin_access = create_admin_token(_admin_user())
    admin_refresh = create_admin_refresh_token(_admin_user())
    user_access = create_token(41)
    credentials = type("Credentials", (), {"credentials": user_access})()

    with pytest.raises(HTTPException) as admin_to_user:
        decode_token_payload(admin_access)
    with pytest.raises(HTTPException) as refresh_to_access:
        decode_token_payload(admin_refresh)
    with pytest.raises(HTTPException) as user_to_admin:
        asyncio.run(get_current_admin(credentials, _PermissionDb([])))

    assert admin_to_user.value.status_code == 401
    assert refresh_to_access.value.status_code == 401
    assert user_to_admin.value.status_code == 401


def test_authentication_security_state_is_fail_closed(monkeypatch):
    async def unavailable(_key):
        raise CacheUnavailableError("redis unavailable")

    monkeypatch.setattr(cache, "get_strict", unavailable)
    valid_user_token, _expires_at = create_token(41)

    async def run_user():
        return await authenticate_user_token(valid_user_token, _PermissionDb([]))

    with pytest.raises(HTTPException) as user_error:
        asyncio.run(run_user())

    admin_access = create_admin_token(_admin_user())
    credentials = type("Credentials", (), {"credentials": admin_access})()

    async def run_admin():
        return await get_current_admin(credentials, _PermissionDb([]))

    with pytest.raises(HTTPException) as admin_error:
        asyncio.run(run_admin())

    assert user_error.value.status_code == 503
    assert admin_error.value.status_code == 503


def test_require_permissions_requires_the_complete_requested_set():
    db = _PermissionDb(["question:read"])
    dependency = require_permissions("question:read", "knowledge:read")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(current_admin=_principal({}), db=db))

    assert exc.value.status_code == 403
    assert db.calls == 1


def test_public_prefixed_cache_endpoint_still_requires_admin_rbac():
    db = _PermissionDb(["cache:read"])

    async def current_admin():
        return _principal({})

    async def current_db():
        return db

    app.dependency_overrides[get_current_admin] = current_admin
    app.dependency_overrides[get_db] = current_db
    try:
        from fastapi.testclient import TestClient

        response = TestClient(app).get("/api/v1/cache/stats")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
