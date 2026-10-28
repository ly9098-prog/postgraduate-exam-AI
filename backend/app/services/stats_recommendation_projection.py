"""Pure recommendation and subject-item projections for learning dashboards."""

from __future__ import annotations

from typing import Any


def build_subject_items_with_label(
    subjects_raw: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project subject statistics into dashboard items with a display label."""
    items = []
    for subject in subjects_raw:
        subject_name = subject.get("subject_name", "")
        items.append(
            {
                "subject_id": subject.get("subject_id"),
                "subject_code": subject.get("subject_code", ""),
                "subject_name": subject_name,
                "label": subject_name,
                "total_questions": subject.get("total_questions", 0),
                "correct_count": subject.get("correct_count", 0),
                "wrong_count": subject.get("wrong_count", 0),
                "accuracy": subject.get("accuracy", 0.0),
                "total_duration_sec": subject.get("total_duration_sec", 0),
            }
        )
    return items


def build_dashboard_recommendation(
    overview: dict[str, Any],
    forgetting: dict[str, Any],
    weak_subject: dict[str, Any] | None,
) -> dict[str, Any]:
    """Choose the highest-priority dashboard recommendation."""
    due = overview.get("due_review_count", 0)
    high_forget = forgetting.get("high_forget_count", 0)
    total_q = overview.get("total_questions", 0)

    if total_q == 0:
        return _first_practice_recommendation()

    if due > 0:
        return _due_review_recommendation(due)

    if high_forget > 0:
        return _forgetting_recommendation(high_forget)

    if (
        weak_subject
        and weak_subject["accuracy"] < 0.5
        and weak_subject["total_questions"] >= 3
    ):
        return _weak_subject_recommendation(weak_subject)

    today_q = overview.get("today_questions", 0)
    streak = overview.get("consecutive_days", 0)
    if streak >= 3 and today_q > 0:
        return _streak_recommendation(streak, today_q)

    return _default_practice_recommendation(total_q, streak)


def _first_practice_recommendation() -> dict[str, Any]:
    return {
        "priority": "practice",
        "title": "完成第一次练习",
        "desc": "练习、复习和错题数据会在这里汇总。先开始第一道题吧！",
        "tags": ["数据不足"],
        "cta_text": "开始练习",
        "cta_type": "practice",
    }


def _due_review_recommendation(due: int) -> dict[str, Any]:
    return {
        "priority": "review",
        "title": "优先复习到期题",
        "desc": f"建议先完成 {due} 道到期复习，再进行新题练习。",
        "tags": ["待复习", "优先处理"],
        "cta_text": "去复习",
        "cta_type": "review",
    }


def _forgetting_recommendation(high_forget: int) -> dict[str, Any]:
    return {
        "priority": "wrong",
        "title": "巩固高频遗忘题",
        "desc": f"有 {high_forget} 道高频遗忘题目，建议集中复盘。",
        "tags": ["高频遗忘", "需要复盘"],
        "cta_text": "查看错题",
        "cta_type": "wrong",
    }


def _weak_subject_recommendation(weak_subject: dict[str, Any]) -> dict[str, Any]:
    return {
        "priority": "subject",
        "title": "巩固薄弱学科",
        "desc": (
            f"{weak_subject['label']}正确率仅"
            f"{round(weak_subject['accuracy'] * 100)}%，建议优先复盘该学科错题。"
        ),
        "tags": ["薄弱学科", "需要补强"],
        "cta_text": "查看学科错题",
        "cta_type": "subject",
    }


def _streak_recommendation(streak: int, today_q: int) -> dict[str, Any]:
    return {
        "priority": "keep",
        "title": "节奏稳定，继续保持",
        "desc": f"已连续学习 {streak} 天，今日完成 {today_q} 题，保持节奏。",
        "tags": ["节奏稳定", "状态良好"],
        "cta_text": "继续练习",
        "cta_type": "practice",
    }


def _default_practice_recommendation(total_q: int, streak: int) -> dict[str, Any]:
    return {
        "priority": "practice",
        "title": "保持每日练习",
        "desc": f"累计 {total_q} 题，连续 {streak} 天。每天进步一点点。",
        "tags": ["保持节奏"],
        "cta_text": "开始练习",
        "cta_type": "practice",
    }


def build_adaptive_summary(status: str, recall_rate: float, target: float) -> str:
    """Project adaptive-learning status into the existing summary copy."""
    if status == "fast_forgetting":
        return "系统已自动缩短复习间隔，帮助巩固记忆"
    if status == "slightly_fast_forgetting":
        return "系统已略微缩短复习间隔"
    if status == "stable_memory":
        return "记忆保持良好，间隔适当拉长"
    return "复习节奏合理，继续保持"
