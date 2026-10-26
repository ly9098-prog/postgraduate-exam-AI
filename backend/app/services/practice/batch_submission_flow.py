"""Orchestration for atomic signed practice-batch submissions."""

from __future__ import annotations

import builtins as _builtins
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime  # noqa: F401 - historical module binding
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.practice_session import PracticeSession
from app.services.practice import batch_submission_preparation as _preparation
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
    build_session_consistency_error,  # noqa: F401 - resolved by _submission_port
    evaluate_batch_answers,  # noqa: F401 - resolved by _submission_port
    validate_answer_duration,  # noqa: F401 - resolved by _submission_port
    validate_batch_submission_inputs,  # noqa: F401 - resolved by _submission_port
)
from app.services.practice.batch_token import (
    PRACTICE_ANSWER_DURATION_TOLERANCE_SEC,  # noqa: F401 - resolved by _submission_port
    PRACTICE_BATCH_MAX_QUESTIONS,  # noqa: F401 - resolved by _submission_port
    PracticeBatchTokenError,
    _validate_practice_batch_token,
)
from app.services.practice.batch_wrong_book import (
    enqueue_wrong_answer_prewarm,
    persist_wrong_answer,
)
from app.services.practice.merge_utils import (
    practice_submission_fingerprint,  # noqa: F401 - resolved by _submission_port
)
from app.services.practice.normalization import (
    normalize_practice_request_id,  # noqa: F401 - resolved by _submission_port
    normalize_practice_session,  # noqa: F401 - resolved by _submission_port
)
from app.services.practice.session_scope import (
    build_practice_session_scope,  # noqa: F401 - resolved by _submission_port
)

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


def _submission_port(name: str) -> Any:
    """Keep validation lookups at their original module and execution time."""
    namespace = globals()
    if name in namespace:
        return namespace[name]
    builtin_namespace = vars(_builtins)
    if name in builtin_namespace:
        return builtin_namespace[name]
    raise NameError(f"name '{name}' is not defined", name=name)


def _validate_protocol(request: BatchSubmissionFlowRequest) -> BatchProtocol:
    return _preparation.validate_protocol(request, ports=_submission_port)


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
    return _preparation.validated_revision_questions(
        issued_revisions, revision_views, ports=_submission_port
    )


def _prepare_batch_submission(
    request: BatchSubmissionFlowRequest,
    protocol: BatchProtocol,
    contract: BatchContract,
) -> PreparedBatchSubmission:
    return _preparation.prepare_batch_submission(
        request, protocol, contract, ports=_submission_port
    )


def _validate_session_contract(
    *,
    request: BatchSubmissionFlowRequest,
    protocol: BatchProtocol,
    contract: BatchContract,
    session_values: dict,
    evaluated_answers: list[tuple[Any, bool, str, int | None]],
) -> None:
    return _preparation.validate_session_contract(
        request=request,
        protocol=protocol,
        contract=contract,
        session_values=session_values,
        evaluated_answers=evaluated_answers,
        ports=_submission_port,
    )


def _validate_scope_subject(scope_snapshot: dict | None, session_values: dict) -> None:
    return _preparation.validate_scope_subject(
        scope_snapshot, session_values, ports=_submission_port
    )


def _build_practice_session(
    prepared: PreparedBatchSubmission,
) -> PracticeSession:
    return _preparation.build_practice_session(prepared, ports=_submission_port)


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
    from app.services.question_revision_service import load_revision_kp_names  # noqa: I001
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
