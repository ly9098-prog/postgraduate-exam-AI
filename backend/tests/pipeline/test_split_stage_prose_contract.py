"""Numbered book prose has its own block diagnostic thresholds and preview cap."""

import pytest

from tests.pipeline.split_stage_support import split_harness


def test_numbered_prose_records_twenty_previews_with_eighty_character_text(monkeypatch):
    h = split_harness(monkeypatch)
    h.questions = []
    body = "定义：甲。 定理：乙。 " + "正文 " * 80
    h.blocks = [{"page": i, "normalized_text": f"{i}.  {body}"} for i in range(1, 26)]
    result = h.pipeline._run_split(h.blocks, import_mode="book", source_type="pdf")
    diagnostics = result["split_diagnostics"]
    assert diagnostics["prose_skipped_count"] == 20
    assert diagnostics["prose_skipped_preview"] == [
        {
            "page": i,
            "number": i,
            "text": (f"{i}. " + body)[:80],
        }
        for i in range(1, 21)
    ]
    assert diagnostics["non_question_like_skipped"] is True
    assert result["raw_questions"] == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1. 定义：甲。定理：乙。", True),
        ("1．定义：甲。定理：乙。", True),
        ("1、定义：甲。定理：乙。", True),
        ("1. 定义：甲。普通正文。", False),
        ("1. 定义：甲，定理：乙。", False),
        ("定义：甲。定理：乙。", False),
        ("1. 定义：甲。定理：乙。计算结果", False),
        ("1. 定义：甲。定理：乙。\nA. 一", False),
        ("1. 定义：甲。定理：乙。\nD）四", False),
    ],
)
def test_block_prose_requires_number_two_markers_two_sentences_and_no_options(
    monkeypatch,
    text,
    expected,
):
    h = split_harness(monkeypatch)
    h.questions = []
    h.blocks = [{"page": 7, "normalized_text": text}]
    result = h.pipeline._run_split(h.blocks, import_mode="book", source_type="pdf")
    assert ("prose_skipped_count" in result["split_diagnostics"]) is expected
    if expected:
        assert result["split_diagnostics"]["prose_skipped_count"] == 1
        assert result["split_diagnostics"]["prose_skipped_preview"][0]["page"] == 7
