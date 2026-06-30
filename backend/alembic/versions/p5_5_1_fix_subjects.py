"""Fix subjects table codes and backfill subject_id.

Revision ID: p5_5_1_fix_subjects
Revises: p5_5_vector_config
Create Date: 2026-06-30

Root cause:
- subjects table was seeded with wrong codes (math, la, ds, cn, co, os, pol, eng)
  that don't match frontend expectations (math2, exam408, exam408-ds, etc.)
- No parent-child hierarchy (all level 1, no exam408/math2 parents)
- questions.subject_id and question_imports.subject_id are NULL because
  the p5_4 backfill ran against the wrong codes

This migration:
1. Clears subjects table and re-seeds with correct codes + hierarchy
2. Backfills questions.subject_id from legacy subject column
3. Backfills question_imports.subject_id from legacy subject column
"""

from alembic import op
import sqlalchemy as sa


revision = "p5_5_1_fix_subjects"
down_revision = "p5_5_vector_config"
branch_labels = None
depends_on = None


# Correct subject hierarchy matching frontend expectations
SUBJECTS_SEED = [
    # (id, parent_id, code, name, level, path, sort_order)
    (1, None, "math2", "数学二", 1, "math2", 1),
    (2, 1, "math2-calculus", "高等数学", 2, "math2>math2-calculus", 1),
    (3, 1, "math2-linalg", "线性代数", 2, "math2>math2-linalg", 2),
    (4, None, "exam408", "408计算机综合", 1, "exam408", 2),
    (5, 4, "exam408-ds", "数据结构", 2, "exam408>exam408-ds", 1),
    (6, 4, "exam408-os", "操作系统", 2, "exam408>exam408-os", 2),
    (7, 4, "exam408-co", "计算机组成原理", 2, "exam408>exam408-co", 3),
    (8, 4, "exam408-cn", "计算机网络", 2, "exam408>exam408-cn", 4),
    (9, None, "english", "英语", 1, "english", 3),
    (10, None, "pol", "政治", 1, "pol", 4),
]


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "subjects"):
        return

    subjects_table = sa.table(
        "subjects",
        sa.column("id", sa.Integer()),
        sa.column("parent_id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("level", sa.SmallInteger()),
        sa.column("path", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )

    # Step 1: Clear existing subjects (FK columns are nullable, so no cascade issues)
    bind.execute(subjects_table.delete())

    # Step 2: Insert correct subjects
    for sid, parent_id, code, name, level, path, sort_order in SUBJECTS_SEED:
        bind.execute(
            subjects_table.insert().values(
                id=sid,
                parent_id=parent_id,
                code=code,
                name=name,
                level=level,
                path=path,
                sort_order=sort_order,
                is_active=True,
            )
        )

    # Step 3: Backfill questions.subject_id from legacy subject column
    inspector = sa.inspect(bind)
    if _has_table(inspector, "questions") and _has_column(inspector, "questions", "subject"):
        if _has_column(inspector, "questions", "subject_id"):
            q_table = sa.table(
                "questions",
                sa.column("id", sa.Integer()),
                sa.column("subject", sa.String()),
                sa.column("subject_id", sa.Integer()),
            )
            # Build code -> id map
            code_to_id = {s[2]: s[0] for s in SUBJECTS_SEED}  # code is index 2

            q_result = bind.execute(
                sa.select(q_table.c.id, q_table.c.subject).where(
                    q_table.c.subject_id.is_(None),
                    q_table.c.subject.isnot(None),
                    q_table.c.subject != "",
                )
            )
            matched = 0
            unmatched = 0
            for q_row in q_result.fetchall():
                q_id, old_subject = q_row[0], q_row[1]
                sid = code_to_id.get(old_subject)
                if sid is not None:
                    bind.execute(
                        sa.update(q_table)
                        .where(q_table.c.id == q_id)
                        .values(subject_id=sid)
                    )
                    matched += 1
                else:
                    unmatched += 1
            if matched:
                print(f"[p5_5_1] Backfilled {matched} questions.subject_id")
            if unmatched:
                print(f"[p5_5_1] WARNING: {unmatched} questions could not be matched")

    # Step 4: Backfill question_imports.subject_id from legacy subject column
    inspector = sa.inspect(bind)
    if _has_table(inspector, "question_imports") and _has_column(inspector, "question_imports", "subject"):
        if _has_column(inspector, "question_imports", "subject_id"):
            qi_table = sa.table(
                "question_imports",
                sa.column("id", sa.Integer()),
                sa.column("subject", sa.String()),
                sa.column("subject_id", sa.Integer()),
            )
            code_to_id = {s[2]: s[0] for s in SUBJECTS_SEED}

            qi_result = bind.execute(
                sa.select(qi_table.c.id, qi_table.c.subject).where(
                    qi_table.c.subject_id.is_(None),
                    qi_table.c.subject.isnot(None),
                    qi_table.c.subject != "",
                )
            )
            matched = 0
            unmatched = 0
            for qi_row in qi_result.fetchall():
                qi_id, old_subject = qi_row[0], qi_row[1]
                sid = code_to_id.get(old_subject)
                if sid is not None:
                    bind.execute(
                        sa.update(qi_table)
                        .where(qi_table.c.id == qi_id)
                        .values(subject_id=sid)
                    )
                    matched += 1
                else:
                    unmatched += 1
            if matched:
                print(f"[p5_5_1] Backfilled {matched} question_imports.subject_id")
            if unmatched:
                print(f"[p5_5_1] WARNING: {unmatched} question_imports could not be matched")


def downgrade() -> None:
    """Cannot reliably restore the old wrong subjects. Just clear and let user re-seed."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "subjects"):
        subjects_table = sa.table("subjects")
        bind.execute(subjects_table.delete())
