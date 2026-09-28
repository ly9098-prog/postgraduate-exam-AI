from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_health
from app.core.admin_security import get_current_admin
from app.core.database import get_db
from app.main import app

client = TestClient(app)


class _FakeSession:
    async def execute(self, _statement):
        return None


class _FakeSessionContext:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_admin_principal():
    from app.core.admin_security import AdminPrincipal
    from app.models.admin import AdminUser

    user = AdminUser(
        id=1, username="admin", password_hash="hash", is_active=True, role_id=2
    )
    return AdminPrincipal(user, {})


@pytest.fixture
def admin_permissions_db():
    """Keep RBAC independent of a provisioned database in health-route tests."""

    class PermissionDb:
        async def execute(self, _statement):
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: ["dashboard:read"])
            )

    app.dependency_overrides[get_db] = lambda: PermissionDb()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_admin_live_health():
    resp = client.get("/api/admin/v1/health/live")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_admin_ready_health_ok_with_redis(monkeypatch, admin_permissions_db):
    app.dependency_overrides[get_current_admin] = lambda: _make_admin_principal()
    monkeypatch.setattr(admin_health, "async_session", lambda: _FakeSessionContext())
    monkeypatch.setattr(admin_health.cache, "set_strict", AsyncMock())
    monkeypatch.setattr(
        admin_health.cache, "get_strict", AsyncMock(return_value="pong")
    )

    try:
        resp = client.get("/api/admin/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok", "redis": "ok"}


def test_admin_ready_health_degrades_when_db_unavailable(
    monkeypatch, admin_permissions_db
):
    class BrokenSessionContext:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    app.dependency_overrides[get_current_admin] = lambda: _make_admin_principal()
    monkeypatch.setattr(admin_health, "async_session", lambda: BrokenSessionContext())

    try:
        resp = client.get("/api/admin/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "degraded",
        "db": "unavailable",
        "redis": "degraded",
    }
