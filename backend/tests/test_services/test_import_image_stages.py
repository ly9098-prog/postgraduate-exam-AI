"""Contracts for image-import checkpoint and OCR stage preparation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.import_image_stages import (
    ImageOcrStage,
    ImageCompletionPersistence,
    ImagePipelineStage,
    ImageStageCheckpointRequest,
    ensure_image_checkpoint,
    run_image_pipeline_stage,
    run_prepared_image_ocr,
    persist_image_completion,
)


def checkpoint_request(**overrides):
    db = SimpleNamespace()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    ensure_record = AsyncMock()
    request = ImageStageCheckpointRequest(
        pipeline_id="img-1",
        source_file="source.png",
        created_by="admin",
        async_session=lambda: session,
        ensure_record=ensure_record,
    )
    for key, value in overrides.items():
        setattr(request, key, value)
    return SimpleNamespace(
        request=request, session=session, db=db, ensure_record=ensure_record
    )


@pytest.mark.asyncio
async def test_checkpoint_uses_independent_session_and_existing_record_contract():
    item = checkpoint_request(source_file="")
    await ensure_image_checkpoint(item.request)
    item.ensure_record.assert_awaited_once_with(
        item.db,
        pipeline_id="img-1",
        source_type="image",
        source_file=None,
        total_pages=1,
        chunk_size=1,
        created_by="admin",
        status="processing",
    )


@pytest.mark.asyncio
async def test_prepared_ocr_reads_bytes_sets_tags_and_delegates(monkeypatch, tmp_path):
    image = tmp_path / "source.png"
    image.write_bytes(b"image-bytes")
    tags = []
    stage_module = SimpleNamespace(
        ImageOcrStageRequest=lambda **kwargs: kwargs,
        run_image_ocr_stage=AsyncMock(return_value="ocr-result"),
    )
    monkeypatch.setattr(
        "app.services.import_image_stages.ImageOcrStageRequest",
        stage_module.ImageOcrStageRequest,
    )
    monkeypatch.setattr(
        "app.services.import_image_stages.run_image_ocr_stage",
        stage_module.run_image_ocr_stage,
    )
    stage = ImageOcrStage(
        pipeline_id="img-1",
        image_path=str(image),
        source_file="source.png",
        read_bytes=lambda _path: b"unused",
        set_stage_tags=lambda stage_name, engine: tags.append((stage_name, engine)),
        build_runtime_diagnostics=lambda: {},
        run_ocr=AsyncMock(return_value={}),
        clean_text=lambda value: value,
        build_diagnostics=lambda raw, clean: {},
        build_blocks=lambda **_kwargs: [],
        set_status=AsyncMock(return_value={}),
    )

    result = await run_prepared_image_ocr(stage)

    assert result.image_bytes == b"image-bytes"
    assert result.stage_result == "ocr-result"
    assert tags == [("ocr", "PaddleOCR")]
    fields = stage_module.run_image_ocr_stage.call_args.args[0]
    assert {key: fields[key] for key in fields if key != "image_bytes"} == {
        "pipeline_id": "img-1",
        "source_file": "source.png",
        "build_runtime_diagnostics": stage.build_runtime_diagnostics,
        "run_ocr": stage.run_ocr,
        "clean_text": stage.clean_text,
        "build_diagnostics": stage.build_diagnostics,
        "build_blocks": stage.build_blocks,
        "set_status": stage.set_status,
    }
    assert fields["image_bytes"] == b"image-bytes"


@pytest.mark.asyncio
async def test_image_pipeline_stage_rechecks_record_and_runs_pipeline_in_session():
    db = SimpleNamespace()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    ensure_record = AsyncMock()
    run_pipeline = AsyncMock(return_value={"status": "completed"})
    stage = ImagePipelineStage(
        pipeline_id="img-1",
        source_file="source.png",
        subject="DS",
        subject_id=3,
        options={"image_fast_mode": True},
        created_by="admin",
        image_bytes=b"image-bytes",
        cleaned_text="cleaned",
        pre_extracted_blocks=[{"boxes": []}],
        async_session=lambda: session,
        ensure_record=ensure_record,
        run_pipeline=run_pipeline,
    )

    result = await run_image_pipeline_stage(stage)

    assert result == {"status": "completed"}
    ensure_record.assert_awaited_once_with(
        db,
        pipeline_id="img-1",
        source_type="image",
        source_file="source.png",
        total_pages=1,
        chunk_size=1,
        created_by="admin",
        status="processing",
    )
    run_pipeline.assert_awaited_once_with(
        file_content=b"cleaned",
        source_type="txt",
        source_file="source.png",
        subject="DS",
        subject_id=3,
        options={"image_fast_mode": True},
        db=db,
        page_images={1: b"image-bytes"},
        pre_extracted_blocks=[{"boxes": []}],
    )


@pytest.mark.asyncio
async def test_completion_persistence_projects_status_and_finishes_record():
    db = SimpleNamespace()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    get_status = AsyncMock(return_value={"started_at": "started"})
    set_status = AsyncMock()
    update_record = AsyncMock()
    events = []
    result = {
        "status": "failed",
        "diagnostics": {"failure_reason": "no_review_batch_created"},
    }

    await persist_image_completion(
        ImageCompletionPersistence(
            pipeline_id="img-1",
            source_file="source.png",
            result=result,
            status="failed",
            async_session=lambda: session,
            get_status=get_status,
            set_status=set_status,
            update_record=update_record,
            log_event=lambda *args, **kwargs: events.append((args, kwargs)),
        )
    )

    assert result["started_at"] == "started"
    set_status.assert_awaited_once_with("img-1", **result)
    update_record.assert_awaited_once_with(
        db,
        "img-1",
        status="failed",
        error_message="no_review_batch_created",
        finished=True,
    )
    assert events[0][1] == {
        "pipeline_id": "img-1",
        "source_type": "image",
        "source_file": "source.png",
        "status": "failed",
    }
