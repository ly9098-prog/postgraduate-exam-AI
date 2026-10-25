"""Contracts for the image-import background lifecycle."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.import_image_lifecycle import (
    ImageLifecycleRequest,
    persist_image_import_failure,
    run_image_import_lifecycle,
)


def session_harness() -> SimpleNamespace:
    db = SimpleNamespace()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    return SimpleNamespace(db=db, session=session)


def lifecycle_request(
    monkeypatch, tmp_path, execution_result=None, exc=None
) -> SimpleNamespace:
    harness = session_harness()
    image = tmp_path / "source.png"
    image.write_bytes(b"image-bytes")
    monkeypatch.setattr(
        "app.services.import_image_lifecycle.execute_image_pipeline_stages",
        AsyncMock(return_value=execution_result, side_effect=exc),
    )
    capture = Mock()
    events = []
    request = ImageLifecycleRequest(
        pipeline_id="img-1",
        image_path=str(image),
        source_file="source.png",
        subject="DS",
        subject_id=3,
        options={"image_fast_mode": True},
        created_by="admin",
        logger=logging.getLogger("test-image-lifecycle"),
        async_session=lambda: harness.session,
        ensure_record=AsyncMock(),
        update_record=AsyncMock(),
        run_pipeline=AsyncMock(return_value={"status": "completed"}),
        clean_text=lambda value: value,
        build_runtime_diagnostics=lambda: {"engine": "paddle"},
        run_ocr=AsyncMock(return_value={}),
        build_diagnostics=lambda raw, clean: {"raw": raw, "clean": clean},
        build_blocks=lambda **_kwargs: [],
        set_status=AsyncMock(),
        set_stage_tags=lambda *_args: None,
        apply_policy=lambda options, enabled: {**options, "fast": enabled},
        finalize_result=lambda completion: (
            {
                "pipeline_id": completion.pipeline_id,
                "status": "completed",
                "result": completion.result,
                "cleaned_text": completion.cleaned_text,
                "ocr_diagnostics": completion.ocr_diagnostics,
                "runtime_diagnostics": completion.runtime_diagnostics,
                "classifier": completion.classify_result(
                    completion.result, completion.cleaned_text
                ),
            },
            "completed",
        ),
        get_status=AsyncMock(return_value={"started_at": "started"}),
        fail_pipeline=AsyncMock(),
        log_event=lambda *args, **kwargs: events.append((args, kwargs)),
        classify_result=lambda result, text: "empty-text" if not text else None,
        capture_exception=capture,
    )
    return SimpleNamespace(
        request=request, harness=harness, capture=capture, events=events
    )


@pytest.mark.asyncio
async def test_lifecycle_finalizes_and_persists_completion(monkeypatch, tmp_path):
    item = lifecycle_request(
        monkeypatch,
        tmp_path,
        execution_result=SimpleNamespace(
            result={"status": "completed"},
            raw_text="cleaned",
            raw_ocr_text="raw",
            ocr_diagnostics={"lines": 1},
            runtime_diagnostics={"engine": "paddle"},
        ),
    )

    await run_image_import_lifecycle(item.request)

    assert item.events[-1][1]["status"] == "completed"
    item.request.get_status.assert_awaited_once_with("img-1")
    item.request.set_status.assert_awaited_once()
    item.request.update_record.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifecycle_failure_is_recorded_and_reraised(monkeypatch, tmp_path):
    exc = ValueError("ocr failed")
    item = lifecycle_request(monkeypatch, tmp_path, exc=exc)

    with pytest.raises(ValueError, match="ocr failed"):
        await run_image_import_lifecycle(item.request)

    assert item.events[-1][0][1] == "import.background.error"
    item.capture.assert_called_once_with(
        exc,
        tags={
            "pipeline_id": "img-1",
            "source_file": "source.png",
            "stage": "ocr",
        },
    )


@pytest.mark.asyncio
async def test_import_failure_persistence_uses_projected_update_record(
    monkeypatch, tmp_path
):
    item = lifecycle_request(monkeypatch, tmp_path)
    exc = ValueError("pipeline failed")

    await persist_image_import_failure(item.request, exc)

    item.request.fail_pipeline.assert_awaited_once_with("img-1", "pipeline failed")
    item.request.update_record.assert_awaited_once_with(
        item.harness.db,
        "img-1",
        status="failed",
        error_message="pipeline failed",
        finished=True,
    )
