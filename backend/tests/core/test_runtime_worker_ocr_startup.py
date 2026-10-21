"""Worker OCR startup retains pre-resolved profile and worker-owned client."""

import asyncio
import builtins
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.runtime_ocr_startup import HttpOcrResources
from tests.core.runtime_worker_ocr_probe import worker_ocr_operation

IMPORTS = [
    "app.core.ocr_runtime_config", "app.features.ocr_gateway",
    "app.services.ocr_worker_client", "app.services.ocr_service",
]
OPERATIONS = ["config", "worker", "gateway", "publish"]


@pytest.fixture
def ports(monkeypatch):
    events, imports, failures = [], [], {}
    config = SimpleNamespace(enabled=True, execution_backend="synthetic-remote", profile="synthetic-config-profile")
    state = SimpleNamespace(
        events=events, imports=imports, failures=failures, config=config,
        profile=object(), worker=object(), gateway=object(), logger=Mock(), published=None,
        resources=HttpOcrResources(),
    )

    def call(name, result):
        def operation(*args, **kwargs):
            events.append((name, args, kwargs))
            if name in failures:
                raise failures[name]
            if name == "publish":
                state.published = args[0]
            return result
        return operation

    modules = {
        "app.core.ocr_runtime_config": SimpleNamespace(get_runtime_config=call("config", config)),
        "app.features.ocr_gateway": SimpleNamespace(OCRGateway=call("gateway", state.gateway)),
        "app.services.ocr_worker_client": SimpleNamespace(create_ocr_worker_client=call("worker", state.worker)),
        "app.services.ocr_service": SimpleNamespace(set_gateway=call("publish", None)),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in modules:
            imports.append(name)
            if name in failures:
                raise failures[name]
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    state.initialize = worker_ocr_operation()
    return state


def test_worker_assembly_uses_exact_pre_resolved_profile_and_no_shared_client_argument(ports):
    assert ports.initialize(ports.profile, ports.logger, ports.resources) is None
    assert ports.events == [
        ("config", (), {}), ("worker", (ports.config,), {}),
        ("gateway", (), {"mode": "gateway", "profile": ports.profile, "worker_client": ports.worker}),
        ("publish", (ports.gateway,), {}),
    ]
    assert ports.published is ports.gateway and ports.imports == IMPORTS
    assert ports.resources.gateway is ports.gateway
    assert ports.resources.worker_client is None
    ports.logger.info.assert_called_once_with(
        "OCR Gateway initialized (role=worker exec_backend=%s profile=%s)",
        "synthetic-remote", "synthetic-config-profile",
    )


def test_disabled_worker_still_imports_original_modules_without_constructing_or_publishing(ports):
    ports.config.enabled = False
    ports.initialize(ports.profile, ports.logger, ports.resources)
    assert ports.events == [("config", (), {})]
    assert ports.imports == IMPORTS[:3] and ports.published is None
    ports.logger.info.assert_called_once_with("OCR not enabled on worker, skipping Gateway")


@pytest.mark.parametrize("failed", [*OPERATIONS, *IMPORTS])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_worker_import_and_construction_errors_propagate_at_original_boundaries(ports, failed, error_type):
    error = error_type("synthetic worker OCR failure")
    ports.failures[failed] = error
    with pytest.raises(error_type) as caught:
        ports.initialize(ports.profile, ports.logger, ports.resources)
    assert caught.value is error and ports.published is None
    if failed in OPERATIONS:
        assert [event[0] for event in ports.events] == OPERATIONS[:OPERATIONS.index(failed) + 1]
    else:
        assert ports.imports == IMPORTS[:IMPORTS.index(failed) + 1]
    ports.logger.info.assert_not_called()
    ports.logger.warning.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_worker_log_failure_preserves_completed_gateway_publication(ports, enabled):
    ports.config.enabled = enabled
    error = RuntimeError("synthetic worker log failure")
    ports.logger.info.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        ports.initialize(ports.profile, ports.logger, ports.resources)
    assert caught.value is error
    assert ports.published is (ports.gateway if enabled else None)


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_gateway_construction_failure_retains_worker_client_for_owner_cleanup(
    ports, error_type,
):
    error = error_type("synthetic gateway construction failure")
    ports.failures["gateway"] = error
    with pytest.raises(error_type) as caught:
        ports.initialize(ports.profile, ports.logger, ports.resources)
    assert caught.value is error
    assert ports.resources.worker_client is ports.worker
    assert ports.resources.gateway is None
    assert ports.published is None
