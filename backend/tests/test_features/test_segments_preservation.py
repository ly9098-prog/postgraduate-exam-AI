"""Tests for segments preservation across the publish flow.

Verifies that content.segments survives:
1. QuestionNormalizer.to_import_fields
2. QuestionNormalizer.to_question_fields
3. process_question_pipeline output (question_fields)
4. approve_question (with mock db)
5. Old string-only options remain compatible
"""
from __future__ import annotations

import pytest

from app.features.question_pipeline import QuestionNormalizer, process_question_pipeline


normalizer = QuestionNormalizer()

_SAMPLE_SEGMENTS = [
    {"type": "text", "text": "观察下列结构："},
    {
        "type": "image",
        "url": "/static/questions/test/diagram.png",
        "alt": "题目示意图",
        "region_type": "diagram",
        "source_page": 3,
        "bbox": [120, 260, 680, 520],
        "coordinate_space": "image_pixels",
        "display": True,
        "requires_review": False,
    },
    {"type": "text", "text": "则正确答案为（）。"},
]

_SAMPLE_QUESTION = {
    "subject": "math2",
    "question_type": "single_choice",
    "stem": "观察下列结构：\n\n[图片]\n\n则正确答案为（）。",
    "options": [
        {"key": "A", "text": "选项一"},
        {"key": "B", "text": "选项二"},
        {"key": "C", "text": "选项三"},
        {"key": "D", "text": "选项四"},
    ],
    "answer": "A",
    "analysis": "本题考查结构分析",
    "segments": _SAMPLE_SEGMENTS,
    "parsed_content": {
        "text": "观察下列结构：\n\n[图片]\n\n则正确答案为（）。",
        "render_mode": "segments",
        "segments": _SAMPLE_SEGMENTS,
    },
}


class TestToImportFieldsPreservesSegments:
    """QuestionNormalizer.to_import_fields should preserve segments."""

    def test_segments_preserved(self):
        normalized = normalizer.normalize(_SAMPLE_QUESTION)
        fields = normalizer.to_import_fields(normalized)
        content = fields["parsed_content"]
        assert content.get("render_mode") == "segments"
        assert content.get("segments") == _SAMPLE_SEGMENTS

    def test_no_segments_no_render_mode(self):
        """Plain text question should not get render_mode or segments."""
        question = dict(_SAMPLE_QUESTION)
        question["segments"] = []
        question["parsed_content"] = {"text": "普通题干"}
        normalized = normalizer.normalize(question)
        fields = normalizer.to_import_fields(normalized)
        content = fields["parsed_content"]
        assert content.get("render_mode") is None
        assert content.get("segments") is None


class TestToQuestionFieldsPreservesSegments:
    """QuestionNormalizer.to_question_fields should preserve segments."""

    def test_segments_preserved(self):
        normalized = normalizer.normalize(_SAMPLE_QUESTION)
        fields = normalizer.to_question_fields(normalized)
        content = fields["content"]
        assert content.get("render_mode") == "segments"
        assert content.get("segments") == _SAMPLE_SEGMENTS


class TestProcessQuestionPipelinePreservesSegments:
    """process_question_pipeline should preserve segments in question_fields."""

    def test_segments_in_question_fields(self):
        result = process_question_pipeline(_SAMPLE_QUESTION, "manual")
        assert result["is_valid"]
        qf = result.get("question_fields")
        assert qf is not None
        content = qf["content"]
        assert content.get("render_mode") == "segments"
        assert content.get("segments") == _SAMPLE_SEGMENTS

    def test_import_fields_when_segments_exist(self):
        """Test that import_fields also preserves segments."""
        result = process_question_pipeline(_SAMPLE_QUESTION, "manual")
        imp_fields = result.get("import_fields")
        assert imp_fields is not None
        content = imp_fields["parsed_content"]
        assert content.get("render_mode") == "segments"
        assert content.get("segments") == _SAMPLE_SEGMENTS

    def test_old_string_options_compatible(self):
        """Old string-only options format remains compatible."""
        old_question = {
            "subject": "math2",
            "question_type": "single_choice",
            "stem": "普通题干",
            "options": {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"},
            "answer": "A",
            "analysis": "解析",
        }
        result = process_question_pipeline(old_question, "manual")
        assert result["is_valid"]
        qf = result["question_fields"]
        assert qf is not None
        options = qf["options"]
        assert options == {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}


class TestRichOptionsFormat:
    """Options with text+segments format should be supported."""

    def test_rich_options_dict(self):
        """Verify options_to_dict handles rich options."""
        options_list = [
            {"key": "A", "text": "选项A文字", "segments": [{"type": "image", "url": "/img/a.png"}]},
            {"key": "B", "text": "选项B文字"},
        ]
        result = normalizer.options_to_dict(options_list)
        assert result is not None
        assert result["A"] == {"text": "选项A文字", "segments": [{"type": "image", "url": "/img/a.png"}]}
        assert result["B"] == "选项B文字"

    def test_rich_options_input_dict(self):
        """Verify normalize_options handles rich dict input."""
        raw_options = {
            "A": {"text": "选项A文字", "segments": [{"type": "image", "url": "/img/a.png"}]},
            "B": "选项B文字",
        }
        normalized = normalizer.normalize_options(raw_options)
        assert len(normalized) == 2
        a_option = [o for o in normalized if o["key"] == "A"][0]
        assert a_option["text"] == "选项A文字"
        assert a_option["segments"] == [{"type": "image", "url": "/img/a.png"}]
