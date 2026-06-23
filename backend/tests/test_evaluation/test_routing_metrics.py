"""Tests for app.evaluation.routing_metrics."""

from __future__ import annotations

import pytest  # noqa: E402

from app.evaluation.routing_metrics import (
    RoutingMetricsCollector,
    RoutingRecord,
    build_routing_metrics,
    reset_global_collector,
)


class TestRoutingMetricsCollector:
    def test_empty_summary(self):
        collector = RoutingMetricsCollector()
        summary = collector.compute_summary()
        assert summary["total_runs"] == 0
        assert summary["mode_distribution"] == {}

    def test_single_record_standard(self):
        collector = RoutingMetricsCollector()
        collector.add_record(RoutingRecord(
            pipeline_id="p1",
            split_mode="standard",
            layout_confidence=0.85,
            option_detection_score=0.9,
            option_detection_failed=False,
            question_count=10,
            option_missing_questions=1,
            avg_split_confidence=0.9,
            split_quality_score=0.85,
        ))
        summary = collector.compute_summary()
        assert summary["total_runs"] == 1
        assert summary["mode_distribution"]["standard"]["count"] == 1
        assert summary["success_rates"]["standard"]["rate"] == 1.0
        assert summary["vl_trigger_rate"] == 0.0

    def test_mixed_modes(self):
        collector = RoutingMetricsCollector()
        collector.add_record(RoutingRecord(pipeline_id="p1", split_mode="standard",
            layout_confidence=0.85, option_detection_score=0.9,
            option_detection_failed=False, question_count=10,
            option_missing_questions=1, avg_split_confidence=0.9,
            split_quality_score=0.85))
        collector.add_record(RoutingRecord(pipeline_id="p2", split_mode="layout_enhanced",
            layout_confidence=0.65, option_detection_score=0.6,
            option_detection_failed=False, question_count=8,
            option_missing_questions=2, avg_split_confidence=0.7,
            split_quality_score=0.65))
        collector.add_record(RoutingRecord(pipeline_id="p3", split_mode="vl_rebuild",
            layout_confidence=0.3, option_detection_score=0.2,
            option_detection_failed=True, question_count=5,
            option_missing_questions=0, avg_split_confidence=0.95,
            split_quality_score=0.9, vl_trigger_reason="low_confidence"))
        summary = collector.compute_summary()
        assert summary["total_runs"] == 3
        assert list(summary["mode_distribution"].keys()) == [
            "layout_enhanced", "standard", "vl_rebuild"
        ]
        assert summary["vl_trigger_rate"] == pytest.approx(1 / 3, rel=0.01)  # noqa: F821

    def test_vl_trigger_reasons(self):
        collector = RoutingMetricsCollector()
        collector.add_record(RoutingRecord(pipeline_id="p1", split_mode="vl_rebuild",
            layout_confidence=0.3, option_detection_score=0.2,
            option_detection_failed=True, question_count=5,
            option_missing_questions=0, avg_split_confidence=0.95,
            split_quality_score=0.9, vl_trigger_reason="low_confidence"))
        collector.add_record(RoutingRecord(pipeline_id="p2", split_mode="vl_rebuild",
            layout_confidence=0.3, option_detection_score=0.2,
            option_detection_failed=False, question_count=3,
            option_missing_questions=1, avg_split_confidence=0.8,
            split_quality_score=0.7, vl_trigger_reason="low_confidence"))
        summary = collector.compute_summary()
        reasons = summary["vl_trigger_reason_distribution"]
        assert len(reasons) == 1
        assert reasons["low_confidence"]["count"] == 2

    def test_over_trigger_warning(self):
        collector = RoutingMetricsCollector()
        for i in range(12):
            split_mode = "vl_rebuild" if i < 2 else "standard"
            collector.add_record(RoutingRecord(
                pipeline_id=f"p{i}", split_mode=split_mode,
                layout_confidence=0.3 if split_mode == "vl_rebuild" else 0.85,
                option_detection_score=0.2 if split_mode == "vl_rebuild" else 0.9,
                option_detection_failed=split_mode == "vl_rebuild",
                question_count=5, option_missing_questions=0,
                avg_split_confidence=0.9, split_quality_score=0.85,
            ))
        summary = collector.compute_summary()
        # 2/12 = 16.7% > 10%, should trigger warning
        assert summary["vl_trigger_rate"] == pytest.approx(2 / 12, rel=0.01)  # noqa: F821
        assert summary["over_trigger_warning"] is not None
        assert "10%" in summary["over_trigger_warning"]

    def test_no_over_trigger(self):
        collector = RoutingMetricsCollector()
        for i in range(12):
            split_mode = "vl_rebuild" if i < 1 else "standard"
            collector.add_record(RoutingRecord(
                pipeline_id=f"p{i}", split_mode=split_mode,
                layout_confidence=0.3 if split_mode == "vl_rebuild" else 0.85,
                option_detection_score=0.2 if split_mode == "vl_rebuild" else 0.9,
                option_detection_failed=split_mode == "vl_rebuild",
                question_count=5, option_missing_questions=0,
                avg_split_confidence=0.9, split_quality_score=0.85,
            ))
        summary = collector.compute_summary()
        # 1/12 = 8.3% < 10%, no warning
        assert summary["over_trigger_warning"] is None

    def test_option_missing_rates(self):
        collector = RoutingMetricsCollector()
        collector.add_record(RoutingRecord(pipeline_id="p1", split_mode="standard",
            layout_confidence=0.85, option_detection_score=0.9,
            option_detection_failed=False, question_count=10,
            option_missing_questions=2, avg_split_confidence=0.9,
            split_quality_score=0.8))
        collector.add_record(RoutingRecord(pipeline_id="p2", split_mode="standard",
            layout_confidence=0.8, option_detection_score=0.85,
            option_detection_failed=False, question_count=10,
            option_missing_questions=1, avg_split_confidence=0.85,
            split_quality_score=0.8))
        summary = collector.compute_summary()
        omr = summary["option_missing_rates"]["standard"]
        assert omr["missing"] == 3
        assert omr["total_questions"] == 20
        assert omr["missing_rate"] == 0.15


class TestBuildRoutingMetrics:
    def test_full_data(self):
        data = {
            "split_diagnostics": {"split_mode": "standard"},
            "raw_questions": [
                {"number": 1, "has_options": True, "confidence": 0.9},
                {"number": 2, "has_options": True, "confidence": 0.85},
                {"number": 3, "has_options": False, "confidence": 0.7},
            ],
            "layout_result": {
                "layout_confidence": 0.85,
                "option_detection_score": 0.9,
                "option_detection_failed": False,
            },
            "split_quality": {"split_quality_score": 0.85},
        }
        metrics = build_routing_metrics(data)
        assert metrics["split_mode"] == "standard"
        assert metrics["question_count"] == 3
        assert metrics["option_missing_count"] == 1
        assert metrics["option_missing_rate"] == pytest.approx(1 / 3, rel=0.01)  # noqa: F821
        assert metrics["vl_trigger_reason"] is None

    def test_vl_rebuild_trigger_reason(self):
        data = {
            "split_diagnostics": {"split_mode": "vl_rebuild"},
            "raw_questions": [],
            "layout_result": {
                "layout_confidence": 0.3,
                "option_detection_score": 0.2,
                "option_detection_failed": True,
            },
            "split_quality": {},
        }
        metrics = build_routing_metrics(data)
        assert metrics["split_mode"] == "vl_rebuild"
        # VL trigger reason is always "low_confidence" under frozen policy
        assert metrics["vl_trigger_reason"] == "low_confidence"

    def test_empty_data_falls_back(self):
        data = {}
        metrics = build_routing_metrics(data)
        assert metrics["split_mode"] == "unknown"
        assert metrics["question_count"] == 0

    def test_global_collector(self):
        reset_global_collector()
        from app.evaluation.routing_metrics import get_global_collector
        c1 = get_global_collector()
        c2 = get_global_collector()
        assert c1 is c2  # same instance
        reset_global_collector()
        c3 = get_global_collector()
        assert c3 is not c1  # new instance after reset

