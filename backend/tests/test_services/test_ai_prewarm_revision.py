"""Revision identity is a shared producer/consumer protocol, not worker state."""

from __future__ import annotations

import importlib
import re

import pytest

from app.ai.prewarm_revision import build_prewarm_revision


@pytest.mark.parametrize("count,normalized", [
    (None, 0), (0, 0), (1, 1), (-1, -1), ("3", 3), (True, 1), (3.9, 3),
])
def test_revision_preserves_legacy_count_coercion(count, normalized):
    revision = build_prewarm_revision(review_count=count, wrong_answer="synthetic-answer")
    assert revision.startswith(f"r{normalized}:")
    assert re.fullmatch(r"r-?\d+:[a-f0-9]{14}", revision)
    assert "synthetic-answer" not in revision


def test_none_and_empty_answer_are_the_same_legacy_revision():
    assert build_prewarm_revision(review_count=None, wrong_answer=None) == (
        build_prewarm_revision(review_count=0, wrong_answer="")
    )


@pytest.mark.parametrize("answer", ["AB", "ab", " AB ", "A|B\n", "合成答案"])
def test_answer_and_count_changes_invalidate_identity_without_exposing_answer(answer):
    first = build_prewarm_revision(review_count=2, wrong_answer=answer)
    assert first == build_prewarm_revision(review_count=2, wrong_answer=answer)
    assert first != build_prewarm_revision(review_count=3, wrong_answer=answer)
    assert first != build_prewarm_revision(review_count=2, wrong_answer=answer + "!")


def test_prompt_revision_invalidates_the_same_answer_event(monkeypatch):
    owner = importlib.import_module(build_prewarm_revision.__module__)
    monkeypatch.setattr(owner, "AI_ANALYSIS_PROMPT_VERSION", "protocol-fixture-v1")
    first = build_prewarm_revision(review_count=2, wrong_answer="AB")
    monkeypatch.setattr(owner, "AI_ANALYSIS_PROMPT_VERSION", "protocol-fixture-v2")
    assert first != build_prewarm_revision(review_count=2, wrong_answer="AB")


@pytest.mark.parametrize("count,exception", [
    ("bad", ValueError), (float("inf"), OverflowError), (float("nan"), ValueError),
    (object(), TypeError),
])
def test_invalid_count_keeps_conversion_failure(count, exception):
    with pytest.raises(exception):
        build_prewarm_revision(review_count=count, wrong_answer="AB")
