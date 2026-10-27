"""Pin region reconstruction, duplicate handling and native table fallback."""

import pytest

from app.services.visual_region_types import CoordinateSpace, VisualRegionType
from tests.visual_crop_support import VisualCropHarness, region


@pytest.fixture
def harness(monkeypatch):
    return VisualCropHarness(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize("page_refs", [None, {}, False])
async def test_missing_images_only_adds_snapshot_flag(harness, page_refs):
    flags = ["existing", "source_snapshot_failed"]
    segments = [{"type": "text", "text": "unchanged"}]
    questions = [{"risk_flags": flags, "segments": segments}, {}]
    result = await harness.run(
        questions, pages=page_refs if page_refs is not None else {}
    )
    assert result == {
        "questions": questions,
        "warnings": ["visual_region_crop: no page images"],
    }
    assert result["questions"] is questions
    assert (
        questions[0]["risk_flags"] == flags and questions[0]["risk_flags"] is not flags
    )
    assert questions[0]["segments"] is segments
    assert questions[1]["risk_flags"] == ["source_snapshot_failed"]
    assert harness.trace == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["diagram", "table", "formula", "invalid"])
@pytest.mark.parametrize(
    "space", ["pdf_points", "normalized_1000", "", None, "invalid"]
)
async def test_reconstruction_uses_original_types_and_region_fields(
    harness, kind, space
):
    question = {
        "page_start": 9,
        "visual_regions": [
            region(
                region_type=kind,
                coordinate_space=space,
                confidence=0.7,
                alt="figure",
                option_key="B",
                requires_review=False,
            )
        ],
    }
    result = await harness.run([question])
    actual, import_id = harness.regions[0]
    assert actual.region_type == (
        VisualRegionType.UNKNOWN if kind == "invalid" else VisualRegionType(kind)
    )
    assert actual.coordinate_space == (
        CoordinateSpace.IMAGE_PIXELS
        if space in {"", None, "invalid"}
        else CoordinateSpace(space)
    )
    assert actual.bbox == (10, 20, 100, 200)
    assert actual.confidence == 0.7 and actual.alt == "figure"
    assert actual.option_key == "B" and actual.requires_review is False
    assert actual.source_page == 1 and len(import_id) == 8
    assert question["parsed_content"]["segments"] is question["segments"]
    assert question["segments"][0] == actual.to_segment()
    assert result["warnings"] == ["visual region r1 cropped for page 1"]
    assert harness.jobs == [] and harness.uploads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bbox", [None, [], [1, 2, 3], "bbox"])
async def test_missing_bbox_is_flagged_without_crop_or_image(harness, bbox):
    flags = ["existing"]
    question = {
        "page_start": 9,
        "risk_flags": flags,
        "visual_regions": [region(bbox=bbox)],
    }
    result = await harness.run([question])
    assert result["warnings"] == [] and harness.regions == []
    assert question["risk_flags"] == ["existing", "visual_region_bbox_missing"]
    assert question["risk_flags"] is not flags
    assert "segments" not in question and "parsed_content" not in question


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_crop_failure_flag_and_existing_flags_are_not_duplicated(harness, failed):
    harness.region_url = None
    harness.crop_failed = failed
    flags = ["existing", "visual_crop_failed"] if failed else ["existing"]
    question = {"page_start": 9, "risk_flags": flags, "visual_regions": [region()]}
    assert (await harness.run([question]))["warnings"] == []
    assert question["risk_flags"] == flags and question["risk_flags"] is not flags
    assert "segments" not in question


@pytest.mark.asyncio
@pytest.mark.parametrize("review", [False, True, None])
@pytest.mark.parametrize("matching", [False, True])
async def test_native_table_attaches_fallback_without_duplicate_screenshot(
    harness, review, matching
):
    table = {
        "type": "table",
        "region_id": "r1" if matching else "other",
        "rows": [["cell"]],
    }
    if review is not None:
        table["requires_review"] = review
    original_segments = [table]
    parsed = {"text": "stem", "extra": {"sentinel": 1}}
    question = {
        "page_start": 9,
        "segments": original_segments,
        "parsed_content": parsed,
        "visual_regions": [region(region_type="table")],
    }
    await harness.run([question])
    assert question["segments"] is not original_segments
    assert question["segments"][0] is table
    assert question["parsed_content"] is not parsed
    assert question["parsed_content"]["extra"] is parsed["extra"]
    assert question["parsed_content"]["segments"] is question["segments"]
    assert len(question["segments"]) == (1 if matching and not review else 2)
    if matching:
        assert (
            table["source_image_url"]
            == table["fallback_image_url"]
            == harness.region_url
        )
    else:
        assert "source_image_url" not in table


@pytest.mark.asyncio
async def test_repeated_ids_skip_and_empty_ids_do_not(harness):
    question = {
        "page_start": 9,
        "visual_regions": [
            region(),
            region(),
            region(region_id=""),
            region(region_id=""),
        ],
    }
    result = await harness.run([question])
    assert [item[0].region_id for item in harness.regions] == ["r1", "", ""]
    assert [item["region_id"] for item in question["segments"]] == ["r1", ""]
    assert len(result["warnings"]) == 3


@pytest.mark.asyncio
async def test_ids_are_scoped_per_question_and_no_bbox_duplicate_is_not_retried(
    harness,
):
    first = {
        "page_start": 9,
        "visual_regions": [region(bbox=None), region()],
    }
    second = {"page_start": 9, "visual_regions": [region()]}
    await harness.run([first, second])
    assert "segments" not in first
    assert len(harness.regions) == 1 and len(second["segments"]) == 1


@pytest.mark.asyncio
async def test_matching_image_is_not_duplicated(harness):
    existing = {"type": "image", "region_id": "r1", "url": harness.region_url}
    question = {"page_start": 9, "segments": [existing], "visual_regions": [region()]}
    result = await harness.run([question])
    assert question["segments"] == [existing] and question["segments"][0] is existing
    assert len(result["warnings"]) == 1


@pytest.mark.asyncio
async def test_multiple_tables_all_receive_fallback_and_any_review_keeps_image(harness):
    tables = [
        {"type": "table", "region_id": "r1", "requires_review": False},
        {"type": "table", "region_id": "r1", "requires_review": True},
    ]
    question = {
        "page_start": 9,
        "segments": tables[:],
        "visual_regions": [region(region_type="table")],
    }
    await harness.run([question])
    assert len(question["segments"]) == 3
    assert all(table["source_image_url"] == harness.region_url for table in tables)
