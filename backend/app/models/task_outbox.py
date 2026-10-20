"""Task outbox model — transactional outbox for DB+Redis task consistency.

Architecture
============
Business operations (e.g., creating an import batch) write both the business
record and a ``task_outbox`` row in the **same PostgreSQL transaction**.
A background dispatcher reads pending outbox rows using ``FOR UPDATE SKIP LOCKED``,
enqueues them to Redis (v2 durable queue), and marks them as ``published``.

This ensures at-least-once delivery to Redis without requiring distributed
transactions. Duplicate enqueue is prevented by the idempotent key in Redis.

Outbox statuses::

    pending → leased → published (success)
    pending → leased → failed    (permanent failure)
    pending → leased → pending   (lease expired, retry)

Key design properties
---------------------
* Outbox and business records are committed atomically in the same PG transaction.
* Dispatcher uses FOR UPDATE SKIP LOCKED — multiple dispatcher processes
  can coexist without contention.
* Idempotent key (task_id) prevents duplicate enqueue even if the dispatcher
  crashes after publishing but before marking ``published_at``.
* Periodic reconciliation fixes drift between DB outbox and Redis state.
* Retention: published rows are purged after 7 days.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

# ── SQLite compatibility ──────────────────────────────────────────────
# JSONB is PostgreSQL-specific.  The ``@compiles`` handler below lets
# SQLite (used in tests and local dev) treat JSONB as plain JSON so
# that table creation and basic read/write operations work without
# a real PostgreSQL instance.
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    """Render JSONB as JSON on SQLite — lossy for binary keys, fine for payload blobs."""
    from sqlalchemy.types import JSON as SA_JSON

    return compiler.visit_JSON(SA_JSON(), **kw)


from app.core.orm_base import Base


class TaskOutbox(Base):
    __tablename__ = "task_outbox"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_task_outbox_task_id"),
        Index("ix_task_outbox_type_status", "task_type", "status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    task_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Idempotent task ID (e.g. import:{pipeline_id})",
    )
    task_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Queue task type (import_pipeline, image_pipeline, etc.)",
    )
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Task payload (will be serialized to Redis task hash)",
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Payload schema version for rolling upgrade compatibility",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | leased | published | failed | cancelled",
    )
    lease_token: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Dispatcher lease token (for FOR UPDATE SKIP LOCKED tracking)",
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="Lease expiry — auto-resets to pending after timeout",
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="When the task was enqueued to Redis",
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of publish attempts",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Last error message from publish attempt",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<TaskOutbox id={self.id} task_id={self.task_id!r} "
            f"type={self.task_type!r} status={self.status!r}>"
        )
