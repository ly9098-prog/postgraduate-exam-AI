from datetime import datetime
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import admin_questions
from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser, QuestionVersion
from app.models.question import Question
from app.models.question_import import QuestionImport

client = TestClient(app)


class _Db:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, _statement):
        class _Scalars:
            def all(self):
                return ["question:read", "question:write", "question:delete"]

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


def _question(question_id=1, review_status="approved", is_active=True):
    now = datetime(2026, 5, 29)
    return Question(
        id=question_id,
        subject="math",
        question_type="choice",
        content={"text": "题干"},
        options={"A": "1"},
        answer="A",
        analysis="解析",
        knowledge_points=["函数"],
        difficulty=3,
        source="source",
        source_type="manual",
        source_file=None,
        import_batch_id="batch-1",
        raw_content="原文",
        image_url=[],
        year=2026,
        review_status=review_status,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _import_record():
    now = datetime(2026, 5, 29)
    return QuestionImport(
        id=1,
        batch_id="batch-1",
        source_type="manual",
        raw_data={"text": "raw"},
        status="approved",
        question_id=1,
        created_at=now,
        updated_at=now,
    )


def _version():
    return QuestionVersion(
        id=1,
        question_id=1,
        version=1,
        content={"text": "旧题干"},
        options={"A": "1"},
        answer="A",
        analysis="旧解析",
        difficulty=3,
        knowledge_points=["函数"],
        edited_by=1,
        edit_reason="修正",
        created_at=datetime(2026, 5, 29),
    )


def test_list_admin_questions(monkeypatch):
    monkeypatch.setattr(admin_questions, "list_admin_questions", AsyncMock(return_value=([_question()], 1)))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/questions")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["review_status"] == "approved"


def test_get_admin_question_detail(monkeypatch):
    detail = _question().__dict__ | {"import_record": _import_record()}
    monkeypatch.setattr(admin_questions, "get_admin_question_detail", AsyncMock(return_value=detail))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/questions/1")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["import_record"]["batch_id"] == "batch-1"


def test_patch_admin_question(monkeypatch):
    patch_question = AsyncMock(return_value=_question(review_status="approved", is_active=True))
    monkeypatch.setattr(admin_questions, "update_admin_question", patch_question)
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.patch("/api/admin/v1/questions/1", json={"answer": "B", "edit_reason": "修正答案"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["review_status"] == "approved"
    patch_question.assert_awaited_once()


def test_delete_and_toggle(monkeypatch):
    monkeypatch.setattr(admin_questions, "soft_delete_admin_question", AsyncMock(return_value=_question(is_active=False)))
    monkeypatch.setattr(admin_questions, "toggle_active_admin_question", AsyncMock(return_value=_question(is_active=False)))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        delete_resp = client.delete("/api/admin/v1/questions/1")
        toggle_resp = client.patch("/api/admin/v1/questions/1/toggle-active", json={"is_active": False})
    finally:
        app.dependency_overrides.clear()

    assert delete_resp.status_code == 200
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["is_active"] is False


def test_question_versions(monkeypatch):
    monkeypatch.setattr(admin_questions, "list_question_versions", AsyncMock(return_value=([_version()], 1)))
    monkeypatch.setattr(admin_questions, "get_question_version_detail", AsyncMock(return_value=_version()))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        list_resp = client.get("/api/admin/v1/questions/1/versions")
        detail_resp = client.get("/api/admin/v1/questions/1/versions/1")
    finally:
        app.dependency_overrides.clear()

    assert list_resp.status_code == 200
    assert list_resp.json()["items"][0]["version"] == 1
    assert detail_resp.status_code == 200
    assert detail_resp.json()["answer"] == "A"


def test_list_admin_questions_requires_permission():
    resp = client.get("/api/admin/v1/questions")

    assert resp.status_code in {401, 403}
