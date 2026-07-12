"""v8: add mastered_at, is_active, removed_at to wrong_questions

Adds timestamp columns for mastered_at/removed_at and a boolean soft-delete
flag is_active, with supporting indexes for common query patterns.

Revision ID: v8_wrong_question_soft_delete
Revises: v7_import_review_source_metadata
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa


revision = "v8_wrong_question_soft_delete"
down_revision = "v7_import_review_source_metadata"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    dialect = conn.dialect.name

    columns = {c["name"] for c in insp.get_columns("wrong_questions")}

    additions = {
        "mastered_at": sa.Column("mastered_at", sa.DateTime(), nullable=True),
        "is_active": sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        "removed_at": sa.Column("removed_at", sa.DateTime(), nullable=True),
    }

    for col_name, col in additions.items():
        if col_name not in columns:
            op.add_column("wrong_questions", col)

    existing_idxs = {idx["name"] for idx in insp.get_indexes("wrong_questions")}

    if "ix_wq_user_active_next" not in existing_idxs and dialect == "postgresql":
        op.create_index(
            "ix_wq_user_active_next",
            "wrong_questions",
            ["user_id", "is_active"],
            postgresql_where=sa.text("is_active = TRUE"),
        )
    elif "ix_wq_user_active_next" not in existing_idxs:
        op.create_index(
            "ix_wq_user_active_next",
            "wrong_questions",
            ["user_id", "is_active"],
        )

    if "ix_wq_user_mastered" not in existing_idxs:
        op.create_index(
            "ix_wq_user_mastered",
            "wrong_questions",
            ["user_id", "mastered"],
        )

    if "ix_wq_user_review_count" not in existing_idxs and dialect == "postgresql":
        op.create_index(
            "ix_wq_user_review_count",
            "wrong_questions",
            ["user_id", "review_count"],
            postgresql_where=sa.text("is_active = TRUE AND mastered = FALSE"),
        )
    elif "ix_wq_user_review_count" not in existing_idxs:
        op.create_index(
            "ix_wq_user_review_count",
            "wrong_questions",
            ["user_id", "review_count"],
        )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = {c["name"] for c in insp.get_columns("wrong_questions")}

    removals = ["mastered_at", "is_active", "removed_at"]
    for col_name in removals:
        if col_name in columns:
            op.drop_column("wrong_questions", col_name)

    index_names = [
        "ix_wq_user_active_next",
        "ix_wq_user_mastered",
        "ix_wq_user_review_count",
    ]
    existing_idxs = {idx["name"] for idx in insp.get_indexes("wrong_questions")}
    for idx_name in index_names:
        if idx_name in existing_idxs:
            op.drop_index(idx_name, table_name="wrong_questions")
