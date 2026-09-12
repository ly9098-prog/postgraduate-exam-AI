"""Add subject_id FK column to questions and question_imports.

Revision ID: p5_4_subject_id_fk
Revises: p5_3_vector_schema
Create Date: 2026-06-29

Adds subject_id (Integer FK -> subjects.id) to both questions and question_imports.
Backfills existing rows by matching the legacy subject string against subjects.code
or subjects.name. Rows that cannot be matched are logged and left with subject_id=NULL.

The legacy subject string column is preserved for backward compatibility.
"""

import sqlalchemy as sa

from alembic import op

revision = "p5_4_subject_id_fk"
down_revision = "p5_3_vector_schema"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- 1. Add subject_id columns ---
    if _has_table(inspector, "questions") and not _has_column(inspector, "questions", "subject_id"):
        op.add_column("questions", sa.Column("subject_id", sa.Integer(), nullable=True))

    if _has_table(inspector, "question_imports") and not _has_column(inspector, "question_imports", "subject_id"):
        op.add_column("question_imports", sa.Column("subject_id", sa.Integer(), nullable=True))

    # Refresh inspector after adding columns
    inspector = sa.inspect(bind)

    # --- 2. Backfill: match old subject string -> subjects.id ---
    if _has_table(inspector, "subjects"):
        # Build a mapping: code -> id, name -> id from subjects table
        subjects_table = sa.table(
            "subjects",
            sa.column("id", sa.Integer()),
            sa.column("code", sa.String()),
            sa.column("name", sa.String()),
            sa.column("is_active", sa.Boolean()),
        )

        conn = op.get_bind()
        result = conn.execute(
            sa.select(
                subjects_table.c.id,
                subjects_table.c.code,
                subjects_table.c.name,
            ).where(subjects_table.c.is_active.is_(True))
        )
        rows = result.fetchall()

        code_to_id: dict[str, int] = {}
        name_to_id: dict[str, int] = {}
        for row in rows:
            code_to_id[row[1]] = row[0]  # code -> id
            name_to_id[row[2]] = row[0]  # name -> id

        # Backfill questions
        if _has_table(inspector, "questions") and _has_column(inspector, "questions", "subject_id"):
            questions_table = sa.table(
                "questions",
                sa.column("id", sa.Integer()),
                sa.column("subject", sa.String()),
                sa.column("subject_id", sa.Integer()),
            )
            q_result = conn.execute(
                sa.select(questions_table.c.id, questions_table.c.subject).where(
                    questions_table.c.subject_id.is_(None)
                )
            )
            unmatched_q = 0
            for q_row in q_result.fetchall():
                q_id, old_subject = q_row[0], q_row[1]
                matched_id = code_to_id.get(old_subject) or name_to_id.get(old_subject)
                if matched_id is not None:
                    conn.execute(
                        sa.update(questions_table)
                        .where(questions_table.c.id == q_id)
                        .values(subject_id=matched_id)
                    )
                else:
                    unmatched_q += 1
            if unmatched_q:
                print(f"[p5_4] WARNING: {unmatched_q} questions could not be matched to subjects table")

        # Backfill question_imports
        inspector = sa.inspect(bind)
        if _has_table(inspector, "question_imports") and _has_column(inspector, "question_imports", "subject_id"):
            qi_table = sa.table(
                "question_imports",
                sa.column("id", sa.Integer()),
                sa.column("subject", sa.String()),
                sa.column("subject_id", sa.Integer()),
            )
            qi_result = conn.execute(
                sa.select(qi_table.c.id, qi_table.c.subject).where(
                    qi_table.c.subject_id.is_(None),
                    qi_table.c.subject.isnot(None),
                    qi_table.c.subject != "",
                )
            )
            unmatched_qi = 0
            for qi_row in qi_result.fetchall():
                qi_id, old_subject = qi_row[0], qi_row[1]
                matched_id = code_to_id.get(old_subject) or name_to_id.get(old_subject)
                if matched_id is not None:
                    conn.execute(
                        sa.update(qi_table)
                        .where(qi_table.c.id == qi_id)
                        .values(subject_id=matched_id)
                    )
                else:
                    unmatched_qi += 1
            if unmatched_qi:
                print(f"[p5_4] WARNING: {unmatched_qi} question_imports could not be matched to subjects table")

    # --- 3. Create indexes on subject_id ---
    inspector = sa.inspect(bind)
    if _has_table(inspector, "questions") and _has_column(inspector, "questions", "subject_id"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("questions")}
        if "ix_questions_subject_id" not in existing_indexes:
            op.create_index("ix_questions_subject_id", "questions", ["subject_id"])

    if _has_table(inspector, "question_imports") and _has_column(inspector, "question_imports", "subject_id"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("question_imports")}
        if "ix_question_imports_subject_id" not in existing_indexes:
            op.create_index("ix_question_imports_subject_id", "question_imports", ["subject_id"])

    # --- 4. Add FK constraints (PostgreSQL only; skip on SQLite) ---
    if bind.dialect.name != "sqlite":
        # FK for questions.subject_id
        inspector = sa.inspect(bind)
        if _has_table(inspector, "questions") and _has_column(inspector, "questions", "subject_id"):
            existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("questions")}
            if "fk_questions_subject_id" not in existing_fks:
                op.create_foreign_key(
                    "fk_questions_subject_id",
                    "questions", "subjects",
                    ["subject_id"], ["id"],
                    ondelete="SET NULL",
                )

        # FK for question_imports.subject_id
        if _has_table(inspector, "question_imports") and _has_column(inspector, "question_imports", "subject_id"):
            existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("question_imports")}
            if "fk_question_imports_subject_id" not in existing_fks:
                op.create_foreign_key(
                    "fk_question_imports_subject_id",
                    "question_imports", "subjects",
                    ["subject_id"], ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop FK constraints first (PostgreSQL only)
    if bind.dialect.name != "sqlite":
        if _has_table(inspector, "question_imports"):
            existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("question_imports")}
            if "fk_question_imports_subject_id" in existing_fks:
                op.drop_constraint("fk_question_imports_subject_id", "question_imports", type_="foreignkey")

        if _has_table(inspector, "questions"):
            existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("questions")}
            if "fk_questions_subject_id" in existing_fks:
                op.drop_constraint("fk_questions_subject_id", "questions", type_="foreignkey")

    # Drop indexes
    inspector = sa.inspect(bind)
    if _has_table(inspector, "question_imports"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("question_imports")}
        if "ix_question_imports_subject_id" in existing_indexes:
            op.drop_index("ix_question_imports_subject_id", table_name="question_imports")

    if _has_table(inspector, "questions"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("questions")}
        if "ix_questions_subject_id" in existing_indexes:
            op.drop_index("ix_questions_subject_id", table_name="questions")

    # Drop columns
    inspector = sa.inspect(bind)
    if _has_table(inspector, "question_imports") and _has_column(inspector, "question_imports", "subject_id"):
        op.drop_column("question_imports", "subject_id")

    if _has_table(inspector, "questions") and _has_column(inspector, "questions", "subject_id"):
        op.drop_column("questions", "subject_id")
