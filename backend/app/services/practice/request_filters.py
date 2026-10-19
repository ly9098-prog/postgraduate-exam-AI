"""Pure validation and parsing for practice-question request filters."""

from __future__ import annotations


class PracticeRequestFilterError(ValueError):
    """A practice filter cannot be represented by the current API contract."""


def validate_knowledge_point_filters(
    *,
    knowledge_point: str | None,
    knowledge_point_id: int | None,
    include_descendants: bool,
    mode: str,
) -> None:
    """Validate mutually exclusive knowledge-point request options."""
    if knowledge_point and knowledge_point_id is not None:
        raise PracticeRequestFilterError(
            "knowledge_point 与 knowledge_point_id 不能同时使用"
        )
    if include_descendants and knowledge_point_id is None:
        raise PracticeRequestFilterError("include_descendants 需要 knowledge_point_id")
    if include_descendants and mode != "random":
        raise PracticeRequestFilterError("章节专项练习当前仅支持 random 模式")


def parse_knowledge_point_names(value: str | None) -> list[str] | None:
    """Normalize the legacy comma-separated knowledge-point filter."""
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_targeted_question_ids(
    value: str | None,
    *,
    source_question_id: int | None,
    knowledge_points: list[str] | None,
    knowledge_point_ids: list[int] | None,
    mode: str,
) -> list[int]:
    """Parse and validate an explicit question-id retry set."""
    if not value:
        return []
    try:
        raw_ids = [part.strip() for part in str(value).split(",") if part.strip()]
        question_ids = [int(part) for part in raw_ids]
    except (TypeError, ValueError) as exc:
        raise PracticeRequestFilterError("question_ids 格式无效") from exc
    if not question_ids or len(question_ids) > 50:
        raise PracticeRequestFilterError("question_ids 数量必须为 1-50")
    if any(question_id <= 0 for question_id in question_ids):
        raise PracticeRequestFilterError("question_ids 必须为正整数")
    if len(set(question_ids)) != len(question_ids):
        raise PracticeRequestFilterError("question_ids 不允许重复")
    if source_question_id or knowledge_points or knowledge_point_ids:
        raise PracticeRequestFilterError(
            "定向题目不可与 source_question_id/knowledge_point 混用"
        )
    if mode != "random":
        raise PracticeRequestFilterError("定向题目仅支持 random runner")
    return question_ids
