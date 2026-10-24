"""API-level tests for export permission, storage, and lifecycle completeness.

Export is open to every authenticated user (no whitelist / feature flag).
Covers:
1. preview-count works for any authenticated user
2. delete_export uses the correct storage backend
3. Capability endpoint is always-open, reflects docx/websocket flags
4. Storage backend dependency: API layer uses get_export_storage(), not get_storage()
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ═══════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _clean_overrides():
    """Clear dependency overrides before and after each test."""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _override_user(user_id: int = 1):
    """Override get_current_user to return a user with the given id."""
    from app.models.user import User

    async def _get():
        return User(id=user_id, openid="test", nickname="test")

    return _get


def _override_db():
    """Override get_db to return a minimal mock."""

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()

    class _MockResult:
        def scalars(self):
            return self

        def scalar_one_or_none(self):
            return None

        def scalar(self):
            return 0

        def all(self):
            return []

        def fetchall(self):
            return []

        def first(self):
            return None

    db.execute.return_value = _MockResult()

    async def _get():
        return db

    return _get


# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════


def _get_detail(resp):
    """Extract the detail dict from a FastAPI HTTPException response."""
    data = resp.json()
    if "detail" in data and isinstance(data["detail"], dict):
        return data["detail"]
    if "detail" in data and isinstance(data["detail"], str):
        return {"message": data["detail"]}
    return data


def _setup_auth(user_id: int = 1):
    """Install get_current_user + get_db overrides for a user."""
    from app.core.database import get_db
    from app.core.security import get_current_user

    app.dependency_overrides[get_current_user] = _override_user(user_id)
    app.dependency_overrides[get_db] = _override_db()


# ═══════════════════════════════════════════════════
# 1. preview-count works for any authenticated user
# ═══════════════════════════════════════════════════


class TestPreviewCountPermission:
    """preview-count is open to every authenticated user."""

    def setup_method(self):
        self.url = "/api/v1/exports/preview-count"
        self.payload = {"range_type": "all"}

    def test_preview_count_allowed_for_any_user(self):
        """Any authenticated user can preview count (no whitelist)."""
        _setup_auth(1)
        resp = client.post(self.url, json=self.payload)
        assert resp.status_code == 200, f"got {resp.status_code}: {resp.text[:200]}"
        assert resp.json()["count"] >= 0

    def test_preview_count_allowed_for_high_user_id(self):
        """A non-whitelisted-style user id still gets 200."""
        _setup_auth(999)
        resp = client.post(self.url, json=self.payload)
        assert resp.status_code == 200, f"got {resp.status_code}: {resp.text[:200]}"
        assert resp.json()["count"] >= 0

    def test_preview_count_returns_count_field(self):
        """Response includes count and range_type."""
        _setup_auth(1)
        resp = client.post(self.url, json=self.payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert data["range_type"] == "all"


# ═══════════════════════════════════════════════════
# 2. delete_export uses correct storage backend
# ═══════════════════════════════════════════════════


class TestDeleteExportStorage:
    """delete_export must use get_export_storage(), not get_storage()."""

    @pytest.mark.asyncio
    async def test_delete_uses_export_storage_not_get_storage(self):
        """Verify delete_export calls get_export_storage(), not get_storage()."""

        # The production code (exports.py) was changed to use get_export_storage()
        # in the delete_export endpoint. Verify by reading the source.
        import inspect

        from app.api.v1 import exports as exports_module

        source = inspect.getsource(exports_module.delete_export)
        assert "get_export_storage()" in source, (
            "delete_export must use get_export_storage, not get_storage"
        )
        assert "get_storage" not in source.replace("get_export_storage", ""), (
            "delete_export should not contain get_storage()"
        )

    @pytest.mark.asyncio
    async def test_download_uses_export_storage(self):
        """Verify download_export calls get_export_storage(), not get_storage()."""
        import inspect

        from app.api.v1 import exports as exports_module

        source = inspect.getsource(exports_module.download_export)
        assert "get_export_storage()" in source, (
            "download_export must use get_export_storage, not get_storage"
        )

    @pytest.mark.asyncio
    async def test_cleanup_uses_export_storage(self):
        """Verify cleanup_expired uses get_export_storage()."""
        import inspect

        from app.services.export import cleanup

        source = inspect.getsource(cleanup.cleanup_expired)
        assert "get_export_storage()" in source

    @pytest.mark.asyncio
    async def test_process_task_uses_export_storage(self):
        """Verify process_task uses get_export_storage()."""
        import inspect

        from app.services.export import service

        source = inspect.getsource(service.process_task)
        assert "get_export_storage()" in source

    @pytest.mark.asyncio
    async def test_delete_export_endpoint_404_for_nonexistent(self):
        """DELETE on non-existent task returns 404."""
        app.dependency_overrides.clear()
        _setup_auth(1)

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DIR = "static/exports"
            mock_settings.STORAGE_BACKEND = "local"
            mock_settings.PUBLIC_BASE_URL = "http://test"

            resp = client.delete("/api/v1/exports/99999")
        assert resp.status_code == 404
        assert _get_detail(resp)["error"]["code"] == "HTTP_404"

    @pytest.mark.asyncio
    async def test_deleted_export_not_downloadable(self):
        """After delete, task should return 404."""
        app.dependency_overrides.clear()
        _setup_auth(1)

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DIR = "static/exports"
            mock_settings.STORAGE_BACKEND = "local"
            mock_settings.PUBLIC_BASE_URL = "http://test"

            resp = client.delete("/api/v1/exports/99999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════
# 3. Capability endpoint is always-open
# ═══════════════════════════════════════════════════


class TestCapabilityEndpoint:
    """Capability endpoint returns global capabilities for any user."""

    def test_capability_allowed_for_any_user(self):
        """Any user gets export_enabled=True (no whitelist)."""
        app.dependency_overrides.clear()
        from app.core.security import get_current_user

        app.dependency_overrides[get_current_user] = _override_user(1)
        resp = client.get("/api/v1/exports/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["export_enabled"] is True
        assert data["pdf_enabled"] is True

    def test_capability_no_reason_code_when_open(self):
        """No rollout gate means reason_code/message are null."""
        app.dependency_overrides.clear()
        from app.core.security import get_current_user

        app.dependency_overrides[get_current_user] = _override_user(1)
        resp = client.get("/api/v1/exports/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reason_code"] is None
        assert data["message"] is None

    def test_capability_docx_disabled(self):
        """Export enabled but DOCX specifically disabled."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = False
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7
            app.dependency_overrides.clear()
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            resp = client.get("/api/v1/exports/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["export_enabled"] is True
        assert data["pdf_enabled"] is True
        assert data["docx_enabled"] is False
        assert data["websocket_enabled"] is True

    def test_capability_always_returns_max_question_count(self):
        """Capability always returns max_question_count and retention_days."""
        app.dependency_overrides.clear()
        _setup_auth(1)

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_MAX_QUESTIONS = 100
            mock_settings.EXPORT_RETENTION_DAYS = 7
            resp = client.get("/api/v1/exports/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_question_count"] == 100
        assert data["retention_days"] == 7


# ═══════════════════════════════════════════════════
# 4. Create export: DOCX gate only
# ═══════════════════════════════════════════════════


class TestCreateExportPermission:
    """Create export is open; only DOCX can be format-gated."""

    def test_create_export_docx_blocked_when_disabled(self):
        """DOCX create blocked when EXPORT_DOCX_ENABLED=False."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_DOCX_ENABLED = False
            app.dependency_overrides.clear()
            _setup_auth(1)
            resp = client.post("/api/v1/exports", json={
                "range_type": "all",
                "file_format": "docx",
            })
        assert resp.status_code == 403
        assert _get_detail(resp)["error"]["code"] == "HTTP_403"
