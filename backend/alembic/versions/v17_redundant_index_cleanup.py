"""v17: remove exact duplicate indexes while preserving unique enforcement."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "v17_redundant_index_cleanup"
down_revision = "v16_schema_contract_alignment"
branch_labels = None
depends_on = None

_REDUNDANT_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("admin_users", "ix_admin_users_username", ("username",)),
    ("permissions", "ix_permissions_name", ("name",)),
    ("roles", "ix_roles_name", ("name",)),
    ("subjects", "ix_subjects_code", ("code",)),
    ("wrong_questions", "idx_wrong_questions_user_question", ("user_id", "question_id")),
    ("app_user_admin_bindings", "ix_app_user_admin_bindings_user_id", ("user_id",)),
    ("app_user_admin_bindings", "ix_app_user_admin_bindings_admin_user_id", ("admin_user_id",)),
    ("ocr_jobs", "ix_ocr_jobs_request_id", ("request_id",)),
    ("question_knowledge_points", "ix_qkp_question_position", ("question_id", "position")),
    ("recommendation_experiments", "ix_recommendation_experiments_name", ("name",)),
    ("recommendation_strategy_configs", "ix_recommendation_strategy_configs_name", ("name",)),
    ("user_question_state", "idx_user_question_state_user_question", ("user_id", "question_id")),
    ("user_question_state", "idx_uqs_user_next_review", ("user_id", "next_review_at")),
    ("user_question_state", "idx_user_question_state_user_next_review", ("user_id", "next_review_at")),
    ("exam_paper_questions", "ix_exam_paper_questions_paper_position", ("paper_id", "position")),
    ("exam_answers", "ix_exam_answers_attempt_item", ("attempt_id", "exam_paper_question_id")),
    ("exam_answers", "ix_exam_answers_practice_record_id", ("practice_record_id",)),
    ("wrong_question_error_diagnoses", "ix_wrong_question_error_diagnoses_practice_record_id", ("practice_record_id",)),
    ("wrong_question_error_diagnoses", "ix_wrong_question_error_diagnoses_exam_answer_id", ("exam_answer_id",)),
    ("syllabus_versions", "ix_syllabus_versions_code", ("code",)),
    ("study_plans", "ix_study_plans_user_id", ("user_id",)),
    ("study_plan_days", "ix_study_plan_days_plan_date", ("plan_id", "plan_date")),
)


def _index_names(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    for table, name, _columns in _REDUNDANT_INDEXES:
        if name in _index_names(table):
            op.drop_index(name, table_name=table)

    for table, name, columns in (
        ("exam_answers", "ix_exam_answers_revision", ("id", "answer_revision")),
        (
            "recommendation_metrics_daily",
            "ix_recommendation_metrics_daily_variant_key",
            ("variant_key",),
        ),
    ):
        if name not in _index_names(table):
            op.create_index(name, table, list(columns), unique=False)


def downgrade() -> None:
    for table, name in (
        ("exam_answers", "ix_exam_answers_revision"),
        ("recommendation_metrics_daily", "ix_recommendation_metrics_daily_variant_key"),
    ):
        if name in _index_names(table):
            op.drop_index(name, table_name=table)

    for table, name, columns in _REDUNDANT_INDEXES:
        if name not in _index_names(table):
            op.create_index(name, table, list(columns), unique=False)
