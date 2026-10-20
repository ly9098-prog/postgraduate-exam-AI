"""Characterize HTTP role writes, OCR isolation and startup failure policy."""

import asyncio
import builtins
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import deployment_profile
from app.core.config import resolve_effective_process_role
from tests.core.http_runtime_policy_probe import http_runtime_policy


@pytest.fixture
def ports(monkeypatch):
    state = SimpleNamespace(
        profile=deployment_profile.DeploymentProfile.CLOUD_API, profile_error=None,
        config=SimpleNamespace(APP_ENV="test", PROCESS_ROLE="web", LOCAL_ASYNC_RUNTIME_ENABLED=False),
        logger=SimpleNamespace(info=Mock(), warning=Mock(), critical=Mock()),
    )

    def detect():
        if state.profile_error is not None:
            raise state.profile_error
        return state.profile

    monkeypatch.setenv("PROCESS_ROLE", "synthetic-prior-role")
    monkeypatch.setattr(deployment_profile, "detect_deployment_profile", detect)
    state.policy = http_runtime_policy(monkeypatch, state.logger, state.config)
    return state


@pytest.mark.parametrize("app_env", ["test", "development", "production", " local ", None, ""])
@pytest.mark.parametrize("configured", ["web", "all", "worker", "scheduler", " ALL ", " Worker ", "unknown", None])
@pytest.mark.parametrize("enabled", [False, True])
def test_role_resolution_writes_only_after_normalization_and_before_http_rejection(ports, app_env, configured, enabled):
    config = ports.config
    config.APP_ENV, config.PROCESS_ROLE, config.LOCAL_ASYNC_RUNTIME_ENABLED = app_env, configured, enabled
    expected = resolve_effective_process_role(app_env, configured, enabled)
    if expected in {"worker", "scheduler"}:
        with pytest.raises(SystemError) as caught:
            ports.policy.role()
        assert str(caught.value) == (
            f"PROCESS_ROLE={expected} must not start the FastAPI HTTP application; "
            f"use python -m app.{expected}_main"
        )
    else:
        assert ports.policy.role() == expected
    assert config.PROCESS_ROLE == expected
    assert os.environ["PROCESS_ROLE"] == (expected if expected != configured else "synthetic-prior-role")
    assert ports.logger.info.call_count == int(expected != configured)


def test_role_normalization_log_failure_precedes_settings_and_environment_writes(ports):
    ports.config.PROCESS_ROLE = "all"
    error = RuntimeError("synthetic log failure")
    ports.logger.info.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        ports.policy.role()
    assert caught.value is error
    assert ports.config.PROCESS_ROLE == "all"
    assert os.environ["PROCESS_ROLE"] == "synthetic-prior-role"


@pytest.mark.parametrize("cloud", [False, True])
@pytest.mark.parametrize("loaded", [[], ["paddle", "paddleocr.synthetic"]])
@pytest.mark.parametrize("restricted", [False, True])
def test_ocr_isolation_only_checks_loaded_modules_in_cloud_and_keeps_fatal_system_error(ports, cloud, loaded, restricted):
    ports.profile = deployment_profile.DeploymentProfile.CLOUD_API if cloud else deployment_profile.DeploymentProfile.LOCAL_IMPORT
    probe, restriction = Mock(return_value=loaded), Mock(return_value=restricted)
    if cloud and loaded:
        with pytest.raises(SystemError, match="Banned local OCR modules loaded in cloud_api"):
            ports.policy.isolate(probe, restriction)
        ports.logger.critical.assert_called_once()
    else:
        ports.policy.isolate(probe, restriction)
        ports.logger.critical.assert_not_called()
    assert probe.call_count == int(cloud)
    restriction.assert_not_called()
    ports.logger.warning.assert_not_called()


@pytest.mark.parametrize("failed", ["profile", "loaded"])
@pytest.mark.parametrize("error_type", [RuntimeError, ImportError, SystemError, asyncio.CancelledError])
@pytest.mark.parametrize("restricted", [False, True])
def test_ocr_profile_probe_error_fallback_and_cancellation_are_original(ports, failed, error_type, restricted):
    error = error_type("synthetic isolation failure")
    probe, restriction = Mock(return_value=[]), Mock(return_value=restricted)
    if failed == "profile":
        ports.profile_error = error
    else:
        probe.side_effect = error
    if error_type in {SystemError, asyncio.CancelledError}:
        with pytest.raises(error_type) as caught:
            ports.policy.isolate(probe, restriction)
        assert caught.value is error
        restriction.assert_not_called()
    elif restricted:
        with pytest.raises(SystemError) as caught:
            ports.policy.isolate(probe, restriction)
        assert caught.value.__cause__ is error
        restriction.assert_called_once()
    else:
        ports.policy.isolate(probe, restriction)
        ports.logger.warning.assert_called_once_with("OCR module isolation check failed: %s", error)
        restriction.assert_called_once()


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("profile", ["local", "cloud", "error", "system_error", "cancel"])
def test_component_failure_profile_fallback_fatal_cause_and_cancellation(ports, mode, profile):
    error = RuntimeError("synthetic component failure")
    if profile == "local":
        ports.profile = deployment_profile.DeploymentProfile.LOCAL_IMPORT
    elif profile != "cloud":
        ports.profile_error = {
            "error": RuntimeError("synthetic profile failure"),
            "system_error": SystemError("synthetic profile system error"),
            "cancel": asyncio.CancelledError(),
        }[profile]
    fatal = profile == "cloud" or (profile == "local" and mode)
    if profile == "cancel":
        with pytest.raises(asyncio.CancelledError) as caught:
            ports.policy.report("Synthetic component", error, mode)
        assert caught.value is ports.profile_error
    elif fatal:
        with pytest.raises(SystemError) as caught:
            ports.policy.report("Synthetic component", error, mode)
        assert caught.value.__cause__ is error
        assert str(caught.value) == "Synthetic component start failed: synthetic component failure"
        ports.logger.critical.assert_called_once()
    else:
        ports.policy.report("Synthetic component", error, mode)
        ports.logger.warning.assert_called_once_with("%s start failed (non-fatal): %s", "Synthetic component", error)


def test_failure_report_deployment_import_error_remains_outside_profile_fallback(ports, monkeypatch):
    error = ImportError("synthetic deployment module failure")
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "app.core.deployment_profile":
            raise error
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(ImportError) as caught:
        ports.policy.report("Synthetic component", RuntimeError("synthetic"), False)
    assert caught.value is error
    ports.logger.warning.assert_not_called()
    ports.logger.critical.assert_not_called()
