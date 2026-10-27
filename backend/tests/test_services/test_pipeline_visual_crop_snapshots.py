"""Snapshot fallback, hashing, executor boundaries and partial output rules."""

import asyncio
import hashlib

import pytest

from app.services import visual_region_cropper
from tests.visual_crop_support import VisualCropHarness


@pytest.fixture
def harness(monkeypatch):
    return VisualCropHarness(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize("bbox", [None, [], [1, 2, 3], [1, 2, 3, 4], (1, 2, 3, 4)])
@pytest.mark.parametrize("parsed", ["absent", "none", "dict", "string"])
async def test_snapshot_executor_upload_and_projection(harness, bbox, parsed):
    question = {"stem": "original stem", "question_bbox": bbox}
    existing = {"text": "existing", "opaque": {"kept": 1}}
    if parsed != "absent":
        question["parsed_content"] = {
            "none": None,
            "dict": existing,
            "string": "opaque",
        }[parsed]
    result = await harness.run([question])
    cropped = bool(bbox) and len(bbox) == 4
    job = harness.jobs[0]
    assert job[0] == ("image" if cropped else "file_io")
    if cropped:
        assert job[1] is visual_region_cropper.crop_region
        assert job[2] == (harness.pages[1], tuple(bbox))
        assert job[3] == {
            "coordinate_space": visual_region_cropper.CoordinateSpace.IMAGE_PIXELS
        }
    else:
        assert job[1].__self__.as_posix() == harness.pages[1]
        assert job[1].__name__ == "read_bytes"
        assert job[2:] == ((), {})
    import_id = hashlib.md5(b"visual-crop-test").hexdigest()[:8]
    digest = hashlib.md5(harness.png).hexdigest()[:12]
    assert harness.uploads == [
        (f"202610/snapshots/{import_id}_snapshot_p1_{digest}.png", harness.png),
    ]
    assert harness.uploads[0][1] is harness.png
    assert result == {"questions": [question], "warnings": []}
    assert "risk_flags" not in question
    if parsed in {"absent", "dict"}:
        output = question["parsed_content"]
        assert output["source_snapshot_url"] == "storage://snapshot.png"
        assert output["source_snapshot_full_page"] is not cropped
        if parsed == "absent":
            assert output["text"] == "original stem"
        else:
            assert output is existing and output["opaque"] == {"kept": 1}
    else:
        assert question["parsed_content"] == (None if parsed == "none" else "opaque")


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [None, 0, 2, 9, "1"])
async def test_page_key_lookup_keeps_original_key_type(harness, page):
    question = {"page_start": page, "stem": "text"}
    await harness.run([question])
    expected_page = page or 1
    if expected_page in harness.pages:
        assert harness.jobs[0][1].__self__.as_posix() == harness.pages[expected_page]
        assert f"_snapshot_p{expected_page}_" in harness.uploads[0][0]
    else:
        assert harness.jobs == harness.uploads == []
        assert "parsed_content" not in question
    assert "risk_flags" not in question


@pytest.mark.asyncio
@pytest.mark.parametrize("png", [None, b""])
async def test_empty_snapshot_has_no_upload_or_failure_flag(harness, png):
    harness.png = png
    question = {"stem": "text"}
    await harness.run([question])
    assert len(harness.jobs) == 1 and harness.uploads == []
    assert question == {"stem": "text"}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [("executor", "file_io"), "run", "upload"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_snapshot_error_policy_and_partial_projection(harness, stage, error_type):
    error = error_type("synthetic snapshot failure")
    harness.errors[stage] = error
    parsed = {"text": "kept"}
    questions = [
        {"parsed_content": parsed, "risk_flags": ["existing"]},
        {"stem": "next"},
    ]
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await harness.run(questions)
        assert caught.value is error
        assert (
            questions[0]["risk_flags"] == ["existing"]
            and "risk_flags" not in questions[1]
        )
        harness.logger.warning.assert_not_called()
    else:
        result = await harness.run(questions)
        assert result["questions"] is questions and result["warnings"] == []
        assert questions[0]["risk_flags"] == ["existing", "source_snapshot_failed"]
        assert questions[1]["risk_flags"] == ["source_snapshot_failed"]
        assert harness.logger.warning.call_count == 2
        assert harness.logger.warning.call_args.args == (
            "source_snapshot failed import=%s page=%s: %s",
            "visual-crop-test",
            1,
            error,
        )
    assert questions[0]["parsed_content"] is parsed and parsed == {"text": "kept"}


@pytest.mark.asyncio
async def test_snapshot_failure_does_not_duplicate_existing_risk(harness):
    harness.errors["run"] = RuntimeError("synthetic")
    original = ["source_snapshot_failed"]
    question = {"risk_flags": original}
    await harness.run([question])
    assert question["risk_flags"] == original and question["risk_flags"] is not original


@pytest.mark.asyncio
@pytest.mark.parametrize("bbox", [7, {"bad": "bbox"}])
async def test_invalid_snapshot_bbox_uses_existing_best_effort_failure(harness, bbox):
    question = {"question_bbox": bbox}
    await harness.run([question])
    if isinstance(bbox, int):
        assert question["risk_flags"] == ["source_snapshot_failed"]
        assert harness.jobs == []
    else:
        assert harness.jobs[0][0] == "file_io"


@pytest.mark.asyncio
async def test_snapshot_logger_failure_propagates_without_adding_flag(harness):
    harness.errors["run"] = RuntimeError("snapshot")
    error = RuntimeError("logger")
    harness.logger.warning.side_effect = error
    question = {}
    with pytest.raises(RuntimeError) as caught:
        await harness.run([question])
    assert caught.value is error and "risk_flags" not in question
