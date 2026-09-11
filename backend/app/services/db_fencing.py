"""DB Fencing — execution generation guard for business writes.

Verifies that the task's generation matches the stored execution_generation
in the business DB record before allowing writes. This prevents stale workers
from writing business state after lease loss (owner or generation mismatch).

Usage::

    from app.services.db_fencing import verify_fencing_or_raise

    # Before business writes:
    verify_fencing_or_raise(
        db=db,
        model=ImportPipeline,
        record_id=pipeline_id,
        expected_task_id=task_id,
        expected_generation=generation,
        expected_owner_token=owner_token,
    )
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("postgraduate-ai.db-fencing")


def _get_pk_column(model_class: Any) -> str:
    """Resolve the primary key column name for a SQLAlchemy model."""
    try:
        pk_cols = sa_inspect(model_class).primary_key
        if pk_cols:
            return pk_cols[0].name
    except Exception:
        pass
    # Fallback: try common PK names
    for candidate in ("id", "pipeline_id", "job_id"):
        if hasattr(model_class, candidate):
            return candidate
    return "id"


class FencingVerificationError(Exception):
    """Raised when generation fencing check fails.

    Indicates that a stale worker is attempting to write business state
    for a task that was re-assigned to another worker.
    """


class FencingRejectedError(Exception):
    """Raised when a conditional fenced UPDATE affects 0 rows.

    The worker no longer owns the fence — its generation/task_id/owner_token
    has been superseded. All further business writes must be aborted and the
    current transaction rolled back.
    """


FENCING_TABLES: dict[str, tuple[Any, str]] = {}
"""Registry of (model_class, id_column) for fencing verification.

Populated at import time by each model that supports fencing.
"""


def register_fencing_table(
    task_type: str, model_class: Any, id_column: str = "id"
) -> None:
    """Register a business table for generation fencing.

    Args:
        task_type: The task type identifier (e.g. "import_pipeline").
        model_class: The SQLAlchemy model class.
        id_column: The column name used as record identifier
                   (default: "id").
    """
    FENCING_TABLES[task_type] = (model_class, id_column)


async def verify_fencing_or_raise(
    db: AsyncSession,
    model_class: Any,
    record_id: str | int,
    *,
    expected_task_id: str,
    expected_generation: int,
    expected_owner_token: str,
) -> None:
    """Verify that the DB record's fence fields match expected values.

    Raises ``FencingVerificationError`` on mismatch. Also logs a warning
    so operators can detect fencing violations.

    The verification is a single SELECT that reads the four fence columns.
    No writes are performed — the caller decides how to handle mismatch.
    """
    from sqlalchemy import select

    pk_col = getattr(model_class, _get_pk_column(model_class))
    stmt = select(
        model_class.execution_generation,
        model_class.current_task_id,
        model_class.current_owner_token,
    ).where(pk_col == record_id)

    result = await db.execute(stmt)
    row = result.one_or_none()

    if row is None:
        logger.warning(
            "Fencing: record not found model=%s id=%s task_id=%s",
            model_class.__name__,
            record_id,
            expected_task_id,
        )
        raise FencingVerificationError(
            f"Record not found: {model_class.__name__} id={record_id}"
        )

    db_generation, db_task_id, db_owner_token = row

    mismatches: list[str] = []
    if db_task_id is not None and db_task_id != expected_task_id:
        mismatches.append(f"task_id ({db_task_id} != {expected_task_id})")
    if db_owner_token is not None and db_owner_token != expected_owner_token:
        mismatches.append("owner_token mismatch")
    if (
        db_generation is not None
        and db_generation != 0
        and db_generation != expected_generation
    ):
        mismatches.append(f"generation ({db_generation} != {expected_generation})")

    if mismatches:
        logger.warning(
            "Fencing FAILED: model=%s id=%s task_id=%s gen=%d — %s",
            model_class.__name__,
            record_id,
            expected_task_id,
            expected_generation,
            "; ".join(mismatches),
        )
        raise FencingVerificationError(
            f"Fencing mismatch for {model_class.__name__} id={record_id}: "
            f"{'; '.join(mismatches)}"
        )


async def conditional_update_with_fencing(
    db: AsyncSession,
    model_class: Any,
    record_id: str | int,
    *,
    expected_task_id: str,
    expected_generation: int,
    expected_owner_token: str,
    **values: Any,
) -> bool:
    """Atomically update a business record guarded by fencing WHERE clauses.

    Executes an UPDATE with conditions on ``current_task_id``,
    ``current_owner_token``, and ``execution_generation``. If any of
    these fields no longer match, the UPDATE affects 0 rows and the
    caller MUST abort.

    Returns ``True`` if exactly 1 row was updated (fence still held).
    Returns ``False`` if 0 rows were updated (fence lost — the caller
    should raise ``FencingRejectedError`` and rollback).

    The caller is responsible for committing or rolling back the
    transaction.
    """
    from sqlalchemy import update

    pk_col = getattr(model_class, _get_pk_column(model_class))
    stmt = (
        update(model_class)
        .where(pk_col == record_id)
        .where(model_class.current_task_id == expected_task_id)
        .where(model_class.current_owner_token == expected_owner_token)
        .where(model_class.execution_generation == expected_generation)
        .values(**values)
    )
    result = await db.execute(stmt)
    ok = result.rowcount == 1 if result.rowcount is not None else False
    if not ok:
        logger.warning(
            "Fencing conditional UPDATE rejected: model=%s id=%s "
            "task_id=%s gen=%d rowcount=%s",
            model_class.__name__,
            record_id,
            expected_task_id,
            expected_generation,
            result.rowcount,
        )
    return ok


async def initialize_fencing_fields(
    db: AsyncSession,
    model_class: Any,
    record_id: str | int,
    *,
    task_id: str,
    owner_token: str,
    generation: int,
    status: str = "processing",
) -> bool:
    """Initialize fencing fields on a business record.

    Sets ``current_task_id``, ``current_owner_token``, ``execution_generation``,
    and ``execution_status``. This is called when a worker begins processing
    a task that is associated with a business record.

    Returns True if the update affected 1 row (success).
    Returns False if the update affected 0 rows (record not found or
    stale generation already written).
    """
    from sqlalchemy import update

    pk_col = getattr(model_class, _get_pk_column(model_class))
    stmt = (
        update(model_class)
        .where(pk_col == record_id)
        .where(
            # Only set if not already set by a higher generation
            (model_class.execution_generation == 0)
            | (model_class.execution_generation < generation)
            | (model_class.execution_generation.is_(None))
        )
        .values(
            current_task_id=task_id,
            current_owner_token=owner_token,
            execution_generation=generation,
            execution_status=status,
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


# ── Fencing table registrations ──
# Maps task_type → (model_class, id_column) for DB fencing verification.


def _register_default_tables() -> None:
    """Register known business models for DB fencing (idempotent)."""
    if FENCING_TABLES:
        return
    try:
        from app.models.import_pipeline import ImportPipeline

        register_fencing_table("import_pipeline", ImportPipeline, "pipeline_id")
    except ImportError:
        pass
    try:
        from app.models.import_pipeline import ImportPipeline

        register_fencing_table("image_pipeline", ImportPipeline, "pipeline_id")
        register_fencing_table("excel_pipeline", ImportPipeline, "pipeline_id")
        register_fencing_table("resume_pipeline", ImportPipeline, "pipeline_id")
        register_fencing_table("admin_resume", ImportPipeline, "pipeline_id")
    except ImportError:
        pass
    try:
        from app.models.import_batch_job import ImportBatchJob

        register_fencing_table("batch_image", ImportBatchJob, "job_id")
    except ImportError:
        pass
    try:
        from app.models.formula import FormulaCard

        register_fencing_table("formula_batch", FormulaCard, "id")
    except ImportError:
        pass


_register_default_tables()
