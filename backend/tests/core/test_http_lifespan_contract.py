"""Run the actual HTTP lifespan with isolated resource and persistence ports."""

import asyncio
import os

import pytest

from app import main
from tests.core.http_lifespan_ports import runtime as runtime

COMMON_STOP = [
    "formula.stop", "executors.stop", "executors.clear", "pdf.stop", "queue.close",
    "ai.close", "budget.close", "db.dispose", "orphans.stop",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [0, 1, 2, 3])
@pytest.mark.parametrize("error_type", [PermissionError, asyncio.CancelledError])
async def test_runtime_directory_failure_precedes_database_and_tasks(runtime, monkeypatch, failed, error_type):
    paths = []
    error = error_type("synthetic complete startup directory failure")

    def mkdir(path, **kwargs):
        paths.append((path, kwargs))
        if len(paths) == failed + 1:
            raise error

    with monkeypatch.context() as patch:
        patch.setattr(os, "makedirs", mkdir)
        with pytest.raises(error_type) as caught:
            async with main.lifespan(main.app):
                pytest.fail("failed directory preparation must not yield")
    assert caught.value is error
    expected = ["static/formulas", "static/question-assets", "static/avatars", main.settings.EXPORT_DIR]
    assert paths == [(path, {"exist_ok": True}) for path in expected[:failed + 1]]
    assert "export.config" in runtime.events
    assert "db.init" not in runtime.events and not runtime.tasks
    assert [event for event in runtime.events if event in COMMON_STOP] == COMMON_STOP


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_startup_sweep_precedes_resources_and_preserves_failure_boundary(runtime, error_type):
    error = error_type("synthetic HTTP startup sweep failure")
    runtime.failures["staging.sweep"] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            async with main.lifespan(main.app):
                pytest.fail("cancelled startup sweep must not yield")
        assert caught.value is error
        assert not runtime.tasks
        assert "db.init" not in runtime.events
        assert [event for event in runtime.events if event in COMMON_STOP] == COMMON_STOP
    else:
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
        runtime.logger.warning.assert_any_call(
            "Staging temp sweep failed (non-fatal)", exc_info=True,
        )
        assert runtime.events.index("staging.sweep") < runtime.events.index("db.init")
        assert all(task.done() for task in runtime.tasks)
        assert [event for event in runtime.events if event in COMMON_STOP] == COMMON_STOP


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_export_config_failure_preserves_http_startup_boundary(runtime, error_type):
    error = error_type("synthetic complete export configuration failure")
    runtime.failures["export.config"] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            async with main.lifespan(main.app):
                pytest.fail("cancelled export configuration must not yield")
        assert caught.value is error
        assert not runtime.tasks and "db.init" not in runtime.events
        assert [event for event in runtime.events if event in COMMON_STOP] == COMMON_STOP
    else:
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
        runtime.logger.warning.assert_any_call(
            "Export config logging failed (non-fatal)", exc_info=True,
        )
        assert all(task.done() for task in runtime.tasks)
        assert [event for event in runtime.events if event in COMMON_STOP] == COMMON_STOP


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["web", "all", "unknown"])
@pytest.mark.parametrize("ocr_enabled", [False, True])
async def test_real_lifespan_success_owns_tasks_and_preserves_close_order(runtime, monkeypatch, role, ocr_enabled):
    monkeypatch.setattr(main.settings, "PROCESS_ROLE", role)
    monkeypatch.setattr(main.settings, "LOCAL_ASYNC_RUNTIME_ENABLED", True)
    runtime.ocr_enabled = ocr_enabled
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
        assert runtime.tasks
        assert all(not task.done() for task in runtime.tasks)
        if role == "all":
            assert runtime.enqueue is not None
            assert await runtime.enqueue("synthetic-id", "synthetic-type", {}, 2) == "synthetic-task"
    assert all(task.done() for task in runtime.tasks)
    events = runtime.events
    assert [name for name in events if name in COMMON_STOP] == COMMON_STOP
    assert events.index("end:lag") < events.index("formula.stop")
    if role in {"web", "all"}:
        assert events.index("ocr.executor.stop") < events.index("executors.stop")
        if ocr_enabled:
            assert events.index("ocr.executor.stop") < events.index("ocr.gateway.stop") < events.index("ocr.client.close") < events.index("executors.stop")
        else:
            assert "ocr.client.close" not in events
    else:
        assert "ocr.executor.stop" not in events
    if role == "all":
        assert events.index("queue.drain") < events.index("end:lag")
        assert events.index("audit.stop") < events.index("metrics.stop") < events.index("prewarm.stop") < events.index("formula.stop")
    warnings = runtime.logger.warning.call_args_list
    assert len(warnings) == int(role in {"web", "all"})
    if warnings:
        assert warnings[0].args[0].startswith(
            "process_role=web export_processor_enabled=false" if role == "web" else "Role=%s: API + worker + scheduler",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_yield_body_failure_still_cleans_resources_and_propagates_original(runtime, error_type):
    error = error_type("synthetic request-side failure")
    with pytest.raises(error_type) as caught:
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
            raise error
    assert caught.value is error
    assert [name for name in runtime.events if name in COMMON_STOP] == COMMON_STOP
    assert all(task.done() for task in runtime.tasks)


@pytest.mark.asyncio
async def test_actual_serving_task_cancellation_finishes_owned_tasks_and_resource_cleanup(runtime):
    ready = asyncio.Event()

    async def serve():
        async with main.lifespan(main.app):
            ready.set()
            await asyncio.Future()

    server = asyncio.get_running_loop().create_task(serve())
    try:
        await asyncio.wait_for(ready.wait(), timeout=5)
        server.cancel()
        with pytest.raises(asyncio.CancelledError):
            await server
    finally:
        if not server.done():
            server.cancel()
        await asyncio.gather(server, return_exceptions=True)
    assert [name for name in runtime.events if name in COMMON_STOP] == COMMON_STOP
    assert all(task.done() for task in runtime.tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "scheduler"])
async def test_http_rejects_standalone_roles_before_any_startup(runtime, monkeypatch, role):
    monkeypatch.setattr(main.settings, "PROCESS_ROLE", role)
    monkeypatch.setattr(main.settings, "LOCAL_ASYNC_RUNTIME_ENABLED", True)
    with pytest.raises(SystemError, match=f"PROCESS_ROLE={role} must not start"):
        async with main.lifespan(main.app):
            pytest.fail("standalone role must not yield an HTTP application")
    assert runtime.events == []
    assert not runtime.tasks


@pytest.mark.asyncio
async def test_local_role_resolution_updates_settings_and_environment(runtime, monkeypatch):
    monkeypatch.setattr(main.settings, "PROCESS_ROLE", "all")
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
        assert main.settings.PROCESS_ROLE == "web"
        assert os.environ["PROCESS_ROLE"] == "web"
        assert [task.get_name() for task in runtime.tasks] == [
            "event-loop-lag-monitor", "export-processor-local",
        ]
    assert "audit.start" not in runtime.events
    assert all(task.done() for task in runtime.tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["executors.init", "ocr.gateway.create", "orphans.start"])
async def test_nonfatal_startup_errors_yield_then_close_existing_resources(runtime, failed):
    runtime.ocr_enabled = True
    runtime.failures[failed] = RuntimeError("synthetic nonfatal startup failure")
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
    assert [name for name in runtime.events if name in COMMON_STOP] == COMMON_STOP
    assert all(task.done() for task in runtime.tasks)
    assert "ocr.client.close" in runtime.events
    if failed == "ocr.gateway.create":
        assert "ocr.gateway.stop" not in runtime.events
        assert "ocr.worker.stop" in runtime.events


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["config.sync", "config.async", "db.init", "executors.init", "ocr.gateway.create"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_pre_yield_failure_cleans_created_resources_and_preserves_original_error(
    runtime, monkeypatch, failed, error_type,
):
    monkeypatch.setattr(main, "_production_mode", True)
    runtime.ocr_enabled = True
    error = error_type("synthetic startup failure")
    runtime.failures[failed] = error
    if failed == "ocr.gateway.create":
        runtime.failures["ocr.client.close"] = RuntimeError(
            "synthetic client close failure"
        )
    wrapped = error_type is RuntimeError and failed in {"executors.init", "ocr.gateway.create"}
    with pytest.raises(SystemError if wrapped else error_type) as caught:
        async with main.lifespan(main.app):
            pytest.fail("startup failure must not yield")
    assert (caught.value.__cause__ if wrapped else caught.value) is error
    assert [name for name in runtime.events if name in COMMON_STOP] == COMMON_STOP
    assert "export.signal" not in runtime.events
    assert ("ocr.client.close" in runtime.events) is (
        failed in {"ocr.gateway.create"}
    )
    assert ("ocr.worker.stop" in runtime.events) is (
        failed == "ocr.gateway.create"
    )
    if failed == "ocr.gateway.create":
        assert runtime.client is not None
        assert [task.get_name() for task in runtime.tasks] == ["event-loop-lag-monitor"]
        assert runtime.tasks[0].done()
    else:
        assert not runtime.tasks
    assert all(task.done() for task in runtime.tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_cleanup_error_for_pre_yield_failure_does_not_override_startup_error(runtime, error_type):
    startup_error = error_type("synthetic startup failure")
    runtime.failures["db.init"] = startup_error
    runtime.failures["pdf.stop"] = RuntimeError("synthetic cleanup failure")
    with pytest.raises(error_type) as caught:
        async with main.lifespan(main.app):
            pytest.fail("startup failure must not yield")
    assert caught.value is startup_error
    assert [name for name in runtime.events if name in COMMON_STOP] == COMMON_STOP
    assert runtime.logger.warning.called


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_shared_client_close_failure_preserves_remaining_shutdown(runtime, error_type):
    runtime.ocr_enabled = True
    error = error_type("synthetic shared client close failure")
    runtime.failures["ocr.client.close"] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(error_type) as caught:
            async with main.lifespan(main.app):
                await asyncio.sleep(0)
        assert caught.value is error
        assert "ocr.gateway.stop" in runtime.events
        assert "ocr.client.close" in runtime.events
        assert "executors.stop" not in runtime.events
        assert "db.dispose" not in runtime.events
        assert "orphans.stop" not in runtime.events
    else:
        with pytest.raises(RuntimeError) as caught:
            async with main.lifespan(main.app):
                await asyncio.sleep(0)
        assert caught.value is error
        assert [name for name in runtime.events if name in COMMON_STOP] == COMMON_STOP
        assert runtime.events[-1] == "orphans.stop"
        assert runtime.logger.warning.called
    assert all(task.done() for task in runtime.tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_shared_client_close_error_does_not_override_startup_error(runtime, error_type):
    runtime.ocr_enabled = True
    startup_error = error_type("synthetic startup failure")
    runtime.failures["db.init"] = startup_error
    runtime.failures["ocr.client.close"] = RuntimeError("synthetic client close failure")
    with pytest.raises(error_type) as caught:
        async with main.lifespan(main.app):
            pytest.fail("startup failure must not yield")
    assert caught.value is startup_error
    assert [name for name in runtime.events if name in COMMON_STOP] == COMMON_STOP
    assert runtime.logger.warning.called


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["executors.stop", "pdf.stop", "queue.close", "ai.close", "budget.close", "db.dispose"])
async def test_common_resource_error_preserves_following_cleanup(runtime, failed):
    runtime.failures[failed] = RuntimeError("synthetic resource close failure")
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
    skipped = {"executors.clear"} if failed == "executors.stop" else {"budget.close"} if failed == "ai.close" else set()
    assert [name for name in runtime.events if name in COMMON_STOP] == [
        name for name in COMMON_STOP if name not in skipped
    ]
    assert runtime.events[-1] == "orphans.stop"
    assert all(task.done() for task in runtime.tasks)
