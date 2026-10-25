"""Final revision-scope guard for practice batches.

The service keeps the public compatibility wrapper and logger name; this module
owns the database projection and structural/semantic rejection rules.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import QuestionVersion, Subject
from app.models.question import Question
from app.services.practice.normalization import (
    detect_408_subject_mismatch,
    question_stem_for_subject_guard,
)

logger = logging.getLogger(__name__)


async def filter_questions_to_revision_scope(
    db: AsyncSession,
    questions: list[Question],
    subject_ids: list[int],
    revision_ids: dict[int, int] | None,
    *,
    load_revision_ids: Callable,
    answerable_types: frozenset[str],
) -> list[Question]:
    """Drop candidates whose mutable row, revision, scope, or semantics disagree."""
    if not questions:
        return []
    scope = {int(sid) for sid in subject_ids or []}
    resolved_revision_ids = revision_ids or await load_revision_ids(
        db, [int(q.id) for q in questions]
    )
    version_ids = {
        int(version_id) for version_id in resolved_revision_ids.values() if version_id
    }
    if not scope or not version_ids:
        logger.error(
            "[PRACTICE_REVISION_SCOPE] empty scope/version set scope=%s question_ids=%s",
            sorted(scope),
            [int(q.id) for q in questions],
        )
        return []

    revisions, subjects = await _load_revision_context(
        db, version_ids, scope
    )
    return _apply_revision_guard(
        questions,
        scope,
        resolved_revision_ids,
        revisions,
        subjects,
        answerable_types,
    )


async def _load_revision_context(
    db: AsyncSession, version_ids: set[int], scope: set[int]
) -> tuple[dict[int, QuestionVersion], dict[int, tuple[str, str]]]:
    rows = await db.execute(
        select(
            QuestionVersion.id,
            QuestionVersion.question_id,
            QuestionVersion.subject_id,
            QuestionVersion.question_type,
            QuestionVersion.is_active,
            QuestionVersion.content,
        ).where(QuestionVersion.id.in_(version_ids))
    )
    revisions = {int(row.id): row for row in rows.all()}

    revision_subject_ids = {
        int(row.subject_id) for row in revisions.values() if row.subject_id is not None
    }
    subject_rows = await db.execute(
        select(Subject.id, Subject.code, Subject.name).where(
            Subject.id.in_(scope | revision_subject_ids)
        )
    )
    subjects = {
        int(row.id): (str(row.code or ""), str(row.name or ""))
        for row in subject_rows.all()
    }
    return revisions, subjects


def _apply_revision_guard(
    questions: list[Question],
    scope: set[int],
    revision_ids: dict[int, int],
    revisions: dict[int, QuestionVersion],
    subjects: dict[int, tuple[str, str]],
    answerable_types: frozenset[str],
) -> list[Question]:
    kept: list[Question] = []
    rejected: list[dict] = []
    for question in questions:
        rejection = _inspect_question(
            question,
            scope,
            revision_ids,
            revisions,
            subjects,
            answerable_types,
        )
        if rejection is None:
            kept.append(question)
        else:
            rejected.append(rejection)

    if rejected:
        logger.error(
            "[PRACTICE_REVISION_SCOPE] rejected=%d scope_ids=%s rows=%s",
            len(rejected),
            sorted(scope),
            rejected,
        )
    return kept


def _inspect_question(
    question: Question,
    scope: set[int],
    revision_ids: dict[int, int],
    revisions: dict[int, QuestionVersion],
    subjects: dict[int, tuple[str, str]],
    answerable_types: frozenset[str],
) -> dict | None:
    qid = int(question.id)
    q_subject_id = (
        int(question.subject_id) if question.subject_id is not None else None
    )
    version_id = revision_ids.get(qid)
    revision = revisions.get(version_id) if version_id else None
    revision_subject_id = (
        int(revision.subject_id)
        if revision is not None and revision.subject_id is not None
        else None
    )
    q_question_type = str(getattr(question, "question_type", "") or "")
    revision_question_type = str(getattr(revision, "question_type", "") or "")
    structural_valid = bool(
        q_subject_id in scope
        and revision is not None
        and int(revision.question_id) == qid
        and revision_subject_id == q_subject_id
        and revision_subject_id in scope
        and revision_question_type == q_question_type
        and revision_question_type in answerable_types
        and bool(getattr(question, "is_active", False))
        and str(getattr(question, "review_status", "") or "") == "approved"
        and revision.is_active is True
    )

    semantic_mismatch = None
    semantic_scores: dict[str, int] = {}
    if structural_valid and revision_subject_id is not None:
        subject_code, subject_name = subjects.get(revision_subject_id, ("", ""))
        semantic_mismatch, semantic_scores = detect_408_subject_mismatch(
            subject_code=subject_code,
            subject_name=subject_name,
            stem=question_stem_for_subject_guard(revision.content),
        )

    if structural_valid and semantic_mismatch is None:
        return None
    return {
        "question_id": qid,
        "question_subject_id": q_subject_id,
        "current_version_id": (
            int(question.current_version_id)
            if getattr(question, "current_version_id", None)
            else None
        ),
        "issued_latest_version_id": version_id,
        "revision_subject_id": revision_subject_id,
        "question_type": q_question_type,
        "revision_question_type": revision_question_type,
        "answerable_type": revision_question_type in answerable_types,
        "question_active": getattr(question, "is_active", None),
        "review_status": getattr(question, "review_status", None),
        "revision_active": getattr(revision, "is_active", None),
        "semantic_mismatch": semantic_mismatch,
        "semantic_scores": semantic_scores or None,
    }
