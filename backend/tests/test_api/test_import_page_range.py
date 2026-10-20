"""PDF 指定页码范围导入 — API 集成测试。

使用 FastAPI TestClient 验证管理端和公共端上传接口的页码语义、
参数校验和错误响应。service 层被 mock 以隔离 API 路由/参数处理逻辑。
"""
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_imports
from app.api.v1 import imports as public_imports
from app.core import admin_security
from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.models.admin import AdminUser
from app.models.user import User
from app.schemas.import_review import PdfPageRangeInfo, PipelineUploadResponse

client = TestClient(app)


class _PermissionDb:
    def __init__(self, permissions=("import:write",)):
        self.permissions = permissions

    async def execute(self, statement):
        assert "permissions" in str(statement)
        assert statement.compile().params["role_id_1"] == 1
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: list(self.permissions)),
        )


@pytest.fixture(autouse=True)
def permission_cache_miss(monkeypatch):
    monkeypatch.setattr(admin_security, "_get_role_version", AsyncMock(return_value=None))


def _assert_safe_bad_request(response):
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "HTTP_400"
    assert error["message"] == "请求参数有误，请检查后重试"
    assert error["retryable"] is False
    assert error["request_id"]
    assert error["trace_id"]


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_mock_response(
    pipeline_id: str = "pl_test_mock",
    effective_start: int = 1,
    effective_end: int = 5,
    selected_page_count: int = 5,
    total_pages: int = 5,
) -> PipelineUploadResponse:
    return PipelineUploadResponse(
        pipeline_id=pipeline_id,
        status="queued",
        page_range=PdfPageRangeInfo(
            requested_start=effective_start,
            requested_end=effective_end,
            effective_start=effective_start,
            effective_end=effective_end,
            selected_page_count=selected_page_count,
            total_pages=total_pages,
        ),
    )


# ── auth / db overrides ─────────────────────────────────────────────────────


async def _app_user():
    return User(id=1, openid="dev_test_user")


async def _allow_admin():
    user = AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=1)
    return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})


def _setup_admin_auth():
    app.dependency_overrides[get_current_admin] = _allow_admin
    app.dependency_overrides[get_db] = lambda: _PermissionDb()


def _setup_app_auth():
    app.dependency_overrides[get_current_user] = _app_user


def _clear_overrides():
    app.dependency_overrides.clear()


# ── Admin endpoint: /api/admin/v1/imports/upload ────────────────────────────


class TestAdminUploadPageRange:
    def setup_method(self):
        _setup_admin_auth()
        self._mock_svc = AsyncMock()
        self._patcher = patch.object(admin_imports, "svc_start_import_pipeline", self._mock_svc)
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()
        _clear_overrides()

    def test_upload_with_page_range(self):
        """page_start=2&page_end=4 → service receives correct params."""
        self._mock_svc.return_value = _make_mock_response(
            effective_start=2, effective_end=4, selected_page_count=3, total_pages=5
        )
        resp = client.post(
            "/api/admin/v1/imports/upload?page_start=2&page_end=4&import_mode=book",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["status"] == "queued"
        pr = data.get("page_range")
        assert pr is not None, "response must include page_range"
        assert pr["effective_start"] == 2
        assert pr["effective_end"] == 4
        assert pr["selected_page_count"] == 3
        assert pr["total_pages"] == 5

        # Verify service was called with correct args
        self._mock_svc.assert_awaited_once()
        _call_kwargs = self._mock_svc.await_args[1]
        assert _call_kwargs["page_start"] == 2
        assert _call_kwargs["page_end"] == 4
        assert _call_kwargs["filename"].endswith(".pdf")

    def test_upload_full_pdf_default_range(self):
        """No page range → service receives page_start=None, page_end=None."""
        self._mock_svc.return_value = _make_mock_response()
        resp = client.post(
            "/api/admin/v1/imports/upload?import_mode=book",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        )
        assert resp.status_code == 200
        self._mock_svc.assert_awaited_once()
        _call_kwargs = self._mock_svc.await_args[1]
        assert _call_kwargs["page_start"] is None
        assert _call_kwargs["page_end"] is None

    def test_non_pdf_with_page_range_returns_400(self):
        """Image with page_start → service raises ValueError → API 400."""
        self._mock_svc.side_effect = ValueError("page_start/page_end 仅适用于 PDF 文件")
        resp = client.post(
            "/api/admin/v1/imports/upload?page_start=1&import_mode=book",
            files={"file": ("test.jpg", io.BytesIO(b"fake image"), "image/jpeg")},
        )
        _assert_safe_bad_request(resp)
        assert "仅适用于 PDF" not in resp.text
        self._mock_svc.assert_awaited_once()

    def test_service_value_error_returns_400(self):
        """Any ValueError from service → 400."""
        self._mock_svc.side_effect = ValueError("page_start=0 无效")
        resp = client.post(
            "/api/admin/v1/imports/upload?page_start=0&page_end=3&import_mode=book",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        _assert_safe_bad_request(resp)
        assert "page_start" not in resp.text
        self._mock_svc.assert_awaited_once()

    def test_upload_without_permission_never_calls_service(self):
        app.dependency_overrides[get_db] = lambda: _PermissionDb(())
        resp = client.post(
            "/api/admin/v1/imports/upload",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert resp.status_code == 403
        self._mock_svc.assert_not_awaited()


# ── Public endpoint: /api/v1/import/pipeline/upload ─────────────────────────


class TestPublicUploadPageRange:
    def setup_method(self):
        _setup_app_auth()
        self._mock_svc = AsyncMock()
        self._patcher = patch.object(public_imports, "svc_start_import_pipeline", self._mock_svc)
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()
        _clear_overrides()

    def test_public_upload_with_page_range(self):
        """Public endpoint: page_start=3&page_end=5 → service receives correctly."""
        self._mock_svc.return_value = _make_mock_response(
            effective_start=3, effective_end=5, selected_page_count=3, total_pages=5
        )
        resp = client.post(
            "/api/v1/import/pipeline/upload?page_start=3&page_end=5&import_mode=book",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        pr = data.get("page_range")
        assert pr is not None
        assert pr["effective_start"] == 3
        assert pr["effective_end"] == 5
        assert pr["selected_page_count"] == 3

        self._mock_svc.assert_awaited_once()
        _call_kwargs = self._mock_svc.await_args[1]
        assert _call_kwargs["page_start"] == 3
        assert _call_kwargs["page_end"] == 5

    def test_public_upload_non_pdf_with_page_range_returns_400(self):
        """Public endpoint: image with page_start → 400."""
        self._mock_svc.side_effect = ValueError("page_start/page_end 仅适用于 PDF 文件")
        resp = client.post(
            "/api/v1/import/pipeline/upload?page_start=1",
            files={"file": ("test.jpg", io.BytesIO(b"fake image"), "image/jpeg")},
        )
        _assert_safe_bad_request(resp)
        assert "仅适用于 PDF" not in resp.text
        self._mock_svc.assert_awaited_once()

    def test_public_upload_no_page_range_ok(self):
        """Public endpoint: no page range → service called with None."""
        self._mock_svc.return_value = _make_mock_response()
        resp = client.post(
            "/api/v1/import/pipeline/upload?import_mode=book",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert resp.status_code == 200
        self._mock_svc.assert_awaited_once()
        _call_kwargs = self._mock_svc.await_args[1]
        assert _call_kwargs["page_start"] is None
        assert _call_kwargs["page_end"] is None
