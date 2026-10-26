"""Characterize source precedence, shallow-copy boundaries and OCR page metadata."""

from __future__ import annotations

import inspect

import pytest

from app.core.config import settings
from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.extract_stage_support import ObservedMapping, make_extract_harness


@pytest.mark.parametrize("source_type", ["image", "txt", "unknown"])
@pytest.mark.parametrize("file_content", [b"cleaned text", b"", None])
def test_non_pdf_content_precedes_path_including_empty_bytes(
    monkeypatch, source_type, file_content
):
    h = make_extract_harness(monkeypatch)
    result = h.pipeline._run_extract(
        file_content=file_content,
        source_type=source_type,
        file_path="/synthetic/image.png",
    )
    expected = file_content if file_content is not None else "/synthetic/image.png"
    assert h.trace == [("text", expected)]
    assert result["raw_blocks"] is h.text_blocks
    assert result["exercise_regions"] == []
    assert result["exercise_regions_missing"] is False


@pytest.mark.parametrize("source_type", ["image", "txt"])
def test_structured_blocks_copy_each_mapping_and_keep_nested_identity(
    monkeypatch, source_type
):
    h = make_extract_harness(monkeypatch)
    geometry = {"bbox": [1, 2, 3, 4]}
    original = [{"text": "geometry", "layout": geometry}]
    result = h.pipeline._run_extract(
        file_content=b"unused",
        source_type=source_type,
        pre_extracted_blocks=original,
    )
    assert h.trace == []
    assert result["raw_blocks"] == original
    assert result["raw_blocks"] is not original
    assert result["raw_blocks"][0] is not original[0]
    assert result["raw_blocks"][0]["layout"] is geometry
    result["raw_blocks"][0]["new"] = True
    assert "new" not in original[0]


@pytest.mark.parametrize("file_path", ["/synthetic/input.pdf", "", None])
def test_pdf_uses_truthy_path_and_ignores_pre_extracted_blocks(monkeypatch, file_path):
    h = make_extract_harness(monkeypatch)
    h.pdf_blocks = [{"text": "x" * 100}]
    result = h.pipeline._run_extract(
        file_content=b"pdf",
        file_path=file_path,
        pre_extracted_blocks=[{"text": "unused"}],
        options={"page_start": 2, "page_end": 4, "_original_raw_text": "source"},
    )
    assert h.trace == [("pdf", file_path or b"pdf", {"page_start": 2, "page_end": 4})]
    assert result["raw_blocks"] is h.pdf_blocks
    assert result["_original_raw_text"] == "source"


@pytest.mark.parametrize("source_type", ["pdf", "image", "txt"])
def test_missing_source_error_precedes_extraction(monkeypatch, source_type):
    h = make_extract_harness(monkeypatch)
    with pytest.raises(ValueError, match="either file"):
        h.pipeline._run_extract(source_type=source_type)
    assert h.trace == []


@pytest.mark.parametrize("character_count", [99, 100, 101])
def test_ocr_threshold_is_strictly_less_than_one_hundred(monkeypatch, character_count):
    h = make_extract_harness(monkeypatch)
    h.pdf_blocks = [{"text": "x" * character_count}]
    result = h.pipeline._run_extract(
        file_content=b"pdf", options={"import_mode": "exam"}
    )
    expected = ["pdf", "ocr"] if character_count < 100 else ["pdf"]
    assert [call[0] for call in h.trace] == expected
    assert result["raw_blocks"] is (
        h.ocr_blocks if character_count < 100 else h.pdf_blocks
    )


def test_ocr_disabled_keeps_short_nonempty_pdf_text(monkeypatch):
    h = make_extract_harness(monkeypatch)
    monkeypatch.setattr(settings, "OCR_ENABLED", False)
    result = h.pipeline._run_extract(file_content=b"pdf")
    assert result["raw_blocks"] is h.pdf_blocks
    assert [call[0] for call in h.trace] == ["pdf"]
    assert h.warnings[0][0].endswith("cannot extract scanned content")


def test_page_diagnostics_keep_sorted_unique_ints_and_page_precedence(monkeypatch):
    h = make_extract_harness(monkeypatch)
    h.text_blocks = [
        {
            "page": "3",
            "page_index": 9,
            "_ocr_boxes_failed": True,
            "source": "ocr_text_fallback",
            "_ocr_text_fallback_unavailable_pages": [3, "2", 0],
            "_ocr_runtime_failed_pages": ["4", 1],
        },
        {
            "page": 0,
            "page_index": "2",
            "_ocr_boxes_failed": True,
            "source": "ocr_text_fallback",
            "_ocr_text_fallback_unavailable_pages": [2],
            "_ocr_runtime_failed_pages": [1],
        },
        {"page": 7, "_ocr_boxes_failed": False, "source": "ordinary"},
    ]
    result = h.pipeline._run_extract(file_content=b"text", source_type="txt")
    assert result["ocr_boxes_failed_pages"] == [2, 3]
    assert result["ocr_text_fallback_pages"] == [2, 3]
    assert result["ocr_text_fallback_unavailable_pages"] == [2, 3]
    assert result["ocr_runtime_failed_pages"] == [1, 4]
    assert result["raw_blocks"] is h.text_blocks
    assert result["extracted"] == 3


def test_pdf_extractor_is_loaded_before_option_getter_replaces_it(monkeypatch):
    h = make_extract_harness(monkeypatch)
    h.pdf_blocks = [{"text": "x" * 100}]
    events = []

    def hook(key):
        if key == "page_start":
            monkeypatch.setattr(
                orchestrator,
                "_extract_pdf_blocks",
                lambda *_args, **_kwargs: pytest.fail("callee already loaded"),
            )

    options = ObservedMapping({"page_start": 2}, events, hook)
    result = h.pipeline._run_extract(file_content=b"pdf", options=options)
    assert result["raw_blocks"] is h.pdf_blocks
    assert events == ["page_start", "page_end", "_original_raw_text"]


def test_original_text_is_read_after_extraction_and_keeps_reference(monkeypatch):
    h = make_extract_harness(monkeypatch)
    marker = object()
    options = {"_original_raw_text": "before"}

    def extract(_source):
        options["_original_raw_text"] = marker
        return h.text_blocks

    monkeypatch.setattr(orchestrator, "_extract_text_blocks", extract)
    result = h.pipeline._run_extract(
        source_type="txt", file_content=b"x", options=options
    )
    assert result["_original_raw_text"] is marker
    assert list(result) == [
        "raw_blocks",
        "extracted",
        "_original_raw_text",
        "exercise_regions",
        "exercise_regions_missing",
        "ocr_boxes_failed_pages",
        "ocr_text_fallback_pages",
        "ocr_text_fallback_unavailable_pages",
        "ocr_runtime_failed_pages",
    ]


def test_diagnostics_keep_four_traversals_and_repeated_get_order(monkeypatch):
    h = make_extract_harness(monkeypatch)
    events = []
    h.text_blocks = [
        ObservedMapping(
            {
                "page": 2,
                "_ocr_boxes_failed": True,
                "source": "ocr_text_fallback",
                "_ocr_text_fallback_unavailable_pages": [3],
                "_ocr_runtime_failed_pages": [4],
            },
            events,
        )
    ]
    result = h.pipeline._run_extract(source_type="txt", file_content=b"x")
    assert result["ocr_runtime_failed_pages"] == [4]
    assert events == [
        "_ocr_boxes_failed",
        "page",
        "page",
        "source",
        "page",
        "page",
        "_ocr_text_fallback_unavailable_pages",
        "_ocr_runtime_failed_pages",
    ]


@pytest.mark.parametrize(
    "field",
    [
        "_ocr_boxes_failed",
        "source",
        "_ocr_text_fallback_unavailable_pages",
        "_ocr_runtime_failed_pages",
    ],
)
def test_diagnostic_getter_exception_keeps_identity_and_stops_projection(
    monkeypatch,
    field,
):
    h = make_extract_harness(monkeypatch)
    events = []
    failure = RuntimeError("diagnostic read")

    def hook(key):
        if key == field:
            raise failure

    h.text_blocks = [ObservedMapping({"text": "text"}, events, hook)]
    with pytest.raises(RuntimeError) as caught:
        h.pipeline._run_extract(source_type="txt", file_content=b"x")
    assert caught.value is failure
    assert events[-1] == field


def test_invalid_page_conversion_precedes_later_diagnostic_reads(monkeypatch):
    h = make_extract_harness(monkeypatch)
    events = []
    h.text_blocks = [
        ObservedMapping(
            {
                "page": "bad",
                "_ocr_boxes_failed": True,
                "_ocr_runtime_failed_pages": [float("inf")],
            },
            events,
        )
    ]
    with pytest.raises(ValueError, match="invalid literal"):
        h.pipeline._run_extract(source_type="txt", file_content=b"x")
    assert events == ["_ocr_boxes_failed", "page", "page"]


def test_source_type_is_compared_twice_without_caching_or_string_coercion(monkeypatch):
    h = make_extract_harness(monkeypatch)
    comparisons = []

    class SourceType:
        def __eq__(self, value):
            comparisons.append(value)
            return len(comparisons) == 1

    result = h.pipeline._run_extract(file_content=b"x", source_type=SourceType())
    assert comparisons == ["pdf", "pdf"]
    assert result["raw_blocks"] is h.text_blocks


def test_extract_entry_keeps_original_signature_globals_and_sync_contract():
    entry = orchestrator.ImportPipeline._run_extract
    assert entry.__globals__ is vars(orchestrator)
    assert entry.__module__ == orchestrator.__name__
    assert entry.__name__ == "_run_extract"
    assert entry.__qualname__ == "ImportPipeline._run_extract"
    assert not inspect.iscoroutinefunction(entry)
    assert str(inspect.signature(entry)) == (
        "(self, file_content: 'bytes | None' = None, source_type: 'str' = 'pdf', "
        "file_path: 'str | None' = None, "
        "pre_extracted_blocks: 'list[dict] | None' = None, **_kw) -> 'dict'"
    )
