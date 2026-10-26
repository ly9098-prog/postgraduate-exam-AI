"""Characterize split input precedence, layout fallback and frozen VL bindings."""

import asyncio

import pytest

from app.features import pipeline_orchestrator as orchestrator
from app.features import visual_boundary_detector as visual
from tests.pipeline.split_stage_support import split_harness


def split_event(harness):
    return next(event for event in harness.events if event[0] == "split")


def test_cross_page_merge_precedes_split_and_preserves_result_references(monkeypatch):
    h = split_harness(monkeypatch)
    h.links = [object()]
    h.merged = [{"page": 1, "normalized_text": "merged"}]
    h.merge_warnings = ["merge-warning"]
    h.merge_results = [{"linked": True}]
    structure = {"section": "one"}
    result = h.pipeline._run_split(h.blocks, structure=structure)
    assert [event[0] for event in h.events] == ["merge", "split", "multi_blank"]
    assert h.events[0][1] is h.blocks
    assert split_event(h)[1] is h.merged
    assert split_event(h)[2]["structure"] is structure
    assert result["raw_questions"] is h.questions
    assert result["cross_page_merge_results"] is h.merge_results
    assert result["warnings"][:2] == ["merge-warning", "cross_page: 1 link(s) applied"]


def test_without_links_merge_replacement_and_warnings_are_ignored(monkeypatch):
    h = split_harness(monkeypatch)
    h.merged = [{"normalized_text": "unused"}]
    h.merge_warnings = ["ignored"]
    result = h.pipeline._run_split(h.blocks)
    assert split_event(h)[1] is h.blocks
    assert "cross_page_merge_results" not in result
    assert "ignored" not in result["warnings"]


@pytest.mark.parametrize("outcome", ["filtered", "missing", "error", "cancel"])
def test_book_layout_reads_original_blocks_after_cross_page_merge(monkeypatch, outcome):
    h = split_harness(monkeypatch)
    h.blocks[0]["boxes"] = [object()]
    h.links = [object()]
    h.merged = [{"normalized_text": "cross-page"}]
    filtered = [{"normalized_text": "layout"}]
    document = object()
    diagnostic = {"enabled": True}
    failure = (
        asyncio.CancelledError() if outcome == "cancel" else RuntimeError("layout")
    )

    def document_ir(blocks):
        h.events.append(("document", blocks))
        return None if outcome == "missing" else document

    def filter_layout(value):
        assert value is document
        h.events.append(("layout", value))
        if outcome in {"error", "cancel"}:
            raise failure
        return filtered, diagnostic

    monkeypatch.setattr(orchestrator, "_get_blocks_document_ir", document_ir)
    monkeypatch.setattr(visual, "filter_book_layout_blocks_from_ir", filter_layout)
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError) as caught:
            h.pipeline._run_split(h.blocks, import_mode="book", source_type="PDF")
        assert caught.value is failure
        assert not any(event[0] == "split" for event in h.events)
        return
    result = h.pipeline._run_split(h.blocks, import_mode="book", source_type="PDF")
    assert next(event[1] for event in h.events if event[0] == "document") is h.blocks
    assert (
        split_event(h)[1]
        is {
            "filtered": filtered,
            "missing": h.blocks,
            "error": h.merged,
        }[outcome]
    )
    if outcome == "filtered":
        assert result["split_diagnostics"]["layout_filter"] is diagnostic
    if outcome == "missing":
        assert result["split_diagnostics"]["layout_filter"] == {
            "error": "no_document_ir"
        }
    if outcome == "error":
        assert h.warnings == [("book layout filter failed: %s", failure)]


@pytest.mark.parametrize("mode", ["book", "BOOK", orchestrator.ImportMode.BOOK])
def test_import_mode_and_strategy_are_forwarded_without_reinterpreting_layout(
    monkeypatch, mode
):
    h = split_harness(monkeypatch)
    groups = {"option_groups": [object()]}
    registry = {1: [object()]}
    h.pipeline._run_split(
        h.blocks,
        import_mode=mode,
        strategy={"question_number_gap_tolerance": 7},
        layout_result=groups,
        frozen_option_registry=registry,
    )
    kwargs = split_event(h)[2]
    assert kwargs["import_mode"] == "book"
    assert kwargs["gap_tolerance"] == 7
    assert kwargs["layout_result"] is groups
    assert kwargs["frozen_option_registry"] is registry
    assert [event[0] for event in h.events][-2:] == ["multi_blank", "freeze"]


@pytest.mark.parametrize(
    "available,registry",
    [
        (True, {}),
        (True, {1: ["binding"]}),
        (False, {}),
        (False, {1: ["binding"]}),
    ],
)
def test_vl_rebuild_resets_layout_and_remaps_frozen_bindings(
    monkeypatch, available, registry
):
    h = split_harness(monkeypatch)
    h.rebuilt = [{"normalized_text": "rebuilt"}] if available else []
    layout = {"option_groups": ["old"]}
    remapped = {2: [object()]}
    config = {"configured": True}

    def remap(old, rebuilt):
        assert old is registry and rebuilt is h.rebuilt
        h.events.append(("remap", old, rebuilt))
        return {"registry": remapped, "binding_lost_questions": [1]}

    monkeypatch.setattr(orchestrator, "_remap_frozen_registry_vl_rebuild", remap)
    result = h.pipeline._run_split(
        h.blocks,
        split_mode="vl_rebuild",
        file_path="/synthetic/source.pdf",
        vision_config=config,
        frozen_option_registry=registry,
        layout_result=layout,
        _original_raw_text="original",
    )
    event = split_event(h)
    assert event[2]["split_mode"] == ("standard" if available else "layout_enhanced")
    assert event[1] is (h.rebuilt if available else h.blocks)
    assert event[2]["layout_result"] is (None if available else layout)
    if available:
        assert event[2]["frozen_option_registry"] is (remapped if registry else None)
    elif registry:
        assert event[2]["frozen_option_registry"] is registry
    else:
        assert event[2]["frozen_option_registry"] == {}
        assert event[2]["frozen_option_registry"] is not registry
    rebuilt_event = next(event for event in h.events if event[0] == "rebuild")
    assert rebuilt_event[1][0] == "/synthetic/source.pdf"
    assert rebuilt_event[1][1] is h.blocks
    assert rebuilt_event[1][2] is config
    assert rebuilt_event[2] == {"original_raw_text": "original"}
    assert result["warnings"][0].startswith("vl_rebuild:")
    if available and registry:
        assert [event[0] for event in h.events] == [
            "merge",
            "rebuild",
            "remap",
            "split",
            "multi_blank",
            "freeze",
        ]


@pytest.mark.parametrize(
    "file_path,config", [(None, {}), ("file", {}), (None, {"vl": 1})]
)
def test_missing_vl_inputs_fall_back_without_rebuilding(monkeypatch, file_path, config):
    h = split_harness(monkeypatch)
    result = h.pipeline._run_split(
        h.blocks, split_mode="vl_rebuild", file_path=file_path, vision_config=config
    )
    assert split_event(h)[2]["split_mode"] == "layout_enhanced"
    assert not any(event[0] == "rebuild" for event in h.events)
    assert result["warnings"][0] == (
        "vl_rebuild: file_path or vl_config missing, falling back to layout_enhanced"
    )
