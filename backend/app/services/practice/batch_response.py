"""Canonical response and reservation cleanup for a committed practice batch."""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder


def build_batch_submission_response(
    *,
    response_by_question: dict[int, dict],
    issued_order: list[int],
    total_correct: int,
    total_wrong: int,
    skipped_questions: list[Any],
    knowledge_context: Any,
    entry_context: Any,
    persisted_knowledge_session,
) -> dict:
    return jsonable_encoder(
        {
            "results": [response_by_question[qid] for qid in issued_order],
            "total_correct": total_correct,
            "total_wrong": total_wrong,
            "total_skipped": len(skipped_questions),
            "knowledge_session": persisted_knowledge_session(knowledge_context),
            "entry_context": (
                dict(entry_context) if isinstance(entry_context, dict) else None
            ),
        }
    )
