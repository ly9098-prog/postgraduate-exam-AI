from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import admin_health
from app.core.admin_security import get_current_admin
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
    user = AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=2)
    return AdminPrincipal(user, {})


def test_admin_live_health():
    resp = client.get("/api/admin/v1/health/live")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_admin_ready_health_ok_with_redis(monkeypatch):
    app.dependency_overrides[get_current_admin] = lambda: _make_admin_principal()
    monkeypatch.setattr(admin_health, "async_session", lambda: _FakeSessionContext())
    monkeypatch.setattr(admin_health.cache, "set", AsyncMock())
    monkeypatch.setattr(admin_health.cache, "get", AsyncMock(return_value="pong"))

    resp = client.get("/api/admin/v1/health/ready")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok", "redis": "ok"}


def test_admin_ready_health_degrades_when_db_unavailable(monkeypatch):
    class BrokenSessionContext:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    app.dependency_overrides[get_current_admin] = lambda: _make_admin_principal()
    monkeypatch.setattr(admin_health, "async_session", lambda: BrokenSessionContext())

    resp = client.get("/api/admin/v1/health/ready")

    assert resp.status_code == 200
    assert resp.json() == {"status": "degraded", "db": "unavailable", "redis": "degraded"}
