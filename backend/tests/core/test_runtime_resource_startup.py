"""Preserve executor setup and orphan reconciler startup failure boundaries."""

import asyncio
import builtins
from types import SimpleNamespace

import pytest

from tests.core.runtime_resource_startup_ports import ports as ports


@pytest.mark.parametrize("role", ["web", "all", "worker", "scheduler", "unknown"])
@pytest.mark.parametrize("cloud", [False, True])
def test_executor_role_profile_mapping_registry_identity_and_log(ports, role, cloud):
    if cloud:
        ports.profile = ports.modules["app.core.deployment_profile"].DeploymentProfile.CLOUD_API
    ports.executors = {"pdf": SimpleNamespace(name="synthetic-pdf"), "ocr": SimpleNamespace(name="synthetic-ocr")}
    assert ports.subject.initialize_role_executors(role) is None
    assert ports.events == [
        ("profile", (), {}), ("executors", (role,), {"is_production": cloud}),
        ("registry", (ports.executors,), {}),
    ]
    assert ports.events[-1][1][0] is ports.executors
    ports.logger.info.assert_called_once_with(
        "Executors initialized for role=%s: %s", role, {"pdf": "synthetic-pdf", "ocr": "synthetic-ocr"},
    )


@pytest.mark.parametrize("failed", ["profile", "executors", "registry"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_executor_error_propagates_at_original_operation_without_extra_work(ports, failed, error_type):
    error = error_type("synthetic startup error")
    ports.failures[failed] = error
    with pytest.raises(error_type) as caught:
        ports.subject.initialize_role_executors("all")
    assert caught.value is error
    sequence = ["profile", "executors", "registry"]
    assert [event[0] for event in ports.events] == sequence[:sequence.index(failed) + 1]
    ports.logger.info.assert_not_called()


def test_executor_log_failure_occurs_after_registry_publication(ports):
    error = RuntimeError("synthetic logger error")
    ports.logger.info.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        ports.subject.initialize_role_executors("web")
    assert caught.value is error
    assert [event[0] for event in ports.events] == ["profile", "executors", "registry"]


def test_executor_name_error_occurs_after_registry_publication(ports):
    ports.executors = {"pdf": object()}
    with pytest.raises(AttributeError, match="name"):
        ports.subject.initialize_role_executors("web")
    assert [event[0] for event in ports.events] == ["profile", "executors", "registry"]
    ports.logger.info.assert_not_called()


@pytest.mark.parametrize("module", ["app.core.deployment_profile", "app.core.executor_registry", "app.core.executors"])
def test_executor_import_failure_precedes_profile_detection(ports, monkeypatch, module):
    original = builtins.__import__
    error = ImportError("synthetic startup import error")

    def guarded(name, *args, **kwargs):
        if name == module:
            raise error
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(ImportError) as caught:
        ports.subject.initialize_role_executors("web")
    assert caught.value is error
    assert ports.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_orphan_start_preserves_nonfatal_error_and_cancellation(ports, outcome):
    error = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("synthetic orphan error")
    if outcome != "success":
        ports.failures["reconciler"] = error
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError) as caught:
            await ports.subject.start_resource_reconciler()
        assert caught.value is error
    else:
        assert await ports.subject.start_resource_reconciler() is None
    assert ports.events == [("reconciler", (), {})]
    if outcome == "error":
        ports.logger.warning.assert_called_once_with("Orphan reconciler start failed (non-fatal): %s", error)
    else:
        ports.logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_orphan_import_failure_is_logged_and_nonfatal(ports, monkeypatch):
    original = builtins.__import__
    error = ImportError("synthetic reconciler import error")

    def guarded(name, *args, **kwargs):
        if name == "app.core.resource_guard":
            raise error
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    await ports.subject.start_resource_reconciler()
    assert ports.events == []
    ports.logger.warning.assert_called_once_with("Orphan reconciler start failed (non-fatal): %s", error)


@pytest.mark.asyncio
async def test_orphan_warning_failure_propagates(ports):
    ports.failures["reconciler"] = RuntimeError("synthetic orphan error")
    error = RuntimeError("synthetic warning error")
    ports.logger.warning.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        await ports.subject.start_resource_reconciler()
    assert caught.value is error
