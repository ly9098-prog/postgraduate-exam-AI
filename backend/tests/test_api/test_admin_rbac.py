from fastapi.testclient import TestClient

from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser, Permission, Role

client = TestClient(app)


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

    def all(self):
        return self._values


class _FakeDb:
    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, _statement):
        return _Result(self._results.pop(0))


def _admin_user():
    return AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=1)


async def _override_current_admin():
    return AdminPrincipal(_admin_user(), {"jti": "token-id", "exp": 4102444800})


def _override_db(required_permissions, *endpoint_values):
    async def dependency():
        yield _FakeDb(required_permissions, *endpoint_values)

    return dependency


def test_list_roles():
    roles = [
        Role(id=1, name="super_admin", display_name="超级管理员", description=None, is_system=True),
        Role(id=2, name="operator", display_name="运营", description="内容运营", is_system=False),
    ]

    app.dependency_overrides[get_current_admin] = _override_current_admin
    app.dependency_overrides[get_db] = _override_db(["role:read"], roles, [(1, 1), (1, 2), (2, 1)])
    try:
        resp = client.get("/api/admin/v1/roles")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json() == {
        "items": [
            {"id": 1, "name": "super_admin", "display_name": "超级管理员", "description": None, "is_system": True, "permission_ids": [1, 2]},
            {"id": 2, "name": "operator", "display_name": "运营", "description": "内容运营", "is_system": False, "permission_ids": [1]},
        ]
    }


def test_list_permissions():
    permissions = [
        Permission(id=1, name="role:read", resource="role", action="read", category="system", description="读取角色"),
        Permission(id=2, name="permission:read", resource="permission", action="read", category="system", description=None),
    ]

    app.dependency_overrides[get_current_admin] = _override_current_admin
    app.dependency_overrides[get_db] = _override_db(["permission:read"], permissions)
    try:
        resp = client.get("/api/admin/v1/permissions")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json() == {
        "items": [
            {"id": 1, "name": "role:read", "resource": "role", "action": "read", "category": "system", "description": "读取角色"},
            {"id": 2, "name": "permission:read", "resource": "permission", "action": "read", "category": "system", "description": None},
        ]
    }


def test_list_permissions_by_category():
    permissions = [
        Permission(id=1, name="role:read", resource="role", action="read", category="system", description="读取角色"),
        Permission(id=2, name="question:read", resource="question", action="read", category="content", description=None),
    ]

    app.dependency_overrides[get_current_admin] = _override_current_admin
    app.dependency_overrides[get_db] = _override_db(["permission:read"], permissions)
    try:
        resp = client.get("/api/admin/v1/permissions")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json() == {
        "items": [
            {"id": 1, "name": "role:read", "resource": "role", "action": "read", "category": "system", "description": "读取角色"},
            {"id": 2, "name": "question:read", "resource": "question", "action": "read", "category": "content", "description": None},
        ]
    }
