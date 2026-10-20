"""HTTP startup diagnostics and directory preparation preserve original effects."""

import asyncio
import builtins
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from tests.core.runtime_http_startup_probe import http_startup_operations


class Attributes:
    def __init__(self, values, reads, failure=None):
        self.values, self.reads, self.failure = values, reads, failure

    def __getattr__(self, name):
        self.reads.append(name)
        if self.failure is not None and name == self.failure[0]:
            raise self.failure[1]
        return self.values[name]


@pytest.fixture
def ports(monkeypatch):
    operations = http_startup_operations()
    state = SimpleNamespace(
        operations=operations, reads=[], logger=Mock(), capability=Mock(), mkdir=Mock(),
        profile=SimpleNamespace(name="synthetic", use_gpu=False, max_workers=2, max_pdf_pages=30),
    )
    state.config = Attributes(
        {"APP_ENV": "synthetic-env", "REDIS_URL": "", "EXPORT_DIR": "/synthetic/export"},
        state.reads,
    )
    monkeypatch.setitem(sys.modules, "app.services.export.capability", SimpleNamespace(
        log_export_config_on_startup=state.capability,
    ))
    monkeypatch.setattr(operations.directory_owner, "os", SimpleNamespace(makedirs=state.mkdir))
    return state


@pytest.mark.parametrize("role", ["web", "worker", "scheduler", "all", "unknown", " WEB "])
@pytest.mark.parametrize("gpu", [False, True])
def test_startup_diagnostics_keep_exact_profile_values_and_role_branch(ports, role, gpu):
    ports.profile.use_gpu = gpu
    assert ports.operations.diagnostics(ports.config, role, ports.profile, ports.logger) is None
    first = call.info(
        "Starting 2240AI \u2014 env=%s role=%s ocr_profile=%s (gpu=%s, workers=%d, max_pdf_pages=%d)",
        "synthetic-env", role, "synthetic", gpu, 2, 30,
    )
    branches = {
        "web": call.info("Role=%s: API serving, OCR gateway active (no worker/dispatcher)", role),
        "worker": call.info("Role=%s: pipeline dispatcher, reaper, AI prewarm active (no API)", role),
        "scheduler": call.info(
            "Role=%s: periodic tasks (token, staging, audit, recommendation metrics, "
            "export cleanup) active (no API, no worker)", role,
        ),
        "all": call.warning(
            "Role=%s: API + worker + scheduler components active in one process "
            "(development mode). In production, use web/worker/scheduler split.", role,
        ),
    }
    assert ports.logger.method_calls == [first] + ([branches[role]] if role in branches else [])
    assert ports.reads == ["APP_ENV"]
    ports.capability.assert_not_called()
    ports.mkdir.assert_not_called()


@pytest.mark.parametrize("failed", ["APP_ENV", "name", "use_gpu", "max_workers", "max_pdf_pages"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_startup_profile_and_config_read_errors_precede_logging(ports, failed, error_type):
    error = error_type("synthetic diagnostic attribute failure")
    if failed == "APP_ENV":
        ports.config.failure = failed, error
    else:
        ports.profile = Attributes(vars(ports.profile), ports.reads, (failed, error))
    with pytest.raises(error_type) as caught:
        ports.operations.diagnostics(ports.config, "all", ports.profile, ports.logger)
    assert caught.value is error
    assert ports.reads[-1] == failed and ports.reads[0] == "APP_ENV"
    assert not ports.logger.method_calls


@pytest.mark.parametrize("role", ["web", "all"])
@pytest.mark.parametrize("failed", ["first", "role"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_startup_logging_errors_propagate_at_original_log_position(ports, role, failed, error_type):
    error = error_type("synthetic diagnostic log failure")
    ports.logger.info.side_effect = error if failed == "first" else [None, error]
    if role == "all" and failed == "role":
        ports.logger.warning.side_effect = error
    with pytest.raises(error_type) as caught:
        ports.operations.diagnostics(ports.config, role, ports.profile, ports.logger)
    assert caught.value is error
    assert len(ports.logger.method_calls) == (1 if failed == "first" else 2)


@pytest.mark.parametrize("role", ["web", "worker", "scheduler", "all", "unknown", " WEB "])
@pytest.mark.parametrize("redis", ["", None, "redis://synthetic", True])
def test_export_status_preserves_role_redis_truthiness_and_capability_call(ports, role, redis):
    ports.config.values["REDIS_URL"] = redis
    assert ports.operations.export(role, ports.config, ports.logger) is None
    ports.capability.assert_called_once_with()
    assert ports.reads == ["REDIS_URL"]
    if role in {"scheduler", "all"}:
        ports.logger.info.assert_called_once_with(
            "export_processor_enabled=true process_role=%s redis_available=%s", role, bool(redis),
        )
        ports.logger.warning.assert_not_called()
    elif role == "web":
        ports.logger.warning.assert_called_once_with(
            "process_role=web export_processor_enabled=false export_processor_mode=external "
            " \u2014 pending export tasks will NOT be processed. "
            "Start a scheduler process (PROCESS_ROLE=scheduler) or use PROCESS_ROLE=all for local dev.",
        )
        ports.logger.info.assert_not_called()
    else:
        assert not ports.logger.method_calls


@pytest.mark.parametrize("role", ["web", "all", "unknown"])
@pytest.mark.parametrize("error_type", [ImportError, RuntimeError, asyncio.CancelledError])
def test_export_capability_failure_preserves_warning_continue_or_cancel_boundary(ports, role, error_type):
    error = error_type("synthetic export configuration failure")
    ports.capability.side_effect = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            ports.operations.export(role, ports.config, ports.logger)
        assert caught.value is error
        assert ports.reads == [] and not ports.logger.method_calls
    else:
        assert ports.operations.export(role, ports.config, ports.logger) is None
        assert ports.logger.method_calls[0] == call.warning(
            "Export config logging failed (non-fatal)", exc_info=True,
        )
        assert ports.reads == ["REDIS_URL"]


@pytest.mark.parametrize("error_type", [ImportError, RuntimeError, asyncio.CancelledError])
def test_export_import_failure_keeps_lazy_original_exception_boundary(ports, monkeypatch, error_type):
    error = error_type("synthetic capability import failure")
    importing = builtins.__import__

    def fail(name, *args, **kwargs):
        if name == "app.services.export.capability":
            raise error
        return importing(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail)
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            ports.operations.export("unknown", ports.config, ports.logger)
        assert caught.value is error
        assert not ports.reads
    else:
        ports.operations.export("unknown", ports.config, ports.logger)
        ports.logger.warning.assert_called_once_with(
            "Export config logging failed (non-fatal)", exc_info=True,
        )
        assert ports.reads == ["REDIS_URL"]
    ports.capability.assert_not_called()


def test_export_redis_is_read_after_capability_and_not_frozen_before_it(ports):
    ports.capability.side_effect = lambda: ports.config.values.update(REDIS_URL="redis://synthetic")
    ports.operations.export("all", ports.config, ports.logger)
    assert ports.logger.info.call_args.args[-1] is True


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_export_warning_error_propagates_before_later_config_reads(ports, error_type):
    ports.capability.side_effect = RuntimeError("synthetic capability failure")
    error = error_type("synthetic warning failure")
    ports.logger.warning.side_effect = error
    with pytest.raises(error_type) as caught:
        ports.operations.export("all", ports.config, ports.logger)
    assert caught.value is error and not ports.reads


@pytest.mark.parametrize("failed", ["read", "truthiness"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_export_redis_errors_propagate_outside_capability_catch(ports, failed, error_type):
    error = error_type("synthetic redis configuration failure")
    if failed == "read":
        ports.config.failure = "REDIS_URL", error
    else:
        class Redis:
            def __bool__(self):
                raise error
        ports.config.values["REDIS_URL"] = Redis()
    with pytest.raises(error_type) as caught:
        ports.operations.export("unknown", ports.config, ports.logger)
    assert caught.value is error
    ports.capability.assert_called_once_with()
    assert not ports.logger.method_calls


@pytest.mark.parametrize("role", ["web", "all"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_export_status_log_error_is_not_swallowed_as_capability_failure(ports, role, error_type):
    error = error_type("synthetic export status log failure")
    getattr(ports.logger, "warning" if role == "web" else "info").side_effect = error
    with pytest.raises(error_type) as caught:
        ports.operations.export(role, ports.config, ports.logger)
    assert caught.value is error
    assert len(ports.logger.method_calls) == 1 and ports.reads == ["REDIS_URL"]


@pytest.mark.parametrize("failed", [0, 1, 2, 3])
@pytest.mark.parametrize("error_type", [PermissionError, asyncio.CancelledError])
def test_directory_failure_preserves_creation_order_and_delayed_export_read(ports, failed, error_type):
    error = error_type("synthetic directory failure")
    ports.mkdir.side_effect = [None] * failed + [error]
    with pytest.raises(error_type) as caught:
        ports.operations.directories(ports.config)
    assert caught.value is error
    paths = ["static/formulas", "static/question-assets", "static/avatars", "/synthetic/export"]
    assert ports.mkdir.call_args_list == [call(path, exist_ok=True) for path in paths[:failed + 1]]
    assert ports.reads == (["EXPORT_DIR"] if failed == 3 else [])


def test_export_directory_read_failure_occurs_after_three_static_directories(ports):
    error = RuntimeError("synthetic export directory attribute failure")
    ports.config.failure = "EXPORT_DIR", error
    with pytest.raises(RuntimeError) as caught:
        ports.operations.directories(ports.config)
    assert caught.value is error
    assert ports.mkdir.call_count == 3


def test_real_directory_preparation_keeps_cwd_relative_paths_and_existing_data(monkeypatch, tmp_path):
    operations = http_startup_operations()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(operations.directory_owner, "os", os)
    config = SimpleNamespace(EXPORT_DIR=str(tmp_path / "custom" / "exports"))
    operations.directories(config)
    marker = tmp_path / "static" / "avatars" / "retained.txt"
    marker.write_text("synthetic existing data")
    assert operations.directories(config) is None
    assert marker.read_text() == "synthetic existing data"
    assert all((tmp_path / path).is_dir() for path in [
        "static/formulas", "static/question-assets", "static/avatars", "custom/exports",
    ])
