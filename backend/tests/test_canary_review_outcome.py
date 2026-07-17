"""Canary review outcome tests."""
from __future__ import annotations

import json

import pytest

from app.features.ocr_canary import CanaryReviewOutcome


class TestCanaryReviewOutcome:
    def test_outcome_creation(self):
        outcome = CanaryReviewOutcome(
            pipeline_id="p123",
            document_id="d456",
            group="canary_c",
            accepted=True,
            reviewer="human1",
            reviewed_at="2026-07-17T10:00:00",
        )
        assert outcome.pipeline_id == "p123"
        assert outcome.accepted is True

    def test_outcome_with_issues(self):
        outcome = CanaryReviewOutcome(
            pipeline_id="p123",
            document_id="d456",
            group="canary_c",
            accepted=False,
            issue_types=["option_missing", "reading_order_wrong"],
            affected_question_ids=["q1", "q2"],
            reviewer="human1",
            reviewed_at="2026-07-17T10:05:00",
            notes="选项B缺失，阅读顺序错误",
        )
        assert outcome.accepted is False
        assert len(outcome.issue_types) == 2
        assert "option_missing" in outcome.issue_types

    def test_outcome_serializable(self):
        outcome = CanaryReviewOutcome(
            pipeline_id="p123",
            document_id="d456",
            group="canary_c",
            accepted=True,
        )
        d = outcome.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["pipeline_id"] == "p123"
        assert parsed["accepted"] is True

    def test_outcome_roundtrip(self):
        outcome = CanaryReviewOutcome(
            pipeline_id="p123",
            document_id="d456",
            group="canary_c",
            accepted=False,
            issue_types=["stem_corrupted"],
            affected_question_ids=["q1"],
            reviewer="human1",
            reviewed_at="2026-07-17T10:10:00",
            notes="题干乱码",
        )
        d = outcome.to_dict()
        restored = CanaryReviewOutcome.from_dict(d)
        assert restored.pipeline_id == outcome.pipeline_id
        assert restored.accepted == outcome.accepted
        assert restored.issue_types == outcome.issue_types
        assert restored.notes == outcome.notes

    def test_default_values(self):
        outcome = CanaryReviewOutcome(pipeline_id="p1", document_id="d1", group="control_a", accepted=True)
        assert outcome.issue_types == []
        assert outcome.affected_question_ids == []
        assert outcome.reviewer == ""
        assert outcome.notes == ""

    def test_from_dict_defaults(self):
        restored = CanaryReviewOutcome.from_dict({"pipeline_id": "p1", "document_id": "d1", "group": "x", "accepted": False})
        assert restored.issue_types == []
        assert restored.notes == ""

    def test_issue_types_enum(self):
        """All common issue types should be valid."""
        valid_issues = [
            "question_missing", "question_extra", "stem_corrupted",
            "option_missing", "option_reordered", "answer_wrong",
            "reading_order_wrong", "cross_page_wrong", "code_corrupted",
            "formula_corrupted", "table_corrupted", "image_binding_wrong",
            "other",
        ]
        outcome = CanaryReviewOutcome(
            pipeline_id="p1",
            document_id="d1",
            group="canary_c",
            accepted=False,
            issue_types=valid_issues,
        )
        assert len(outcome.issue_types) == 13
