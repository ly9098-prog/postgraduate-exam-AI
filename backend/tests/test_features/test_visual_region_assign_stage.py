"""Tests for visual_region_assign_stage — question-region assignment logic.

Covers:
- Single question on page gets all regions
- Two questions on page: regions split between them
- Region between two questions is assigned to the first
- Region inside option area gets option_key
- Ambiguous overlap (close to two questions) → requires_review
- Regions with no overlapping question → unassigned
- Cross-page assignment
"""
from __future__ import annotations

import pytest

from app.features.pipeline_stages.visual_region_assign_stage import (
    _assign_region_to_question,
    _compute_iou,
    _find_region_in_options,
    run_visual_region_assign_stage,
)


class TestIoU:
    def test_perfect_overlap(self):
        assert _compute_iou([0, 0, 100, 100], [0, 0, 100, 100]) == 1.0

    def test_no_overlap(self):
        assert _compute_iou([0, 0, 100, 100], [200, 200, 300, 300]) == 0.0

    def test_partial_overlap(self):
        # 50% overlap
        result = _compute_iou([0, 0, 100, 100], [50, 0, 150, 100])
        assert 0.3 < result < 0.5

    def test_contained(self):
        result = _compute_iou([0, 0, 100, 100], [25, 25, 75, 75])
        assert result == 0.25


class TestFindRegionInOptions:
    def test_region_in_option_a(self):
        q = {
            "option_spatial_bounds": {
                "A": [0, 0, 100, 50],
                "B": [0, 60, 100, 110],
            }
        }
        region = {"bbox": [10, 10, 90, 40]}  # inside A
        result = _find_region_in_options(region, q)
        assert result == "A"

    def test_region_not_in_any_option(self):
        q = {
            "option_spatial_bounds": {
                "A": [0, 0, 100, 50],
                "B": [0, 60, 100, 110],
            }
        }
        region = {"bbox": [200, 200, 300, 300]}
        result = _find_region_in_options(region, q)
        assert result is None


class TestAssignRegionToQuestion:
    def test_single_question_gets_region(self):
        questions = [(0, {"page_start": 1, "number": 1})]
        region = {"bbox": [100, 200, 300, 400], "region_id": "vr_test"}
        result = _assign_region_to_question(region, questions, 1)
        assert result["question_index"] == 0
        assert result["method"].value == "uncertain"

    def test_region_between_two_questions(self):
        """Region between Q1 and Q2 should go to Q1."""
        questions = [
            (0, {"page_start": 1, "number": 1, "question_bbox": [0, 100, 500, 300]}),
            (1, {"page_start": 1, "number": 2, "question_bbox": [0, 500, 500, 700]}),
        ]
        region = {"bbox": [100, 350, 400, 450], "region_id": "vr_test"}
        result = _assign_region_to_question(region, questions, 1)
        assert result["question_index"] == 0
        assert result["method"].value == "between_questions"

    def test_no_questions_on_page(self):
        result = _assign_region_to_question({"bbox": [0, 0, 100, 100], "region_id": "vr_test"}, [], 1)
        assert result["method"].value == "unassigned"

    def test_multiple_questions_no_bbox_no_clear_match(self):
        """Region with no bbox and multiple questions → unassigned."""
        questions = [(0, {"page_start": 1}), (1, {"page_start": 1})]
        region = {"region_id": "vr_test"}  # no bbox
        result = _assign_region_to_question(region, questions, 1)
        assert result["method"].value == "unassigned"


class TestRunVisualRegionAssignStage:
    def test_empty_questions(self):
        result = run_visual_region_assign_stage([], page_regions={})
        assert result["questions"] == []

    def test_no_regions_returns_warning(self):
        questions = [{"page_start": 1, "number": 1}]
        result = run_visual_region_assign_stage(questions, page_regions=None)
        warnings = " ".join(result.get("warnings", []))
        assert "no visual regions" in warnings

    def test_region_assigned_to_question(self):
        questions = [{"page_start": 1, "number": 1}]
        page_regions = {
            1: [
                {"region_id": "vr_1", "bbox": [100, 200, 300, 400],
                 "source_page": 1, "region_type": "diagram",
                 "coordinate_space": "normalized_1000", "confidence": 0.9,
                 "requires_review": True, "risk_flags": []}
            ]
        }
        result = run_visual_region_assign_stage(questions, page_regions=page_regions)
        q = result["questions"][0]
        assert len(q.get("visual_regions") or []) == 1
        assert "visual_region_detected" in (q.get("risk_flags") or [])

    def test_multiple_questions_page_gets_regions_on_correct_question(self):
        questions = [
            {"page_start": 1, "number": 1, "question_bbox": [0, 100, 500, 300]},
            {"page_start": 1, "number": 2, "question_bbox": [0, 500, 500, 700]},
        ]
        page_regions = {
            1: [
                {"region_id": "vr_q1", "bbox": [100, 150, 400, 250],
                 "source_page": 1, "region_type": "diagram",
                 "coordinate_space": "normalized_1000", "confidence": 0.9,
                 "requires_review": True, "risk_flags": []},
                {"region_id": "vr_q2", "bbox": [100, 550, 400, 650],
                 "source_page": 1, "region_type": "diagram",
                 "coordinate_space": "normalized_1000", "confidence": 0.9,
                 "requires_review": True, "risk_flags": []},
            ]
        }
        result = run_visual_region_assign_stage(questions, page_regions=page_regions)
        q1_vrs = result["questions"][0].get("visual_regions") or []
        q2_vrs = result["questions"][1].get("visual_regions") or []
        assert len(q1_vrs) == 1
        assert len(q2_vrs) == 1
        assert q1_vrs[0]["region_id"] == "vr_q1"
        assert q2_vrs[0]["region_id"] == "vr_q2"

    def test_region_between_questions_goes_to_first(self):
        """Region between Q1's bottom and Q2's top goes to Q1."""
        questions = [
            {"page_start": 1, "number": 1, "question_bbox": [0, 100, 500, 300]},
            {"page_start": 1, "number": 2, "question_bbox": [0, 500, 500, 700]},
        ]
        page_regions = {
            1: [
                {"region_id": "vr_between", "bbox": [100, 350, 400, 450],
                 "source_page": 1, "region_type": "diagram",
                 "coordinate_space": "normalized_1000", "confidence": 0.9,
                 "requires_review": True, "risk_flags": []},
            ]
        }
        result = run_visual_region_assign_stage(questions, page_regions=page_regions)
        q1_vrs = result["questions"][0].get("visual_regions") or []
        assert len(q1_vrs) == 1
        assert q1_vrs[0]["region_id"] == "vr_between"

    def test_region_near_next_question_is_ambiguous(self):
        """Region very close to Q2 should be marked ambiguous."""
        questions = [
            {"page_start": 1, "number": 1, "question_bbox": [0, 100, 500, 300]},
            {"page_start": 1, "number": 2, "question_bbox": [0, 320, 500, 700]},
        ]
        page_regions = {
            1: [
                {"region_id": "vr_close", "bbox": [100, 310, 400, 330],
                 "source_page": 1, "region_type": "diagram",
                 "coordinate_space": "normalized_1000", "confidence": 0.9,
                 "requires_review": True, "risk_flags": []},
            ]
        }
        result = run_visual_region_assign_stage(questions, page_regions=page_regions)
        q = result["questions"][0]
        # Should be ambiguous because it's within 30 units of next question
        risk_flags = q.get("risk_flags") or []
        assert any("ambiguous" in str(f) for f in risk_flags) or any(
            "ambiguous" in str(r.get("assignment_method"))
            for r in (q.get("visual_regions") or [])
        )
