from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.models.user import User

client = TestClient(app)


class _Db:
    async def execute(self, _statement):
        raise AssertionError("blocked app import endpoints must not query the database")


async def _override_db():
    yield _Db()


async def _app_user():
    return User(id=1, openid="dev_test_user")


def test_app_import_management_endpoints_are_forbidden():
    app.dependency_overrides[get_current_user] = _app_user
    app.dependency_overrides[get_db] = _override_db
    try:
        responses = [
            client.post("/api/v1/import/batches/batch-1/approve"),
            client.post("/api/v1/import/batches/batch-1/reject"),
            client.put("/api/v1/import/questions/1", json={"status": "approved"}),
            client.put("/api/v1/import/questions/1/fix", json={"stem": "题干"}),
            client.post("/api/v1/import/review/publish", json={"batch_id": "batch-1"}),
            client.post("/api/v1/import/review/approve-and-publish", json={"question_ids": [1]}),
        ]
    finally:
        app.dependency_overrides.clear()

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403, 403]


def test_app_ai_import_management_endpoints_are_forbidden():
    app.dependency_overrides[get_current_user] = _app_user
    app.dependency_overrides[get_db] = _override_db
    try:
        responses = [
            client.post("/api/v1/ai-import/enrich/1"),
            client.post("/api/v1/ai-import/enrich-batch/batch-1"),
            client.post("/api/v1/ai-import/complete/1"),
        ]
    finally:
        app.dependency_overrides.clear()

    assert [response.status_code for response in responses] == [403, 403, 403]


def test_app_ai_import_generate_remains_available(monkeypatch):
    from app.api.v1 import ai_import

    monkeypatch.setattr(
        ai_import.svc,
        "generate_drafts",
        AsyncMock(
            return_value={
                "batch_id": "batch-1",
                "generated": 1,
                "from_fallback": False,
                "tokens_used": 0,
                "duration_ms": 0,
            }
        ),
    )
    app.dependency_overrides[get_current_user] = _app_user
    app.dependency_overrides[get_db] = _override_db
    try:
        response = client.post(
            "/api/v1/ai-import/generate",
            json={"subject": "math", "knowledge_points": ["函数"], "count": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["batch_id"] == "batch-1"
