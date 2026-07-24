"""add missing performance indexes for practice/knowledge queries

Revision ID: 2240ai_v12_missing_idx
Revises: c392c0978aca
Create Date: 2026-07-24

New indexes:
  1. idx_questions_subject_id_active       — questions(subject_id, is_active) partial
  2. idx_uqs_user_next_review              — user_question_state(user_id, next_review_at)
  3. idx_qkp_knowledge_point_question      — question_knowledge_points(knowledge_point_id, question_id)
  4. ix_wrong_questions_question_id        — wrong_questions(question_id)
  5. ix_review_schedules_question_id       — review_schedules(question_id)
  6. ix_review_records_question_id         — review_records(question_id)

Dropped (duplicates):
  - idx_review_schedules_user_next         — duplicate of ix_review_schedules_user_next_review
  - idx_review_records_user_date           — duplicate of ix_review_records_user_reviewed
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2240ai_v12_missing_idx"
down_revision: Union[str, Sequence[str], None] = "c392c0978aca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _idx_names(inspector, table: str) -> set[str]:
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. questions(subject_id, is_active) partial index ──
    # The old idx_questions_subject_active was on questions(subject, is_active)
    # but the `subject` column was dropped (see p5_6_drop_subject_column).
    # Replace with (subject_id, is_active) for practice query performance.
    q_names = _idx_names(inspector, "questions")
    if "idx_questions_subject_id_active" not in q_names:
        op.create_index(
            "idx_questions_subject_id_active",
            "questions",
            ["subject_id", "is_active"],
            unique=False,
            postgresql_where=sa.text("is_active = true"),
        )

    # ── 2. user_question_state(user_id, next_review_at) ──
    # Heavily used in Leitner queries: outer join + next_review_at ≤ now
    uqs_names = _idx_names(inspector, "user_question_state")
    if "idx_uqs_user_next_review" not in uqs_names:
        op.create_index(
            "idx_uqs_user_next_review",
            "user_question_state",
            ["user_id", "next_review_at"],
            unique=False,
        )

    # ── 3. question_knowledge_points(knowledge_point_id, question_id) ──
    # Used by attach_recommended_questions_to_path and smart-score queries
    qkp_names = _idx_names(inspector, "question_knowledge_points")
    if "idx_qkp_knowledge_point_question" not in qkp_names:
        op.create_index(
            "idx_qkp_knowledge_point_question",
            "question_knowledge_points",
            ["knowledge_point_id", "question_id"],
            unique=False,
        )

    # ── 4–6. question_id single-column indexes on FK-only columns ──
    for table, idx_name, cols in [
        ("wrong_questions", "ix_wrong_questions_question_id", ["question_id"]),
        ("review_schedules", "ix_review_schedules_question_id", ["question_id"]),
        ("review_records", "ix_review_records_question_id", ["question_id"]),
    ]:
        tbl_names = _idx_names(inspector, table)
        if idx_name not in tbl_names:
            op.create_index(idx_name, table, cols, unique=False)

    # ── Drop duplicate indexes ──
    # idx_review_schedules_user_next duplicates ix_review_schedules_user_next_review
    rs_names = _idx_names(inspector, "review_schedules")
    if "idx_review_schedules_user_next" in rs_names:
        op.drop_index("idx_review_schedules_user_next", table_name="review_schedules")

    # idx_review_records_user_date duplicates ix_review_records_user_reviewed
    rr_names = _idx_names(inspector, "review_records")
    if "idx_review_records_user_date" in rr_names:
        op.drop_index("idx_review_records_user_date", table_name="review_records")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop new indexes in reverse order
    for table, idx_name in [
        ("review_records", "ix_review_records_question_id"),
        ("review_schedules", "ix_review_schedules_question_id"),
        ("wrong_questions", "ix_wrong_questions_question_id"),
        ("question_knowledge_points", "idx_qkp_knowledge_point_question"),
        ("user_question_state", "idx_uqs_user_next_review"),
        ("questions", "idx_questions_subject_id_active"),
    ]:
        tbl_names = _idx_names(inspector, table)
        if idx_name in tbl_names:
            op.drop_index(idx_name, table_name=table)

    # Re-create dropped duplicates
    rs_names = _idx_names(inspector, "review_schedules")
    if "idx_review_schedules_user_next" not in rs_names:
        op.create_index(
            "idx_review_schedules_user_next",
            "review_schedules",
            ["user_id", "next_review_at"],
            unique=False,
        )
    rr_names = _idx_names(inspector, "review_records")
    if "idx_review_records_user_date" not in rr_names:
        op.create_index(
            "idx_review_records_user_date",
            "review_records",
            ["user_id", "reviewed_at"],
            unique=False,
        )
