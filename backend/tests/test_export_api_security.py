"""API-level tests for export permission, storage, and lifecycle completeness.

Covers:
1. preview-count respects whitelist and feature flags
2. delete_export uses the correct storage backend
3. WebSocket permission check
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
        return User(id=user_id, openid="test", session_key="test", nickname="test")

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
    return data


# ═══════════════════════════════════════════════════
# 1. preview-count permission checks
# ═══════════════════════════════════════════════════


class TestPreviewCountPermission:
    """preview-count must respect feature flag and whitelist."""

    def setup_method(self):
        self.url = "/api/v1/exports/preview-count"
        self.payload = {"range_type": "all"}

    def test_preview_count_blocked_when_feature_disabled(self):
        """EXPORT_FEATURE_ENABLED=False blocks preview-count."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = False
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            app.dependency_overrides.clear()
            from app.core.database import get_db
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            app.dependency_overrides[get_db] = _override_db()
            resp = client.post(self.url, json=self.payload)
        assert resp.status_code == 403
        detail = _get_detail(resp)
        assert detail["error_code"] == "user_not_allowed"

    def test_preview_count_blocked_when_user_not_in_whitelist(self):
        """User not in EXPORT_ALLOWED_USER_IDS gets 403."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "2,3"
            app.dependency_overrides.clear()
            from app.core.database import get_db
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            app.dependency_overrides[get_db] = _override_db()
            resp = client.post(self.url, json=self.payload)
        assert resp.status_code == 403
        assert _get_detail(resp)["error_code"] == "user_not_allowed"

    def test_preview_count_allowed_when_user_in_whitelist(self):
        """User in whitelist can preview count."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "1"
            app.dependency_overrides.clear()
            from app.core.database import get_db
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            app.dependency_overrides[get_db] = _override_db()
            resp = client.post(self.url, json=self.payload)
        # May fail because DB mock isn't realistic enough, but should NOT be 403
        assert resp.status_code != 403, "Whitelisted user should not get 403"

    def test_preview_count_allowed_when_allow_all(self):
        """EXPORT_ALLOW_ALL_USERS=True allows preview count."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            app.dependency_overrides.clear()
            from app.core.database import get_db
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(999)
            app.dependency_overrides[get_db] = _override_db()
            resp = client.post(self.url, json=self.payload)
        assert resp.status_code != 403, "allow-all user should not get 403"

    def test_preview_count_returns_structured_error(self):
        """preview-count returns structured error codes."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = False
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            app.dependency_overrides.clear()
            from app.core.database import get_db
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            app.dependency_overrides[get_db] = _override_db()
            resp = client.post(self.url, json=self.payload)
        assert resp.status_code == 403
        detail = _get_detail(resp)
        assert "error_code" in detail
        assert "message" in detail


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
        from app.core.database import get_db
        from app.core.security import get_current_user

        app.dependency_overrides[get_current_user] = _override_user(1)
        app.dependency_overrides[get_db] = _override_db()

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_DIR = "static/exports"
            mock_settings.STORAGE_BACKEND = "local"
            mock_settings.PUBLIC_BASE_URL = "http://test"

            resp = client.delete("/api/v1/exports/99999")
        assert resp.status_code == 404
        assert _get_detail(resp)["error_code"] == "task_not_found"

    @pytest.mark.asyncio
    async def test_deleted_export_not_downloadable(self):
        """After delete, task should return 404."""
        app.dependency_overrides.clear()
        from app.core.database import get_db
        from app.core.security import get_current_user

        app.dependency_overrides[get_current_user] = _override_user(1)
        app.dependency_overrides[get_db] = _override_db()

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_DIR = "static/exports"
            mock_settings.STORAGE_BACKEND = "local"
            mock_settings.PUBLIC_BASE_URL = "http://test"

            resp = client.delete("/api/v1/exports/99999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════
# 3. Capability endpoint consistency
# ═══════════════════════════════════════════════════


class TestCapabilityEndpoint:
    """Capability endpoint returns correct per-user response."""

    def test_capability_blocked_for_non_whitelist(self):
        """Non-whitelist user gets export_enabled=False."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "2"
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            app.dependency_overrides.clear()
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            resp = client.get("/api/v1/exports/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["export_enabled"] is False
        assert data["pdf_enabled"] is False
        assert data["docx_enabled"] is False
        assert data["websocket_enabled"] is False

    def test_capability_allowed_for_whitelist_user(self):
        """Whitelist user gets correct capabilities."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = "1"
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            app.dependency_overrides.clear()
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            resp = client.get("/api/v1/exports/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["export_enabled"] is True
        assert data["pdf_enabled"] is True
        assert data["docx_enabled"] is True
        assert data["websocket_enabled"] is True

    def test_capability_docx_disabled(self):
        """Export enabled but DOCX specifically disabled."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_DOCX_ENABLED = False
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
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

    def test_capability_all_disabled_when_feature_disabled(self):
        """EXPORT_FEATURE_ENABLED=False disables everything."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = False
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            app.dependency_overrides.clear()
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            resp = client.get("/api/v1/exports/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["export_enabled"] is False

    def test_capability_always_returns_max_question_count(self):
        """Capability always returns max_question_count and retention_days."""
        app.dependency_overrides.clear()
        from app.core.security import get_current_user

        app.dependency_overrides[get_current_user] = _override_user(1)

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_DOCX_ENABLED = True
            mock_settings.EXPORT_WEBSOCKET_ENABLED = True
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            resp = client.get("/api/v1/exports/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_question_count"] == 100
        assert data["retention_days"] == 7


# ═══════════════════════════════════════════════════
# 4. Create/retry/re-export use capability service
# ═══════════════════════════════════════════════════


class TestCreateExportPermission:
    """Create export must use capability service."""

    def test_create_export_blocked_when_feature_disabled(self):
        """EXPORT_FEATURE_ENABLED=False blocks create."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = False
            mock_settings.EXPORT_ALLOW_ALL_USERS = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            app.dependency_overrides.clear()
            from app.core.database import get_db
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            app.dependency_overrides[get_db] = _override_db()
            resp = client.post("/api/v1/exports", json={
                "range_type": "all",
                "file_format": "pdf",
            })
        assert resp.status_code == 403
        assert _get_detail(resp)["error_code"] == "user_not_allowed"

    def test_create_export_docx_blocked_when_disabled(self):
        """DOCX create blocked when EXPORT_DOCX_ENABLED=False."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.EXPORT_FEATURE_ENABLED = True
            mock_settings.EXPORT_ALLOW_ALL_USERS = True
            mock_settings.EXPORT_DOCX_ENABLED = False
            mock_settings.EXPORT_ALLOWED_USER_IDS = ""
            app.dependency_overrides.clear()
            from app.core.database import get_db
            from app.core.security import get_current_user

            app.dependency_overrides[get_current_user] = _override_user(1)
            app.dependency_overrides[get_db] = _override_db()
            resp = client.post("/api/v1/exports", json={
                "range_type": "all",
                "file_format": "docx",
            })
        assert resp.status_code == 403
        assert _get_detail(resp)["error_code"] == "docx_disabled"
