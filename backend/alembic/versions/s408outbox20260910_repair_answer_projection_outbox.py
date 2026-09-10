"""repair legacy answer_projection Outbox schema envelopes

Revision ID: s408outbox20260910
Revises: s408pscope20260909
Create Date: 2026-09-10

A short-lived producer version persisted the current per-answer
``answer_projection`` payload with the generic Outbox default ``schema_version=1``.
The v2 queue publisher correctly rejected that envelope, but the deterministic
validation error was retried until those rows became permanently failed.

This data repair upgrades only payloads that are already compatible with the
current per-answer contract. Retired batch-shaped payloads are never guessed or
rewritten; the business projection reconciler can regenerate those from the
durable ``practice_records`` source of truth. It also terminalizes legacy
non-terminal rows that already exhausted the publisher retry budget, preventing
a permanently unclaimable row from keeping Outbox health in a stalled state.
"""
from __future__ import annotations

import json
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "s408outbox20260910"
down_revision = "s408pscope20260909"
branch_labels = None
depends_on = None

_CURRENT_SCHEMA_VERSION = 2
_RETIRED_BATCH_FIELDS = frozenset({
    "question_ids",
    "answers",
    "correct_count",
    "wrong_count",
    "duration_sec",
    "started_at",
    "finished_at",
})


def _payload_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _is_safe_current_payload(value: Any) -> bool:
    payload = _payload_dict(value)
    if payload is None or _RETIRED_BATCH_FIELDS.intersection(payload):
        return False
    try:
        record_id = int(payload.get("practice_record_id") or 0)
    except (TypeError, ValueError):
        return False
    return record_id > 0


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "task_outbox" not in inspector.get_table_names():
        return

    outbox = sa.table(
        "task_outbox",
        sa.column("id", sa.BigInteger()),
        sa.column("task_type", sa.String(length=32)),
        sa.column("payload", sa.JSON()),
        sa.column("schema_version", sa.Integer()),
        sa.column("status", sa.String(length=16)),
        sa.column("lease_token", sa.String(length=64)),
        sa.column("lease_expires_at", sa.DateTime()),
        sa.column("retry_count", sa.Integer()),
        sa.column("error_message", sa.Text()),
    )

    rows = bind.execute(
        sa.select(
            outbox.c.id,
            outbox.c.payload,
            outbox.c.status,
            outbox.c.retry_count,
            outbox.c.error_message,
        ).where(
            outbox.c.task_type == "answer_projection",
            outbox.c.schema_version == 1,
            outbox.c.status.in_(["pending", "leased", "failed"]),
        )
    ).mappings().all()

    for row in rows:
        if not _is_safe_current_payload(row["payload"]):
            continue

        values: dict[str, Any] = {"schema_version": _CURRENT_SCHEMA_VERSION}
        error = str(row["error_message"] or "").lower()
        if (
            row["status"] in {"failed", "pending"}
            and "unsupported answer_projection schema_version=" in error
        ):
            values.update({
                "status": "pending",
                "retry_count": 0,
                "error_message": None,
                "lease_token": None,
                "lease_expires_at": None,
            })

        bind.execute(
            outbox.update().where(outbox.c.id == row["id"]).values(**values)
        )

    # Older implementations could leave a row non-terminal after it had already
    # consumed the entire publish retry budget. Such a row is excluded by the
    # dispatcher claim query forever, so make the state machine consistent.
    exhausted = bind.execute(
        sa.select(
            outbox.c.id,
            outbox.c.retry_count,
            outbox.c.error_message,
        ).where(
            sa.or_(
                outbox.c.status == "pending",
                sa.and_(
                    outbox.c.status == "leased",
                    sa.or_(
                        outbox.c.lease_expires_at.is_(None),
                        outbox.c.lease_expires_at < sa.func.now(),
                    ),
                ),
            ),
            outbox.c.retry_count >= 10,
        )
    ).mappings().all()
    for row in exhausted:
        previous_error = str(row["error_message"] or "").strip()
        suffix = f"retry budget exhausted ({int(row['retry_count'] or 0)}/10)"
        bind.execute(
            outbox.update().where(outbox.c.id == row["id"]).values(
                status="failed",
                error_message=(
                    f"{previous_error}; {suffix}" if previous_error else suffix
                )[:500],
                lease_token=None,
                lease_expires_at=None,
            )
        )


def downgrade() -> None:
    # This is an operational data repair. Reverting valid envelopes back to v1
    # would recreate the poison-pill condition and is intentionally unsupported.
    pass
