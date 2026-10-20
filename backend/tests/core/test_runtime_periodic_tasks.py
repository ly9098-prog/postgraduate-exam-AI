"""Characterize periodic task IDs, labels, lazy imports and cancellation."""

import asyncio
import builtins
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.core.runtime_periodic_probe import periodic_operations

CASES = [
    ("_periodic_token_cleanup", "refresh_token_cleanup", "Refresh token cleanup"),
    ("_periodic_staging_cleanup", "staging_cleanup", "Staging cleanup"),
    ("_periodic_export_cleanup", "export_cleanup", "Export cleanup"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["http", "standalone"])
@pytest.mark.parametrize("name,task_id,label", CASES)
@pytest.mark.parametrize("outcome", ["success", "error", "cancel", "import"])
async def test_periodic_cleanup_uses_original_catalog_id_label_and_failure_boundary(
    monkeypatch, entry, name, task_id, label, outcome,
):
    run = AsyncMock()
    module = "app.services.system_task_service"
    monkeypatch.setitem(sys.modules, module, SimpleNamespace(run_registered_periodic_task=run))
    error = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("synthetic periodic failure")
    if outcome in {"error", "cancel"}:
        run.side_effect = error
    imported = []
    original = builtins.__import__

    def guarded(imported_name, *args, **kwargs):
        if imported_name == module:
            imported.append(imported_name)
            if outcome == "import":
                raise error
        return original(imported_name, *args, **kwargs)

    operation = getattr(periodic_operations(entry), name)
    monkeypatch.setattr(builtins, "__import__", guarded)
    if outcome == "success":
        assert await operation() is None
    else:
        with pytest.raises(type(error)) as caught:
            await operation()
        assert caught.value is error
    assert imported == [module]
    if outcome == "import":
        run.assert_not_awaited()
    else:
        run.assert_awaited_once_with(task_id, label)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["http", "standalone"])
@pytest.mark.parametrize("outcome", ["success", "error", "cancel", "import", "log"])
async def test_export_processor_keeps_caller_logger_and_exception_policy(monkeypatch, entry, outcome):
    run, logger = AsyncMock(), Mock()
    module = "app.services.export.processor"
    monkeypatch.setitem(sys.modules, module, SimpleNamespace(run_export_processor=run))
    error = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("synthetic export failure")
    if outcome in {"error", "cancel", "log"}:
        run.side_effect = error
    operation = periodic_operations(entry)._periodic_export_processor
    module_entry = __import__("app.main" if entry == "http" else "app.core.bootstrap", fromlist=["logger"])
    monkeypatch.setattr(module_entry, "logger", logger)
    original = builtins.__import__
    imported = []

    def guarded(name, *args, **kwargs):
        if name == module:
            imported.append(name)
            if outcome == "import":
                raise error
        return original(name, *args, **kwargs)

    log_error = RuntimeError("synthetic warning failure")
    if outcome == "log":
        logger.warning.side_effect = log_error
    monkeypatch.setattr(builtins, "__import__", guarded)
    if outcome in {"cancel", "log"}:
        with pytest.raises(type(error if outcome == "cancel" else log_error)) as caught:
            await operation()
        assert caught.value is (error if outcome == "cancel" else log_error)
    else:
        assert await operation() is None
    assert imported == [module]
    if outcome == "import":
        run.assert_not_awaited()
    else:
        run.assert_awaited_once_with()
    if outcome in {"error", "import", "log"}:
        logger.warning.assert_called_once_with("Export processor exited: %s", error)
    else:
        logger.warning.assert_not_called()
