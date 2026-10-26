"""Preserve prose/fallback decisions, overlap mutations and final freeze order."""

import asyncio

import pytest

from app.features import pipeline_orchestrator as orchestrator
from app.features import question_splitter
from app.features import visual_boundary_detector as visual
from tests.pipeline.split_stage_support import question, split_harness


def test_prose_filter_counts_precede_final_raw_count_and_freeze(monkeypatch):
    h = split_harness(monkeypatch)
    prose = question(1, prose=True)
    kept = question(2)
    h.questions = [prose, kept]
    registry = {2: [object()]}
    result = h.pipeline._run_split(
        h.blocks, import_mode="book", source_type="pdf", frozen_option_registry=registry
    )
    assert result["raw_questions"] == [kept]
    assert result["raw_questions"][0] is kept
    diagnostics = result["split_diagnostics"]
    assert diagnostics["raw_question_count"] == 2
    assert diagnostics["raw_question_count_after_prose_filter"] == 1
    assert diagnostics["prose_skipped_count"] == 1
    assert diagnostics["raw_questions_hash"] == "raw-hash"
    assert diagnostics["prose_skipped_preview"][0]["number"] == 1
    assert result["warnings"] == ["book_pdf_prose_skipped: 1"]
    multi_blank, freeze = h.events[-2:]
    assert multi_blank[0] == "multi_blank" and freeze[0] == "freeze"
    assert multi_blank[1][1] is result["raw_questions"]
    assert freeze[1][0] is result["raw_questions"]
    assert freeze[2]["normalized_blocks"] is h.blocks


def test_prose_preview_is_capped_without_limiting_filter_count(monkeypatch):
    h = split_harness(monkeypatch)
    h.questions = [question(i, prose=True) for i in range(25)]
    result = h.pipeline._run_split(h.blocks, import_mode="book", source_type="pdf")
    assert result["raw_questions"] == []
    diagnostics = result["split_diagnostics"]
    assert diagnostics["prose_skipped_count"] == 25
    assert len(diagnostics["prose_skipped_preview"]) == 20
    assert diagnostics["failure_reason"] == "book_text_present_but_no_question_boundary"


@pytest.mark.parametrize(
    "mode,source,expected_count,reason",
    [
        ("book", "pdf", 0, "book_text_present_but_no_question_boundary"),
        ("exam", "pdf", 1, "text_present_but_no_question_boundary"),
        ("book", "txt", 1, "text_present_but_no_question_boundary"),
        (None, None, 1, "text_present_but_no_question_boundary"),
    ],
)
def test_empty_split_retains_manual_review_fallback_rules(
    monkeypatch,
    mode,
    source,
    expected_count,
    reason,
):
    h = split_harness(monkeypatch)
    h.questions = []
    result = h.pipeline._run_split(h.blocks, import_mode=mode, source_type=source)
    assert result["split_count"] == expected_count
    assert result["split_diagnostics"]["failure_reason"] == reason
    assert result["split_diagnostics"]["fallback_created"] is bool(expected_count)
    if expected_count:
        assert result["raw_questions"][0] == {
            "number": 1,
            "raw_question_text": "1. question",
            "page_start": 1,
            "page_end": 1,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.2,
            "risk_flags": ["fallback_low_confidence"],
        }


def test_no_text_does_not_create_a_fallback_question(monkeypatch):
    h = split_harness(monkeypatch)
    h.questions = []
    result = h.pipeline._run_split([{"normalized_text": " \n"}])
    assert result["raw_questions"] is h.questions
    assert result["warnings"] == ["no questions found in document"]
    assert result["split_diagnostics"]["failure_reason"] == "no_text_blocks"


@pytest.mark.parametrize("outcome", ["success", "prose", "empty", "error", "cancel"])
def test_visual_fallback_decision_and_exception_boundary(monkeypatch, outcome):
    h = split_harness(monkeypatch)
    h.questions = []
    h.blocks[0]["boxes"] = [object()]
    document = object()
    boundaries = [{"page": 1, "signal": "one"}, {"page": 2, "signal": "two"}]
    visual_questions = [question(3, prose=outcome == "prose")]
    error = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("visual")
    monkeypatch.setattr(
        orchestrator, "_get_blocks_document_ir", lambda blocks: document
    )
    monkeypatch.setattr(
        orchestrator, "_visual_boundary_preview", lambda blocks, b: b["signal"]
    )

    def detect(value):
        assert value is document
        h.events.append(("visual", value))
        if outcome in {"error", "cancel"}:
            raise error
        return [] if outcome == "empty" else boundaries

    def split(blocks, bounds):
        assert blocks is h.blocks and bounds is boundaries
        return visual_questions

    monkeypatch.setattr(visual, "detect_visual_boundaries_from_ir", detect)
    monkeypatch.setattr(question_splitter, "split_by_visual_boundaries", split)
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError) as caught:
            h.pipeline._run_split(h.blocks)
        assert caught.value is error
        return
    result = h.pipeline._run_split(h.blocks)
    if outcome in {"success", "prose"}:
        assert result["raw_questions"] is visual_questions
        assert result["split_diagnostics"]["detection_method"] == "visual_boundary"
        assert result["split_diagnostics"]["visual_boundary"][
            "boundaries"
        ] == boundaries_to_preview(boundaries)
    else:
        assert result["raw_questions"][0]["risk_flags"] == ["fallback_low_confidence"]
    if outcome == "error":
        assert h.warnings == [("visual boundary detection failed: %s", error)]


def boundaries_to_preview(boundaries):
    return [
        {"page": b["page"], "signal": b["signal"], "preview": b["signal"]}
        for b in boundaries
    ]


def test_shared_overlap_set_is_updated_before_each_following_question(monkeypatch):
    h = split_harness(monkeypatch)
    seen = {"existing"}
    original = [question(1, page=3), question(2, page=3), question(3, page=1)]
    h.questions = original
    traces = []

    def qhash(item):
        traces.append((item["number"], set(seen)))
        return "new" if item["number"] < 3 else "existing"

    monkeypatch.setattr(orchestrator, "_compute_overlap_hash", qhash)
    result = h.pipeline._run_split(
        h.blocks, _chunk_seen_hashes=seen, _chunk_logical_end=2
    )
    assert result["raw_questions"] == [original[0], original[2]]
    assert all(
        a is b for a, b in zip(result["raw_questions"], [original[0], original[2]])
    )
    assert seen == {"existing", "new"}
    assert traces == [
        (1, {"existing"}),
        (2, {"existing", "new"}),
        (3, {"existing", "new"}),
    ]
    assert result["split_diagnostics"]["overlap_skipped_numbers"] == [2]
    assert result["warnings"] == ["boundary_overlap_skipped: [2]"]


@pytest.mark.parametrize("error", [RuntimeError("hash"), asyncio.CancelledError()])
def test_overlap_failure_preserves_earlier_shared_set_updates(monkeypatch, error):
    h = split_harness(monkeypatch)
    h.questions = [question(1), question(2)]
    seen = set()

    def qhash(item):
        if item["number"] == 2:
            raise error
        return "first"

    monkeypatch.setattr(orchestrator, "_compute_overlap_hash", qhash)
    with pytest.raises(type(error)) as caught:
        h.pipeline._run_split(h.blocks, _chunk_seen_hashes=seen, _chunk_logical_end=2)
    assert caught.value is error
    assert seen == {"first"}
    assert not any(event[0] in {"multi_blank", "freeze"} for event in h.events)


@pytest.mark.parametrize(
    "page_end,options,expected",
    [
        (1, "ABC", True),
        (2, "abc", True),
        (3, "ABC", True),
        (4, "ABC", False),
        (2, "AB", False),
        (2, "ABCD", False),
        (2, "ABCE", False),
    ],
)
def test_boundary_warning_retains_three_option_truncation_heuristic(
    monkeypatch,
    page_end,
    options,
    expected,
):
    h = split_harness(monkeypatch)
    h.questions = [
        question(page_end=page_end, option_lines=dict.fromkeys(options, "x"))
    ]
    monkeypatch.setattr(orchestrator, "_compute_overlap_hash", lambda item: None)
    result = h.pipeline._run_split(
        h.blocks, _chunk_seen_hashes=set(), _chunk_logical_end=2
    )
    assert ("boundary_unclosed_question" in result["split_diagnostics"]) is expected


def test_visual_recovery_reapplies_prose_filter_and_accumulates_counts(monkeypatch):
    h = split_harness(monkeypatch)
    h.questions = [question(1, prose=True)]
    h.blocks[0]["boxes"] = [object()]
    recovered = [question(2, prose=True), question(3)]
    monkeypatch.setattr(
        orchestrator, "_get_blocks_document_ir", lambda blocks: object()
    )
    monkeypatch.setattr(
        visual,
        "filter_book_layout_blocks_from_ir",
        lambda document: (h.blocks, {"enabled": True}),
    )
    monkeypatch.setattr(
        visual,
        "detect_visual_boundaries_from_ir",
        lambda document: [{"page": 1}, {"page": 2}],
    )
    monkeypatch.setattr(
        orchestrator, "_visual_boundary_preview", lambda *args: "preview"
    )
    monkeypatch.setattr(
        question_splitter, "split_by_visual_boundaries", lambda *args: recovered
    )
    result = h.pipeline._run_split(h.blocks, import_mode="book", source_type="pdf")
    assert result["raw_questions"] == [recovered[1]]
    assert result["raw_questions"][0] is recovered[1]
    diagnostic = result["split_diagnostics"]
    assert diagnostic["prose_skipped_count"] == 2
    assert diagnostic["book_pdf_prose_skipped"] == 2
    assert [q["number"] for q in diagnostic["prose_skipped_preview"]] == [1, 2]
    assert result["warnings"] == [
        "book_pdf_prose_skipped: 1",
        "visual_boundary: split 2 questions via bbox",
        "book_pdf_prose_skipped: 1",
    ]
