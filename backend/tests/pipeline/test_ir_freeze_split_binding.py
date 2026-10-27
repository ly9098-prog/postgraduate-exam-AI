"""Real freeze-to-split P1 acceptance; no proposed protocol fields are assumed."""

import pytest

from tests.pipeline.ir_freeze_binding_support import (
    assert_bound_questions,
    assert_unbound_questions,
    isolated_runtime,
    run_real_stages,
)


@pytest.fixture
def binding_runtime(monkeypatch, tmp_path):
    yield from isolated_runtime(monkeypatch, tmp_path)


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_single_block_question_is_frozen_and_stripped(
    binding_runtime, monkeypatch, mode
):
    questions, originals = run_real_stages(binding_runtime, monkeypatch, mode, "single")
    assert_bound_questions(questions, originals)


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_same_page_independent_blocks_keep_distinct_frozen_options(
    binding_runtime, monkeypatch, mode
):
    questions, originals = run_real_stages(
        binding_runtime, monkeypatch, mode, "independent"
    )
    assert_bound_questions(questions, originals)


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_layout_page_with_two_questions_falls_back_without_cross_contamination(
    binding_runtime, monkeypatch, mode
):
    questions, originals = run_real_stages(
        binding_runtime, monkeypatch, mode, "layout_page"
    )
    assert_unbound_questions(questions, originals)


@pytest.mark.parametrize("mode", ["legacy", "dual"])
@pytest.mark.parametrize("shape", ["single", "independent"])
def test_legacy_and_dual_keep_real_block_binding(
    binding_runtime, monkeypatch, mode, shape
):
    questions, originals = run_real_stages(binding_runtime, monkeypatch, mode, shape)
    assert_bound_questions(questions, originals)
