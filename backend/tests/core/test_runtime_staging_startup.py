"""Startup sweep policy preserves lazy imports, logging and cancellation."""

import asyncio
import builtins
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.core.runtime_staging_probe import staging_startup_operation


@pytest.fixture(params=["http", "standalone"])
def sweep_ports(request, monkeypatch):
    state = SimpleNamespace(
        operation=staging_startup_operation(request.param), logger=Mock(),
        sweep=AsyncMock(return_value=1), log_event=Mock(), imports=[],
        import_error=None, failed_import=None,
    )
    monkeypatch.setitem(sys.modules, "app.services.staging_storage", SimpleNamespace(
        async_sweep_temp_files=state.sweep,
    ))
    monkeypatch.setitem(sys.modules, "app.core.log_context", SimpleNamespace(
        log_event=state.log_event,
    ))
    original_import = builtins.__import__

    def importing(name, *args, **kwargs):
        if name in {"app.core.log_context", "app.services.staging_storage"}:
            state.imports.append(name)
            if name == state.failed_import:
                raise state.import_error
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, -1, None, [], {"retained": 2}])
async def test_startup_sweep_keeps_truthiness_and_exact_event_payload(sweep_ports, count):
    state = sweep_ports
    state.sweep.return_value = count
    assert await state.operation(state.logger) is None
    state.sweep.assert_awaited_once_with()
    assert state.imports == ["app.core.log_context", "app.services.staging_storage"]
    if count:
        state.log_event.assert_called_once_with(state.logger, "staging.sweep", count=count)
        assert state.log_event.call_args.kwargs["count"] is count
    else:
        state.log_event.assert_not_called()
    state.logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["sweep", "event", "truthiness"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_startup_sweep_ordinary_errors_warn_and_cancellation_propagates(sweep_ports, stage, error_type):
    state = sweep_ports
    error = error_type("synthetic startup sweep failure")
    if stage == "truthiness":
        class Count:
            def __bool__(self):
                raise error
        state.sweep.return_value = Count()
    else:
        getattr(state, "sweep" if stage == "sweep" else "log_event").side_effect = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await state.operation(state.logger)
        assert caught.value is error
        state.logger.warning.assert_not_called()
    else:
        assert await state.operation(state.logger) is None
        state.logger.warning.assert_called_once_with(
            "Staging temp sweep failed (non-fatal)", exc_info=True,
        )
    if stage != "event":
        state.log_event.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_import", ["app.core.log_context", "app.services.staging_storage"])
@pytest.mark.parametrize("error_type", [ImportError, RuntimeError, asyncio.CancelledError])
async def test_startup_sweep_import_failure_keeps_original_catch_boundary(sweep_ports, failed_import, error_type):
    state = sweep_ports
    state.failed_import, state.import_error = failed_import, error_type("synthetic import failure")
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await state.operation(state.logger)
        assert caught.value is state.import_error
        state.logger.warning.assert_not_called()
    else:
        await state.operation(state.logger)
        state.logger.warning.assert_called_once_with(
            "Staging temp sweep failed (non-fatal)", exc_info=True,
        )
    state.sweep.assert_not_awaited()
    state.log_event.assert_not_called()
    assert state.imports == (
        ["app.core.log_context"] if failed_import == "app.core.log_context"
        else ["app.core.log_context", "app.services.staging_storage"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_startup_sweep_warning_failure_propagates(sweep_ports, error_type):
    state = sweep_ports
    state.sweep.side_effect = RuntimeError("synthetic storage failure")
    error = error_type("synthetic warning failure")
    state.logger.warning.side_effect = error
    with pytest.raises(error_type) as caught:
        await state.operation(state.logger)
    assert caught.value is error


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["http", "standalone"])
async def test_real_startup_scan_runs_off_loop_and_preserves_fresh_files(monkeypatch, tmp_path, entrypoint):
    from app.services import staging_storage

    fresh = tmp_path / "fresh.tmp"
    fresh.write_bytes(b"synthetic fresh content")
    nested = tmp_path / "objects" / "retained.data"
    nested.parent.mkdir()
    nested.write_bytes(b"synthetic nested content")
    monkeypatch.setattr(staging_storage, "_STAGING_DIR", tmp_path)
    original = staging_storage.sweep_temp_files
    thread_ids = []

    def scan():
        thread_ids.append(threading.get_ident())
        return original()

    monkeypatch.setattr(staging_storage, "sweep_temp_files", scan)
    logger = Mock()
    assert await staging_startup_operation(entrypoint)(logger) is None
    assert len(thread_ids) == 1 and thread_ids[0] != threading.get_ident()
    assert fresh.read_bytes() == b"synthetic fresh content"
    assert nested.read_bytes() == b"synthetic nested content"
    logger.warning.assert_not_called()
