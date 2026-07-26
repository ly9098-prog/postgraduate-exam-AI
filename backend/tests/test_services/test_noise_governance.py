"""Unit tests for v2 noise governance modules: metrics, drift detection, rule governor."""

from __future__ import annotations

import pytest

from app.features.pipeline_stages.code_language_noise_metrics import (
    NoiseMetrics,
    NoiseMetricsCollector,
    format_metrics_summary,
)
from app.features.pipeline_stages.noise_drift_detector import (
    DEFAULT_BASELINE,
    _distribution_from_counts,
    _kl_divergence,
    detect_drift,
)
from app.features.pipeline_stages.noise_rule_governor import (
    _FP_RATE_HIGH,
    _FP_RATE_LOW,
    DEFAULT_POLICY,
    evaluate_policy,
)

# ============================================================================
# NoiseMetrics
# ============================================================================


class TestNoiseMetrics:
    def test_noise_ratio(self):
        metrics = NoiseMetrics(total_lines=100, total_noise_detected=25)
        assert metrics.noise_ratio == 0.25

    def test_noise_ratio_zero_lines(self):
        """total_lines=0 uses max(0,1)=1 divisor."""
        metrics = NoiseMetrics(total_lines=0, total_noise_detected=5)
        assert metrics.noise_ratio == 5.0

    def test_c_cpp_noise_ratio(self):
        metrics = NoiseMetrics(total_lines=100)
        metrics.noise_type_counts["c_cpp_noise"] = 20
        assert metrics.c_cpp_noise_ratio == 0.20

    def test_c_cpp_noise_ratio_zero_lines(self):
        """total_lines=0 uses max(0,1)=1 divisor."""
        metrics = NoiseMetrics(total_lines=0)
        metrics.noise_type_counts["c_cpp_noise"] = 5
        assert metrics.c_cpp_noise_ratio == 5.0

    @pytest.mark.parametrize("noise_ratio,expected", [
        (0.0, "low"),
        (0.05, "low"),
        (0.1, "low"),
        (0.15, "medium"),
        (0.3, "medium"),
        (0.35, "high"),
        (0.5, "high"),
    ])
    def test_risk_level(self, noise_ratio, expected):
        """noise_ratio <= 0.1 → low, > 0.1 and <= 0.3 → medium, > 0.3 → high."""
        metrics = NoiseMetrics(total_lines=100, total_noise_detected=int(noise_ratio * 100))
        assert metrics.risk_level == expected

    def test_to_dict(self):
        metrics = NoiseMetrics(
            doc_id="doc_1",
            total_lines=50,
            total_transition_zones=3,
            total_noise_detected=8,
            removed_lines_count=5,
            protected_lines_count=2,
            false_positive_suspected_count=1,
        )
        metrics.noise_type_counts["c_cpp_noise"] = 6
        metrics.noise_type_counts["tag_noise"] = 2
        d = metrics.to_dict()
        assert d["doc_id"] == "doc_1"
        assert d["noise_ratio"] == 0.16
        assert d["risk_level"] == "medium"
        assert d["noise_type_counts"]["c_cpp_noise"] == 6
        assert d["removed_lines_count"] == 5
        assert d["protected_lines_count"] == 2
        assert "removed_lines" not in d  # internal field, not serialized


# ============================================================================
# NoiseMetricsCollector
# ============================================================================


class TestNoiseMetricsCollector:
    def test_record_total_lines(self):
        c = NoiseMetricsCollector("d1")
        c.record_total_lines(42)
        assert c.metrics.total_lines == 42

    def test_record_zones(self):
        c = NoiseMetricsCollector("d1")
        c.record_zones([(1, 3), (5, 6)])
        assert c.metrics.total_transition_zones == 2
        assert c.metrics.total_zone_lines == 5  # 3 + 2

    def test_record_classification_skips_empty(self):
        c = NoiseMetricsCollector("d1")
        c.record_classification("", 0.9)
        assert c.metrics.total_noise_detected == 0

    def test_record_classification_counts(self):
        c = NoiseMetricsCollector("d1")
        c.record_classification("c_cpp_noise", 0.95)
        c.record_classification("tag_noise", 0.85)
        c.record_classification("c_cpp_noise", 0.95)
        assert c.metrics.total_noise_detected == 3
        assert c.metrics.noise_type_counts["c_cpp_noise"] == 2
        assert c.metrics.noise_type_counts["tag_noise"] == 1

    def test_record_removal(self):
        c = NoiseMetricsCollector("d1")
        c.record_removal(5, "c_cpp_noise")
        c.record_removal(12, "tag_noise")
        assert c.metrics.removed_lines_count == 2
        assert c.metrics.removed_lines == [5, 12]

    def test_record_protected_counts_as_false_positive(self):
        c = NoiseMetricsCollector("d1")
        c.record_protected("c_cpp_noise")
        assert c.metrics.protected_lines_count == 1
        assert c.metrics.false_positive_suspected_count == 1

    def test_collector_lifecycle(self):
        """End-to-end: record and read back."""
        c = NoiseMetricsCollector("lifecycle")
        c.record_total_lines(10)
        c.record_zones([(2, 4)])
        c.record_classification("c_cpp_noise", 0.95)
        c.record_classification("c_cpp_noise", 0.95)
        c.record_classification("python_noise", 0.90)
        c.record_removal(2, "c_cpp_noise")
        c.record_removal(3, "c_cpp_noise")
        c.record_protected("python_noise")
        m = c.metrics
        assert m.total_lines == 10
        assert m.total_transition_zones == 1
        assert m.total_noise_detected == 3
        assert m.removed_lines_count == 2
        assert m.protected_lines_count == 1
        assert m.false_positive_suspected_count == 1
        assert m.noise_type_counts["c_cpp_noise"] == 2
        assert m.noise_type_counts["python_noise"] == 1
        assert m.risk_level == "medium"  # 3/10 = 0.3


# ============================================================================
# format_metrics_summary
# ============================================================================


class TestFormatMetricsSummary:
    def test_empty_list(self):
        assert format_metrics_summary([]) == {}

    def test_aggregates_counts(self):
        m1 = NoiseMetrics(
            doc_id="0", total_lines=100, total_noise_detected=10,
            removed_lines_count=5, protected_lines_count=2,
            false_positive_suspected_count=1,
        )
        m1.noise_type_counts["c_cpp_noise"] = 8
        m2 = NoiseMetrics(
            doc_id="1", total_lines=50, total_noise_detected=5,
            removed_lines_count=3, protected_lines_count=0,
        )
        m2.noise_type_counts["tag_noise"] = 5

        summary = format_metrics_summary([m1, m2])
        assert summary["documents_processed"] == 2
        assert summary["total_noise_detected"] == 15
        assert summary["total_removed_lines"] == 8
        assert summary["total_protected_lines"] == 2
        assert summary["total_false_positive_suspected"] == 1
        assert summary["noise_type_distribution"]["c_cpp_noise"] == 8
        assert summary["noise_type_distribution"]["tag_noise"] == 5

    def test_risk_distribution(self):
        m1 = NoiseMetrics(total_lines=100, total_noise_detected=5)    # low
        m2 = NoiseMetrics(total_lines=100, total_noise_detected=20)   # medium
        m3 = NoiseMetrics(total_lines=100, total_noise_detected=40)   # high
        m4 = NoiseMetrics(total_lines=100, total_noise_detected=5)    # low

        summary = format_metrics_summary([m1, m2, m3, m4])
        assert summary["risk_distribution"]["low"] == 2
        assert summary["risk_distribution"]["medium"] == 1
        assert summary["risk_distribution"]["high"] == 1

    def test_avg_noise_ratio(self):
        m1 = NoiseMetrics(total_lines=100, total_noise_detected=10)   # 0.10
        m2 = NoiseMetrics(total_lines=100, total_noise_detected=30)   # 0.30
        summary = format_metrics_summary([m1, m2])
        assert summary["avg_noise_ratio"] == 0.20

    def test_high_risk_docs(self):
        m1 = NoiseMetrics(doc_id="a", total_lines=10, total_noise_detected=1)   # low
        m2 = NoiseMetrics(doc_id="b", total_lines=10, total_noise_detected=4)   # high (>0.3)
        summary = format_metrics_summary([m1, m2])
        assert summary["high_risk_docs"] == ["b"]


# ============================================================================
# _distribution_from_counts
# ============================================================================


class TestDistributionFromCounts:
    def test_normal_counts(self):
        dist = _distribution_from_counts({"a": 10, "b": 30})
        assert dist["a"] == 0.25
        assert dist["b"] == 0.75

    def test_empty_counts(self):
        dist = _distribution_from_counts({})
        assert dist == {}

    def test_zero_total(self):
        dist = _distribution_from_counts({"a": 0, "b": 0})
        assert dist == {}


# ============================================================================
# _kl_divergence
# ============================================================================


class TestKLDivergence:
    def test_identical_distributions(self):
        p = {"a": 0.5, "b": 0.5}
        q = {"a": 0.5, "b": 0.5}
        assert _kl_divergence(p, q) == 0.0

    def test_divergent_distributions(self):
        """Completely non-overlapping → high KL score via Laplace smoothing."""
        p = {"a": 1.0}
        q = {"b": 1.0}
        # KL(P||Q) = 1.0 * log(1.0 / 1e-10) ≈ 23.0
        score = _kl_divergence(p, q)
        assert score > 20.0

    def test_missing_keys_smoothed(self):
        p = {"a": 1.0}
        q = {"b": 1.0}
        # Laplace smoothing gives both sides 1e-10 for missing keys
        score = _kl_divergence(p, q)
        assert score > 0.0

    def test_partial_overlap(self):
        p = {"a": 0.6, "b": 0.4}
        q = {"a": 0.6, "c": 0.4}  # b missing, c unexpected
        score = _kl_divergence(p, q)
        assert score > 0.0


# ============================================================================
# detect_drift
# ============================================================================


class TestDetectDrift:
    def test_no_drift(self):
        """Runtime counts matching baseline → drift_score ≈ 0, no drift."""
        counts = {"c_cpp_noise": 50, "python_noise": 5, "tag_noise": 15, "lang_label": 10, "generic_ocr_noise": 20}
        result = detect_drift(counts)
        assert result["drift_detected"] is False
        assert result["drift_score"] < 0.01

    def test_drift_detected(self):
        """Runtime has c_cpp_noise only → large divergence from baseline."""
        counts = {"c_cpp_noise": 100}
        result = detect_drift(counts)
        assert result["drift_detected"] is True
        assert result["drift_score"] > 0.15

    def test_empty_runtime(self):
        """No runtime data → drift_detected=False with message."""
        result = detect_drift({})
        assert result["drift_detected"] is False
        assert result["drift_score"] == 0.0
        assert result["message"] == "no_runtime_data"

    def test_custom_baseline(self):
        baseline = {"my_noise": 1.0}
        counts = {"my_noise": 10}
        result = detect_drift(counts, baseline=baseline)
        assert result["drift_detected"] is False

    def test_custom_threshold(self):
        counts = {"c_cpp_noise": 100, "python_noise": 0, "tag_noise": 0, "lang_label": 0, "generic_ocr_noise": 0}
        result = detect_drift(counts, threshold=10.0)  # very high threshold
        assert result["drift_detected"] is False

    def test_top_changed_noise(self):
        counts = {"c_cpp_noise": 100}
        result = detect_drift(counts)
        assert result["top_changed_noise"] == "c_cpp_noise"
        # max_delta should be ~0.50 (0.50→1.0 or 0.50→0.0 for other types)
        assert result["max_delta"] > 0.30

    def test_uses_default_baseline_when_none(self):
        counts = {"c_cpp_noise": 50, "python_noise": 5, "tag_noise": 15, "lang_label": 10, "generic_ocr_noise": 20}
        result = detect_drift(counts, baseline=None)
        assert not result["drift_detected"]
        assert result["baseline_distribution"] == DEFAULT_BASELINE

    def test_runtime_distribution_in_result(self):
        counts = {"c_cpp_noise": 10, "tag_noise": 10}
        result = detect_drift(counts)
        assert result["runtime_distribution"]["c_cpp_noise"] == 0.5
        assert result["runtime_distribution"]["tag_noise"] == 0.5


# ============================================================================
# evaluate_policy
# ============================================================================


class TestEvaluatePolicy:
    def test_no_data_returns_no_data_available(self):
        result = evaluate_policy()
        assert result["changes"] == ["no_data_available"]
        assert result["false_positive_rate"] == 0.0
        assert result["policy"]["safe_mode"] is False

    def test_fp_rate_below_low_threshold_stays_normal(self):
        """FP rate < 0.02 → normal mode stays normal."""
        result = evaluate_policy(
            false_positive_suspected_count=1,
            total_protected_count=10,
            total_removed_count=90,
        )
        fp_rate = 1 / (90 + 10)
        assert fp_rate < _FP_RATE_LOW
        assert result["false_positive_rate"] == fp_rate
        assert result["policy"]["safe_mode"] is False
        assert result["changes"] == ["no_change_needed"]

    def test_fp_rate_above_high_threshold_enables_safe_mode(self):
        """FP rate > 0.10 → enable safe_mode."""
        result = evaluate_policy(
            false_positive_suspected_count=15,
            total_protected_count=20,
            total_removed_count=80,
        )
        fp_rate = 15 / (80 + 20)
        assert fp_rate > _FP_RATE_HIGH
        assert result["policy"]["safe_mode"] is True
        assert "safe_mode_enabled" in result["changes"][0]

    def test_fp_rate_between_thresholds_no_change(self):
        """0.02 <= FP rate <= 0.10 → no change."""
        result = evaluate_policy(
            false_positive_suspected_count=5,
            total_protected_count=10,
            total_removed_count=90,
        )
        fp_rate = 5 / (90 + 10)
        assert _FP_RATE_LOW <= fp_rate <= _FP_RATE_HIGH
        assert result["changes"] == ["no_change_needed"]

    def test_fp_rate_below_low_with_safe_mode_on_disables_safe_mode(self):
        """Already in safe_mode, FP rate drops below 0.02 → disable safe_mode."""
        result = evaluate_policy(
            false_positive_suspected_count=1,
            total_protected_count=10,
            total_removed_count=90,
            current_policy={"safe_mode": True},
        )
        assert result["policy"]["safe_mode"] is False
        assert "safe_mode_disabled" in result["changes"][0]

    def test_fp_rate_above_high_already_in_safe_mode(self):
        """Already in safe_mode, FP rate still high → no change needed."""
        result = evaluate_policy(
            false_positive_suspected_count=15,
            total_protected_count=20,
            total_removed_count=80,
            current_policy={"safe_mode": True},
        )
        assert result["policy"]["safe_mode"] is True
        assert result["changes"] == ["no_change_needed"]

    def test_hysteresis_mid_band(self):
        """FP rate between 0.02 and 0.10 in safe_mode → stays safe_mode."""
        result = evaluate_policy(
            false_positive_suspected_count=5,
            total_protected_count=10,
            total_removed_count=90,
            current_policy={"safe_mode": True},
        )
        assert result["policy"]["safe_mode"] is True  # no transition
        assert result["changes"] == ["no_change_needed"]

    def test_zero_protected_zero_removed(self):
        """No decisions at all → no_data_available."""
        result = evaluate_policy(false_positive_suspected_count=0)
        assert result["changes"] == ["no_data_available"]

    def test_custom_current_policy_preserved(self):
        """Custom policy fields not touched by governor."""
        result = evaluate_policy(
            false_positive_suspected_count=0,
            total_protected_count=0,
            total_removed_count=0,
            current_policy={"safe_mode": True, "custom_field": "keep_me"},
        )
        assert result["policy"]["custom_field"] == "keep_me"
        assert result["policy"]["safe_mode"] is True

    def test_default_policy_copy_not_mutated(self):
        """evaluate_policy should not mutate the module-level DEFAULT_POLICY."""
        original_safe_mode = DEFAULT_POLICY["safe_mode"]
        evaluate_policy(
            false_positive_suspected_count=15,
            total_protected_count=20,
            total_removed_count=80,
        )
        assert DEFAULT_POLICY["safe_mode"] == original_safe_mode
