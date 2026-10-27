"""Reject unprovable origins, grouped options and offset-changing text views."""

import copy

import pytest

from tests.pipeline.ir_freeze_binding_support import (
    OPTIONS,
    isolated_runtime,
    source_blocks,
)
from tests.pipeline.ir_freeze_safety_support import (
    assert_unbound,
    freeze_sources,
    split_frozen,
)


@pytest.fixture
def binding_runtime(monkeypatch, tmp_path):
    yield from isolated_runtime(monkeypatch, tmp_path)


@pytest.mark.parametrize("duplicate", ["coordinate", "region", "instance"])
def test_duplicate_sources_cannot_become_authoritative(
    binding_runtime, monkeypatch, duplicate
):
    blocks = source_blocks(2)
    expected = list(OPTIONS)
    if duplicate == "coordinate":
        blocks[1]["block_index"] = blocks[0]["block_index"]
    elif duplicate == "region":
        blocks[1]["normalized_text"] = blocks[0]["normalized_text"]
        expected = [OPTIONS[0], OPTIONS[0]]
    else:
        blocks[1] = blocks[0]
        expected = [OPTIONS[0], OPTIONS[0]]
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch, blocks)
    assert "freeze_block_binding" not in frozen
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="missing_source_binding")
    assert [
        question["option_lines"] for question in result["raw_questions"]
    ] == expected


@pytest.mark.parametrize(
    "field,value", [("page", 0), ("block_index", -1), ("block_index", False)]
)
def test_invalid_coordinates_cannot_become_authoritative(
    binding_runtime, monkeypatch, field, value
):
    blocks = source_blocks(1)
    blocks[0][field] = value
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch, blocks)
    assert "freeze_block_binding" not in frozen
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="missing_source_binding")
    assert result["raw_questions"][0]["option_lines"] == OPTIONS[0]


@pytest.mark.parametrize("mutation", ["text", "revision", "page"])
def test_changed_ir_cannot_reuse_builder_origins(
    binding_runtime, monkeypatch, mutation
):
    pipeline, blocks, _, document = freeze_sources(binding_runtime, monkeypatch)
    region = document.pages[0].regions[0]
    if mutation == "text":
        region.lines[1].text = "A. altered-in-ir"
    elif mutation == "revision":
        region.revision += 1
    else:
        document.pages[0].page_index += 1
    frozen = pipeline._run_structure_freeze(blocks)
    assert "freeze_block_binding" not in frozen
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="missing_source_binding")
    assert result["raw_questions"][0]["option_lines"] == OPTIONS[0]


def test_restored_ir_does_not_guess_origins_from_region_order(
    binding_runtime, monkeypatch
):
    from app.core.document_ir import document_ir_from_dict, document_ir_to_dict

    pipeline, blocks, _, document = freeze_sources(binding_runtime, monkeypatch)
    payload = document_ir_to_dict(document)
    assert "_freeze_source_capture" not in payload
    restored = document_ir_from_dict(payload)
    assert not hasattr(restored, "_freeze_source_capture")
    blocks[0]["_document_ir"] = restored
    frozen = pipeline._run_structure_freeze(blocks)
    assert "freeze_block_binding" not in frozen
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="missing_source_binding")
    assert result["raw_questions"][0]["option_lines"] == OPTIONS[0]


def test_book_trim_invalidates_offsets_even_when_blocks_are_unchanged(
    binding_runtime, monkeypatch
):
    blocks = source_blocks(1)
    blocks[0]["normalized_text"] = (
        "Introductory material.\n\u4e60\u9898\u7cbe\u9009\n"
        + blocks[0]["normalized_text"]
    )
    blocks[0]["boxes"] = []
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch, blocks)
    result = split_frozen(pipeline, blocks, frozen, import_mode="book")
    assert_unbound(result, reason="split_text_transformed")
    assert result["raw_questions"][0]["raw_question_text"].startswith("1.")
    assert result["raw_questions"][0]["option_lines"] == OPTIONS[0]


def test_grouped_options_remain_separate_and_unfrozen(binding_runtime, monkeypatch):
    blocks = source_blocks(1)
    blocks[0]["normalized_text"] = (
        "1. Choose (1) and (2).\n"
        "(1) A. first  B. second  C. third  D. fourth\n"
        "(2) A. fifth  B. sixth  C. seventh  D. eighth"
    )
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch, blocks)
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="grouped_options")
    question = result["raw_questions"][0]
    assert question["has_grouped_options"] is True
    assert question["option_lines"] == {}
    assert [group["options"]["A"] for group in question["blank_option_groups"]] == [
        "first",
        "fifth",
    ]


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_selected_legacy_fallback_still_requires_provable_sources(
    binding_runtime, monkeypatch, mode
):
    from app.features import ocr_canary
    from app.features.pipeline_stages import structure_freeze_stage

    pipeline, blocks, _, _ = freeze_sources(binding_runtime, monkeypatch, mode=mode)
    if mode == "ir":
        monkeypatch.setattr(
            structure_freeze_stage,
            "freeze_from_document_ir",
            lambda document: {"frozen_option_registry": {}, "warnings": []},
        )
    else:
        monkeypatch.setattr(
            ocr_canary,
            "check_ir_canary_failover",
            lambda **kwargs: (True, ["synthetic-policy-fallback"]),
        )
    frozen = pipeline._run_structure_freeze(blocks)
    assert frozen.get("freeze_ir_empty") or frozen.get("freeze_canary_fallback")
    result = split_frozen(pipeline, blocks, frozen)
    question = result["raw_questions"][0]
    assert question["is_frozen"] is True
    assert question["option_lines"] == OPTIONS[0]
    assert result["freeze_binding_diagnostics"]["accepted_questions"] == 1


def test_unavailable_document_ir_falls_back_without_guessing_sources(
    binding_runtime, monkeypatch
):
    pipeline, blocks, _, _ = freeze_sources(binding_runtime, monkeypatch)
    monkeypatch.setattr(
        binding_runtime.pipeline_module, "_get_blocks_document_ir", lambda values: None
    )
    frozen = pipeline._run_structure_freeze(blocks)
    assert frozen["freeze_ir_empty"] is True
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="missing_source_binding")
    assert result["raw_questions"][0]["option_lines"] == OPTIONS[0]


@pytest.mark.parametrize("side", [0, 1])
def test_cross_page_recovery_protects_either_frozen_participant(binding_runtime, side):
    from app.features.question_splitter import _recover_cross_page_options

    questions = [
        {
            "raw_question_text": "1. Which result?\nA. a\nB. b",
            "option_lines": {"A": "a", "B": "b"},
            "has_options": True,
            "page_start": 1,
            "page_end": 1,
        },
        {
            "raw_question_text": "C. c\nD. d\n2. Another question?",
            "option_lines": {"C": "c", "D": "d"},
            "has_options": True,
            "page_start": 2,
            "page_end": 2,
        },
    ]
    questions[side]["is_frozen"] = True
    snapshot = copy.deepcopy(questions)
    assert _recover_cross_page_options(questions, respect_frozen=True) == snapshot
    control = _recover_cross_page_options(copy.deepcopy(snapshot))
    assert control != snapshot
    assert control[0]["option_lines"] == {"A": "a", "B": "b", "C": "c", "D": "d"}
