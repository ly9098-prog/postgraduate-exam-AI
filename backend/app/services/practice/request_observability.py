"""Observe issued practice batches without owning selection or transactions."""

from __future__ import annotations

import logging
from collections import Counter

from app.models.question import Question
from app.services.practice.request_assembly import PreparedPracticeRequest
from app.utils.trace.debug import debug_log, save_debug_snapshot

# Preserve the existing log category for deployed filters and dashboards.
logger = logging.getLogger("app.api.v1.practice")


def log_practice_scope(
    prepared: PreparedPracticeRequest,
    *,
    include_children: bool,
    mode: str,
    questions: list[Question],
) -> None:
    request = prepared.candidate
    logger.info(
        "[PRACTICE_SCOPE] subject_id=%s subject_code=%s include_children=%s "
        "include_descendants=%s knowledge_scope_size=%d has_children=%s "
        "scope=%s scope_ids=%s mode=%s count=%d result_count=%d subject_distribution=%s",
        request.subject_id,
        request.subject_code,
        include_children,
        request.include_descendants,
        len(request.knowledge_point_ids or []),
        prepared.subject_scope.has_enabled_children,
        "聚合" if len(request.subject_ids) > 1 else "精确",
        request.subject_ids,
        mode,
        request.count,
        len(questions),
        dict(Counter(q.subject_id for q in questions)),
    )


def log_practice_response(
    trace_id: str, subject_id: int, questions: list[Question],
) -> None:
    debug_log(
        trace_id,
        "API_RESPONSE",
        {
            "endpoint": "practice/questions",
            "subject_id": subject_id,
            "count": len(questions),
        },
    )
    save_debug_snapshot(
        trace_id,
        "api_response",
        {
            "endpoint": "practice/questions",
            "subject_id": subject_id,
            "question_ids": [q.id for q in questions],
            "total": len(questions),
        },
    )
