"""Run the smart weakness-vector supplement with provider ownership."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

VectorMatch = tuple[Any, dict]
RecommendationResult = tuple[list[Any], dict[int, dict]]


@dataclass(slots=True)
class SmartWeaknessVectorRequest:
    db: Any
    user_id: int
    subject_code: str
    count: int
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    exclude_ids: set[int] | None
    subject_ids: list[int] | None
    logger: Logger
    resolve_scope_ids: Callable[[Any, int, str], Awaitable[list[int]]]
    load_mastery: Callable[..., Awaitable[list[dict]]]
    compute_weak_kps: Callable[[Any, int, list[int]], Awaitable[list[dict]]]
    load_random: Callable[..., Awaitable[list[Any]]]
    load_vector_recalls: Callable[..., Awaitable[list[dict]]]
    load_vector_matches: Callable[
        [list[dict], list[int], set[int]], Awaitable[list[VectorMatch]]
    ]
    load_fill_questions: Callable[[int, list[int], set[int]], Awaitable[list[Any]]]


async def run_smart_weakness_vector(
    request: SmartWeaknessVectorRequest,
) -> RecommendationResult:
    """Select weak-KP vector candidates, then fill any remaining deficit."""
    exclude_ids = request.exclude_ids or set()
    metadata: dict[int, dict] = {}
    scope_ids = (
        request.subject_ids
        if request.subject_ids is not None
        else await request.resolve_scope_ids(
            request.db, request.user_id, request.subject_code
        )
    )

    weak_kps = await _load_weak_kps(request, scope_ids)
    if not weak_kps:
        return await _random_fallback(request, scope_ids, exclude_ids, metadata)

    kp_names = [kp["name"] for kp in weak_kps[:5]]
    result_questions: list[Any] = []
    try:
        recalls = await request.load_vector_recalls(
            db=request.db,
            user_id=request.user_id,
            subject=request.subject_code,
            query_text=build_weakness_query(request.subject_code, kp_names),
            count=request.count,
            exclude_answered=request.exclude_answered,
            no_repeat_days=request.no_repeat_days,
        )
        matches = await request.load_vector_matches(recalls, scope_ids, exclude_ids)
        result_questions, metadata = build_vector_metadata(matches, kp_names)
    except Exception:
        request.logger.warning("weakness_vector 向量召回失败", exc_info=True)

    if len(result_questions) >= request.count:
        return result_questions[: request.count], metadata

    existing_ids = {question.id for question in result_questions} | exclude_ids
    fill_questions = await request.load_fill_questions(
        request.count - len(result_questions), scope_ids, existing_ids
    )
    for question in fill_questions:
        metadata[question.id] = build_fallback_metadata()
    result_questions.extend(fill_questions)
    return result_questions[: request.count], metadata


def build_weakness_query(subject_code: str, kp_names: list[str]) -> str:
    return (
        f"科目：{subject_code}。请推荐这些薄弱知识点的练习题："
        f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
    )


def build_vector_metadata(
    matches: list[VectorMatch], kp_names: list[str]
) -> tuple[list[Any], dict[int, dict]]:
    questions: list[Any] = []
    metadata: dict[int, dict] = {}
    for question, recall in matches:
        questions.append(question)
        metadata[question.id] = {
            "recommend_reason": f"薄弱知识点推荐：{'、'.join(kp_names[:3])}",
            "recommend_score": recall.get("recommend_score"),
            "strategy": "smart_vector",
            "similarity": recall.get("similarity"),
        }
    return questions, metadata


def build_fallback_metadata() -> dict:
    return {
        "recommend_reason": "薄弱知识点补齐",
        "recommend_score": None,
        "strategy": "kp_fallback",
        "similarity": None,
    }


async def _load_weak_kps(
    request: SmartWeaknessVectorRequest, scope_ids: list[int]
) -> list[dict]:
    try:
        return await request.load_mastery(
            request.db,
            request.user_id,
            request.subject_code,
            limit=5,
        )
    except Exception:
        request.logger.warning(
            "mastery_service.get_user_weak_knowledge_points failed", exc_info=True
        )
    return await request.compute_weak_kps(request.db, request.user_id, scope_ids)


async def _random_fallback(
    request: SmartWeaknessVectorRequest,
    scope_ids: list[int],
    exclude_ids: set[int],
    metadata: dict[int, dict],
) -> RecommendationResult:
    # Over-fetch by the hard-exclusion count so filtering does not shrink a
    # supplement batch that is already filling a scored/path deficit.
    questions = await request.load_random(
        db=request.db,
        user_id=request.user_id,
        subject_code=request.subject_code,
        count=request.count + len(exclude_ids),
        mode="random",
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
        use_leitner=request.use_leitner,
        subject_ids=scope_ids,
    )
    for question in questions:
        if question.id not in exclude_ids:
            metadata[question.id] = {
                "recommend_reason": "随机推荐（薄弱知识点数据不足）",
                "recommend_score": None,
                "strategy": "random_fallback",
                "similarity": None,
            }
    return [q for q in questions if q.id not in exclude_ids][: request.count], metadata
