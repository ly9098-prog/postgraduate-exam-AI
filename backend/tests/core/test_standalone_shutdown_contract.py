"""Preserve standalone shutdown's own role, import and exception boundaries."""

import asyncio
import builtins
from types import SimpleNamespace

import pytest

from tests.core.standalone_role_ports import role_runtime as role_runtime
from tests.core.standalone_shutdown_probe import shutdown_operations


@pytest.fixture
def operations(role_runtime, monkeypatch):
    subject = shutdown_operations()
    state = role_runtime
    state.deadlines, state.thread_calls = [], []

    async def wait_for(coro, *, timeout):
        state.deadlines.append(timeout)
        if "deadline" in state.failures:
            coro.close()
            raise state.failures["deadline"]
        return await coro

    async def to_thread(function, *args, **kwargs):
        state.thread_calls.append((args, kwargs))
        return function(*args, **kwargs)

    monkeypatch.setattr(subject, "asyncio", SimpleNamespace(wait_for=wait_for, to_thread=to_thread, CancelledError=asyncio.CancelledError))
    return subject


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "all", "scheduler", "web", "unknown"])
@pytest.mark.parametrize("cloud", [False, True])
async def test_original_standalone_sections_keep_role_profile_resource_order_and_deadlines(operations, role_runtime, role, cloud):
    state = role_runtime
    state.cloud = cloud
    state.gateway = SimpleNamespace(shutdown=state.asynchronous("ocr.gateway.stop"))
    await operations.stop_standalone_worker_services(role, state.logger)
    await operations.stop_standalone_scheduler_services(role, state.logger)
    await operations.shutdown_standalone_formula_pool(state.logger)
    await operations.shutdown_standalone_ocr(role, state.logger)
    await operations.shutdown_standalone_render_resources(state.logger)
    await operations.close_standalone_runtime_connections(state.logger)
    worker = role in {"worker", "all"}
    expected = ["queue.drain", "reaper.signal", "prewarm.stop"] if worker else ["queue.draining"]
    if role in {"scheduler", "all"}:
        expected += ["audit.stop", "metrics.stop", "export.signal"]
    expected += ["formula.stop"]
    if worker:
        expected += ([] if cloud else ["ocr.executor.stop"]) + ["ocr.gateway.stop"]
    expected += ["executors.stop", "executors.clear", "pdf.stop", "queue.close", "db.dispose", "orphans.stop"]
    assert state.events == expected
    assert state.deadlines == ([30, 30] if worker and not cloud else [30])
    assert state.thread_calls == [((), {"wait": True, "cancel_futures": False})]
    state.logger.warning.assert_not_called()
    state.logger.exception.assert_not_called()


FAILURES = [
    ("stop_standalone_worker_services", "worker", "queue.drain"),
    ("stop_standalone_worker_services", "worker", "reaper.signal"),
    ("stop_standalone_worker_services", "worker", "prewarm.stop"),
    ("stop_standalone_worker_services", "web", "queue.draining"),
    ("stop_standalone_scheduler_services", "scheduler", "audit.stop"),
    ("stop_standalone_scheduler_services", "scheduler", "metrics.stop"),
    ("stop_standalone_scheduler_services", "scheduler", "export.signal"),
    ("shutdown_standalone_formula_pool", None, "formula.stop"),
    ("shutdown_standalone_ocr", "worker", "ocr.executor.stop"),
    ("shutdown_standalone_ocr", "worker", "ocr.gateway.stop"),
    ("shutdown_standalone_render_resources", None, "executors.stop"),
    ("shutdown_standalone_render_resources", None, "executors.clear"),
    ("shutdown_standalone_render_resources", None, "pdf.stop"),
    ("close_standalone_runtime_connections", None, "queue.close"),
    ("close_standalone_runtime_connections", None, "db.dispose"),
    ("close_standalone_runtime_connections", None, "orphans.stop"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,role,failed", FAILURES)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_shutdown_sections_keep_original_nonfatal_errors_and_cancel_propagation(
    operations, role_runtime, name, role, failed, error_type,
):
    state = role_runtime
    state.gateway = SimpleNamespace(shutdown=state.asynchronous("ocr.gateway.stop"))
    error = error_type("synthetic standalone shutdown error")
    state.failures[failed] = error
    args = [state.logger] if role is None else [role, state.logger]
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await getattr(operations, name)(*args)
        assert caught.value is error and state.events[-1] == failed
        state.logger.warning.assert_not_called()
        state.logger.exception.assert_not_called()
    else:
        await getattr(operations, name)(*args)
        silent = failed in {"queue.draining", "ocr.gateway.stop"}
        assert state.logger.warning.call_count + state.logger.exception.call_count == int(not silent)
        if failed == "executors.stop":
            assert state.events == ["executors.stop", "pdf.stop"]
        if failed == "ocr.executor.stop":
            assert state.events[-1] == "ocr.gateway.stop"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,role,message", [
    ("shutdown_standalone_formula_pool", None, "Formula render pool shutdown timed out"),
    ("shutdown_standalone_ocr", "worker", None),
])
async def test_formula_timeout_warns_without_http_force_retry_and_ocr_timeout_uses_exception_log(
    operations, role_runtime, name, role, message,
):
    state = role_runtime
    state.failures["deadline"] = TimeoutError("synthetic timeout")
    args = [state.logger] if role is None else [role, state.logger]
    await getattr(operations, name)(*args)
    assert state.deadlines == [30]
    assert not state.events
    if message:
        state.logger.warning.assert_called_once_with(message)
        assert not state.thread_calls
    else:
        state.logger.exception.assert_called_once_with("OCR executor shutdown error")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "web"])
async def test_ocr_profile_import_is_outside_error_handler_only_for_worker(operations, role_runtime, monkeypatch, role):
    original = builtins.__import__
    error = ImportError("synthetic profile module unavailable")

    def guarded(name, *args, **kwargs):
        if name == "app.core.deployment_profile":
            raise error
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    if role == "worker":
        with pytest.raises(ImportError) as caught:
            await operations.shutdown_standalone_ocr(role, role_runtime.logger)
        assert caught.value is error
    else:
        await operations.shutdown_standalone_ocr(role, role_runtime.logger)
    assert not role_runtime.events


@pytest.mark.asyncio
@pytest.mark.parametrize("cloud", [False, True])
async def test_cloud_skips_local_executor_import_and_gateway_import_errors_are_silent(operations, role_runtime, monkeypatch, cloud):
    state = role_runtime
    state.cloud = cloud
    original, attempts = builtins.__import__, []

    def guarded(name, *args, **kwargs):
        if name in {"app.services.ocr_executor_service", "app.services.ocr_service"}:
            attempts.append(name)
            raise ImportError("synthetic unavailable OCR shutdown port")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    await operations.shutdown_standalone_ocr("worker", state.logger)
    assert attempts == (
        ["app.services.ocr_service"] if cloud else
        ["app.services.ocr_executor_service", "app.services.ocr_service"]
    )
    assert not state.events
    assert state.logger.exception.call_count == int(not cloud)
    state.logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_close_warning_failure_propagates_before_following_resources(operations, role_runtime):
    state = role_runtime
    state.failures["queue.close"] = RuntimeError("synthetic queue close failure")
    error = RuntimeError("synthetic warning failure")
    state.logger.warning.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        await operations.close_standalone_runtime_connections(state.logger)
    assert caught.value is error
    assert state.events == ["queue.close"]
