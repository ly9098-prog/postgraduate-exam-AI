"""Unsafe source views must never reach frozen or page-level option injection."""

import copy

import pytest

from tests.pipeline.ir_freeze_binding_support import (
    OPTIONS,
    isolated_runtime,
    source_blocks,
)
from tests.pipeline.ir_freeze_safety_support import (
    assert_bound,
    assert_unbound,
    freeze_sources,
    split_frozen,
)


@pytest.fixture
def binding_runtime(monkeypatch, tmp_path):
    yield from isolated_runtime(monkeypatch, tmp_path)


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
@pytest.mark.parametrize("mutation", ["text", "coordinate", "order", "removed"])
def test_changed_input_view_rejects_old_bindings(
    binding_runtime, monkeypatch, mode, mutation
):
    pipeline, blocks, frozen, _ = freeze_sources(
        binding_runtime, monkeypatch, source_blocks(2), mode=mode
    )
    changed = copy.deepcopy(blocks)
    if mutation == "text":
        changed[0]["normalized_text"] += "\nAdditional material."
    elif mutation == "coordinate":
        changed[0]["block_index"] += 1
    elif mutation == "order":
        changed.reverse()
    else:
        changed.pop()
    result = split_frozen(pipeline, changed, frozen)
    assert_unbound(result, reason="input_view_changed")


def test_accepted_cross_page_transform_invalidates_even_identical_view(
    binding_runtime, monkeypatch
):
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch)
    monkeypatch.setattr(
        binding_runtime.pipeline_module,
        "_merge_cross_page_blocks",
        lambda values: (copy.deepcopy(values), [object()], [], []),
    )
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="split_input_transformed")
    assert result["raw_questions"][0]["option_lines"] == OPTIONS[0]


def test_vl_rebuild_does_not_remap_or_reinject_ir_registry(
    binding_runtime, monkeypatch
):
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch)
    monkeypatch.setattr(
        pipeline, "_run_vl_rebuild_blocks", lambda *args, **kwargs: list(blocks)
    )

    def remap(*args):
        pytest.fail("unverified IR bindings must not enter the legacy VL remapper")

    monkeypatch.setattr(
        binding_runtime.pipeline_module, "_remap_frozen_registry_vl_rebuild", remap
    )
    result = split_frozen(
        pipeline,
        blocks,
        frozen,
        split_mode="vl_rebuild",
        file_path="synthetic.pdf",
        vision_config={"synthetic": True},
    )
    assert_unbound(result, reason="split_input_transformed")
    assert result["raw_questions"][0]["option_lines"] == OPTIONS[0]


def test_real_book_layout_filter_disables_unmapped_binding(
    binding_runtime, monkeypatch
):
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch)
    result = split_frozen(pipeline, blocks, frozen, import_mode="book")
    assert_unbound(result, reason="split_input_transformed")
    assert result["raw_questions"][0]["option_lines"] == OPTIONS[0]


@pytest.mark.parametrize("split_mode", ["standard", "layout_enhanced"])
def test_missing_plan_cannot_inject_page_layout_or_call_final_apply(
    binding_runtime, monkeypatch, split_mode
):
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch)
    frozen.pop("freeze_block_binding")
    blocks[0]["normalized_text"] = "1. Which result is correct?\nA. own-answer"
    page = str(blocks[0]["page"])

    def apply(*args, **kwargs):
        pytest.fail("IR fallback must not perform a second substring injection")

    monkeypatch.setattr(binding_runtime.pipeline_module, "_apply_frozen_options", apply)
    result = split_frozen(
        pipeline,
        blocks,
        frozen,
        split_mode=split_mode,
        layout_result={"option_groups": {page: OPTIONS[1]}},
    )
    assert_unbound(result, reason="missing_source_binding")
    assert result["raw_questions"][0]["option_lines"] == {"A": "own-answer"}


def test_separated_answer_pages_keep_original_source_indices(
    binding_runtime, monkeypatch
):
    monkeypatch.setenv("DISABLE_CROSS_PAGE_MERGING", "1")
    blocks = source_blocks(2)
    blocks[0]["page"] = 2
    blocks[1]["page"] = 7
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch, blocks)
    result = split_frozen(
        pipeline,
        blocks,
        frozen,
        structure={"mode": "SEPARATED", "answer_pages": [2], "question_pages": [7]},
    )
    assert_bound(result, [OPTIONS[1]])
    assert result["raw_questions"][0]["number"] == 2


def test_shared_source_disables_partial_freeze_of_the_same_question(
    binding_runtime, monkeypatch
):
    blocks = source_blocks(2)
    blocks[0]["normalized_text"] += "\n2. A second question begins here?"
    blocks[1]["normalized_text"] = "\n".join(
        f"{key}. {value}" for key, value in OPTIONS[1].items()
    )
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch, blocks)
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="source_spans_questions")
    assert [q["option_lines"] for q in result["raw_questions"]] == list(OPTIONS)


def test_one_question_can_bind_several_unique_source_blocks(
    binding_runtime, monkeypatch
):
    blocks = source_blocks(2)
    blocks[0]["normalized_text"] = "1. Which result is correct?\nA. a\nB. b"
    blocks[1]["normalized_text"] = "C. c\nD. d"
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch, blocks)
    result = split_frozen(pipeline, blocks, frozen)
    assert_bound(result, [{"A": "a", "B": "b", "C": "c", "D": "d"}])
    question = result["raw_questions"][0]
    assert question["raw_question_text"] == "1. Which result is correct?"
    assert question["_original_raw_text"] == "\n".join(
        block["normalized_text"] for block in blocks
    )


def test_conflicting_sources_fall_back_without_authoritative_overwrite(
    binding_runtime, monkeypatch
):
    blocks = source_blocks(2)
    blocks[0]["normalized_text"] = "1. Which result is correct?\nA. first\nB. second"
    blocks[1]["normalized_text"] = "A. different\nC. third"
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch, blocks)
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="conflicting_frozen_options")
    assert "A. first" in result["raw_questions"][0]["raw_question_text"]
    assert "A. different" in result["raw_questions"][0]["raw_question_text"]


def test_unsafe_and_verified_questions_on_same_page_have_independent_decisions(
    binding_runtime, monkeypatch
):
    blocks = source_blocks(2)
    blocks[0]["normalized_text"] += "\n" + blocks[1]["normalized_text"]
    third = {"A": "unique-a", "B": "unique-b", "C": "unique-c", "D": "unique-d"}
    blocks[1]["normalized_text"] = "3. A separate question?\n" + "\n".join(
        f"{key}. {value}" for key, value in third.items()
    )
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch, blocks)
    result = split_frozen(pipeline, blocks, frozen)
    questions = result["raw_questions"]
    assert [question["option_lines"] for question in questions] == [*OPTIONS, third]
    assert [question["is_frozen"] for question in questions] == [False, False, True]
    assert result["freeze_binding_diagnostics"]["accepted_questions"] == 1
    assert "source_spans_questions" in result["freeze_binding_diagnostics"]["reasons"]
