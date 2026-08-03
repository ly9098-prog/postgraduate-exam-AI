from datetime import datetime
from io import BytesIO
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from PIL import Image

from app.api.v1 import admin_imports
from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser
from app.schemas.admin_imports import (
    AdminImportBatchDetail,
    AdminImportCompleteResponse,
    AdminImportEnrichResponse,
    AdminImportQuestionItem,
)


def _minimal_png_bytes() -> bytes:
    """Generate a minimal valid PNG for upload tests."""
    img = Image.new("RGB", (16, 16), (128, 128, 128))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

client = TestClient(app)


class _Db:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, _statement):
        class _Scalars:
            def all(self):
                return ["import:read", "import:write"]

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


def _batch():
    now = datetime(2026, 5, 29)
    return {
        "batch_id": "batch-1",
        "source_type": "manual",
        "source_file": "file.xlsx",
        "total_count": 1,
        "pending_count": 1,
        "approved_count": 0,
        "rejected_count": 0,
        "published_count": 0,
        "ai_count": 0,
        "created_at": now,
        "updated_at": now,
    }


def _question_item():
    now = datetime(2026, 5, 29)
    return AdminImportQuestionItem(
        id=1,
        batch_id="batch-1",
        source_type="manual",
        source_file="file.xlsx",
        subject_id=1,
        question_type="choice",
        raw_data={"text": "raw"},
        parsed_content={"text": "题干"},
        parsed_options={"A": "1"},
        parsed_answer="A",
        parsed_analysis="解析",
        status="pending",
        ai_generated=False,
        ai_answer_flag=False,
        created_at=now,
        updated_at=now,
    )


def test_list_import_batches(monkeypatch):
    monkeypatch.setattr(admin_imports, "list_import_batches", AsyncMock(return_value=([_batch()], 1)))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/imports")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["batch_id"] == "batch-1"


def test_get_import_batch_detail(monkeypatch):
    detail = AdminImportBatchDetail(**_batch(), items=[_question_item()], page=1, page_size=20, total_pages=1)
    monkeypatch.setattr(admin_imports, "get_import_batch_detail", AsyncMock(return_value=detail))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/imports/batch-1")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["items"][0]["parsed_answer"] == "A"


def test_create_enrich_task_and_status(monkeypatch):
    now = datetime(2026, 5, 29)
    task = AdminImportEnrichResponse(task_id="task-1", batch_id="batch-1", status="pending", created_at=now)
    monkeypatch.setattr(admin_imports, "create_enrich_task", AsyncMock(return_value=task))
    monkeypatch.setattr(admin_imports, "get_enrich_status", AsyncMock(return_value={"task_id": "task-1", "batch_id": "batch-1", "status": "pending", "created_at": now.isoformat()}))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        create_resp = client.post("/api/admin/v1/imports/batch-1/enrich")
        status_resp = client.get("/api/admin/v1/imports/batch-1/status")
    finally:
        app.dependency_overrides.clear()

    assert create_resp.status_code == 200
    assert create_resp.json()["task_id"] == "task-1"
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "pending"


def test_complete_import_question(monkeypatch):
    response = AdminImportCompleteResponse(
        missing=["answer"],
        from_fallback=False,
        ai_metadata={"complete_suggestion": {"answer": "B"}},
        tokens_used=12,
        duration_ms=34,
        item=_question_item(),
    )
    monkeypatch.setattr(admin_imports, "complete_import_question", AsyncMock(return_value=response))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/imports/questions/1/complete")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["missing"] == ["answer"]
    assert resp.json()["item"]["id"] == 1


def test_complete_import_question_missing(monkeypatch):
    monkeypatch.setattr(admin_imports, "complete_import_question", AsyncMock(side_effect=ValueError("导入题目不存在")))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/imports/questions/1/complete")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


def test_import_errors(monkeypatch):
    monkeypatch.setattr(admin_imports, "get_import_batch_detail", AsyncMock(side_effect=ValueError("导入批次不存在")))
    monkeypatch.setattr(admin_imports, "get_enrich_status", AsyncMock(side_effect=ValueError("AI任务不存在")))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        detail_resp = client.get("/api/admin/v1/imports/missing")
        status_resp = client.get("/api/admin/v1/imports/batch-1/status")
    finally:
        app.dependency_overrides.clear()

    assert detail_resp.status_code == 404
    assert status_resp.status_code == 404


def test_list_imports_requires_permission():
    resp = client.get("/api/admin/v1/imports")

    assert resp.status_code in {401, 403}


def test_upload_segment_image(monkeypatch):
    """POST /segment-image/upload accepts image and returns URL."""
    from app.services import storage_backend

    async def fake_upload(_self, filename, data):
        return f"http://test.local/static/formulas/{filename}"

    monkeypatch.setattr(storage_backend.LocalFileStorage, "upload", fake_upload)
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post(
            "/api/admin/v1/imports/segment-image/upload",
            files={"file": ("test.png", _minimal_png_bytes(), "image/png")},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["url"].startswith("http://test.local/static/formulas/")
    # The endpoint compresses + content-names the file; only the extension is stable.
    assert data["filename"].endswith((".png", ".jpg", ".webp"))


def test_upload_segment_image_rejects_non_image(monkeypatch):
    """POST /segment-image/upload rejects non-image files."""
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post(
            "/api/admin/v1/imports/segment-image/upload",
            files={"file": ("test.txt", b"not-an-image", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "图片" in resp.json()["detail"]


def test_question_content_sanitizer():
    """_sanitize_content strips admin-only fields from question content."""
    from app.api.v1.questions import _sanitize_content

    raw = {
        "text": "题目内容",
        "stem": "题目题干",
        "segments": [{"type": "image", "url": "/static/q.png"}],
        "source_snapshot_url": "http://internal/snap.png",
        "source_snapshot_full_page": True,
        "visual_regions": [{"bbox": [0, 0, 100, 100]}],
        "visual_region_ids": ["vr_1"],
    }
    result = _sanitize_content(raw)

    assert result is not None
    assert result["text"] == "题目内容"
    assert result["stem"] == "题目题干"
    assert len(result["segments"]) == 1
    # Admin-only fields must be stripped
    assert "source_snapshot_url" not in result
    assert "source_snapshot_full_page" not in result
    assert "visual_regions" not in result
    assert "visual_region_ids" not in result


def test_question_content_sanitizer_none():
    """_sanitize_content handles None gracefully."""
    from app.api.v1.questions import _sanitize_content

    assert _sanitize_content(None) is None
    assert _sanitize_content("not a dict") == "not a dict"
