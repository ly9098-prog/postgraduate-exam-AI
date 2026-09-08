"""Immutable question revision lifecycle.

``questions`` is the mutable projection used by authoring/search.  Every stable
student-facing state is persisted in ``question_versions`` and referenced by
``Question.current_version_id``.  Practice, wrong-book review and asynchronous
learning projections must bind to the immutable revision id instead of reading
whatever happens to be in ``questions`` when they execute.

All code that mutates a published Question must call :func:`ensure_question_revision`
after its scalar fields and knowledge-point links have reached their final state.
The function is idempotent and serializes revisions per question with a row lock.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint
from app.services import syllabus_service


def _canonical_state_payload(question: Question, kp_links: list[tuple[int, int, str, float, str]]) -> dict:
    return {
        "question_id": int(question.id),
        "subject_id": int(question.subject_id),
        "question_type": str(question.question_type or ""),
        "content": question.content,
        "options": question.options,
        "answer": str(question.answer or ""),
        "analysis": question.analysis,
        "difficulty": int(question.difficulty or 3),
        "image_url": question.image_url,
        "is_active": bool(question.is_active),
        "source": question.source,
        "source_type": question.source_type,
        "source_file": question.source_file,
        "raw_content": question.raw_content,
        "year": question.year,
        "knowledge_points": [
            [int(kp_id), int(position), str(role), float(weight), str(source)]
            for kp_id, position, role, weight, source in kp_links
        ],
    }


def compute_question_state_hash(question: Question, kp_links: list[tuple[int, int, str, float, str]]) -> str:
    payload = _canonical_state_payload(question, kp_links)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def load_question_kp_link_ids(
    db: AsyncSession, question_id: int
) -> list[tuple[int, int, str, float, str]]:
    """Load the complete immutable KP association for a mutable question."""
    rows = await db.execute(
        select(
            QuestionKnowledgePoint.knowledge_point_id,
            QuestionKnowledgePoint.position,
            QuestionKnowledgePoint.role,
            QuestionKnowledgePoint.weight,
            QuestionKnowledgePoint.source,
        )
        .where(QuestionKnowledgePoint.question_id == question_id)
        .order_by(QuestionKnowledgePoint.position, QuestionKnowledgePoint.id)
    )
    return [
        (
            int(kp_id),
            int(position),
            str(role or "main"),
            float(weight if weight is not None else 1.0),
            str(source or "imported"),
        )
        for kp_id, position, role, weight, source in rows.all()
    ]


async def lock_question_for_revision(
    db: AsyncSession,
    question_id: int,
) -> Question:
    """Lock and refresh the mutable projection before revision-sensitive work.

    ORM SELECTs normally reuse an already-loaded identity without overwriting its
    attributes.  Concurrent editors can therefore leave a stale in-memory field
    even after their UPDATE waited for another transaction. ``populate_existing``
    makes the locked row reflect the actual database state that the revision will
    snapshot.  Pending local scalar changes are autoflushed before the lock query.
    """
    statement = (
        select(Question)
        .where(Question.id == int(question_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    question = await db.scalar(statement)
    if question is None:
        raise RuntimeError(f"question {question_id} does not exist")
    return question


async def ensure_question_revision(
    db: AsyncSession,
    question: Question,
    *,
    editor_id: int | None = None,
    change_source: str = "system",
    edit_reason: str | None = None,
) -> QuestionVersion:
    """Persist the current Question+KP state as its immutable current revision.

    This is intentionally *post-change* snapshotting.  The previously-current
    revision already contains the pre-change state, so no mutation path needs a
    separate "snapshot before edit" branch.
    """
    # Serialize version-number allocation and refresh any stale identity-map
    # fields after pending caller changes have been flushed.
    question = await lock_question_for_revision(db, int(question.id))

    kp_links = await load_question_kp_link_ids(db, int(question.id))
    state_hash = compute_question_state_hash(question, kp_links)

    latest = await db.scalar(
        select(QuestionVersion)
        .where(QuestionVersion.question_id == question.id)
        .order_by(QuestionVersion.version.desc(), QuestionVersion.id.desc())
        .limit(1)
    )
    current = None
    if question.current_version_id:
        current = await db.get(QuestionVersion, int(question.current_version_id))

    # ``current_version_id`` is a projection pointer, not a separate branch of
    # history.  If it ever falls behind the newest immutable revision (for
    # example after a manual repair), never keep returning an older version just
    # because its state hash happens to equal the mutable projection.  Re-point
    # to the newest matching revision, or append a new monotonic revision when
    # the projection represents an older state.
    if latest is not None and latest.state_hash == state_hash:
        if int(question.current_version_id or 0) != int(latest.id):
            question.current_version_id = int(latest.id)
            await db.flush()
        return latest

    if (
        current is not None
        and int(current.question_id) == int(question.id)
        and current.state_hash == state_hash
        and latest is not None
        and int(latest.id) == int(current.id)
    ):
        return current

    next_version = int(latest.version if latest is not None else 0) + 1

    revision = QuestionVersion(
        question_id=int(question.id),
        version=next_version,
        subject_id=int(question.subject_id),
        question_type=str(question.question_type or ""),
        image_url=question.image_url,
        is_active=bool(question.is_active),
        source=question.source,
        source_type=question.source_type,
        source_file=question.source_file,
        raw_content=question.raw_content,
        year=question.year,
        content=question.content,
        options=question.options,
        answer=str(question.answer or ""),
        analysis=question.analysis,
        difficulty=int(question.difficulty or 3),
        edited_by=editor_id,
        change_source=str(change_source or "system")[:32],
        state_hash=state_hash,
        edit_reason=edit_reason,
    )
    db.add(revision)
    await db.flush()

    if kp_links:
        syllabus_memberships = await syllabus_service.active_membership_ids_for_kps(
            db, [kp_id for kp_id, *_rest in kp_links]
        )
        db.add_all(
            [
                QuestionVersionKnowledgePoint(
                    question_version_id=revision.id,
                    knowledge_point_id=kp_id,
                    syllabus_knowledge_point_id=syllabus_memberships.get(kp_id),
                    position=position,
                    role=role,
                    weight=weight,
                    source=source,
                )
                for kp_id, position, role, weight, source in kp_links
            ]
        )
    question.current_version_id = int(revision.id)
    await db.flush()
    return revision


def latest_question_revision_scope_condition(
    subject_ids: Iterable[int],
    answerable_question_types: Iterable[str],
):
    """SQL condition binding a Question to its newest immutable revision.

    Practice used to join through ``Question.current_version_id``.  A stale
    pointer then made the student endpoint serve an older snapshot even when a
    newer ``question_versions.version`` already existed.  The version history is
    monotonic per question, so student-facing candidate queries should resolve
    the newest revision directly and only use the mutable row as a projection
    consistency check.
    """
    ids = [int(sid) for sid in dict.fromkeys(subject_ids or []) if sid is not None]
    types = [str(value) for value in dict.fromkeys(answerable_question_types or []) if value]
    if not ids or not types:
        return Question.id == -1

    qv_rank = aliased(QuestionVersion)
    latest_version_number = (
        select(func.max(qv_rank.version))
        .where(qv_rank.question_id == Question.id)
        .correlate(Question)
        .scalar_subquery()
    )
    return select(QuestionVersion.id).where(
        QuestionVersion.question_id == Question.id,
        QuestionVersion.version == latest_version_number,
        QuestionVersion.subject_id == Question.subject_id,
        QuestionVersion.subject_id.in_(ids),
        QuestionVersion.question_type == Question.question_type,
        QuestionVersion.question_type.in_(types),
        QuestionVersion.is_active.is_(True),
        Question.is_active.is_(True),
        Question.review_status == "approved",
    ).exists()


async def load_latest_question_revision_ids(
    db: AsyncSession,
    question_ids: Iterable[int],
) -> dict[int, int]:
    """Return ``question_id -> newest QuestionVersion.id`` for a batch.

    This deliberately does not trust ``questions.current_version_id``.  It is a
    read-only resolver, so GET /practice/questions can issue the newest immutable
    version without mutating data or relying on transaction commit side effects.
    """
    ids = list(dict.fromkeys(int(qid) for qid in question_ids if qid))
    if not ids:
        return {}

    latest = (
        select(
            QuestionVersion.question_id.label("question_id"),
            func.max(QuestionVersion.version).label("version"),
        )
        .where(QuestionVersion.question_id.in_(ids))
        .group_by(QuestionVersion.question_id)
        .subquery()
    )
    rows = await db.execute(
        select(QuestionVersion.question_id, QuestionVersion.id)
        .join(
            latest,
            and_(
                latest.c.question_id == QuestionVersion.question_id,
                latest.c.version == QuestionVersion.version,
            ),
        )
    )
    return {int(question_id): int(version_id) for question_id, version_id in rows.all()}


async def require_current_question_revisions(
    db: AsyncSession, questions: Iterable[Question]
) -> dict[int, int]:
    """Return question_id -> current revision id, failing on broken invariants."""
    result: dict[int, int] = {}
    for question in questions:
        version_id = getattr(question, "current_version_id", None)
        if not version_id:
            raise RuntimeError(
                f"question {question.id} has no current_version_id; run migrations/repair revisions"
            )
        result[int(question.id)] = int(version_id)
    return result


async def load_revision_views(
    db: AsyncSession,
    revision_ids: Iterable[int],
) -> dict[int, SimpleNamespace]:
    """Load immutable revision views keyed by revision id."""
    ids = list(dict.fromkeys(int(v) for v in revision_ids if v))
    if not ids:
        return {}
    rows = await db.execute(
        select(QuestionVersion, Subject)
        .outerjoin(Subject, Subject.id == QuestionVersion.subject_id)
        .where(QuestionVersion.id.in_(ids))
    )
    result: dict[int, SimpleNamespace] = {}
    for revision, subject in rows.all():
        result[int(revision.id)] = SimpleNamespace(
            id=int(revision.question_id),
            question_id=int(revision.question_id),
            question_version_id=int(revision.id),
            version=int(revision.version),
            subject_id=int(revision.subject_id) if revision.subject_id is not None else None,
            subject_ref=subject,
            question_type=str(revision.question_type or ""),
            content=revision.content,
            options=revision.options,
            answer=revision.answer,
            analysis=revision.analysis,
            difficulty=int(revision.difficulty or 3),
            image_url=revision.image_url,
            is_active=bool(revision.is_active),
            source=revision.source,
            source_type=revision.source_type,
            source_file=revision.source_file,
            raw_content=revision.raw_content,
            year=revision.year,
            state_hash=revision.state_hash,
        )
    return result


async def load_revision_kp_ids(
    db: AsyncSession,
    revision_ids: Iterable[int],
) -> dict[int, list[int]]:
    ids = list(dict.fromkeys(int(v) for v in revision_ids if v))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            QuestionVersionKnowledgePoint.question_version_id,
            QuestionVersionKnowledgePoint.knowledge_point_id,
        )
        .where(QuestionVersionKnowledgePoint.question_version_id.in_(ids))
        .order_by(
            QuestionVersionKnowledgePoint.question_version_id,
            QuestionVersionKnowledgePoint.position,
            QuestionVersionKnowledgePoint.id,
        )
    )
    result: dict[int, list[int]] = {}
    for version_id, kp_id in rows.all():
        result.setdefault(int(version_id), []).append(int(kp_id))
    return result


async def load_revision_kp_links(
    db: AsyncSession,
    revision_ids: Iterable[int],
) -> dict[int, list[SimpleNamespace]]:
    """Load immutable KP association metadata for each revision."""
    ids = list(dict.fromkeys(int(v) for v in revision_ids if v))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            QuestionVersionKnowledgePoint.question_version_id,
            QuestionVersionKnowledgePoint.knowledge_point_id,
            QuestionVersionKnowledgePoint.position,
            QuestionVersionKnowledgePoint.role,
            QuestionVersionKnowledgePoint.weight,
            QuestionVersionKnowledgePoint.source,
        )
        .where(QuestionVersionKnowledgePoint.question_version_id.in_(ids))
        .order_by(
            QuestionVersionKnowledgePoint.question_version_id,
            QuestionVersionKnowledgePoint.position,
            QuestionVersionKnowledgePoint.id,
        )
    )
    result: dict[int, list[SimpleNamespace]] = {}
    for version_id, kp_id, position, role, weight, source in rows.all():
        result.setdefault(int(version_id), []).append(
            SimpleNamespace(
                knowledge_point_id=int(kp_id),
                position=int(position),
                role=str(role or "main"),
                weight=float(weight if weight is not None else 1.0),
                source=str(source or "imported"),
            )
        )
    return result


async def load_revision_kp_names(
    db: AsyncSession,
    revision_ids: Iterable[int],
) -> dict[int, list[str]]:
    ids = list(dict.fromkeys(int(v) for v in revision_ids if v))
    if not ids:
        return {}
    frozen_name = func.coalesce(SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name)
    rows = await db.execute(
        select(
            QuestionVersionKnowledgePoint.question_version_id,
            frozen_name,
        )
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionVersionKnowledgePoint.knowledge_point_id,
        )
        .outerjoin(
            SyllabusKnowledgePoint,
            SyllabusKnowledgePoint.id == QuestionVersionKnowledgePoint.syllabus_knowledge_point_id,
        )
        .where(QuestionVersionKnowledgePoint.question_version_id.in_(ids))
        .order_by(
            QuestionVersionKnowledgePoint.question_version_id,
            QuestionVersionKnowledgePoint.position,
            QuestionVersionKnowledgePoint.id,
        )
    )
    result: dict[int, list[str]] = {}
    for version_id, name in rows.all():
        result.setdefault(int(version_id), []).append(str(name))
    return result
