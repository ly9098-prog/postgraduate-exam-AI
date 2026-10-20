"""Characterize standalone HTTP refusal, scratch and startup failure policy."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import deployment_profile
from tests.core.standalone_policy_probe import standalone_policies


@pytest.fixture
def ports(monkeypatch):
    policy = standalone_policies()
    state = SimpleNamespace(
        policy=policy, config=SimpleNamespace(
            APP_ENV="test", WORKER_SCRATCH_DIR="/synthetic/explicit", STAGING_STORAGE_DIR="/synthetic/staging",
        ), logger=Mock(), environment={}, argv=["python"],
        profile=deployment_profile.DeploymentProfile.LOCAL_IMPORT, profile_calls=[],
        mkdir=Mock(), profile_error=None,
    )

    def detect():
        state.profile_calls.append("profile")
        if state.profile_error is not None:
            raise state.profile_error
        return state.profile

    monkeypatch.setattr(policy.module, "os", SimpleNamespace(path=os.path, environ=state.environment, makedirs=state.mkdir))
    monkeypatch.setattr(policy.module, "sys", SimpleNamespace(argv=state.argv))
    monkeypatch.setattr(deployment_profile, "detect_deployment_profile", detect)
    return state


@pytest.mark.parametrize("role", ["worker", "scheduler", "all", "web", " Worker ", None])
@pytest.mark.parametrize("argv,environment,http", [
    (["python"], {}, False), ([], {}, False),
    (["/usr/bin/GUNICORN"], {}, True), (["uvicorn"], {}, True),
    (["python", "uvicorn"], {}, False),
    (["python"], {"GUNICORN_CMD_ARGS": "--bind"}, True),
    (["python"], {"UVICORN_CMD_ARGS": " "}, True),
    (["python"], {"GUNICORN_CMD_ARGS": ""}, False),
])
def test_http_guard_uses_original_first_argv_and_presence_checks(ports, role, argv, environment, http):
    ports.argv[:] = argv
    ports.environment.update(environment)
    if http and role in {"worker", "scheduler"}:
        with pytest.raises(SystemError) as caught:
            ports.policy.guard(role)
        assert str(caught.value) == (
            f"PROCESS_ROLE={role} started over HTTP (Gunicorn/uvicorn). "
            "This role must be started as a standalone process: "
            f"python -m app.{role}_main"
        )
    else:
        assert ports.policy.guard(role) is None
    assert not ports.profile_calls
    ports.mkdir.assert_not_called()


@pytest.mark.parametrize("scratch", [None, "", "/tmp", "/tmp/worker-scratch", "/tmp/", "/tmp/worker-scratch/", "./relative", "/synthetic/custom"])
@pytest.mark.parametrize("cloud", [False, True])
@pytest.mark.parametrize("app_env", ["test", "production", " production "])
def test_scratch_checks_profile_only_for_original_defaults_and_keeps_path_semantics(ports, scratch, cloud, app_env):
    ports.config.WORKER_SCRATCH_DIR, ports.config.APP_ENV = scratch, app_env
    if cloud:
        ports.profile = deployment_profile.DeploymentProfile.CLOUD_API
    default = not scratch or scratch in {"/tmp", "/tmp/worker-scratch"}
    if default and (cloud or app_env == "production"):
        with pytest.raises(SystemError, match="WORKER_SCRATCH_DIR must be explicitly configured"):
            ports.policy.scratch(ports.config)
        ports.mkdir.assert_not_called()
    else:
        expected = "/synthetic/scratch" if default else scratch
        assert ports.policy.scratch(ports.config) == expected
        ports.mkdir.assert_called_once_with(expected, exist_ok=True)
    assert ports.profile_calls == (["profile"] if default else [])


@pytest.mark.parametrize("staging,expected", [
    (None, "/opt/2240ai-v2/scratch"), ("", "/opt/2240ai-v2/scratch"),
    ("staging", "scratch"), ("/tmp/staging/", "/tmp/staging/scratch"),
])
def test_scratch_fallback_uses_original_staging_dirname_without_normalization(ports, staging, expected):
    ports.config.WORKER_SCRATCH_DIR = ""
    ports.config.STAGING_STORAGE_DIR = staging
    assert ports.policy.scratch(ports.config) == expected
    ports.mkdir.assert_called_once_with(expected, exist_ok=True)


@pytest.mark.parametrize("failed", ["profile", "mkdir"])
@pytest.mark.parametrize("error_type", [RuntimeError, PermissionError, asyncio.CancelledError])
def test_scratch_profile_and_mkdir_errors_propagate(ports, failed, error_type):
    error = error_type("synthetic scratch failure")
    if failed == "profile":
        ports.config.WORKER_SCRATCH_DIR = ""
        ports.profile_error = error
    else:
        ports.mkdir.side_effect = error
    with pytest.raises(error_type) as caught:
        ports.policy.scratch(ports.config)
    assert caught.value is error
    if failed == "profile":
        ports.mkdir.assert_not_called()


@pytest.mark.parametrize("cloud", [False, True])
@pytest.mark.parametrize("app_env", ["test", "production", " production ", None])
def test_reporter_freezes_restriction_at_factory_time_and_preserves_error_cause(ports, cloud, app_env):
    profile = deployment_profile.DeploymentProfile.CLOUD_API if cloud else deployment_profile.DeploymentProfile.LOCAL_IMPORT
    ports.config.APP_ENV = app_env
    fatal = cloud or app_env == "production"
    report = ports.policy.reporter(profile, ports.config, ports.logger)
    ports.config.APP_ENV = "test" if fatal else "production"
    error = RuntimeError("synthetic component failure")
    if fatal:
        with pytest.raises(SystemError, match="Synthetic component start failed: synthetic component failure") as caught:
            report("Synthetic component", error)
        assert caught.value.__cause__ is error
        ports.logger.critical.assert_called_once_with("%s start failed \u2014 fatal in production", "Synthetic component")
        ports.logger.warning.assert_not_called()
    else:
        assert report("Synthetic component", error) is None
        ports.logger.warning.assert_called_once_with("%s start failed (non-fatal): %s", "Synthetic component", error)
        ports.logger.critical.assert_not_called()
    assert not ports.profile_calls


@pytest.mark.parametrize("cloud", [False, True])
def test_reporter_logging_failure_propagates_before_systemerror_wrapping(ports, cloud):
    profile = deployment_profile.DeploymentProfile.CLOUD_API if cloud else deployment_profile.DeploymentProfile.LOCAL_IMPORT
    report = ports.policy.reporter(profile, ports.config, ports.logger)
    log_error = RuntimeError("synthetic reporter log failure")
    getattr(ports.logger, "critical" if cloud else "warning").side_effect = log_error
    with pytest.raises(RuntimeError) as caught:
        report("Synthetic component", RuntimeError("synthetic original failure"))
    assert caught.value is log_error


@pytest.mark.parametrize("explicit", [False, True])
def test_real_temporary_scratch_creation_is_idempotent_and_preserves_existing_data(monkeypatch, tmp_path, explicit):
    monkeypatch.setattr(
        deployment_profile, "detect_deployment_profile",
        lambda: deployment_profile.DeploymentProfile.LOCAL_IMPORT,
    )
    expected = tmp_path / "scratch"
    config = SimpleNamespace(
        APP_ENV="test", WORKER_SCRATCH_DIR=str(expected) if explicit else "",
        STAGING_STORAGE_DIR=str(tmp_path / "staging"),
    )
    operation = standalone_policies().scratch
    assert operation(config) == str(expected)
    assert expected.is_dir()
    marker = expected / "retained.txt"
    marker.write_text("synthetic existing data")
    assert operation(config) == str(expected)
    assert marker.read_text() == "synthetic existing data"
