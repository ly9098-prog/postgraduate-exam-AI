"""Run the smart-practice knowledge-path branch with provider ownership."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy import and_, select, true
from sqlalchemy.orm import selectinload

from app.models.question import Question

RecommendationResult = tuple[list[Any], dict[int, dict]]


@dataclass(slots=True)
class SmartPathRequest:
    db: Any
    user_id: int
    subject_code: str
    count: int
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    scope_ids: list[int]
    skip_finalize: bool
    experiment_id: int | None
    variant_key: str | None
    request_id: str | None
    logger: Logger
    load_path: Callable[..., Awaitable[dict]]
    load_fallback: Callable[..., Awaitable[RecommendationResult]]
    merge_results: Callable[..., RecommendationResult]
    finalize: Callable[..., Awaitable[RecommendationResult]]
    build_conditions: Callable[..., list[Any]]


async def run_smart_path(request: SmartPathRequest) -> RecommendationResult | None:
    """Return a complete path result, or None so the caller can fall through."""
    try:
        path_result = await request.load_path(
            db=request.db,
            user_id=request.user_id,
            subject=request.subject_code,
            limit=8,
            questions_per_node=3,
            write_logs=False,
        )
        path_qids = path_result.get("recommended_question_ids", [])
        if not path_qids:
            return None

        candidate_ids = list(
            dict.fromkeys(int(qid) for qid in path_qids if qid is not None)
        )
        questions = await _load_path_questions(request, candidate_ids)
        if not questions:
            return None
        metadata = build_path_metadata(questions, path_result)

        if len(questions) >= request.count:
            return await _finalize(request, questions[: request.count], metadata)

        request.logger.info(
            "path 策略题量不足 (%d/%d)，fallback 到 weakness_vector",
            len(questions),
            request.count,
        )
        fallback, fallback_metadata = await request.load_fallback(
            request.db,
            request.user_id,
            request.subject_code,
            count=request.count - len(questions),
            exclude_answered=request.exclude_answered,
            no_repeat_days=request.no_repeat_days,
            use_leitner=request.use_leitner,
            exclude_ids={question.id for question in questions},
            subject_ids=request.scope_ids,
        )
        merged, merged_metadata = request.merge_results(
            questions,
            metadata,
            fallback,
            fallback_metadata,
            count=request.count,
        )
        return await _finalize(request, merged[: request.count], merged_metadata)
    except Exception:
        request.logger.warning(
            "knowledge_path 策略失败，fallback 到 weakness_vector", exc_info=True
        )
        return None


def build_path_metadata(questions: list[Any], path_result: dict) -> dict[int, dict]:
    node_map: dict[int, dict] = {}
    for node in path_result.get("nodes", []):
        for qid in node.get("recommended_question_ids", []):
            node_map[qid] = node

    metadata: dict[int, dict] = {}
    for question in questions:
        node = node_map.get(question.id, {})
        metadata[question.id] = {
            "recommend_reason": node.get(
                "reason", f"知识路径推荐：{node.get('name', '')}"
            ),
            "recommend_score": node.get("priority"),
            "strategy": "knowledge_path",
            "similarity": None,
        }
    return metadata


async def _finalize(
    request: SmartPathRequest,
    questions: list[Any],
    metadata: dict[int, dict],
) -> RecommendationResult:
    return await request.finalize(
        questions,
        metadata,
        request.skip_finalize,
        request.db,
        request.user_id,
        request.subject_code,
        request_id=request.request_id,
        experiment_id=request.experiment_id,
        variant_key=request.variant_key,
    )


async def _load_path_questions(
    request: SmartPathRequest, candidate_ids: list[int]
) -> list[Any]:
    conditions = request.build_conditions(
        candidate_ids=candidate_ids,
        scope_ids=request.scope_ids,
        user_id=request.user_id,
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
    )
    result = await request.db.execute(
        select(Question)
        .where(and_(true(), *conditions))
        .options(selectinload(Question.subject_ref))
    )
    by_id = {question.id: question for question in result.scalars().all()}
    return [by_id[qid] for qid in candidate_ids if qid in by_id][: request.count]
