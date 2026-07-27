"""OCR 告警规则回归测试 — evaluate_alerts 正确性与边界覆盖。"""

import pytest

from app.features.ocr_alert_rules import evaluate_alerts


class TestImportFailedAlert:
    def test_failed_status_quality_report(self):
        """quality_report status=failed 应触发 import_failed error。"""
        alerts = evaluate_alerts({"status": "failed"}, {})
        codes = [a["code"] for a in alerts]
        assert "import_failed" in codes
        error_levels = [a for a in alerts if a["code"] == "import_failed"]
        assert error_levels[0]["level"] == "error"

    def test_failed_status_diagnostics(self):
        """diagnostics status=failed 也应触发 import_failed。"""
        alerts = evaluate_alerts({}, {"status": "failed"})
        codes = [a["code"] for a in alerts]
        assert "import_failed" in codes

    def test_success_no_import_failed(self):
        """正常完成不应触发 import_failed。"""
        alerts = evaluate_alerts(
            {"status": "completed", "total_questions": 10, "high_risk": 1},
            {"status": "completed"},
        )
        codes = [a["code"] for a in alerts]
        assert "import_failed" not in codes


class TestHighRiskRatioAlert:
    def test_high_risk_exceeds_threshold(self):
        """高风险比例 > 0.40 应触发 warning。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "high_risk": 5, "requires_manual_review": 5},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "high_risk_ratio_too_high" in codes

    def test_high_risk_below_threshold(self):
        """高风险比例 ≤ 0.40 不应触发。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "high_risk": 3, "requires_manual_review": 3},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "high_risk_ratio_too_high" not in codes

    def test_high_risk_zero_total(self):
        """total_questions=0 不应触发（safe_ratio 返回 0）。"""
        alerts = evaluate_alerts(
            {"total_questions": 0, "high_risk": 5, "requires_manual_review": 5},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "high_risk_ratio_too_high" not in codes

    def test_high_risk_missing_total(self):
        """total_questions 缺失时不触发（safe_ratio 返回 0）。"""
        alerts = evaluate_alerts({"high_risk": 5}, {})
        codes = [a["code"] for a in alerts]
        assert "high_risk_ratio_too_high" not in codes


class TestManualReviewRateAlert:
    def test_review_rate_exceeds_threshold(self):
        """人工审核率 > 0.50 应触发 warning。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "requires_manual_review": 6, "high_risk": 2},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "manual_review_rate_too_high" in codes

    def test_review_rate_below_threshold(self):
        """人工审核率 ≤ 0.50 不应触发。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "requires_manual_review": 5, "high_risk": 1},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "manual_review_rate_too_high" not in codes

    def test_review_rate_boundary(self):
        """人工审核率恰好 0.50 不应触发（gt 而非 gte）。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "requires_manual_review": 5, "high_risk": 2},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "manual_review_rate_too_high" not in codes


class TestAiAnswerCountAlert:
    def test_ai_answer_count_high(self):
        """AI 答案 > 10 应触发 warning。"""
        alerts = evaluate_alerts(
            {"total_questions": 50, "ai_answer_count": 15, "high_risk": 0},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "ai_answer_count_too_high" in codes

    def test_ai_answer_count_low(self):
        """AI 答案 ≤ 10 不应触发。"""
        alerts = evaluate_alerts(
            {"total_questions": 50, "ai_answer_count": 5, "high_risk": 0},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "ai_answer_count_too_high" not in codes

    def test_ai_answer_count_none(self):
        """ai_answer_count 为 None 应视为 0，不触发。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "ai_answer_count": None, "high_risk": 0},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "ai_answer_count_too_high" not in codes


class TestOcrCacheHitRateAlert:
    def test_cache_hit_rate_low(self):
        """缓存命中率 < 0.20 应触发 info。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "ocr_cache_hit": 1, "ocr_cache_miss": 9, "high_risk": 0},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "ocr_cache_hit_rate_too_low" in codes

    def test_cache_hit_rate_high(self):
        """缓存命中率 ≥ 0.20 不应触发。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "ocr_cache_hit": 5, "ocr_cache_miss": 5, "high_risk": 0},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "ocr_cache_hit_rate_too_low" not in codes

    def test_cache_hit_miss_both_zero(self):
        """cache_hit 和 cache_miss 均为 0 时 ratio=0.0 < 0.20，会触发 info 级告警。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "ocr_cache_hit": 0, "ocr_cache_miss": 0, "high_risk": 0},
            {},
        )
        codes = [a["code"] for a in alerts]
        assert "ocr_cache_hit_rate_too_low" in codes


class TestOcrFailedPageRatioAlert:
    def test_failed_page_ratio_high(self):
        """OCR 失败页比例 > 0.30 应触发 warning。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "high_risk": 0},
            {
                "ocr_boxes_failed_pages": [1, 2, 3, 4],
                "ocr_runtime_failed_pages": [5, 6],
                "structure": {"total_pages": 15},
            },
        )
        codes = [a["code"] for a in alerts]
        assert "ocr_failed_page_ratio_too_high" in codes

    def test_failed_page_ratio_low(self):
        """OCR 失败页比例 ≤ 0.30 不应触发。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "high_risk": 0},
            {
                "ocr_boxes_failed_pages": [1],
                "structure": {"total_pages": 50},
            },
        )
        codes = [a["code"] for a in alerts]
        assert "ocr_failed_page_ratio_too_high" not in codes

    def test_failed_page_no_structure(self):
        """structure 缺失时使用 page_classifications 长度作为总页数。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "high_risk": 0},
            {
                "ocr_boxes_failed_pages": [1, 2, 3, 4, 5, 6, 7, 8],
                "page_classifications": ["math"] * 10,
            },
        )
        codes = [a["code"] for a in alerts]
        assert "ocr_failed_page_ratio_too_high" in codes


class TestDurationAlert:
    def test_duration_exceeds_threshold(self):
        """duration > 300s 应触发 warning。"""
        alerts = evaluate_alerts(
            {"total_questions": 100, "high_risk": 0},
            {
                "performance_profile": {
                    "_summary": {"total_duration_ms": 350000},
                },
            },
        )
        codes = [a["code"] for a in alerts]
        assert "pipeline_duration_too_long" in codes

    def test_duration_below_threshold(self):
        """duration ≤ 300s 不应触发。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "high_risk": 0},
            {
                "performance_profile": {
                    "_summary": {"total_duration_ms": 50000},
                },
            },
        )
        codes = [a["code"] for a in alerts]
        assert "pipeline_duration_too_long" not in codes

    def test_duration_missing_profile(self):
        """performance_profile 缺失时不触发。"""
        alerts = evaluate_alerts({"total_questions": 10, "high_risk": 0}, {})
        codes = [a["code"] for a in alerts]
        assert "pipeline_duration_too_long" not in codes


class TestAlertOrdering:
    def test_error_before_warning_before_info(self):
        """告警应按 error → warning → info 排序。"""
        alerts = evaluate_alerts(
            {"status": "failed"},
            {"status": "failed"},
        )
        if len(alerts) < 2:
            return
        levels = [a["level"] for a in alerts]
        prev_order = 0
        order = {"error": 0, "warning": 1, "info": 2}
        for level in levels:
            curr = order.get(level, 99)
            assert curr >= prev_order, f"告警顺序错误: {levels}"
            prev_order = curr


class TestEdgeCases:
    def test_none_inputs(self):
        """quality_report 和 diagnostics 均为 None 时仅可能触发 info 级告警。"""
        alerts = evaluate_alerts(None, None)
        # 空 dict 导致 ocr_cache_hit=0, ocr_cache_miss=0, ratio=0.0 < 0.20 → info
        for a in alerts:
            assert a["level"] in ("info",), f"意外的告警级别: {a}"
        assert all(a["level"] == "info" for a in alerts), "None 输入最多触发 info 级告警"

    def test_empty_dicts(self):
        """空字典输入时仅 info 级告警可触发。"""
        alerts = evaluate_alerts({}, {})
        for a in alerts:
            assert a["level"] == "info", f"空 dict 不应触发 {a['level']} 级告警: {a}"

    def test_missing_all_fields(self):
        """缺失所有字段时仅 info 级告警（缓存命中率低）。"""
        alerts = evaluate_alerts(
            {"status": "completed"},
            {"status": "completed"},
        )
        for a in alerts:
            assert a["level"] == "info", f"正常完成不应触发 {a['level']} 级告警: {a}"

    def test_alert_value_and_threshold_included(self):
        """触发的告警应包含 value 和 threshold 字段。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "high_risk": 5, "requires_manual_review": 5},
            {},
        )
        for alert in alerts:
            if alert["code"] == "high_risk_ratio_too_high":
                assert "value" in alert
                assert "threshold" in alert
                assert alert["value"] == 0.5
                assert alert["threshold"] == 0.40
                return
        pytest.fail("high_risk_ratio_too_high 告警未触发")

    def test_alert_suggested_action_included(self):
        """告警应包含 suggested_action。"""
        alerts = evaluate_alerts(
            {"total_questions": 10, "high_risk": 5, "requires_manual_review": 5},
            {},
        )
        for alert in alerts:
            assert "suggested_action" in alert, f"{alert['code']} 缺少 suggested_action"
