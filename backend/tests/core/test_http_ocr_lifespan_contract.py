"""Exercise partial OCR startup through the complete HTTP lifespan."""

import asyncio

import pytest

from app import main
from tests.core.http_lifespan_ports import runtime as runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [
    "ocr.client.create", "ocr.worker.create", "ocr.gateway.create", "ocr.gateway.publish",
])
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_partial_ocr_startup_keeps_original_resource_cleanup_boundary(
    runtime, monkeypatch, failed, production, error_type,
):
    monkeypatch.setattr(main, "_production_mode", production)
    runtime.ocr_enabled = True
    error = error_type("synthetic partial OCR startup")
    runtime.failures[failed] = error
    fatal = production or error_type is asyncio.CancelledError
    if fatal:
        wrapped = error_type is RuntimeError
        with pytest.raises(SystemError if wrapped else error_type) as caught:
            async with main.lifespan(main.app):
                pytest.fail("fatal startup must not yield")
        assert (caught.value.__cause__ if wrapped else caught.value) is error
        assert "ocr.client.close" not in runtime.events
        assert "ocr.gateway.stop" not in runtime.events
        assert "db.dispose" not in runtime.events
        assert [task.get_name() for task in runtime.tasks] == ["event-loop-lag-monitor"]
        assert not runtime.tasks[0].done()
    else:
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
        assert ("ocr.client.close" in runtime.events) is (failed != "ocr.client.create")
        assert ("ocr.gateway.stop" in runtime.events) is (failed == "ocr.gateway.publish")
        assert "db.dispose" in runtime.events
        assert all(task.done() for task in runtime.tasks)
