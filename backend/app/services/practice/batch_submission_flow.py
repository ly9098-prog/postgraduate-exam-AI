"""Orchestration for atomic signed practice-batch submissions."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.practice_session import PracticeSession
from app.services.practice.batch_claim import (
    claim_practice_request_id,
    load_committed_replay,
)
from app.services.practice.batch_commit import persist_claimed_practice_batch
from app.services.practice.batch_persistence import persist_practice_batch_records
from app.services.practice.batch_reservation_cleanup import (
    build_sequential_reservation_cleanup,
)
from app.services.practice.batch_response import build_batch_submission_response
from app.services.practice.batch_submission import (
    build_response_by_question,
    build_session_consistency_error,
    evaluate_batch_answers,
    validate_answer_duration,
    validate_batch_submission_inputs,
)
from app.services.practice.batch_token import (
    PRACTICE_ANSWER_DURATION_TOLERANCE_SEC,
    PRACTICE_BATCH_MAX_QUESTIONS,
    PracticeBatchTokenError,
    _validate_practice_batch_token,
)
from app.services.practice.batch_wrong_book import (
    enqueue_wrong_answer_prewarm,
    persist_wrong_answer,
)
from app.services.practice.merge_utils import practice_submission_fingerprint
from app.services.practice.normalization import (
    normalize_practice_request_id,
    normalize_practice_session,
)
from app.services.practice.session_scope import build_practice_session_scope

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchSubmissionFlowRequest:
    db: AsyncSession
    user_id: int
    answers: list[dict]
    session_meta: dict
    skipped_question_ids: list[int]
    batch_token: str
    logger: logging.Logger
    replay: Callable[[Any, str], dict]
    start_transaction: Callable[[AsyncSession], Awaitable[None]]
    is_unique_violation: Callable[[Exception], bool]
    create_outbox: Callable[..., Awaitable[None]]


@dataclass(slots=True)
class BatchProtocol:
    skipped_ids: list[int]
    all_question_ids: list[int]
    payload_hash: str
    request_id: str


@dataclass(slots=True)
class BatchContract:
    issued_revisions: dict[int, int]
    issued_order: list[int]
    batch_payload: dict
    questions: dict[int, Any]


@dataclass(slots=True)
class PreparedBatchSubmission:
    evaluated_answers: list[tuple[Any, bool, str, int | None]]
    answer_request_ids: dict[int, str | None]
    skipped_questions: list[Any]
    all_question_ids: list[int]
    issued_revisions: dict[int, int]
    issued_order: list[int]
    batch_payload: dict
    session_values: dict
    scope_snapshot: dict | None
    payload_hash: str


async def submit_practice_batch(request: BatchSubmissionFlowRequest) -> dict:
    protocol = _validate_protocol(request)
    replay = await _load_committed_replay(request, protocol)
    if replay is not None:
        return replay
    contract = await _load_batch_contract(request, protocol)
    prepared = _prepare_batch_submission(request, protocol, contract)
    return await _claim_and_commit(request, prepared)


def _validate_protocol(request: BatchSubmissionFlowRequest) -> BatchProtocol:
    if not request.batch_token:
        raise PracticeBatchTokenError("batch_token 不能为空，请重新获取题目")
    if not request.session_meta:
        raise PracticeBatchTokenError("session 不能为空，请重新获取题目")
    if request.skipped_question_ids is None:
        raise PracticeBatchTokenError("skipped_question_ids 必须显式提交")
    if len(request.answers) > PRACTICE_BATCH_MAX_QUESTIONS:
        raise ValueError(f"answers 最多允许 {PRACTICE_BATCH_MAX_QUESTIONS} 题")
    if len(request.skipped_question_ids) > PRACTICE_BATCH_MAX_QUESTIONS:
        raise ValueError(
            f"skipped_question_ids 最多允许 {PRACTICE_BATCH_MAX_QUESTIONS} 题"
        )
    _answer_ids, skipped_ids, all_ids = validate_batch_submission_inputs(
        answers=request.answers,
        skipped_question_ids=request.skipped_question_ids,
        max_questions=PRACTICE_BATCH_MAX_QUESTIONS,
    )
    payload_hash = practice_submission_fingerprint(
        answers=request.answers,
        skipped_question_ids=skipped_ids,
        session_meta=request.session_meta,
        batch_token=request.batch_token,
    )
    request_id = normalize_practice_request_id(request.session_meta.get("request_id"))
    if not request_id:
        raise ValueError("session.request_id 不能为空")
    return BatchProtocol(skipped_ids, all_ids, payload_hash, request_id)


async def _load_committed_replay(
    request: BatchSubmissionFlowRequest, protocol: BatchProtocol
) -> dict | None:
    return await load_committed_replay(
        request.db,
        user_id=request.user_id,
        request_id=protocol.request_id,
        payload_hash=protocol.payload_hash,
        replay=request.replay,
    )


async def _load_batch_contract(
    request: BatchSubmissionFlowRequest, protocol: BatchProtocol
) -> BatchContract:
    issued_revisions, issued_order, batch_payload = _validate_practice_batch_token(
        request.batch_token,
        user_id=request.user_id,
        question_ids=protocol.all_question_ids,
        session_meta=request.session_meta,
        answers=request.answers,
    )
    from app.services.question_revision_service import load_revision_views

    revision_views = await load_revision_views(request.db, issued_revisions.values())
    if len(revision_views) != len(issued_revisions):
        raise PracticeBatchTokenError("练习批次引用的题目 revision 不完整")
    return BatchContract(
        issued_revisions=issued_revisions,
        issued_order=issued_order,
        batch_payload=batch_payload,
        questions=_validated_revision_questions(issued_revisions, revision_views),
    )


def _validated_revision_questions(
    issued_revisions: dict[int, int], revision_views: dict[int, Any]
) -> dict[int, Any]:
    questions: dict[int, Any] = {}
    for question_id, revision_id in issued_revisions.items():
        view = revision_views.get(int(revision_id))
        if view is None or int(view.question_id) != int(question_id):
            raise PracticeBatchTokenError("练习批次题目与 revision 绑定关系无效")
        if not view.is_active:
            # A valid issued batch can only originate from active revisions; this
            # catches corrupted/manual token state, not later editorial changes.
            raise PracticeBatchTokenError("练习批次包含不可用题目 revision")
        questions[int(question_id)] = view
    return questions


def _prepare_batch_submission(
    request: BatchSubmissionFlowRequest,
    protocol: BatchProtocol,
    contract: BatchContract,
) -> PreparedBatchSubmission:
    evaluated_answers, answer_request_ids, correct, wrong = evaluate_batch_answers(
        answers=request.answers, questions=contract.questions
    )
    skipped_questions = [contract.questions[qid] for qid in protocol.skipped_ids]
    session_values = normalize_practice_session(
        request.session_meta,
        user_id=request.user_id,
        answered_count=len(evaluated_answers),
        total_correct=correct,
        total_wrong=wrong,
    )
    _validate_session_contract(
        request=request,
        protocol=protocol,
        contract=contract,
        session_values=session_values,
        evaluated_answers=evaluated_answers,
    )
    scope_snapshot = build_practice_session_scope(
        contract.batch_payload.get("knowledge_context"),
        fallback_subject_id=int(session_values.get("subject_id") or 0),
    )
    _validate_scope_subject(scope_snapshot, session_values)
    return PreparedBatchSubmission(
        evaluated_answers=evaluated_answers,
        answer_request_ids=answer_request_ids,
        skipped_questions=skipped_questions,
        all_question_ids=protocol.all_question_ids,
        issued_revisions=contract.issued_revisions,
        issued_order=contract.issued_order,
        batch_payload=contract.batch_payload,
        session_values=session_values,
        scope_snapshot=scope_snapshot,
        payload_hash=protocol.payload_hash,
    )


def _validate_session_contract(
    *,
    request: BatchSubmissionFlowRequest,
    protocol: BatchProtocol,
    contract: BatchContract,
    session_values: dict,
    evaluated_answers: list[tuple[Any, bool, str, int | None]],
) -> None:
    consistency_error = build_session_consistency_error(
        session_values=session_values,
        request_id=protocol.request_id,
        total_question_count=len(protocol.all_question_ids),
        batch_payload=contract.batch_payload,
    )
    if consistency_error:
        if "request_id" in consistency_error or "question_count" in consistency_error:
            raise ValueError(consistency_error)
        raise PracticeBatchTokenError(consistency_error)
    duration_error = validate_answer_duration(
        evaluated_answers=evaluated_answers,
        duration_sec=int(session_values.get("duration_sec") or 0),
        tolerance_sec=PRACTICE_ANSWER_DURATION_TOLERANCE_SEC,
    )
    if duration_error:
        raise ValueError(duration_error)


def _validate_scope_subject(scope_snapshot: dict | None, session_values: dict) -> None:
    if scope_snapshot is None:
        return
    signed_subject_id = int(scope_snapshot.get("subject_id") or 0)
    if signed_subject_id and signed_subject_id != int(
        session_values.get("subject_id") or 0
    ):
        raise PracticeBatchTokenError("知识练习范围与练习科目不一致")


def _build_practice_session(
    prepared: PreparedBatchSubmission,
) -> PracticeSession:
    scope = prepared.scope_snapshot
    return PracticeSession(
        **prepared.session_values,
        submission_payload_hash=prepared.payload_hash,
        scope_type=str(scope["practice_mode"]) if scope is not None else None,
        scope_root_knowledge_point_id=(
            int(scope["root_knowledge_point_id"]) if scope is not None else None
        ),
        scope_snapshot=scope,
    )


async def _claim_and_commit(
    request: BatchSubmissionFlowRequest, prepared: PreparedBatchSubmission
) -> dict:
    claim = await claim_practice_request_id(
        request.db,
        user_id=request.user_id,
        session_obj=_build_practice_session(prepared),
        request_id=prepared.session_values["request_id"],
        payload_hash=prepared.payload_hash,
        start_transaction=request.start_transaction,
        is_unique_violation=request.is_unique_violation,
        replay=request.replay,
    )
    if not claim.claimed:
        return claim.replay
    committed = await _persist_claimed_batch(request, prepared, claim.session)
    await _enqueue_prewarm_safely(request, committed.prewarm_wrong_questions)
    return committed.response_payload


async def _persist_claimed_batch(
    request: BatchSubmissionFlowRequest,
    prepared: PreparedBatchSubmission,
    session_obj: PracticeSession,
):
    from app.services.question_revision_service import load_revision_kp_names
    from app.services.wrong_question_service import record_wrong

    from app.services.practice.knowledge_session_summary import (
        persisted_knowledge_session,
    )

    now = utcnow()
    return await persist_claimed_practice_batch(
        request.db,
        session_obj=session_obj,
        persist_records=persist_practice_batch_records,
        load_revision_kp_names=load_revision_kp_names,
        build_response_by_question=build_response_by_question,
        build_response=build_batch_submission_response,
        persisted_knowledge_session=persisted_knowledge_session,
        build_cleanup=build_sequential_reservation_cleanup,
        execute=request.db.execute,
        commit=request.db.commit,
        rollback=request.db.rollback,
        user_id=request.user_id,
        batch_payload=prepared.batch_payload,
        all_question_ids=prepared.all_question_ids,
        issued_revisions=prepared.issued_revisions,
        issued_order=prepared.issued_order,
        skipped_questions=prepared.skipped_questions,
        total_correct=prepared.session_values["correct_count"],
        total_wrong=prepared.session_values["wrong_count"],
        knowledge_context=prepared.batch_payload.get("knowledge_context"),
        entry_context=prepared.batch_payload.get("entry_context"),
        persist_records_kwargs={
            "user_id": request.user_id,
            "evaluated_answers": prepared.evaluated_answers,
            "answer_request_ids": prepared.answer_request_ids,
            "mode": prepared.session_values["mode"],
            "now": now,
            "record_wrong": record_wrong,
            "create_outbox": request.create_outbox,
            "persist_wrong_answer": persist_wrong_answer,
        },
    )


async def _enqueue_prewarm_safely(
    request: BatchSubmissionFlowRequest, wrong_questions: list[Any]
) -> None:
    if not wrong_questions:
        return
    try:
        from app.ai.prewarm_revision import build_prewarm_revision
        from app.services.ai_prewarm_worker import enqueue_prewarm

        await enqueue_wrong_answer_prewarm(
            wrong_questions,
            request.user_id,
            build_revision=build_prewarm_revision,
            enqueue=enqueue_prewarm,
        )
    except Exception:
        request.logger.warning(
            "AI prewarm enqueue failed after practice batch", exc_info=True
        )
