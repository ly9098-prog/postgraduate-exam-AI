"""Tests for readiness probe, production config validator, and role lifecycle.

Covers Batch 8 checks:
- Enhanced _check_role_deps() — real web/worker/scheduler deps
- OCR readiness hysteresis — degraded vs unavailable
- Queue health — Redis error = unavailable (not degraded) in production
- Staging space reporting
- Worker scratch dir validation
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.production_config_validator import (
    _check_worker_scratch_dir,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolate_ocr_hysteresis(monkeypatch):
    import app.main

    monkeypatch.setattr(app.main, "_ocr_remote_consecutive_failures", 0)


# ══════════════════════════════════════════════════════════════════════════════
# _check_worker_scratch_dir
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckWorkerScratchDir:
    """WORKER_SCRATCH_DIR must be set, not pointing to temp dir, and writable."""

    def test_scratch_dir_not_set(self):
        """When WORKER_SCRATCH_DIR is empty, an error is appended."""
        errors: list[str] = []
        with patch("app.services.production_config_validator.settings") as mock_settings:
            mock_settings.PROCESS_ROLE = "worker"
            mock_settings.WORKER_SCRATCH_DIR = ""
            _check_worker_scratch_dir(errors)
        assert any("WORKER_SCRATCH_DIR 未设置" in e for e in errors), errors

    def test_scratch_dir_is_tempdir(self, tmp_path):
        """When WORKER_SCRATCH_DIR points to the system temp dir, an error is appended."""
        import tempfile
        errors: list[str] = []
        with patch("app.services.production_config_validator.settings") as mock_settings:
            mock_settings.PROCESS_ROLE = "worker"
            mock_settings.WORKER_SCRATCH_DIR = tempfile.gettempdir()
            _check_worker_scratch_dir(errors)
        assert any("临时目录" in e for e in errors), errors

    def test_scratch_dir_valid(self, tmp_path):
        """A valid, writable scratch dir produces no errors."""
        scratch = str(tmp_path / "worker_scratch")
        errors: list[str] = []
        with patch("app.services.production_config_validator.settings") as mock_settings:
            mock_settings.PROCESS_ROLE = "worker"
            mock_settings.WORKER_SCRATCH_DIR = scratch
            _check_worker_scratch_dir(errors)
        assert len(errors) == 0, errors

    def test_scratch_dir_not_writable(self):
        """A non-writable scratch dir produces an error."""
        scratch = "/proc/readonly_scratch"
        errors: list[str] = []
        with patch("app.services.production_config_validator.settings") as mock_settings:
            mock_settings.PROCESS_ROLE = "worker"
            mock_settings.WORKER_SCRATCH_DIR = scratch
            _check_worker_scratch_dir(errors)
        assert any("不可写" in e or "检查失败" in e for e in errors), errors


# ══════════════════════════════════════════════════════════════════════════════
# _check_role_deps
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestCheckRoleDeps:
    """Role-specific dependency checks must reflect actual process state."""

    @staticmethod
    def _import_check_role_deps():
        """Import the module-level function lazily to avoid startup side effects."""
        from app.main import _check_role_deps
        return _check_role_deps

    async def test_web_role_ok(self):
        """Web role should pass deps check by default."""
        check = self._import_check_role_deps()
        with patch("app.main.settings") as mock_settings:
            mock_settings.PROCESS_ROLE = "web"
            result = await check()
        assert result is True

    async def test_web_role_cloud_with_paddle_fails(self):
        """Web role with cloud_api and paddle in sys.modules must fail."""
        check = self._import_check_role_deps()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.core.ocr_isolation.detect_deployment_profile") as mock_profile,
        ):
            mock_settings.PROCESS_ROLE = "web"
            mock_profile.return_value = "cloud_api"
            with patch.dict(sys.modules, {"paddle": MagicMock()}):
                result = await check()
        assert result is False

    async def test_worker_role_ok(self):
        """Worker role should pass deps check by default."""
        check = self._import_check_role_deps()
        with patch("app.main.settings") as mock_settings:
            mock_settings.PROCESS_ROLE = "worker"
            with patch("app.services.task_queue_worker.is_draining_v2", return_value=False):
                result = await check()
        assert result is True

    async def test_worker_role_draining_fails(self):
        """Worker role with draining flag must fail."""
        check = self._import_check_role_deps()
        with patch("app.main.settings") as mock_settings:
            mock_settings.PROCESS_ROLE = "worker"
            with patch("app.services.task_queue_worker.is_draining_v2", return_value=True):
                result = await check()
        assert result is False

    async def test_worker_role_cloud_local_process_fails(self):
        """Worker with cloud_api + local_process OCR must fail."""
        check = self._import_check_role_deps()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.core.ocr_isolation.detect_deployment_profile") as mock_profile,
            patch("app.services.task_queue_worker.is_draining_v2", return_value=False),
        ):
            mock_settings.PROCESS_ROLE = "worker"
            mock_settings.OCR_EXECUTION_BACKEND = "local_process"
            mock_profile.return_value = "cloud_api"
            result = await check()
        assert result is False

    async def test_scheduler_role_audit_running_ok(self):
        """Scheduler role with audit cleanup running passes."""
        check = self._import_check_role_deps()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.services.audit_cleanup_scheduler.audit_log_cleanup_scheduler") as mock_audit,
        ):
            mock_settings.PROCESS_ROLE = "scheduler"
            mock_settings.AUDIT_LOG_CLEANUP_ENABLED = True
            mock_settings.RECOMMENDATION_METRICS_AGG_ENABLED = False
            mock_audit._running = True
            result = await check()
        assert result is True

    async def test_scheduler_role_audit_not_running_fails(self):
        """Scheduler role with audit enabled but not running must fail."""
        check = self._import_check_role_deps()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.services.audit_cleanup_scheduler.audit_log_cleanup_scheduler") as mock_audit,
        ):
            mock_settings.PROCESS_ROLE = "scheduler"
            mock_settings.AUDIT_LOG_CLEANUP_ENABLED = True
            mock_settings.RECOMMENDATION_METRICS_AGG_ENABLED = False
            mock_audit._running = False
            result = await check()
        assert result is False

    async def test_scheduler_role_audit_disabled_passes(self):
        """Scheduler role with audit cleanup disabled passes."""
        check = self._import_check_role_deps()
        with patch("app.main.settings") as mock_settings:
            mock_settings.PROCESS_ROLE = "scheduler"
            mock_settings.AUDIT_LOG_CLEANUP_ENABLED = False
            mock_settings.RECOMMENDATION_METRICS_AGG_ENABLED = False
            result = await check()
        assert result is True

    @pytest.mark.parametrize("running", [False, True])
    async def test_scheduler_requires_enabled_recommendation_loop(self, running):
        check = self._import_check_role_deps()
        with (
            patch("app.main.settings") as mock_settings,
            patch(
                "app.services.recommendation_metrics_scheduler.recommendation_metrics_scheduler"
            ) as mock_recommendation,
        ):
            mock_settings.PROCESS_ROLE = "scheduler"
            mock_settings.AUDIT_LOG_CLEANUP_ENABLED = False
            mock_settings.RECOMMENDATION_METRICS_AGG_ENABLED = True
            mock_recommendation._running = running
            assert await check() is running

    async def test_unknown_role_fails(self):
        """Unknown PROCESS_ROLE must fail the probe."""
        check = self._import_check_role_deps()
        with patch("app.main.settings") as mock_settings:
            mock_settings.PROCESS_ROLE = "unknown_role_xyz"
            result = await check()
        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# _check_ocr_config
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestCheckOcrConfig:
    """OCR config checks with hysteresis for remote connectivity."""

    @staticmethod
    def _import_check_ocr_config():
        from app.main import _check_ocr_config
        return _check_ocr_config

    async def test_ocr_disabled_returns_none(self):
        """When OCR_ENABLED is False, returns None (not checked)."""
        check = self._import_check_ocr_config()
        with patch("app.main.settings") as mock_settings:
            mock_settings.OCR_ENABLED = False
            result = await check()
        assert result is None

    async def test_local_process_cloud_unavailable(self):
        """local_process backend in cloud returns 'unavailable'."""
        check = self._import_check_ocr_config()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.core.ocr_isolation.detect_deployment_profile", return_value="cloud_api"),
        ):
            mock_settings.OCR_ENABLED = True
            mock_settings.OCR_EXECUTION_BACKEND = "local_process"
            mock_settings.OCR_USE_GPU = False
            result = await check()
        assert result == "unavailable"

    async def test_missing_token_cloud_unavailable(self):
        """Missing OCR_REMOTE_TOKEN in cloud paddlex_http returns 'unavailable'."""
        check = self._import_check_ocr_config()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.core.ocr_isolation.detect_deployment_profile", return_value="cloud_api"),
        ):
            mock_settings.OCR_ENABLED = True
            mock_settings.OCR_EXECUTION_BACKEND = "paddlex_http"
            mock_settings.OCR_REMOTE_TOKEN = ""
            mock_settings.OCR_USE_GPU = False
            result = await check()
        assert result == "unavailable"

    async def test_config_errors_dev_degraded(self):
        """Config issues in development return 'degraded', not 'unavailable'."""
        check = self._import_check_ocr_config()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.core.ocr_isolation.detect_deployment_profile", return_value="local_import"),
        ):
            mock_settings.OCR_ENABLED = True
            mock_settings.OCR_EXECUTION_BACKEND = "local_process"
            mock_settings.OCR_USE_GPU = True
            result = await check()
        assert result == "degraded"

    async def test_remote_connectivity_three_failures_degraded(self):
        """3 consecutive remote check failures returns 'degraded'."""
        check = self._import_check_ocr_config()
        import app.main
        app.main._ocr_remote_consecutive_failures = 2

        with (
            patch("app.main.settings") as mock_settings,
            patch("app.main._check_ocr_remote_connectivity", return_value=False),
            patch("app.core.ocr_isolation.detect_deployment_profile", return_value="local_import"),
        ):
            mock_settings.OCR_ENABLED = True
            mock_settings.OCR_EXECUTION_BACKEND = "paddlex_http"
            mock_settings.OCR_REMOTE_TOKEN = "test-token"
            mock_settings.OCR_USE_GPU = False
            result = await check()
        assert result == "degraded"

    async def test_remote_connectivity_recovers(self):
        """After 3 failures, 1 success resets counter and returns 'ok'."""
        check = self._import_check_ocr_config()
        import app.main
        app.main._ocr_remote_consecutive_failures = 3

        with (
            patch("app.main.settings") as mock_settings,
            patch("app.main._check_ocr_remote_connectivity", return_value=True),
            patch("app.core.ocr_isolation.detect_deployment_profile", return_value="local_import"),
        ):
            mock_settings.OCR_ENABLED = True
            mock_settings.OCR_EXECUTION_BACKEND = "paddlex_http"
            mock_settings.OCR_REMOTE_TOKEN = "test-token"
            mock_settings.OCR_USE_GPU = False
            result = await check()
        assert result == "ok"
        assert app.main._ocr_remote_consecutive_failures == 0

    async def test_remote_connectivity_one_failure_still_ok(self):
        """1 remote failure (below threshold) still returns 'ok'."""
        check = self._import_check_ocr_config()
        import app.main
        app.main._ocr_remote_consecutive_failures = 0

        with (
            patch("app.main.settings") as mock_settings,
            patch("app.main._check_ocr_remote_connectivity", return_value=False),
            patch("app.core.ocr_isolation.detect_deployment_profile", return_value="local_import"),
        ):
            mock_settings.OCR_ENABLED = True
            mock_settings.OCR_EXECUTION_BACKEND = "paddlex_http"
            mock_settings.OCR_REMOTE_TOKEN = "test-token"
            mock_settings.OCR_USE_GPU = False
            result = await check()
        assert result == "ok"
        assert app.main._ocr_remote_consecutive_failures == 1

    async def test_paddle_modules_cloud_unavailable(self):
        """Local paddle OCR modules in sys.modules under cloud returns 'unavailable'."""
        check = self._import_check_ocr_config()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.core.ocr_isolation.detect_deployment_profile", return_value="cloud_api"),
            patch.dict(sys.modules, {"paddleocr": MagicMock()}),
        ):
            mock_settings.OCR_ENABLED = True
            mock_settings.OCR_EXECUTION_BACKEND = "paddlex_http"
            mock_settings.OCR_REMOTE_TOKEN = "test-token"
            mock_settings.OCR_USE_GPU = False
            result = await check()
        assert result == "unavailable"


# ══════════════════════════════════════════════════════════════════════════════
# check_queue
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestCheckQueue:
    """Queue health check must report unavailable (not degraded) on Redis error."""

    @staticmethod
    def _import_check_queue():
        import app.main

        return lambda: app.main.check_queue(
            redis_url=app.main.settings.REDIS_URL,
            production_mode=app.main._production_mode,
        )

    async def test_no_redis_returns_none(self):
        """Without REDIS_URL, returns None (queue not relevant)."""
        check = self._import_check_queue()
        with patch("app.main.settings") as mock_settings:
            mock_settings.REDIS_URL = ""
            result = await check()
        assert result is None

    async def test_redis_error_production_unavailable(self):
        """Redis error in production returns 'unavailable'."""
        check = self._import_check_queue()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.main._production_mode", True),
            patch("app.services.task_queue_service.task_queue") as mock_queue,
        ):
            mock_settings.REDIS_URL = "redis://localhost:6379"
            mock_settings.APP_ENV = "production"
            mock_queue.ready_length_v2 = AsyncMock(side_effect=Exception("Redis connection refused"))
            mock_queue.processing_length_v2 = AsyncMock(side_effect=Exception("Redis connection refused"))
            result = await check()
        assert result == "unavailable"

    async def test_redis_error_dev_degraded(self):
        """Redis error in development returns 'degraded' (non-critical for dev)."""
        check = self._import_check_queue()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.main._production_mode", False),
            patch("app.services.task_queue_service.task_queue") as mock_queue,
        ):
            mock_settings.REDIS_URL = "redis://localhost:6379"
            mock_settings.APP_ENV = "development"
            mock_queue.ready_length_v2 = AsyncMock(side_effect=Exception("Redis connection refused"))
            mock_queue.processing_length_v2 = AsyncMock(side_effect=Exception("Redis connection refused"))
            result = await check()
        assert result == "degraded"

    async def test_queue_ok_below_threshold(self):
        """Queue depth below 100 returns 'ok'."""
        check = self._import_check_queue()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.services.task_queue_service.task_queue") as mock_queue,
        ):
            mock_settings.REDIS_URL = "redis://localhost:6379"
            mock_settings.APP_ENV = "production"
            mock_queue.ready_length_v2 = AsyncMock(return_value=5)
            mock_queue.processing_length_v2 = AsyncMock(return_value=3)
            result = await check()
        assert result == "ok"

    async def test_queue_degraded_above_threshold(self):
        """Queue depth above 100 returns 'degraded'."""
        check = self._import_check_queue()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.services.task_queue_service.task_queue") as mock_queue,
        ):
            mock_settings.REDIS_URL = "redis://localhost:6379"
            mock_settings.APP_ENV = "production"
            mock_queue.ready_length_v2 = AsyncMock(return_value=80)
            mock_queue.processing_length_v2 = AsyncMock(return_value=40)
            result = await check()
        assert result == "degraded"

    @pytest.mark.parametrize("depth,expected", [(100, "ok"), (101, "degraded")])
    async def test_queue_threshold_uses_all_three_v2_task_types(self, depth, expected):
        check = self._import_check_queue()
        with (
            patch("app.main.settings") as mock_settings,
            patch("app.services.task_queue_service.task_queue") as mock_queue,
        ):
            mock_settings.REDIS_URL = "redis://synthetic:6379"
            mock_queue.ready_length_v2 = AsyncMock(side_effect=[depth, 0, 0])
            mock_queue.processing_length_v2 = AsyncMock(return_value=0)
            assert await check() == expected
        task_types = ["import_pipeline", "image_pipeline", "excel_pipeline"]
        assert [args.args[0] for args in mock_queue.ready_length_v2.await_args_list] == task_types
        assert [args.args[0] for args in mock_queue.processing_length_v2.await_args_list] == task_types


# ══════════════════════════════════════════════════════════════════════════════
# check_staging_space
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestCheckStagingSpace:
    """Staging space check must return dict with free/total/used_percent."""

    @staticmethod
    def _import_check_staging_space():
        from app.main import check_staging_space
        return check_staging_space

    async def test_returns_dict_with_keys(self, tmp_path):
        """The staging space check returns a dict with expected keys."""
        check = self._import_check_staging_space()
        with (
            patch("app.services.staging_storage._STAGING_DIR", tmp_path),
            patch("app.main.os.statvfs", return_value=SimpleNamespace(
                f_frsize=100, f_bavail=10, f_blocks=40,
            )) as statvfs,
        ):
            result = await check()
        statvfs.assert_called_once_with(str(tmp_path))
        assert result == {
            "staging_free_bytes": 1000,
            "staging_total_bytes": 4000,
            "staging_used_percent": 75.0,
        }

    async def test_empty_on_error(self):
        """When statvfs fails, returns empty dict."""
        check = self._import_check_staging_space()
        with (
            patch("app.services.staging_storage._STAGING_DIR"),
            patch("app.main.os.statvfs", side_effect=OSError("statvfs failed")),
        ):
            result = await check()
        assert result == {}


# ══════════════════════════════════════════════════════════════════════════════
# _check_ocr_remote_connectivity
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestCheckOcrRemoteConnectivity:
    """Lightweight OCR remote health check."""

    @staticmethod
    def _import_fn():
        from app.main import _check_ocr_remote_connectivity
        return _check_ocr_remote_connectivity

    async def test_ocr_disabled_returns_true(self):
        """When OCR is disabled, connectivity check trivially passes."""
        fn = self._import_fn()
        with patch("app.main.settings") as mock_settings:
            mock_settings.OCR_ENABLED = False
            result = await fn()
        assert result is True

    async def test_not_remote_backend_returns_true(self):
        """Non-remote backends trivially pass connectivity check."""
        fn = self._import_fn()
        with patch("app.main.settings") as mock_settings:
            mock_settings.OCR_ENABLED = True
            mock_settings.OCR_EXECUTION_BACKEND = "disabled"
            mock_settings.OCR_REMOTE_URL = ""
            result = await fn()
        assert result is True

    async def test_remote_unreachable_returns_false(self):
        """When remote OCR URL is unreachable, returns False."""
        fn = self._import_fn()
        with (
            patch("app.main.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.OCR_ENABLED = True
            mock_settings.OCR_EXECUTION_BACKEND = "paddlex_http"
            mock_settings.OCR_REMOTE_URL = "https://ocr.example.com/ocr"
            mock_settings.OCR_REMOTE_HEALTH_TIMEOUT_SEC = 3.0
            mock_settings.OCR_REMOTE_TOKEN = "test-token"
            mock_settings.OCR_REMOTE_AUTH_HEADER = "Authorization"
            mock_settings.OCR_REMOTE_AUTH_SCHEME = "Bearer"

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client_cls.return_value = mock_client

            result = await fn()
        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# Readiness endpoint integration (via TestClient with mocked deps)
# ══════════════════════════════════════════════════════════════════════════════


class TestReadinessEndpoint:
    """Integration-level readiness probe behavior.

    These tests use FastAPI TestClient and mock the critical dependency
    check functions to verify probe response status and content.
    """

    @pytest.fixture
    def client(self, monkeypatch):
        """Create a TestClient that does NOT trigger lifespan startup."""
        from fastapi.testclient import TestClient

        import app.main

        monkeypatch.setattr(app.main, "_production_mode", False)
        monkeypatch.setattr(app.main, "_check_ocr_config", AsyncMock(return_value=None))
        # A client used without a context manager does not start the lifespan.
        return TestClient(app.main.app)

    def test_healthy_probe(self, client):
        """All deps healthy → 200 with status=ok."""
        with (
            patch("app.main.check_database", return_value=True),
            patch("app.main.check_redis", return_value=True),
            patch("app.main.check_alembic_head", return_value=True),
            patch("app.main.check_staging", return_value=True),
            patch("app.main.check_staging_space", return_value={}),
            patch("app.main._check_role_deps", return_value=True),
            patch("app.main.check_queue", return_value="ok"),
            patch("app.services.task_queue_worker.is_draining_v2", return_value=False),
            patch("app.main.settings.REDIS_URL", "redis://localhost:6379"),
        ):
            resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_db_unavailable_returns_503(self, client):
        """Database unavailable → 503."""
        with (
            patch("app.main.check_database", return_value=False),
            patch("app.main.check_redis", return_value=True),
            patch("app.main.check_alembic_head", return_value=True),
            patch("app.main.check_staging", return_value=True),
            patch("app.main.check_staging_space", return_value={}),
            patch("app.main._check_role_deps", return_value=True),
            patch("app.main.check_queue", return_value="ok"),
            patch("app.services.task_queue_worker.is_draining_v2", return_value=False),
            patch("app.main.settings.REDIS_URL", "redis://localhost:6379"),
        ):
            resp = client.get("/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unavailable"

    def test_draining_returns_503(self, client):
        """Worker draining → 503."""
        with (
            patch("app.main.check_database", return_value=True),
            patch("app.main.check_redis", return_value=True),
            patch("app.main.check_alembic_head", return_value=True),
            patch("app.main.check_staging", return_value=True),
            patch("app.main.check_staging_space", return_value={}),
            patch("app.main._check_role_deps", return_value=True),
            patch("app.main.check_queue", return_value="ok"),
            patch("app.services.task_queue_worker.is_draining_v2", return_value=True),
            patch("app.main.settings.REDIS_URL", "redis://localhost:6379"),
        ):
            resp = client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["checks"]["draining"] == "draining"

    def test_role_deps_fail_returns_503(self, client):
        """Role deps unavailable → 503."""
        with (
            patch("app.main.check_database", return_value=True),
            patch("app.main.check_redis", return_value=True),
            patch("app.main.check_alembic_head", return_value=True),
            patch("app.main.check_staging", return_value=True),
            patch("app.main.check_staging_space", return_value={}),
            patch("app.main._check_role_deps", return_value=False),
            patch("app.main.check_queue", return_value="ok"),
            patch("app.services.task_queue_worker.is_draining_v2", return_value=False),
            patch("app.main.settings.REDIS_URL", "redis://localhost:6379"),
        ):
            resp = client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["checks"]["role_deps"] == "unavailable"

    def test_ocr_unavailable_returns_503(self, client):
        """OCR unavailable (config error) → 503 (critical in production)."""
        with (
            patch("app.main.check_database", return_value=True),
            patch("app.main.check_redis", return_value=True),
            patch("app.main.check_alembic_head", return_value=True),
            patch("app.main.check_staging", return_value=True),
            patch("app.main.check_staging_space", return_value={}),
            patch("app.main._check_role_deps", return_value=True),
            patch("app.main.check_queue", return_value="ok"),
            patch("app.services.task_queue_worker.is_draining_v2", return_value=False),
            patch("app.main.settings.REDIS_URL", "redis://localhost:6379"),
        ):
            # Override _check_ocr_config to return "unavailable"
            with patch("app.main._check_ocr_config", return_value="unavailable"):
                resp = client.get("/health/ready")
        assert resp.status_code == 503

    def test_ocr_degraded_returns_200(self, client):
        """OCR degraded (remote down) → 200 with degraded flag (not critical)."""
        with (
            patch("app.main.check_database", return_value=True),
            patch("app.main.check_redis", return_value=True),
            patch("app.main.check_alembic_head", return_value=True),
            patch("app.main.check_staging", return_value=True),
            patch("app.main.check_staging_space", return_value={}),
            patch("app.main._check_role_deps", return_value=True),
            patch("app.main.check_queue", return_value="ok"),
            patch("app.services.task_queue_worker.is_draining_v2", return_value=False),
            patch("app.main.settings.REDIS_URL", "redis://localhost:6379"),
        ):
            with patch("app.main._check_ocr_config", return_value="degraded"):
                resp = client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["degraded"] is True

    def test_queue_unavailable_returns_200(self, client):
        """Queue 'unavailable' returns 200 — queue is not a hard dep (Redis is)."""
        with (
            patch("app.main.check_database", return_value=True),
            patch("app.main.check_redis", return_value=True),
            patch("app.main.check_alembic_head", return_value=True),
            patch("app.main.check_staging", return_value=True),
            patch("app.main.check_staging_space", return_value={}),
            patch("app.main._check_role_deps", return_value=True),
            patch("app.services.task_queue_worker.is_draining_v2", return_value=False),
            patch("app.main.settings.REDIS_URL", "redis://localhost:6379"),
        ):
            with patch("app.main.check_queue", return_value="unavailable"):
                resp = client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["checks"]["queue"] == "unavailable"

    def test_liveness_always_ok(self, client):
        """Liveness probe always returns 200."""
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.parametrize("production", [False, True])
    @pytest.mark.parametrize("failed_probe,status", [
        (None, 200), ("check_database", 503), ("check_redis", 503),
        ("check_staging", 503), ("_check_role_deps", 503),
        ("_check_ocr_config", 503), ("check_queue", 200),
        # Existing readiness classifies stale Alembic as informational.
        ("check_alembic_head", 200),
    ])
    def test_original_readiness_status_and_cloud_detail_boundary(
        self, client, monkeypatch, production, failed_probe, status
    ):
        import app.main
        from app.services import task_queue_worker

        probes = {
            "check_database": True, "check_redis": True,
            "check_alembic_head": True, "check_staging": True,
            "_check_role_deps": True, "_check_ocr_config": None,
            "check_queue": None, "check_staging_space": {},
        }
        if failed_probe:
            probes[failed_probe] = (
                "unavailable" if failed_probe in {"_check_ocr_config", "check_queue"}
                else False
            )
        for name, result in probes.items():
            monkeypatch.setattr(app.main, name, AsyncMock(return_value=result))
        monkeypatch.setattr(app.main, "_production_mode", production)
        monkeypatch.setattr(app.main.settings, "REDIS_URL", "redis://synthetic:6379")
        monkeypatch.setattr(
            app.main, "get_db_pool_metrics", lambda: {"private": "synthetic-private"},
        )
        monkeypatch.setattr(task_queue_worker, "is_draining_v2", lambda: False)
        response = client.get("/health/ready")
        assert response.status_code == status
        expected = {"status": "ok" if status == 200 else "unavailable", "degraded": False}
        if production:
            assert response.json() == expected
            assert "synthetic-private" not in response.text
        else:
            assert response.json().items() >= expected.items()
            assert response.json()["checks"]["db_pool"] == {"private": "synthetic-private"}
            if failed_probe == "check_alembic_head":
                assert response.json()["checks"]["alembic"] == "stale"
