"""Exercise HTTP prerun shutdown helpers without starting external resources."""

import asyncio

import pytest

from app.core import runtime_http_shutdown
from types import SimpleNamespace
from unittest.mock import Mock


@pytest.fixture
def logger(monkeypatch):
    logger = SimpleNamespace(
        info=Mock(), warning=Mock(), exception=Mock(),
    )
    monkeypatch.setattr(runtime_http_shutdown, "logger", logger)
    return logger


@pytest.mark.asyncio
async def test_stop_lag_monitor_cancels_and_awaits_pending_task(logger):
    events = []

    async def lag():
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            events.append("cancelled")
            raise

    task = asyncio.get_running_loop().create_task(lag())
    await asyncio.sleep(0)
    assert not task.done()
    await runtime_http_shutdown.stop_lag_monitor(task)
    assert events == ["cancelled"]
    assert task.done()


@pytest.mark.asyncio
async def test_stop_lag_monitor_skips_none_and_done_tasks(logger):
    # None task: no-op
    await runtime_http_shutdown.stop_lag_monitor(None)

    # Use a real completed task: no cancellation attempted
    async def completed():
        return 42

    done_task = asyncio.get_running_loop().create_task(completed())
    await done_task
    assert done_task.done()
    await runtime_http_shutdown.stop_lag_monitor(done_task)
    logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_stop_export_processor_calls_stop_and_logs(logger, monkeypatch):
    called = []

    async def stop_processor():
        called.append("stop")

    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "app.services.export.processor", SimpleNamespace(stop_processor=stop_processor))
    await runtime_http_shutdown.stop_export_processor("all")
    assert called == ["stop"]
    logger.info.assert_called_once_with("export_processor_stopped role=%s", "all")
    logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_stop_export_processor_import_error_is_warning(logger, monkeypatch):
    import builtins

    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "app.services.export.processor":
            raise ImportError("synthetic unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    await runtime_http_shutdown.stop_export_processor("web")
    logger.warning.assert_called_once()
    assert "Export processor stop signal failed" in logger.warning.call_args[0][0]


@pytest.mark.asyncio
async def test_stop_export_processor_runtime_error_is_warning(logger, monkeypatch):
    error = RuntimeError("synthetic stop failure")

    async def stop_processor():
        raise error

    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "app.services.export.processor", SimpleNamespace(stop_processor=stop_processor))
    await runtime_http_shutdown.stop_export_processor("scheduler")
    logger.warning.assert_called_once()
    assert logger.warning.call_args[0][1] is error


@pytest.mark.asyncio
async def test_stop_export_processor_cancel_propagates(logger, monkeypatch):
    error = asyncio.CancelledError("synthetic cancel")

    async def stop_processor():
        raise error

    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "app.services.export.processor", SimpleNamespace(stop_processor=stop_processor))
    with pytest.raises(asyncio.CancelledError) as caught:
        await runtime_http_shutdown.stop_export_processor("worker")
    assert caught.value is error
    logger.warning.assert_not_called()
    logger.info.assert_not_called()
