"""Prepare typed practice inputs in the established validation order."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.log_context import get_log_context, normalize_trace_id
from app.services.practice.batch_issuance import PracticeIssueContext
from app.services.practice.candidate_selection import PracticeCandidateRequest
from app.services.practice.request_filters import (
    parse_targeted_question_ids,
    validate_knowledge_point_filters,
)
from app.services.practice.request_scope import (
    PracticeKnowledgeFilter,
    PracticeSubjectScope,
    resolve_knowledge_filter,
    resolve_subject_scope,
)


@dataclass
class PracticeQuestionsRequest:
    user_id: int
    subject_id: int
    include_children: bool
    count: int
    mode: str
    knowledge_point: str | None
    knowledge_point_id: int | None
    include_descendants: bool
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    source_question_id: int | None
    question_ids: str | None
    start_request_id: str | None
    smart_strategy: str
    plan_token: str | None
    trace_header: str | None


@dataclass
class PreparedPracticeRequest:
    candidate: PracticeCandidateRequest
    subject_scope: PracticeSubjectScope
    issue_context: PracticeIssueContext


async def prepare_practice_request(
    db: AsyncSession,
    request: PracticeQuestionsRequest,
) -> PreparedPracticeRequest:
    subject_scope = await resolve_subject_scope(
        db, subject_id=request.subject_id,
        include_children=request.include_children, mode=request.mode,
    )
    trace_id = str(
        get_log_context().get("trace_id") or normalize_trace_id(request.trace_header)
    )
    validate_knowledge_point_filters(
        knowledge_point=request.knowledge_point,
        knowledge_point_id=request.knowledge_point_id,
        include_descendants=request.include_descendants,
        mode=request.mode,
    )
    knowledge_filter = await resolve_knowledge_filter(
        db,
        knowledge_point=request.knowledge_point,
        knowledge_point_id=request.knowledge_point_id,
        subject_ids=subject_scope.subject_ids,
        include_descendants=request.include_descendants,
    )
    targeted_ids = parse_targeted_question_ids(
        request.question_ids,
        source_question_id=request.source_question_id,
        knowledge_points=knowledge_filter.names,
        knowledge_point_ids=knowledge_filter.point_ids,
        mode=request.mode,
    )
    return PreparedPracticeRequest(
        candidate=_candidate_request(request, subject_scope, knowledge_filter, targeted_ids),
        subject_scope=subject_scope,
        issue_context=PracticeIssueContext(
            trace_id=trace_id,
            knowledge_scope=knowledge_filter.scope,
            knowledge_point_id=request.knowledge_point_id,
            plan_token=request.plan_token,
            question_ids=request.question_ids,
        ),
    )


def _candidate_request(
    request: PracticeQuestionsRequest,
    scope: PracticeSubjectScope,
    knowledge_filter: PracticeKnowledgeFilter,
    targeted_ids: list[int],
) -> PracticeCandidateRequest:
    return PracticeCandidateRequest(
        user_id=request.user_id,
        subject_id=request.subject_id,
        subject_code=scope.code,
        subject_ids=scope.subject_ids,
        count=len(targeted_ids) if targeted_ids else request.count,
        mode=request.mode,
        knowledge_points=knowledge_filter.names,
        knowledge_point_ids=knowledge_filter.point_ids,
        include_descendants=request.include_descendants,
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
        use_leitner=request.use_leitner,
        source_question_id=request.source_question_id,
        targeted_question_ids=targeted_ids,
        start_request_id=request.start_request_id,
        smart_strategy=request.smart_strategy,
    )
