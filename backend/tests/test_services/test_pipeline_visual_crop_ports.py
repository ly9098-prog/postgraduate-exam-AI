"""Pin captured crop ports, live executor imports and cancellation boundaries."""

import asyncio
import hashlib

import pytest

from app.core import executor_registry
from app.services import storage_backend, visual_region_cropper, visual_region_types
from tests.visual_crop_support import VisualCropHarness, region


@pytest.fixture
def harness(monkeypatch):
    return VisualCropHarness(monkeypatch)


@pytest.mark.asyncio
async def test_crop_and_storage_are_captured_but_executor_import_remains_live(
    monkeypatch, harness
):
    state = harness
    crop, executor = state.crop, state.executor
    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError("captured storage/crop port was rebound")

    def replacement_executor(name):
        calls.append(name)
        return executor(name)

    async def changing_crop(*args):
        monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", forbidden)
        monkeypatch.setattr(storage_backend, "get_storage", forbidden)
        monkeypatch.setattr(executor_registry, "get_executor", replacement_executor)
        state.pipeline.pipeline_id = "changed-after-first-crop"
        return await crop(*args)

    monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", changing_crop)
    questions = [{"visual_regions": [region()]}, {"visual_regions": [region()]}]
    result = await state.run(questions)
    assert result["questions"] is questions and len(state.regions) == 2
    import_id = hashlib.md5(b"visual-crop-test").hexdigest()[:8]
    assert all(item[1] == import_id for item in state.regions)
    assert all(f"/{import_id}_snapshot_" in key for key, _ in state.uploads)
    assert calls == ["file_io", "file_io"]


@pytest.mark.asyncio
async def test_snapshot_failure_logger_reads_current_pipeline_id(monkeypatch, harness):
    crop = harness.crop

    async def changing_crop(*args):
        harness.pipeline.pipeline_id = "current-id"
        return await crop(*args)

    monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", changing_crop)
    harness.errors["run"] = RuntimeError("snapshot failure")
    await harness.run([{"visual_regions": [region()]}])
    assert harness.logger.warning.call_args.args[1] == "current-id"


@pytest.mark.asyncio
async def test_snapshot_stem_is_captured_before_crop_but_projection_reads_live_question(
    monkeypatch, harness
):
    question = {
        "parsed_content": {"text": "captured stem"},
        "visual_regions": [region()],
    }
    crop = harness.crop

    async def changing_crop(*args):
        question["stem"] = "changed stem"
        question.pop("parsed_content")
        return await crop(*args)

    monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", changing_crop)
    harness.region_url = None
    await harness.run([question])
    assert question["parsed_content"]["text"] == "captured stem"


@pytest.mark.asyncio
async def test_region_constructor_is_captured_before_loop(monkeypatch, harness):
    crop = harness.crop

    async def changing_crop(*args):
        monkeypatch.setattr(
            visual_region_types,
            "VisualRegion",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("constructor rebound")
            ),
        )
        return await crop(*args)

    monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", changing_crop)
    await harness.run(
        [{"page_start": 9, "visual_regions": [region(), region(region_id="r2")]}]
    )
    assert len(harness.regions) == 2


@pytest.mark.asyncio
async def test_coordinate_enum_is_reimported_for_each_region(monkeypatch, harness):
    original = visual_region_types.CoordinateSpace
    crop = harness.crop
    seen = []
    harness.region_url = None

    class CoordinateProxy:
        IMAGE_PIXELS = original.IMAGE_PIXELS

        def __new__(cls, value):
            seen.append(value)
            return original(value)

    async def changing_crop(*args):
        monkeypatch.setattr(visual_region_types, "CoordinateSpace", CoordinateProxy)
        return await crop(*args)

    monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", changing_crop)
    await harness.run(
        [
            {
                "page_start": 9,
                "visual_regions": [
                    region(coordinate_space="pdf_points"),
                    region(region_id="r2", coordinate_space="normalized_1"),
                ],
            }
        ]
    )
    assert seen == ["normalized_1"]


@pytest.mark.asyncio
async def test_snapshot_crop_function_and_coordinate_source_are_reimported(
    monkeypatch, harness
):
    crop = harness.crop
    sentinel = object()

    def replacement_crop(*args, **kwargs):
        raise AssertionError("executor double must not execute image code")

    async def changing_crop(*args):
        monkeypatch.setattr(visual_region_cropper, "crop_region", replacement_crop)
        monkeypatch.setattr(
            visual_region_cropper,
            "CoordinateSpace",
            type("SnapshotCoordinates", (), {"IMAGE_PIXELS": sentinel}),
        )
        return await crop(*args)

    monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", changing_crop)
    await harness.run([{"visual_regions": [region()], "question_bbox": [1, 2, 3, 4]}])
    assert harness.jobs[0][1] is replacement_crop
    assert harness.jobs[0][3]["coordinate_space"] is sentinel


@pytest.mark.asyncio
async def test_replacement_region_retains_original_dedup_identity_and_table_policy(
    monkeypatch, harness
):
    crop = harness.crop
    table = {"type": "table", "region_id": "r1", "requires_review": False}

    async def changing_crop(pages, incoming, import_id):
        incoming.region_id = "replacement-id"
        incoming.region_type = visual_region_types.VisualRegionType.DIAGRAM
        return await crop(pages, incoming, import_id)

    monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", changing_crop)
    question = {
        "page_start": 9,
        "segments": [table],
        "visual_regions": [region(region_type="table"), region(region_type="table")],
    }
    result = await harness.run([question])
    assert question["segments"] == [table]
    assert table["source_image_url"] == harness.region_url
    assert len(harness.regions) == 1
    assert result["warnings"] == ["visual region r1 cropped for page 1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["storage", "crop"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_region_and_initialization_failures_are_not_snapshot_fallback(
    harness, stage, error_type
):
    error = error_type("synthetic region failure")
    harness.errors[stage] = error
    questions = [{"visual_regions": [region()]}, {"visual_regions": [region()]}]
    with pytest.raises(error_type) as caught:
        await harness.run(questions)
    assert caught.value is error
    assert harness.jobs == harness.uploads == []
    assert all("risk_flags" not in question for question in questions)
    harness.logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["crop", "run", "upload"])
async def test_real_task_cancel_keeps_partial_output_and_stops_next_question(
    monkeypatch, harness, stage
):
    entered = asyncio.Event()
    finalized = []

    async def pending(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finalized.append(True)

    if stage == "crop":
        monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", pending)
    elif stage == "run":
        monkeypatch.setattr(
            executor_registry,
            "get_executor",
            lambda name: type("Executor", (), {"run": staticmethod(pending)})(),
        )
    else:
        monkeypatch.setattr(harness.storage, "upload", pending)
    questions = [{"visual_regions": [region()]}, {"visual_regions": [region()]}]
    task = asyncio.create_task(harness.run(questions))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("visual-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert caught.value.args == ("visual-cancel",) and task.cancelled()
    assert finalized == [True]
    assert ("segments" in questions[0]) is (stage != "crop")
    assert "segments" not in questions[1]
    assert all("risk_flags" not in question for question in questions)
    harness.logger.warning.assert_not_called()
