from datetime import datetime
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import admin_subjects
from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser, Subject

client = TestClient(app)


class _Db:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, _statement):
        class _Scalars:
            def all(self):
                return ["subject:read", "subject:write", "subject:delete"]

        class _Result:
            def scalars(self):
                return _Scalars()

        return _Result()


async def _override_db():
    yield _Db()


def _principal():
    user = AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=1)
    return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})


async def _allow():
    return _principal()


def _subject(subject_id=1):
    now = datetime(2026, 5, 29)
    return Subject(
        id=subject_id,
        parent_id=None,
        code="math",
        name="数学",
        level=1,
        path="math",
        sort_order=0,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_list_subjects(monkeypatch):
    monkeypatch.setattr(admin_subjects, "list_subject_tree", AsyncMock(return_value=[_subject().__dict__ | {"children": []}]))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/subjects")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["items"][0]["code"] == "math"


def test_get_subject_detail(monkeypatch):
    monkeypatch.setattr(admin_subjects, "get_subject", AsyncMock(return_value=_subject()))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/subjects/1")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["name"] == "数学"


def test_create_update_delete_subject(monkeypatch):
    monkeypatch.setattr(admin_subjects, "create_subject", AsyncMock(return_value=_subject()))
    monkeypatch.setattr(admin_subjects, "update_subject", AsyncMock(return_value=_subject()))
    monkeypatch.setattr(admin_subjects, "delete_subject", AsyncMock())
    invalidate = AsyncMock()
    monkeypatch.setattr(admin_subjects, "invalidate_subject_tree_cache", invalidate)
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        create_resp = client.post("/api/admin/v1/subjects", json={"code": "math", "name": "数学"})
        update_resp = client.patch("/api/admin/v1/subjects/1", json={"name": "高数"})
        delete_resp = client.delete("/api/admin/v1/subjects/1")
    finally:
        app.dependency_overrides.clear()

    assert create_resp.status_code == 200
    assert update_resp.status_code == 200
    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"deleted": True}
    assert invalidate.await_count == 3


def test_subject_errors(monkeypatch):
    monkeypatch.setattr(admin_subjects, "get_subject", AsyncMock(side_effect=ValueError("科目不存在")))
    monkeypatch.setattr(admin_subjects, "create_subject", AsyncMock(side_effect=admin_subjects.SubjectConflictError("科目编码已存在")))
    monkeypatch.setattr(admin_subjects, "update_subject", AsyncMock(side_effect=ValueError("科目层级不能超过3级")))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        not_found_resp = client.get("/api/admin/v1/subjects/1")
        conflict_resp = client.post("/api/admin/v1/subjects", json={"code": "math", "name": "数学"})
        rule_resp = client.patch("/api/admin/v1/subjects/1", json={"name": "高数"})
    finally:
        app.dependency_overrides.clear()

    assert not_found_resp.status_code == 404
    assert conflict_resp.status_code == 409
    assert rule_resp.status_code == 422


def test_list_subjects_requires_permission():
    resp = client.get("/api/admin/v1/subjects")

    assert resp.status_code in {401, 403}
