"""Explicit indexes retained from the historical Alembic schema.

Many of these predate SQLAlchemy's current automatic ``ix_<table>_<column>``
naming.  Registering them in metadata keeps autogenerate authoritative without
renaming or dropping proven production indexes.
"""

from __future__ import annotations

from sqlalchemy import Index, text

from app.core.database import Base

_RENAME_INDEXES = {
    "ix_knowledge_edges_source_knowledge_point_id": "ix_knowledge_edges_source_kp",
    "ix_knowledge_edges_target_knowledge_point_id": "ix_knowledge_edges_target_kp",
    "ix_question_knowledge_points_knowledge_point_id": "ix_qkp_knowledge_point_id",
    "ix_question_knowledge_points_question_id": "ix_qkp_question_id",
    "ix_question_version_knowledge_points_syllabus_knowledge_point_id": "ix_qvkp_syllabus_kp_id",
    "ix_recommendation_experiment_assignments_experiment_id": "ix_rea_experiment_id",
    "ix_recommendation_experiment_assignments_strategy": "ix_rea_strategy",
    "ix_recommendation_experiment_assignments_user_id": "ix_rea_user_id",
    "ix_recommendation_experiment_assignments_variant_key": "ix_rea_variant_key",
    "ix_recommendation_metrics_daily_date": "ix_rmd_date",
    "ix_recommendation_metrics_daily_scene": "ix_rmd_scene",
    "ix_recommendation_metrics_daily_strategy": "ix_rmd_strategy",
    "ix_syllabus_knowledge_point_mappings_from_syllabus_knowledge_point_id": "ix_syllabus_kp_mappings_from_kp_id",
    "ix_syllabus_knowledge_point_mappings_to_syllabus_knowledge_point_id": "ix_syllabus_kp_mappings_to_kp_id",
    "ix_user_knowledge_adaptive_state_knowledge_point_id": "ix_ukas_kp_id",
    "ix_user_knowledge_adaptive_state_user_id": "ix_ukas_user_id",
    "ix_user_knowledge_states_knowledge_point_id": "ix_uks_knowledge_point_id",
    "ix_user_knowledge_states_user_id": "ix_uks_user_id",
    "ix_user_question_difficulty_state_question_id": "ix_uqds_question_id",
    "ix_user_question_difficulty_state_user_id": "ix_uqds_user_id",
    "ix_user_question_state_question_id": "idx_user_question_state_question_id",
    "ix_user_question_state_user_id": "idx_user_question_state_user_id",
}

# name -> (table, columns, options).  All are intentional query indexes present
# in the migration chain and are not duplicates of a unique/primary index.
_INDEXES = {
    "idx_answer_behavior_user_date": ("answer_behaviors", ("user_id", "created_at"), {}),
    "idx_audit_logs_resource": ("audit_logs", ("resource_type", "resource_id"), {}),
    "ix_export_tasks_status_created": ("export_tasks", ("status", "created_at"), {}),
    "ix_export_tasks_user_status": ("export_tasks", ("user_id", "status"), {}),
    "ix_formula_cards_exam_study_type_status": (
        "formula_cards", ("exam_scope", "study_card_type", "status"), {}
    ),
    "ix_import_batch_jobs_execution_status": ("import_batch_jobs", ("execution_status",), {}),
    "ix_import_batch_jobs_request_id": ("import_batch_jobs", ("request_id",), {"unique": True}),
    "ix_import_batch_jobs_subject_id": ("import_batch_jobs", ("subject_id",), {}),
    "ix_import_pipelines_created_by_status": ("import_pipelines", ("created_by", "status"), {}),
    "ix_import_pipelines_execution_status": ("import_pipelines", ("execution_status",), {}),
    "idx_pr_user_question": ("practice_records", ("user_id", "question_id"), {}),
    "idx_practice_records_user_date": ("practice_records", ("user_id", "answered_at"), {}),
    "ix_practice_records_user_created": ("practice_records", ("user_id", "created_at"), {}),
    "ix_question_imports_question_id": ("question_imports", ("question_id",), {}),
    "idx_qkp_knowledge_point_question": (
        "question_knowledge_points", ("knowledge_point_id", "question_id"), {}
    ),
    "idx_questions_subject_id_active": (
        "questions",
        ("subject_id", "is_active"),
        {
            "postgresql_where": text("is_active = true"),
            "sqlite_where": text("is_active = 1"),
        },
    ),
    "ix_questions_import_batch_id": ("questions", ("import_batch_id",), {}),
    "ix_questions_review_status_is_active": (
        "questions", ("review_status", "is_active"), {}
    ),
    "ix_rl_created_at": ("recommendation_logs", ("created_at",), {}),
    "ix_rl_shown_at": ("recommendation_logs", ("shown_at",), {}),
    "ix_rl_shown_at_subject_scene_strategy": (
        "recommendation_logs", ("shown_at", "subject_id", "scene", "strategy"), {}
    ),
    "ix_rl_user_request": ("recommendation_logs", ("user_id", "request_id"), {}),
    "ix_rl_user_scene_created": (
        "recommendation_logs", ("user_id", "scene", "created_at"), {}
    ),
    "ix_review_records_user_reviewed": ("review_records", ("user_id", "reviewed_at"), {}),
    "ix_review_schedules_user_next_review": (
        "review_schedules", ("user_id", "next_review_at"), {}
    ),
    "idx_uks_user_mastery": ("user_knowledge_states", ("user_id", "mastery_score"), {}),
    "idx_uks_user_mastery_conf": (
        "user_knowledge_states", ("user_id", "mastery_score", "confidence"), {}
    ),
    "idx_uqs_user_box": ("user_question_state", ("user_id", "box_level"), {}),
    "ix_users_is_banned": ("users", ("is_banned",), {}),
    "ix_wq_user_active_created": (
        "wrong_questions",
        ("user_id", "is_active", "created_at_desc"),
        {},
    ),
    "ix_wq_user_mastered": ("wrong_questions", ("user_id", "mastered"), {}),
    "ix_wq_user_review_count": (
        "wrong_questions",
        ("user_id", "review_count"),
        {
            "postgresql_where": text("is_active = true AND mastered = false"),
            "sqlite_where": text("is_active = 1 AND mastered = 0"),
        },
    ),
}


def register_schema_contract() -> None:
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            replacement = _RENAME_INDEXES.get(index.name)
            if replacement:
                index.name = replacement

    for name, (table_name, column_names, options) in _INDEXES.items():
        table = Base.metadata.tables[table_name]
        if any(index.name == name for index in table.indexes):
            continue
        expressions = []
        for column_name in column_names:
            if column_name == "created_at_desc":
                expressions.append(table.c.created_at.desc())
            else:
                expressions.append(table.c[column_name])
        Index(name, *expressions, **options)
