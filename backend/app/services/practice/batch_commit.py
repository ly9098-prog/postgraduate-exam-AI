"""Transactional persistence orchestration for a claimed practice batch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class _ClaimedPracticeBatchRequest:
    db: AsyncSession
    session_obj: Any
    persist_records: Callable[..., Awaitable[Any]]
    load_revision_kp_names: Callable[..., Awaitable[Any]]
    build_response_by_question: Callable[..., Awaitable[dict]]
    build_response: Callable[..., dict]
    persisted_knowledge_session: Callable[..., Any]
    build_cleanup: Callable[..., Any]
    execute: Callable[..., Awaitable[Any]]
    commit: Callable[..., Awaitable[None]]
    rollback: Callable[..., Awaitable[None]]
    persist_records_kwargs: dict
    issued_revisions: dict
    issued_order: list[int]
    skipped_questions: list[Any]
    total_correct: int
    total_wrong: int
    knowledge_context: Any
    entry_context: Any
    user_id: int
    batch_payload: dict
    all_question_ids: list[int]


async def _build_claimed_practice_response(
    db: AsyncSession,
    *,
    persisted: Any,
    load_revision_kp_names: Callable[..., Awaitable[Any]],
    build_response_by_question: Callable[..., Awaitable[dict]],
    build_response: Callable[..., dict],
    issued_revisions: dict,
    issued_order: list[int],
    skipped_questions: list[Any],
    total_correct: int,
    total_wrong: int,
    knowledge_context: Any,
    entry_context: Any,
    persisted_knowledge_session: Callable[..., Any],
) -> dict:
    revision_kps = await load_revision_kp_names(db, issued_revisions.values())
    response_by_question = build_response_by_question(
        records=persisted.records,
        skipped_questions=skipped_questions,
        revision_kps=revision_kps,
        wrong_question_ids=persisted.wrong_question_ids,
    )
    return build_response(
        response_by_question=response_by_question,
        issued_order=issued_order,
        total_correct=total_correct,
        total_wrong=total_wrong,
        skipped_questions=skipped_questions,
        knowledge_context=knowledge_context,
        entry_context=entry_context,
        persisted_knowledge_session=persisted_knowledge_session,
    )


async def _finalize_claimed_practice_batch(
    session_obj: Any,
    *,
    response_payload: dict,
    user_id: int,
    batch_payload: dict,
    all_question_ids: list[int],
    build_cleanup: Callable[..., Any],
    execute: Callable[..., Awaitable[Any]],
    commit: Callable[..., Awaitable[None]],
) -> None:
    # submission_response is a SQL JSON column and is also the source used
    # for idempotent replay. Nested diagnostics may contain datetime values,
    # so normalize the entire payload once before persistence and response.
    session_obj.submission_response = response_payload
    cleanup = build_cleanup(
        user_id=user_id,
        batch_payload=batch_payload,
        all_question_ids=all_question_ids,
    )
    if cleanup is not None:
        await execute(cleanup)
    await commit()


async def _run_claimed_practice_batch(
    request: _ClaimedPracticeBatchRequest,
) -> BatchCommitResult:
    persisted = await request.persist_records(
        request.db, **request.persist_records_kwargs
    )
    response_payload = await _build_claimed_practice_response(
        request.db,
        persisted=persisted,
        load_revision_kp_names=request.load_revision_kp_names,
        build_response_by_question=request.build_response_by_question,
        build_response=request.build_response,
        issued_revisions=request.issued_revisions,
        issued_order=request.issued_order,
        skipped_questions=request.skipped_questions,
        total_correct=request.total_correct,
        total_wrong=request.total_wrong,
        knowledge_context=request.knowledge_context,
        entry_context=request.entry_context,
        persisted_knowledge_session=request.persisted_knowledge_session,
    )
    await _finalize_claimed_practice_batch(
        request.session_obj,
        response_payload=response_payload,
        user_id=request.user_id,
        batch_payload=request.batch_payload,
        all_question_ids=request.all_question_ids,
        build_cleanup=request.build_cleanup,
        execute=request.execute,
        commit=request.commit,
    )
    return BatchCommitResult(response_payload, persisted.prewarm_wrong_questions)


async def persist_claimed_practice_batch(
    db: AsyncSession,
    *,
    session_obj: Any,
    persist_records: Callable[..., Awaitable[Any]],
    load_revision_kp_names: Callable[..., Awaitable[Any]],
    build_response_by_question: Callable[..., Awaitable[dict]],
    build_response: Callable[..., dict],
    persisted_knowledge_session: Callable[..., Any],
    build_cleanup: Callable[..., Any],
    execute: Callable[..., Awaitable[Any]],
    commit: Callable[..., Awaitable[None]],
    rollback: Callable[..., Awaitable[None]],
    persist_records_kwargs: dict,
    issued_revisions: dict,
    issued_order: list[int],
    skipped_questions: list[Any],
    total_correct: int,
    total_wrong: int,
    knowledge_context: Any,
    entry_context: Any,
    user_id: int,
    batch_payload: dict,
    all_question_ids: list[int],
) -> BatchCommitResult:
    request = _ClaimedPracticeBatchRequest(**locals())
    try:
        return await _run_claimed_practice_batch(request)
    except BaseException:
        await request.rollback()
        raise


@dataclass(slots=True)
class BatchCommitResult:
    response_payload: dict
    prewarm_wrong_questions: list[Any]
