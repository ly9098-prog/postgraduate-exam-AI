"""Complete HTTP all-role startup retains its scheduler failure policies."""

import asyncio

import pytest

from app import main
from tests.core.http_lifespan_ports import runtime as runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["audit.start", "metrics.start"])
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_http_scheduler_startup_keeps_entrypoint_failure_boundary(
    runtime, monkeypatch, failed, production, error_type,
):
    monkeypatch.setattr(main.settings, "PROCESS_ROLE", "all")
    monkeypatch.setattr(main.settings, "LOCAL_ASYNC_RUNTIME_ENABLED", True)
    monkeypatch.setattr(main, "_production_mode", production)
    error = error_type("synthetic HTTP scheduler startup failure")
    runtime.failures[failed] = error
    fatal = production or error_type is asyncio.CancelledError
    if fatal:
        wrapped = error_type is RuntimeError
        with pytest.raises(SystemError if wrapped else error_type) as caught:
            async with main.lifespan(main.app):
                pytest.fail("fatal scheduler startup must not yield")
        assert (caught.value.__cause__ if wrapped else caught.value) is error
        assert "formula.stop" not in runtime.events and "db.dispose" not in runtime.events
        assert [task.get_name() for task in runtime.tasks] == [
            "event-loop-lag-monitor", "pipeline-dispatcher-v2", "task-reaper-v2", "scheduler-heartbeat",
        ]
        assert all(not task.done() for task in runtime.tasks)
    else:
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
        assert runtime.events.index("audit.start") < runtime.events.index("metrics.start")
        assert "db.dispose" in runtime.events
        assert all(task.done() for task in runtime.tasks)
