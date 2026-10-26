"""Project committed practice answers from immutable question revisions.

The projection worker treats ``practice_records`` as an explicit event contract,
not as a fully-hydrated ORM aggregate.  Only the columns required by the current
projection protocol are selected, and the terminal projection state is written
with an explicit UPDATE.  This keeps the worker decoupled from unrelated model
columns and makes schema changes fail at the contract boundary instead of being
silently pulled into a hot-path ``SELECT *``.

``PracticeRecord.question_version_id`` is the durable grading boundary.
``PracticeRecord.projection_state`` is the durable processing receipt;
reconciliation only repairs records explicitly left in ``pending``.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import QuestionVersion
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.services.practice.answer_projection_contract import (
    REQUIRED_PROJECTION_COLUMNS,
    RETIRED_PRACTICE_BATCH_COLUMNS,
)
from app.services.practice.answer_projection_stages import (
    _ProjectionSource,
    _RevisionSource,
    apply_current_revision_state,
    apply_revision_evidence,
    capture_projection_answer,
)

logger = logging.getLogger(__name__)

PROJECTION_PENDING = "pending"
PROJECTION_COMPLETED = "completed"
PROJECTION_REVISION_ONLY = "revision_only"

_schema_contract_verified = False
_schema_contract_lock = asyncio.Lock()


async def _verify_projection_schema_contract(db: AsyncSession) -> None:
    """Fail fast unless ``practice_records`` is the strict per-answer schema.

    The emergency compatibility approach of re-adding batch columns is
    intentionally unsupported.  A worker must run only against the migrated
    per-answer schema; otherwise it stops this projection with a clear invariant
    error instead of allowing ORM/schema drift to survive unnoticed.
    """
    global _schema_contract_verified
    if _schema_contract_verified:
        return

    async with _schema_contract_lock:
        if _schema_contract_verified:
            return

        mapped_columns = set(PracticeRecord.__table__.columns.keys())
        mapped_legacy = sorted(mapped_columns & RETIRED_PRACTICE_BATCH_COLUMNS)
        if mapped_legacy:
            raise RuntimeError(
                "PracticeRecord ORM maps retired batch columns: "
                + ", ".join(mapped_legacy)
            )

        connection = await db.connection()

        def _load_columns(sync_connection) -> set[str]:
            inspector = inspect(sync_connection)
            if "practice_records" not in inspector.get_table_names():
                raise RuntimeError("practice_records table does not exist")
            return {
                str(column["name"])
                for column in inspector.get_columns("practice_records")
            }

        database_columns = await connection.run_sync(_load_columns)
        _assert_projection_columns(database_columns)
        _schema_contract_verified = True


def _assert_projection_columns(database_columns: set[str]) -> None:
    missing = sorted(REQUIRED_PROJECTION_COLUMNS - database_columns)
    legacy = sorted(RETIRED_PRACTICE_BATCH_COLUMNS & database_columns)
    if missing or legacy:
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if legacy:
            details.append("retired_present=" + ",".join(legacy))
        raise RuntimeError(
            "practice_records per-answer schema invariant failed ("
            + "; ".join(details)
            + "). Apply Alembic upgrade to head before running answer_projection workers."
        )


async def _lock_projection_source(
    db: AsyncSession,
    practice_record_id: int,
) -> _ProjectionSource | None:
    """Lock and load only the stable projection-event contract.

    A row lock is the single concurrency primitive for exactly-once projection.
    No advisory lock is needed: all projection work for an existing record is
    serialized by the same ``practice_records`` row until commit/rollback.
    """
    stmt = select(
        PracticeRecord.id,
        PracticeRecord.user_id,
        PracticeRecord.question_id,
        PracticeRecord.question_version_id,
        PracticeRecord.subject_id,
        PracticeRecord.user_answer,
        PracticeRecord.is_correct,
        PracticeRecord.used_time,
        PracticeRecord.answered_at,
        PracticeRecord.mode,
        PracticeRecord.projection_state,
    ).where(PracticeRecord.id == practice_record_id)

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(of=PracticeRecord)

    row = (await db.execute(stmt)).mappings().one_or_none()
    if row is None:
        return None

    return _ProjectionSource(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        question_id=int(row["question_id"]),
        question_version_id=(
            int(row["question_version_id"])
            if row["question_version_id"] is not None
            else None
        ),
        subject_id=int(row["subject_id"]),
        user_answer=str(row["user_answer"] or ""),
        is_correct=bool(row["is_correct"]),
        used_time=int(row["used_time"]) if row["used_time"] is not None else None,
        answered_at=row["answered_at"],
        mode=str(row["mode"]) if row["mode"] is not None else None,
        projection_state=str(row["projection_state"]),
    )


async def _load_revision_source(
    db: AsyncSession,
    question_version_id: int,
) -> _RevisionSource | None:
    """Load the immutable revision fields consumed by projection."""
    row = (
        (
            await db.execute(
                select(
                    QuestionVersion.id,
                    QuestionVersion.question_id,
                    QuestionVersion.subject_id,
                    QuestionVersion.answer,
                ).where(QuestionVersion.id == question_version_id)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return _RevisionSource(
        id=int(row["id"]),
        question_id=int(row["question_id"]),
        subject_id=int(row["subject_id"]) if row["subject_id"] is not None else None,
        answer=str(row["answer"]) if row["answer"] is not None else None,
    )


async def _load_current_question_version(
    db: AsyncSession,
    question_id: int,
) -> int | None:
    """Read the mutable question's current revision id.

    Do not lock the question row here: projections for different users commonly
    target the same question and must remain parallel.  Immutable grading still
    comes exclusively from ``question_version_id``; this value only decides
    whether mutable review/adaptive state may be advanced.
    """
    value = await db.scalar(
        select(Question.current_version_id).where(Question.id == question_id)
    )
    return int(value) if value is not None else None


async def _finish_projection(
    db: AsyncSession,
    *,
    practice_record_id: int,
    target_state: str,
) -> None:
    """Move a locked pending record to its terminal projection state."""
    result = await db.execute(
        update(PracticeRecord)
        .where(
            PracticeRecord.id == practice_record_id,
            PracticeRecord.projection_state == PROJECTION_PENDING,
        )
        .values(projection_state=target_state)
    )
    if result.rowcount != 1:
        raise RuntimeError(
            "practice projection state transition lost ownership: "
            f"record_id={practice_record_id} target={target_state} rowcount={result.rowcount}"
        )


async def _validate_projection_revision(
    db: AsyncSession,
    record: _ProjectionSource,
    practice_record_id: int,
) -> _RevisionSource:
    if record.question_version_id is None:
        raise RuntimeError(
            f"practice record {practice_record_id} has no question_version_id"
        )

    revision = await _load_revision_source(db, record.question_version_id)
    if revision is None or revision.question_id != record.question_id:
        raise RuntimeError(
            f"practice record {practice_record_id} references invalid question revision"
        )
    return revision


async def _invalidate_projection_cache(user_id: int) -> None:
    try:
        from app.services.vector_retrieval_service import invalidate_vector_cache

        await invalidate_vector_cache(user_id)
    except Exception:
        logger.debug("vector cache invalidation failed uid=%d", user_id, exc_info=True)


async def project_practice_answer(
    db: AsyncSession,
    *,
    practice_record_id: int,
    request_id: str | None = None,
) -> dict:
    """Project immutable evidence once, guarding mutable state by current revision."""
    await _verify_projection_schema_contract(db)
    record = await _lock_projection_source(db, practice_record_id)
    if record is None:
        logger.warning(
            "answer projection record missing: record_id=%s", practice_record_id
        )
        return {"processed": False, "missing": True}
    if record.projection_state != PROJECTION_PENDING:
        return {
            "processed": False,
            "duplicate": True,
            "projection_state": record.projection_state,
        }

    revision = await _validate_projection_revision(db, record, practice_record_id)
    current_version_id = await _load_current_question_version(db, record.question_id)
    is_current_revision = current_version_id == record.question_version_id
    answer = capture_projection_answer(record)
    await apply_revision_evidence(db, record, revision, answer, request_id)
    if is_current_revision:
        await apply_current_revision_state(db, record, answer)
        target_state = PROJECTION_COMPLETED
    else:
        target_state = PROJECTION_REVISION_ONLY

    await _finish_projection(
        db,
        practice_record_id=record.id,
        target_state=target_state,
    )
    await db.commit()
    await _invalidate_projection_cache(answer.user_id)
    return {
        "processed": True,
        "duplicate": False,
        "projection_state": target_state,
        "question_version_id": record.question_version_id,
    }
