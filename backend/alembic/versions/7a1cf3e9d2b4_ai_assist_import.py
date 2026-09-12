"""ai assist import — add ai fields and ai_generation_logs

Revision ID: 7a1cf3e9d2b4
Revises: 95eefdba4c27
Create Date: 2026-05-22 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "7a1cf3e9d2b4"
down_revision: Union[str, Sequence[str], None] = "95eefdba4c27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("question_imports") as batch:
        batch.add_column(sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("ai_source", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("ai_confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("ai_metadata", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("ai_raw_response", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ai_reviewed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("ai_answer_flag", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "ai_generation_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("parsed_result", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_generation_logs_user_id"), "ai_generation_logs", ["user_id"], unique=False)
    op.create_index(op.f("ix_ai_generation_logs_action"), "ai_generation_logs", ["action"], unique=False)
    op.create_index(op.f("ix_ai_generation_logs_batch_id"), "ai_generation_logs", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_generation_logs_batch_id"), table_name="ai_generation_logs")
    op.drop_index(op.f("ix_ai_generation_logs_action"), table_name="ai_generation_logs")
    op.drop_index(op.f("ix_ai_generation_logs_user_id"), table_name="ai_generation_logs")
    op.drop_table("ai_generation_logs")
    with op.batch_alter_table("question_imports") as batch:
        batch.drop_column("ai_answer_flag")
        batch.drop_column("ai_reviewed_at")
        batch.drop_column("ai_raw_response")
        batch.drop_column("ai_metadata")
        batch.drop_column("ai_confidence")
        batch.drop_column("ai_source")
        batch.drop_column("ai_generated")
