import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import admin_rbac
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

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None

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
    app.dependency_overrides[get_db] = _override_db(["super_admin"], permissions)
    try:
        resp = client.get("/api/admin/v1/permissions/by-category")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == payload["categories"] == 2
    assert set(payload["items"]) == {"system", "content"}
    assert payload["items"]["system"][0]["name"] == "role:read"
    assert payload["items"]["content"][0]["name"] == "question:read"


def test_grouped_permissions_reject_non_super_admin():
    app.dependency_overrides[get_current_admin] = _override_current_admin
    app.dependency_overrides[get_db] = _override_db(["operator"])
    try:
        response = client.get("/api/admin/v1/permissions/by-category")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_replace_permissions_waits_for_commit_before_version_bump(monkeypatch):
    events = []
    commit_started = asyncio.Event()
    release_commit = asyncio.Event()
    role = SimpleNamespace(id=3)

    async def commit():
        events.append("commit:start")
        commit_started.set()
        await release_commit.wait()
        events.append("commit:end")

    async def bump(db, role_id):
        assert db is database and role_id == 3
        events.append("bump")

    async def refresh(value):
        assert value is role
        events.append("refresh")

    database = SimpleNamespace(commit=commit, refresh=refresh, rollback=AsyncMock())
    update = AsyncMock(return_value=role)
    monkeypatch.setattr(admin_rbac, "update_role_permissions", update)
    monkeypatch.setattr(admin_rbac, "bump_role_version", bump)
    operator = await _override_current_admin()
    request = SimpleNamespace()
    task = asyncio.create_task(admin_rbac.replace_role_permissions(
        3, admin_rbac.RolePermissionsUpdateRequest(permission_ids=[9, 2, 9]),
        request, current_admin=operator, db=database,
    ))
    try:
        await asyncio.wait_for(commit_started.wait(), timeout=2)
        assert events == ["commit:start"]
        database.rollback.assert_not_awaited()
    finally:
        release_commit.set()
        result = await task
    assert result == {"status": "ok", "permission_ids": [2, 9]}
    assert events == ["commit:start", "commit:end", "bump", "refresh"]
    update.assert_awaited_once_with(
        database, 3, [9, 2, 9], operator=operator,
        operator_id=operator.id, request=request,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("error,expected_status", [
    (PermissionError("protected role"), 403),
    (ValueError("unknown permission"), 422),
])
async def test_replace_permissions_rolls_back_before_returning_error(monkeypatch, error, expected_status):
    database = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock(), rollback=AsyncMock())
    bump = AsyncMock()
    monkeypatch.setattr(admin_rbac, "update_role_permissions", AsyncMock(side_effect=error))
    monkeypatch.setattr(admin_rbac, "bump_role_version", bump)
    with pytest.raises(HTTPException) as raised:
        await admin_rbac.replace_role_permissions(
            3, admin_rbac.RolePermissionsUpdateRequest(permission_ids=[1]),
            SimpleNamespace(), current_admin=await _override_current_admin(), db=database,
        )
    assert raised.value.status_code == expected_status
    database.rollback.assert_awaited_once()
    database.commit.assert_not_awaited()
    database.refresh.assert_not_awaited()
    bump.assert_not_awaited()
