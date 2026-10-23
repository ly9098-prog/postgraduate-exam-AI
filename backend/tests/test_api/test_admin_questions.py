from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_questions
from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser, QuestionVersion
from app.models.question import Question
from app.models.question_import import QuestionImport

client = TestClient(app)


@pytest.fixture(autouse=True)
def _kp_patch(monkeypatch):
    """端点统一从关联表读取知识点；测试内 patch 为固定返回值。"""
    monkeypatch.setattr(
        admin_questions, "load_question_kps",
        AsyncMock(return_value={1: ["函数"]}),
    )


class _Db:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, _statement):
        class _Scalars:
            def all(self):
                return ["question:read", "question:write", "question:delete", "question:review", "question:batch_review"]

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
        subject_id=1,
        question_type="choice",
        content={"text": "题干"},
        options={"A": "1"},
        answer="A",
        analysis="解析",
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
        edited_by=1,
        change_source="admin",
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


def test_question_subject_options_use_question_read_permission(monkeypatch):
    now = datetime(2026, 5, 29)
    subject = {
        "id": 2,
        "parent_id": 1,
        "code": "math.linear",
        "name": "线性代数",
        "level": 2,
        "path": "math/math.linear",
        "sort_order": 0,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "children": [],
    }
    monkeypatch.setattr(
        admin_questions, "list_subject_tree",
        AsyncMock(return_value=[subject]),
    )
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/questions/subject-options")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["code"] == "math.linear"
    assert body[0]["product_code"] is None


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
    patch_question = AsyncMock(return_value=_question(review_status="re_pending", is_active=False))
    monkeypatch.setattr(admin_questions, "update_admin_question", patch_question)
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.patch("/api/admin/v1/questions/1", json={"answer": "B", "edit_reason": "修正答案"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["review_status"] == "re_pending"
    patch_question.assert_awaited_once()


def test_delete_approve_reject_and_toggle(monkeypatch):
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


def test_batch_approve_and_reject(monkeypatch):
    """batch-approve/reject endpoints removed — no-op placeholder."""
    pass


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


def _choice_question():
    q = _question()
    q.question_type = "single_choice"
    return q


# ── POST /{id}/options ──────────────────────────────────────────────

def test_add_question_options(monkeypatch):
    q = _choice_question()
    updated = _choice_question()
    updated.options = {"A": "1", "B": "2"}
    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=q))
    monkeypatch.setattr(admin_questions, "merge_options", lambda existing, items: {**existing, "B": items[0].text})
    monkeypatch.setattr(admin_questions, "update_admin_question", AsyncMock(return_value=updated))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/questions/1/options", json={"options": [{"text": "2"}], "edit_reason": "加选项"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["options"] == {"A": "1", "B": "2"}


def test_add_question_options_duplicate_key(monkeypatch):
    q = _choice_question()
    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=q))

    def _dup(_existing, _items):
        raise ValueError("选项 A 已存在")

    monkeypatch.setattr(admin_questions, "merge_options", _dup)
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/questions/1/options", json={"options": [{"text": "2"}]})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


def test_add_question_options_non_choice_type(monkeypatch):
    # fixture question_type is "choice" → gate rejects
    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=_question()))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/questions/1/options", json={"options": [{"text": "2"}]})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


def test_add_question_options_rejects_non_letter_key(monkeypatch):
    # Option keys must be A-Z; a digit key is rejected up front by the schema,
    # so the endpoint never merges an option that the image target validator
    # (option:[A-Z]) would later refuse.
    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=_choice_question()))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post(
            "/api/admin/v1/questions/1/options",
            json={"options": [{"key": "1", "text": "2"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


# ── POST /{id}/images ───────────────────────────────────────────────

def test_upload_question_image_stem(monkeypatch):
    q = _choice_question()
    captured: dict = {}

    async def _fake_upload(_file, _qid):
        return "http://x/static/question-assets/1/abc.png"

    def _fake_upsert_stem(content, url, replace_url=None):
        out = dict(content)
        out["render_mode"] = "segments"
        out["segments"] = [
            {"type": "text", "text": "题干"},
            {"type": "image", "url": url, "semantic_role": "content_image"},
        ]
        return out

    async def _fake_update(_db, _qid, data, _operator, _request):
        captured["data"] = data
        return q

    monkeypatch.setattr(admin_questions, "_upload_question_asset", _fake_upload)
    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=q))
    monkeypatch.setattr(admin_questions, "upsert_stem_image", _fake_upsert_stem)
    monkeypatch.setattr(admin_questions, "update_admin_question", _fake_update)
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post(
            "/api/admin/v1/questions/1/images",
            files={"file": ("q.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
            data={"target": "stem"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    # image_url recomputed from the new content segment and patched together with content
    assert captured["data"].content["render_mode"] == "segments"
    assert captured["data"].image_url == ["http://x/static/question-assets/1/abc.png"]


def test_upload_question_image_option(monkeypatch):
    q = _choice_question()

    async def _fake_upload(_file, _qid):
        return "http://x/static/question-assets/1/opt.png"

    def _fake_upsert_option(options, key, url, replace_url=None):
        return {**options, key: {"text": "1", "segments": [{"type": "image", "url": url}]}}

    monkeypatch.setattr(admin_questions, "_upload_question_asset", _fake_upload)
    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=q))
    monkeypatch.setattr(admin_questions, "upsert_option_image", _fake_upsert_option)
    monkeypatch.setattr(admin_questions, "update_admin_question", AsyncMock(return_value=q))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post(
            "/api/admin/v1/questions/1/images",
            files={"file": ("o.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
            data={"target": "option:A"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


def test_upload_question_image_rejects_non_image(monkeypatch):
    # F7: 先校验题目存在/权限，再校验文件类型 —— 因此需 mock 一个合法题目，
    # 才能走到 _upload_question_asset 的非图片拒绝路径。
    q = _choice_question()
    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=q))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post(
            "/api/admin/v1/questions/1/images",
            files={"file": ("a.txt", b"not an image", "text/plain")},
            data={"target": "stem"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400


def test_upload_question_image_rejects_bad_target(monkeypatch):
    monkeypatch.setattr(admin_questions, "_upload_question_asset", AsyncMock())
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post(
            "/api/admin/v1/questions/1/images",
            files={"file": ("q.png", b"x", "image/png")},
            data={"target": "option:1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400


def test_upload_question_image_cleans_up_on_generic_db_error(monkeypatch):
    # A non-ValueError/PermissionError failure during the DB write must still
    # orphan-clean the just-uploaded file before re-raising.
    q = _choice_question()
    monkeypatch.setattr(
        admin_questions, "_upload_question_asset",
        AsyncMock(return_value="http://x/static/question-assets/1/abc.png"),
    )
    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=q))

    async def _boom(_db, _qid, _data, _operator, _request):
        raise RuntimeError("db boom")

    monkeypatch.setattr(admin_questions, "update_admin_question", _boom)
    cleanup = AsyncMock()
    monkeypatch.setattr(admin_questions, "delete_question_asset_if_orphan", cleanup)
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        with pytest.raises(RuntimeError):
            client.post(
                "/api/admin/v1/questions/1/images",
                files={"file": ("q.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
                data={"target": "stem"},
            )
    finally:
        app.dependency_overrides.clear()

    cleanup.assert_awaited_once()


# ── DELETE /{id}/images ─────────────────────────────────────────────

def test_delete_question_image_stem(monkeypatch):
    q = _choice_question()
    q.content = {
        "text": "题干",
        "render_mode": "segments",
        "segments": [{"type": "text", "text": "题干"}, {"type": "image", "url": "http://x/static/question-assets/1/abc.png"}],
    }
    captured: dict = {}

    async def _fake_update(_db, _qid, data, _operator, _request):
        captured["data"] = data
        return q

    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=q))
    monkeypatch.setattr(admin_questions, "remove_stem_image", lambda content, url: {**content, "segments": [{"type": "text", "text": "题干"}]})
    monkeypatch.setattr(admin_questions, "update_admin_question", _fake_update)
    monkeypatch.setattr(admin_questions, "delete_question_asset_if_orphan", AsyncMock())
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.request(
            "DELETE",
            "/api/admin/v1/questions/1/images",
            json={"target": "stem", "url": "http://x/static/question-assets/1/abc.png"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    # image_url recomputed to None (no image segments remain)
    assert captured["data"].image_url is None


def test_delete_question_image_option(monkeypatch):
    q = _choice_question()
    q.options = {"A": {"text": "1", "segments": [{"type": "image", "url": "http://x/static/question-assets/1/opt.png"}]}}
    monkeypatch.setattr(admin_questions, "get_admin_question", AsyncMock(return_value=q))
    monkeypatch.setattr(admin_questions, "remove_option_image", lambda options, key, url: {"A": "1"})
    monkeypatch.setattr(admin_questions, "update_admin_question", AsyncMock(return_value=q))
    monkeypatch.setattr(admin_questions, "delete_question_asset_if_orphan", AsyncMock())
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.request(
            "DELETE",
            "/api/admin/v1/questions/1/images",
            json={"target": "option:A", "url": "http://x/static/question-assets/1/opt.png"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


def test_delete_question_image_requires_permission():
    resp = client.request("DELETE", "/api/admin/v1/questions/1/images", json={"target": "stem", "url": "http://x/a.png"})

    assert resp.status_code in {401, 403}
