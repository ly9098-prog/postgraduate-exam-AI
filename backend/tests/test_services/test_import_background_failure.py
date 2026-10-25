"""Compatibility contract for generic import background failure persistence."""

from __future__ import annotations

import pytest

from app.services.import_background_failure import record_background_pipeline_failure


class Session:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_failure_is_persisted_to_checkpoint_store_and_sentry(monkeypatch):
    calls = []

    async def update_status(*args, **kwargs):
        calls.append(("checkpoint", args, kwargs))

    async def set_store(pipeline_id, payload):
        calls.append(("store", pipeline_id, payload))

    def capture(exc, *, tags):
        calls.append(("capture", exc, tags))

    monkeypatch.setattr(
        "app.features.pipeline_checkpoint.update_pipeline_status",
        update_status,
    )
    exc = RuntimeError("backend failed")

    await record_background_pipeline_failure(
        pipeline_id="pl-1",
        source_type="pdf",
        source_file="book.pdf",
        exc=exc,
        async_session=lambda: Session(),
        set_pipeline_store=set_store,
        capture_exception=capture,
    )

    assert calls[0][0] == "checkpoint"
    assert calls[0][2] == {
        "status": "failed",
        "error_message": "backend failed",
        "finished": True,
    }
    assert calls[1] == (
        "store",
        "pl-1",
        {
            "pipeline_id": "pl-1",
            "status": "failed",
            "source_type": "pdf",
            "errors": ["后台任务崩溃: backend failed"],
            "started_at": "",
            "finished_at": "",
        },
    )
    assert calls[2] == (
        "capture",
        exc,
        {"pipeline_id": "pl-1", "stage": "pipeline_background"},
    )


@pytest.mark.asyncio
async def test_store_and_sentry_still_run_when_checkpoint_persistence_fails(
    monkeypatch,
):
    calls = []

    async def update_status(*args, **kwargs):
        raise RuntimeError("database unavailable")

    async def set_store(pipeline_id, payload):
        calls.append(("store", pipeline_id, payload))

    def capture(exc, *, tags):
        calls.append(("capture", exc, tags))

    monkeypatch.setattr(
        "app.features.pipeline_checkpoint.update_pipeline_status",
        update_status,
    )
    exc = ValueError("invalid source")

    await record_background_pipeline_failure(
        pipeline_id="pl-2",
        source_type="txt",
        source_file="source.txt",
        exc=exc,
        async_session=lambda: Session(),
        set_pipeline_store=set_store,
        capture_exception=capture,
    )

    assert [call[0] for call in calls] == ["store", "capture"]
