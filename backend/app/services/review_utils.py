"""Pure review scheduling helpers: mastery mapping and error classification.

Extracted from review_scheduler.py to keep the main service focused on
DB orchestration and SM-2 scheduling logic.
"""

from __future__ import annotations

# SM-2 repetitions map onto visible mastery percentages.
_REVIEW_MASTERY_BY_REPETITIONS = {
    0: 20,
    1: 45,
    2: 65,
    3: 80,
    4: 90,
}
_REVIEW_AUTO_MASTER_REPETITIONS = 3


def review_mastery_percent(repetitions: int | None) -> int:
    """Map SM-2 repetitions to a visible mastery percentage (0-100)."""
    reps = max(0, int(repetitions or 0))
    if reps >= 5:
        return 100
    return _REVIEW_MASTERY_BY_REPETITIONS.get(reps, 20)


def review_auto_mastered(repetitions: int | None) -> bool:
    """Return True when repetitions reach the auto-mastery threshold."""
    return max(0, int(repetitions or 0)) >= _REVIEW_AUTO_MASTER_REPETITIONS


def review_item_error_meta(message: str) -> tuple[str, bool, bool]:
    """Classify deterministic per-item review rejections for clients.

    Returns (error_code, is_retryable, should_fetch_fresh_task).
    Network/5xx failures never arrive here: those abort the HTTP request.
    Every ValueError below describes a task snapshot that cannot be fixed by
    replaying the same schedule/version/occurrence tuple, so the client should
    fetch a fresh task instead of creating an endless local retry loop.
    """
    text = str(message or "")
    if "request_id 已用于不同提交" in text:
        return "REVIEW_REQUEST_CONFLICT", False, True
    if "复习记录不存在" in text:
        return "REVIEW_SCHEDULE_MISSING", False, True
    if "题目与复习记录不匹配" in text:
        return "REVIEW_TASK_MISMATCH", False, True
    if "版本" in text and ("更新" in text or "不存在" in text):
        return "REVIEW_VERSION_STALE", False, True
    if (
        "已从复习队列移除" in text
        or "已标记掌握" in text
        or "已经提交" in text
        or "已失效" in text
    ):
        return "REVIEW_TASK_STALE", False, True
    return "REVIEW_ITEM_REJECTED", False, True
