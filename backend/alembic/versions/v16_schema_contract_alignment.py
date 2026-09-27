"""v16: align nullable and comment contracts with ORM metadata."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "v16_schema_contract_alignment"
down_revision = "v15_schema_integrity_core"
branch_labels = None
depends_on = None

# table -> column -> deterministic SQL backfill expression
_TARGETS: dict[str, dict[str, str]] = {
    "formula_graph_previews": {"created_at": "CURRENT_TIMESTAMP"},
    "knowledge_edges": {
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "knowledge_points": {
        "difficulty_level": "3",
        "is_active": "true",
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "practice_records": {
        # Historical rows must already identify their question; fabricating this
        # FK would corrupt provenance, so NULL values deliberately fail ALTER.
        "question_id": "question_id",
        "answered_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "question_knowledge_points": {
        "role": "'main'",
        "weight": "1.0",
        "source": "'imported'",
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "recommendation_logs": {
        "shown_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "review_sessions": {"created_at": "CURRENT_TIMESTAMP"},
    "study_plan_days": {
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "study_plans": {
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "user_knowledge_states": {
        "attempt_count": "0",
        "correct_count": "0",
        "wrong_count": "0",
        "accuracy": "0.0",
        "mastery_score": "50.0",
        "weakness_level": "'unknown'",
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "user_adaptive_profile": {
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "user_knowledge_adaptive_state": {
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "user_question_difficulty_state": {
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "user_question_state": {
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
    "user_recommend_preference": {
        "created_at": "CURRENT_TIMESTAMP",
        "updated_at": "COALESCE(created_at, CURRENT_TIMESTAMP)",
    },
}

_TASK_OUTBOX_COMMENTS = {
    "task_id": "Idempotent task ID (e.g. import:{pipeline_id})",
    "task_type": "Queue task type (import_pipeline, image_pipeline, etc.)",
    "payload": "Task payload (will be serialized to Redis task hash)",
    "schema_version": "Payload schema version for rolling upgrade compatibility",
    "status": "pending | leased | published | failed | cancelled",
    "lease_token": "Dispatcher lease token (for FOR UPDATE SKIP LOCKED tracking)",
    "lease_expires_at": "Lease expiry — auto-resets to pending after timeout",
    "published_at": "When the task was enqueued to Redis",
    "retry_count": "Number of publish attempts",
    "error_message": "Last error message from publish attempt",
}


def _column_map(table: str) -> dict[str, dict]:
    return {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns(table)}


def _set_nullable(nullable: bool) -> None:
    dialect = op.get_bind().dialect.name
    for table, columns in _TARGETS.items():
        reflected = _column_map(table)
        changes = []
        for column, expression in columns.items():
            info = reflected[column]
            if not nullable:
                op.execute(
                    sa.text(
                        f'UPDATE "{table}" SET "{column}" = {expression} '
                        f'WHERE "{column}" IS NULL'
                    )
                )
            if bool(info["nullable"]) != nullable:
                changes.append((column, info["type"]))
        if not changes:
            continue
        if dialect == "sqlite":
            with op.batch_alter_table(table, recreate="always") as batch_op:
                for column, existing_type in changes:
                    batch_op.alter_column(
                        column, existing_type=existing_type, nullable=nullable
                    )
        else:
            for column, existing_type in changes:
                op.alter_column(
                    table, column, existing_type=existing_type, nullable=nullable
                )


def _set_task_outbox_comments(comments: dict[str, str | None]) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    reflected = _column_map("task_outbox")
    for column, comment in comments.items():
        op.alter_column(
            "task_outbox",
            column,
            existing_type=reflected[column]["type"],
            comment=comment,
        )


def upgrade() -> None:
    _set_nullable(False)
    _set_task_outbox_comments(_TASK_OUTBOX_COMMENTS)


def downgrade() -> None:
    _set_task_outbox_comments({name: None for name in _TASK_OUTBOX_COMMENTS})
    _set_nullable(True)
