"""统计推荐与自适应摘要纯函数兼容基线。

覆盖 stats_service 中可脱离数据库独立测试的推荐和摘要规则：
- _subject_items_with_label：科目统计项投影
- _build_recommendation：智能建议优先级决策
- _adaptive_summary：自适应复习摘要文案
"""

from __future__ import annotations

from app.services.stats_service import (
    _adaptive_summary,
    _build_recommendation,
    _subject_items_with_label,
)


class TestSubjectItemsWithLabel:
    """_subject_items_with_label 将原始科目统计投影为带 label 的展示项。"""

    def test_empty_list(self) -> None:
        assert _subject_items_with_label([]) == []

    def test_basic_projection(self) -> None:
        raw = [
            {
                "subject_id": 1,
                "subject_code": "data_structure",
                "subject_name": "数据结构",
                "total_questions": 100,
                "correct_count": 80,
                "wrong_count": 20,
                "accuracy": 0.8,
                "total_duration_sec": 3600,
            }
        ]
        items = _subject_items_with_label(raw)
        assert len(items) == 1
        item = items[0]
        assert item["subject_id"] == 1
        assert item["subject_code"] == "data_structure"
        assert item["subject_name"] == "数据结构"
        assert item["label"] == "数据结构"
        assert item["total_questions"] == 100
        assert item["correct_count"] == 80
        assert item["wrong_count"] == 20
        assert item["accuracy"] == 0.8
        assert item["total_duration_sec"] == 3600

    def test_missing_fields_use_defaults(self) -> None:
        items = _subject_items_with_label([{"subject_id": 1}])
        item = items[0]
        assert item["subject_code"] == ""
        assert item["subject_name"] == ""
        assert item["label"] == ""
        assert item["total_questions"] == 0
        assert item["correct_count"] == 0
        assert item["wrong_count"] == 0
        assert item["accuracy"] == 0.0
        assert item["total_duration_sec"] == 0

    def test_multiple_items(self) -> None:
        raw = [
            {"subject_id": 1, "subject_name": "数学"},
            {"subject_id": 2, "subject_name": "英语"},
        ]
        items = _subject_items_with_label(raw)
        assert len(items) == 2
        assert items[0]["label"] == "数学"
        assert items[1]["label"] == "英语"


class TestBuildRecommendation:
    """_build_recommendation 按优先级生成智能建议。"""

    def test_no_questions_practice_first(self) -> None:
        ov = {"total_questions": 0}
        result = _build_recommendation(ov, {}, None)
        assert result["priority"] == "practice"
        assert result["cta_type"] == "practice"
        assert "第一次" in result["title"]

    def test_due_review_takes_priority(self) -> None:
        ov = {"total_questions": 50, "due_review_count": 5}
        result = _build_recommendation(ov, {}, None)
        assert result["priority"] == "review"
        assert result["cta_type"] == "review"
        assert "5" in result["desc"]

    def test_high_forget_second_priority(self) -> None:
        ov = {"total_questions": 50, "due_review_count": 0}
        forgetting = {"high_forget_count": 3}
        result = _build_recommendation(ov, forgetting, None)
        assert result["priority"] == "wrong"
        assert result["cta_type"] == "wrong"
        assert "3" in result["desc"]

    def test_weak_subject_third_priority(self) -> None:
        ov = {"total_questions": 50, "due_review_count": 0}
        weak = {
            "label": "数据结构",
            "accuracy": 0.3,
            "total_questions": 10,
        }
        result = _build_recommendation(ov, {}, weak)
        assert result["priority"] == "subject"
        assert result["cta_type"] == "subject"
        assert "数据结构" in result["desc"]

    def test_weak_subject_skipped_when_accuracy_ok(self) -> None:
        ov = {"total_questions": 50, "due_review_count": 0}
        weak = {
            "label": "数据结构",
            "accuracy": 0.6,
            "total_questions": 10,
        }
        result = _build_recommendation(ov, {}, weak)
        assert result["priority"] != "subject"

    def test_weak_subject_skipped_when_few_questions(self) -> None:
        ov = {"total_questions": 50, "due_review_count": 0}
        weak = {
            "label": "数据结构",
            "accuracy": 0.3,
            "total_questions": 2,
        }
        result = _build_recommendation(ov, {}, weak)
        assert result["priority"] != "subject"

    def test_streak_keep_priority(self) -> None:
        ov = {
            "total_questions": 50,
            "due_review_count": 0,
            "consecutive_days": 5,
            "today_questions": 10,
        }
        result = _build_recommendation(ov, {}, None)
        assert result["priority"] == "keep"
        assert result["cta_type"] == "practice"

    def test_default_practice(self) -> None:
        ov = {"total_questions": 50, "due_review_count": 0, "consecutive_days": 1}
        result = _build_recommendation(ov, {}, None)
        assert result["priority"] == "practice"
        assert "保持" in result["title"]


class TestAdaptiveSummary:
    """_adaptive_summary 根据遗忘状态返回摘要文案。"""

    def test_fast_forgetting(self) -> None:
        result = _adaptive_summary("fast_forgetting", 0.3, 0.85)
        assert "缩短" in result

    def test_slightly_fast_forgetting(self) -> None:
        result = _adaptive_summary("slightly_fast_forgetting", 0.5, 0.85)
        assert "缩短" in result

    def test_stable_memory(self) -> None:
        result = _adaptive_summary("stable_memory", 0.9, 0.85)
        assert "良好" in result

    def test_unknown_status(self) -> None:
        result = _adaptive_summary("unknown", 0.85, 0.85)
        assert "保持" in result

    def test_empty_status(self) -> None:
        result = _adaptive_summary("", 0.85, 0.85)
        assert "保持" in result
