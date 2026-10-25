"""Transactional persistence orchestration for a claimed practice batch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


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
    try:
        persisted = await persist_records(db, **persist_records_kwargs)
        revision_kps = await load_revision_kp_names(db, issued_revisions.values())
        response_by_question = build_response_by_question(
            records=persisted.records,
            skipped_questions=skipped_questions,
            revision_kps=revision_kps,
            wrong_question_ids=persisted.wrong_question_ids,
        )
        response_payload = build_response(
            response_by_question=response_by_question,
            issued_order=issued_order,
            total_correct=total_correct,
            total_wrong=total_wrong,
            skipped_questions=skipped_questions,
            knowledge_context=knowledge_context,
            entry_context=entry_context,
            persisted_knowledge_session=persisted_knowledge_session,
        )
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
        return BatchCommitResult(response_payload, persisted.prewarm_wrong_questions)
    except BaseException:
        await rollback()
        raise


@dataclass(slots=True)
class BatchCommitResult:
    response_payload: dict
    prewarm_wrong_questions: list[Any]
