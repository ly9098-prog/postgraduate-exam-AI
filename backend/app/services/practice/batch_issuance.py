"""Sign and serialize a guarded batch without committing its transaction."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.practice import PracticeQuestionsResponse
from app.services import practice_service as svc
from app.services.practice.candidate_selection import (
    PracticeCandidateRequest,
    PracticeCandidates,
)
from app.services.practice.final_candidates import FinalPracticeCandidates
from app.services.practice.issued_response import build_issued_response
from app.services.practice.knowledge_session_summary import (
    build_issue_knowledge_context,
)
from app.services.study_hub_plan_token import validate_plan_task_token

logger = logging.getLogger(__name__)


@dataclass
class PracticeIssueContext:
    trace_id: str
    knowledge_scope: dict | None
    knowledge_point_id: int | None
    plan_token: str | None
    question_ids: str | None


async def build_signed_practice_response(
    db: AsyncSession,
    request: PracticeCandidateRequest,
    candidates: PracticeCandidates,
    final: FinalPracticeCandidates,
    context: PracticeIssueContext,
) -> PracticeQuestionsResponse:
    knowledge_context = await build_issue_knowledge_context(
        db,
        user_id=request.user_id,
        knowledge_scope=context.knowledge_scope,
        questions=final.questions,
        revision_ids=final.revision_ids,
        practice_subject_id=request.subject_id,
    )
    entry_context = _plan_entry_context(request, candidates.mode, context)
    submission_id = _sequential_request_id(request, candidates, context)
    batch_token, issued_revisions, submission_request_id = (
        svc.create_practice_batch_token(
            user_id=request.user_id,
            subject_id=request.subject_id,
            mode=candidates.mode,
            questions=final.questions,
            revision_ids=final.revision_ids,
            recommendation_request_id=candidates.request_id,
            knowledge_context=knowledge_context,
            entry_context=entry_context,
            sequential_reservation_request_id=candidates.reservation_request_id,
            submission_request_id=submission_id,
        )
    )
    return await build_issued_response(
        db,
        questions=final.questions,
        issued_revisions=issued_revisions,
        question_metadata=final.metadata,
        trace_id=context.trace_id,
        mode=candidates.mode,
        request_id=candidates.request_id,
        sequential_progress=candidates.sequential_progress,
        knowledge_scope=context.knowledge_scope,
        batch_token=batch_token,
        submission_request_id=submission_request_id,
    )


def _plan_entry_context(
    request: PracticeCandidateRequest,
    mode: str,
    context: PracticeIssueContext,
) -> dict | None:
    if not context.plan_token:
        return None
    entry = validate_plan_task_token(
        context.plan_token,
        user_id=request.user_id,
        subject_id=request.subject_id,
        mode=mode,
        count=request.count,
        knowledge_point_id=context.knowledge_point_id,
        include_descendants=request.include_descendants,
        question_ids=context.question_ids,
    )
    if entry is None:
        logger.info(
            "[STUDY_HUB_PLAN_ATTRIBUTION_SKIPPED] user_id=%s subject_id=%s mode=%s",
            request.user_id,
            request.subject_id,
            mode,
        )
    return entry


def _sequential_request_id(
    request: PracticeCandidateRequest,
    candidates: PracticeCandidates,
    context: PracticeIssueContext,
) -> str | None:
    if not candidates.reservation_request_id:
        return None
    scope_identity = (
        {"knowledge_scope": context.knowledge_scope}
        if context.knowledge_scope is not None
        else {"knowledge_points": sorted(request.knowledge_points or [])}
    )
    return sequential_submission_request_id(
        candidates.reservation_request_id, request.subject_id, scope_identity
    )


def sequential_submission_request_id(
    start_request_id: str,
    subject_id: int,
    scope_identity: dict,
) -> str:
    """Derive a stable submission id without crossing practice scopes."""
    canonical_scope = json.dumps(
        scope_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(
        f"{start_request_id}:{subject_id}:{canonical_scope}".encode()
    ).hexdigest()[:48]
    return f"practice_{digest}"
