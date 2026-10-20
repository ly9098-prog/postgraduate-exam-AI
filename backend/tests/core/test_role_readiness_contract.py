"""Characterize role checks and their original failure/logging order."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import main


@pytest.fixture
def role_ports(monkeypatch):
    from app.services import (
        audit_cleanup_scheduler,
        recommendation_metrics_scheduler,
        task_queue_worker,
    )

    config = SimpleNamespace(
        PROCESS_ROLE="web", OCR_EXECUTION_BACKEND="paddlex_http",
        AUDIT_LOG_CLEANUP_ENABLED=True, RECOMMENDATION_METRICS_AGG_ENABLED=True,
    )
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr("app.core.ocr_isolation.is_restricted_ocr_environment", lambda: False)
    monkeypatch.setattr("app.core.ocr_isolation.loaded_local_ocr_modules", lambda: [])
    monkeypatch.setattr(task_queue_worker, "is_draining_v2", lambda: False)
    monkeypatch.setattr(audit_cleanup_scheduler.audit_log_cleanup_scheduler, "_running", True)
    monkeypatch.setattr(
        recommendation_metrics_scheduler.recommendation_metrics_scheduler, "_running", True,
    )
    return SimpleNamespace(
        config=config, worker=task_queue_worker, audit=audit_cleanup_scheduler,
        recommendation=recommendation_metrics_scheduler,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role,expected", [
    ("web", True), ("worker", True), ("scheduler", True), ("all", True),
    ("unknown", False), ("", False),
])
async def test_role_defaults_and_unknown_role(role_ports, role, expected):
    role_ports.config.PROCESS_ROLE = role
    assert await main.check_role_dependencies(main.settings) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["web", "worker", "all", "scheduler"])
async def test_cloud_role_restrictions_have_original_priority(monkeypatch, role_ports, role):
    role_ports.config.PROCESS_ROLE = role
    role_ports.config.OCR_EXECUTION_BACKEND = "LOCAL_PROCESS"
    monkeypatch.setattr("app.core.ocr_isolation.is_restricted_ocr_environment", lambda: True)
    monkeypatch.setattr("app.core.ocr_isolation.loaded_local_ocr_modules", lambda: ["paddle"])
    warning = Mock()
    monkeypatch.setattr(main.logger, "warning", warning)
    assert await main.check_role_dependencies(main.settings) is (role == "scheduler")
    assert warning.call_count == int(role != "scheduler")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "all"])
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_worker_draining_errors_keep_original_fallback(
    monkeypatch, role_ports, role, failure
):
    role_ports.config.PROCESS_ROLE = role
    error = asyncio.CancelledError() if failure == "cancel" else RuntimeError("synthetic")
    monkeypatch.setattr(role_ports.worker, "is_draining_v2", Mock(side_effect=error))
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError) as caught:
            await main.check_role_dependencies(main.settings)
        assert caught.value is error
    else:
        assert await main.check_role_dependencies(main.settings) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "all"])
async def test_draining_stops_before_scheduler_access(monkeypatch, role_ports, role):
    role_ports.config.PROCESS_ROLE = role
    monkeypatch.setattr(role_ports.worker, "is_draining_v2", lambda: True)

    class Forbidden:
        @property
        def _running(self):
            raise AssertionError("scheduler must not be reached")

    monkeypatch.setattr(role_ports.audit, "audit_log_cleanup_scheduler", Forbidden())
    assert await main.check_role_dependencies(main.settings) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("port", ["audit", "recommendation"])
@pytest.mark.parametrize("failure", ["import", "error", "cancel"])
async def test_scheduler_failure_logging_and_cancellation(
    monkeypatch, role_ports, port, failure
):
    role_ports.config.PROCESS_ROLE = "scheduler"
    error = {
        "import": ImportError("synthetic import"),
        "error": RuntimeError("synthetic access"),
        "cancel": asyncio.CancelledError(),
    }[failure]

    class Broken:
        @property
        def _running(self):
            raise error

    module = role_ports.audit if port == "audit" else role_ports.recommendation
    name = "audit_log_cleanup_scheduler" if port == "audit" else "recommendation_metrics_scheduler"
    monkeypatch.setattr(module, name, Broken())
    warning = Mock()
    monkeypatch.setattr(main.logger, "warning", warning)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError) as caught:
            await main.check_role_dependencies(main.settings)
        assert caught.value is error
        warning.assert_not_called()
    else:
        assert await main.check_role_dependencies(main.settings) is False
        warning.assert_called_once()
        text = warning.call_args.args[0]
        assert ("import failed" in text) is (failure == "import")
        assert ("check error" in text) is (failure == "error")
