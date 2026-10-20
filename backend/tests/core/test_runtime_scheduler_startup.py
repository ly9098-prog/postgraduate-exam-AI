"""Preserve scheduler import, await and caller logging boundaries."""

import asyncio
import builtins
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.core.runtime_scheduler_startup_probe import scheduler_operations

CASES = [
    ("start_audit_cleanup_scheduler", "app.services.audit_cleanup_scheduler",
     "audit_log_cleanup_scheduler", "Audit log cleanup scheduler started"),
    ("start_recommendation_metrics_scheduler", "app.services.recommendation_metrics_scheduler",
     "recommendation_metrics_scheduler", "Recommendation metrics scheduler started"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,module,singleton,message", CASES)
@pytest.mark.parametrize("outcome", ["success", "error", "cancel", "import", "log"])
async def test_original_startup_awaits_once_and_preserves_errors_and_logger(
    monkeypatch, name, module, singleton, message, outcome,
):
    start, logger = AsyncMock(), Mock()
    monkeypatch.setitem(sys.modules, module, SimpleNamespace(**{singleton: SimpleNamespace(start=start)}))
    error = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("synthetic scheduler failure")
    if outcome in {"error", "cancel"}:
        start.side_effect = error
    elif outcome == "log":
        logger.info.side_effect = error
    original = builtins.__import__
    imported = []

    def guarded(imported_name, *args, **kwargs):
        if imported_name == module:
            imported.append(imported_name)
            if outcome == "import":
                raise error
        return original(imported_name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    operation = getattr(scheduler_operations(), name)
    if outcome == "success":
        assert await operation(logger) is None
    else:
        with pytest.raises(type(error)) as caught:
            await operation(logger)
        assert caught.value is error
    assert imported == [module]
    if outcome == "import":
        start.assert_not_awaited()
    else:
        start.assert_awaited_once_with()
    if outcome in {"success", "log"}:
        logger.info.assert_called_once_with(message)
    else:
        logger.info.assert_not_called()
    logger.warning.assert_not_called()
    logger.critical.assert_not_called()
