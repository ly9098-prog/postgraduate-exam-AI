"""add occurrence-level 408 wrong-answer error diagnosis facts

Revision ID: s408error20260907
Revises: s408exam20260907
Create Date: 2026-09-07
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "s408error20260907"
down_revision: Union[str, Sequence[str], None] = "s408exam20260907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wrong_question_error_diagnoses",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wrong_question_id", sa.Integer(), sa.ForeignKey("wrong_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "question_version_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("question_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("practice_record_id", sa.Integer(), sa.ForeignKey("practice_records.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "exam_answer_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("exam_answers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_context", sa.String(length=16), nullable=False),
        sa.Column("user_answer", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=32), nullable=False, server_default="408-error-v1"),
        sa.Column("classification_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ai_primary_type", sa.String(length=32), nullable=True),
        sa.Column("ai_secondary_types", sa.JSON(), nullable=True),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("ai_reason", sa.Text(), nullable=True),
        sa.Column("ai_status", sa.String(length=16), nullable=False, server_default="not_requested"),
        sa.Column("ai_model", sa.String(length=128), nullable=True),
        sa.Column("ai_suggested_at", sa.DateTime(), nullable=True),
        sa.Column("user_primary_type", sa.String(length=32), nullable=True),
        sa.Column("user_secondary_types", sa.JSON(), nullable=True),
        sa.Column("user_confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("practice_record_id", name="uq_wrong_error_diagnoses_practice_record"),
        sa.UniqueConstraint("exam_answer_id", name="uq_wrong_error_diagnoses_exam_answer"),
        sa.CheckConstraint("source_context IN ('practice','exam','legacy')", name="ck_wrong_error_diagnoses_source_context"),
        sa.CheckConstraint("ai_status IN ('not_requested','pending','suggested','failed')", name="ck_wrong_error_diagnoses_ai_status"),
        sa.CheckConstraint("classification_version >= 1", name="ck_wrong_error_diagnoses_classification_version"),
        sa.CheckConstraint("ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 1)", name="ck_wrong_error_diagnoses_ai_confidence"),
    )
    op.create_index("ix_wrong_question_error_diagnoses_user_id", "wrong_question_error_diagnoses", ["user_id"])
    op.create_index("ix_wrong_question_error_diagnoses_wrong_question_id", "wrong_question_error_diagnoses", ["wrong_question_id"])
    op.create_index("ix_wrong_question_error_diagnoses_question_id", "wrong_question_error_diagnoses", ["question_id"])
    op.create_index("ix_wrong_question_error_diagnoses_question_version_id", "wrong_question_error_diagnoses", ["question_version_id"])
    op.create_index("ix_wrong_question_error_diagnoses_practice_record_id", "wrong_question_error_diagnoses", ["practice_record_id"])
    op.create_index("ix_wrong_question_error_diagnoses_exam_answer_id", "wrong_question_error_diagnoses", ["exam_answer_id"])
    op.create_index("ix_wrong_error_diagnoses_user_occurred", "wrong_question_error_diagnoses", ["user_id", "occurred_at"])
    op.create_index("ix_wrong_error_diagnoses_wq_occurred", "wrong_question_error_diagnoses", ["wrong_question_id", "occurred_at"])
    op.create_index("ix_wrong_error_diagnoses_user_primary", "wrong_question_error_diagnoses", ["user_id", "user_primary_type"])
    op.create_index("ix_wrong_error_diagnoses_ai_primary", "wrong_question_error_diagnoses", ["user_id", "ai_primary_type"])

    # Preserve the old single-value WrongQuestion.error_type as a user-confirmed
    # legacy fact where it contains meaningful information. New attempts use the
    # occurrence table directly and do not inherit this old cause automatically.
    op.execute(sa.text("""
        INSERT INTO wrong_question_error_diagnoses (
            user_id, wrong_question_id, question_id, question_version_id,
            source_context, user_answer, occurred_at, taxonomy_version, classification_version,
            ai_status, user_primary_type, user_confirmed_at,
            created_at, updated_at
        )
        SELECT
            w.user_id,
            w.id,
            w.question_id,
            w.question_version_id,
            'legacy',
            w.wrong_answer,
            COALESCE(
                (
                    SELECT MAX(pr.answered_at)
                    FROM practice_records pr
                    WHERE pr.user_id = w.user_id
                      AND pr.question_id = w.question_id
                      AND pr.is_correct = FALSE
                ),
                w.created_at,
                CURRENT_TIMESTAMP
            ),
            '408-error-v1',
            1,
            'not_requested',
            CASE COALESCE(w.error_type, '')
                WHEN 'knowledge_gap' THEN 'knowledge_gap'
                WHEN 'concept_confusion' THEN 'concept_confusion'
                WHEN 'memory_error' THEN 'memory_error'
                WHEN 'calculation_error' THEN 'calculation_error'
                WHEN 'misread' THEN 'misread'
                WHEN 'reasoning_error' THEN 'reasoning_error'
                WHEN 'time_pressure' THEN 'time_pressure'
                WHEN 'careless' THEN 'careless'
                WHEN 'concept_mistake' THEN 'concept_confusion'
                WHEN 'concept' THEN 'concept_confusion'
                WHEN 'calculation' THEN 'calculation_error'
                WHEN 'memory' THEN 'memory_error'
                WHEN 'method' THEN 'reasoning_error'
                WHEN 'logic' THEN 'reasoning_error'
                ELSE NULL
            END,
            CASE
                WHEN COALESCE(w.error_type, '') IN (
                    'knowledge_gap','concept_confusion','memory_error','calculation_error',
                    'misread','reasoning_error','time_pressure','careless',
                    'concept_mistake','concept','calculation','memory','method','logic'
                ) THEN COALESCE(w.updated_at, w.last_review_at, w.created_at, CURRENT_TIMESTAMP)
                ELSE NULL
            END,
            COALESCE(w.created_at, CURRENT_TIMESTAMP),
            COALESCE(w.updated_at, CURRENT_TIMESTAMP)
        FROM wrong_questions w
    """))


def downgrade() -> None:
    op.drop_table("wrong_question_error_diagnoses")
