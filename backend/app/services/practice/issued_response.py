"""Build student responses from the exact immutable revisions in a signed batch."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.schemas.practice import (
    PracticeMode,
    PracticeQuestion,
    PracticeQuestionsResponse,
)
from app.services.practice.response_content import (
    ensure_true_false_options,
    sanitize_question_content,
    sanitize_question_options,
)
from app.services.question_revision_service import (
    load_revision_kp_names,
    load_revision_views,
)

logger = logging.getLogger(__name__)


class IncompletePracticeRevisionError(ValueError):
    """A signed revision is missing or belongs to a different question."""


async def build_issued_response(
    db: AsyncSession,
    *,
    questions: list[Question],
    issued_revisions: dict[int, int],
    question_metadata: dict[int, dict],
    trace_id: str,
    mode: PracticeMode,
    request_id: str | None,
    sequential_progress: dict | None,
    knowledge_scope: dict | None,
    batch_token: str,
    submission_request_id: str,
) -> PracticeQuestionsResponse:
    rows, revision_kps = await _load_issued_rows(db, questions, issued_revisions)
    return PracticeQuestionsResponse(
        questions=[
            _practice_question(
                selected, revision, revision_kps, question_metadata, trace_id
            )
            for selected, revision in rows
        ],
        total=len(questions),
        mode=mode,
        trace_id=trace_id,
        request_id=request_id,
        sequential_progress=sequential_progress,
        knowledge_scope=_public_knowledge_scope(knowledge_scope),
        batch_token=batch_token,
        submission_request_id=submission_request_id,
    )


async def _load_issued_rows(
    db: AsyncSession,
    questions: list[Question],
    issued_revisions: dict[int, int],
) -> tuple[list[tuple[Question, Any]], dict[int, list]]:
    revision_views = await load_revision_views(db, issued_revisions.values())
    revision_kps = await load_revision_kp_names(db, issued_revisions.values())
    issued_rows = []
    for selected in questions:
        revision_id = issued_revisions.get(int(selected.id))
        revision = revision_views.get(int(revision_id or 0))
        if revision is None or int(revision.question_id) != int(selected.id):
            raise IncompletePracticeRevisionError("题目版本数据不完整，请稍后重试")
        issued_rows.append((selected, revision))
        content = sanitize_question_content(revision.content)
        stem = (content or {}).get("text") or (content or {}).get("stem") or ""
        logger.info(
            "[API_LAYER] qid=%s revision_id=%s textLen=%d textHash=%s stemKeys=%s",
            selected.id,
            revision_id,
            len(stem),
            hashlib.sha256(stem.encode()).hexdigest()[:8],
            [key for key in (content or {}) if key in ("text", "stem", "segments")],
        )
    return issued_rows, revision_kps


def _practice_question(
    selected: Question,
    revision: Any,
    revision_kps: dict[int, list],
    question_metadata: dict[int, dict],
    trace_id: str,
) -> PracticeQuestion:
    metadata = question_metadata.get(selected.id) or {}
    return PracticeQuestion(
        id=revision.question_id,
        question_version_id=revision.question_version_id,
        question_version=revision.version,
        subject_id=revision.subject_id,
        subject_code=revision.subject_ref.code if revision.subject_ref else "",
        subject_name=revision.subject_ref.name if revision.subject_ref else "",
        question_type=revision.question_type,
        content=sanitize_question_content(revision.content),
        options=sanitize_question_options(
            ensure_true_false_options(revision.question_type, revision.options)
        ),
        knowledge_points=revision_kps.get(revision.question_version_id, []),
        difficulty=revision.difficulty,
        image_url=revision.image_url,
        trace_id=trace_id,
        recommend_reason=metadata.get("recommend_reason"),
        recommend_score=metadata.get("recommend_score"),
        strategy=metadata.get("strategy"),
        similarity=metadata.get("similarity"),
    )


def _public_knowledge_scope(scope: dict | None) -> dict | None:
    if scope is None:
        return None
    return {
        "root_knowledge_point_id": int(scope["root_id"]),
        "root_name": str(scope["root_name"]),
        "include_descendants": bool(scope["include_descendants"]),
        "knowledge_point_count": len(scope["knowledge_point_ids"]),
    }
