"""Add subject_id FK to question_embeddings, drop legacy subject column.

Revision ID: b2c3d4e5f6a7
Revises: a7b8c9d0e1f2
Create Date: 2026-08-03

question_embeddings (the mini-program smart-recommendation vector table) still
carries a string `subject` column holding subject *codes* (plus a few legacy
codes: exam408, exam408-os).  This migration:

  1. adds subject_id -> subjects.id
  2. backfills subject_id from questions.subject_id (relation) with legacy
     alias resolution fallback against the live subjects table
  3. adds fk_question_embeddings_subject_id (guarded against pre-existence)
  4. enforces NOT NULL on subject_id
  5. drops the legacy subject column (auto-drops ix_question_embeddings_subject)
  6. adds ix_question_embeddings_subject_id

Production data audit (2026-08-03): 1695 rows, 0 empty subject, 0 orphan
question_id.  All six distinct subject values resolve and agree with
questions.subject_id:

    ds(587)->ds, os(556)->os, co(524)->co, computer(18)->computer,
    exam408(7)->computer (alias), exam408-os(3)->os (alias)

Backfill precedence mirrors a7b8c9d0e1f2: relation-derived (question -> subject)
wins; the legacy value is used only when the question row is absent or has no
subject_id.  A disagreement between the two aborts the migration; an
unresolvable subject aborts too (subject_id is NOT NULL).

PostgreSQL-only in practice: p5_3_vector_schema creates the table only when
pgvector is available, so on other dialects the table does not exist and this
migration is a no-op.
"""

import sqlalchemy as sa

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None

# Legacy string aliases -> canonical subjects.code (spec §5.2, mirrors a7b8c9d0e1f2).
_ALIAS_TO_CODE = {
    "math": "math", "math2": "math", "数学": "math", "数学二": "math",
    "computer": "computer", "exam408": "computer", "408": "computer",
    "计算机": "computer", "408计算机综合": "computer",
    "english": "english", "英语": "english",
    "politics": "politics", "pol": "politics", "political": "politics", "政治": "politics",
    "advanced_math": "advanced_math", "calculus": "advanced_math",
    "math2-calculus": "advanced_math", "高数": "advanced_math", "高等数学": "advanced_math",
    "linear_algebra": "linear_algebra", "linalg": "linear_algebra",
    "math2-linalg": "linear_algebra", "线代": "linear_algebra", "线性代数": "linear_algebra",
    "ds": "ds", "data_structure": "ds", "exam408-ds": "ds", "数据结构": "ds",
    "co": "co", "computer_organization": "co", "exam408-co": "co",
    "组成原理": "co", "计算机组成原理": "co",
    "os": "os", "operating_system": "os", "exam408-os": "os", "操作系统": "os",
    "cn": "cn", "computer_network": "cn", "exam408-cn": "cn",
    "计网": "cn", "计算机网络": "cn",
}


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


class _Resolver:
    """Resolve legacy subject strings to subject ids from the live subjects table.

    Same chain as app/models/subject_resolver.py: exact subjects.code -> exact
    subjects.name -> legacy alias map -> canonical code.
    """

    def __init__(self, bind):
        self.code_to_id = {}
        self.name_to_id = {}
        subjects = sa.table(
            "subjects",
            sa.column("id", sa.Integer()),
            sa.column("code", sa.String()),
            sa.column("name", sa.String()),
        )
        for row in bind.execute(
            sa.select(subjects.c.id, subjects.c.code, subjects.c.name)
        ):
            self.code_to_id[row[1]] = row[0]
            if row[2]:
                self.name_to_id[row[2]] = row[0]

    def resolve(self, value):
        raw = (value or "").strip()
        if not raw:
            return None
        if raw in self.code_to_id:
            return self.code_to_id[raw]
        if raw in self.name_to_id:
            return self.name_to_id[raw]
        code = _ALIAS_TO_CODE.get(raw.lower())
        if code is None:
            return None
        return self.code_to_id.get(code)


def _fk_name(inspector, table: str) -> str | None:
    for fk in inspector.get_foreign_keys(table):
        cols = fk.get("constrained_columns") or []
        if "subject_id" in cols and fk.get("referred_table") == "subjects":
            return fk["name"]
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "question_embeddings"):
        return
    if not _has_column(inspector, "question_embeddings", "subject"):
        return  # already migrated

    resolver = _Resolver(bind)
    conn = bind

    # ======================= 1. add subject_id column =======================
    if not _has_column(inspector, "question_embeddings", "subject_id"):
        op.add_column(
            "question_embeddings",
            sa.Column("subject_id", sa.Integer(), nullable=True),
        )
    inspector = sa.inspect(bind)

    # ======================= 2. backfill =======================
    t = sa.table(
        "question_embeddings",
        sa.column("id", sa.Integer()),
        sa.column("question_id", sa.Integer()),
        sa.column("subject", sa.String()),
        sa.column("subject_id", sa.Integer()),
    )
    questions = sa.table(
        "questions",
        sa.column("id", sa.Integer()),
        sa.column("subject_id", sa.Integer()),
    )
    rows = conn.execute(sa.select(t.c.id, t.c.question_id, t.c.subject)).fetchall()

    conflicts, unmatched = [], []
    for rid, qid, legacy in rows:
        rel_id = None
        if qid is not None:
            qrow = conn.execute(
                sa.select(questions.c.subject_id).where(questions.c.id == qid)
            ).fetchone()
            if qrow and qrow[0] is not None:
                rel_id = int(qrow[0])
        alias_id = resolver.resolve(legacy)
        if rel_id is not None and alias_id is not None and rel_id != alias_id:
            conflicts.append((rid, legacy, rel_id, alias_id))
            continue
        sid = rel_id if rel_id is not None else alias_id
        if sid is None:
            unmatched.append((rid, legacy))
            continue
        conn.execute(sa.update(t).where(t.c.id == rid).values(subject_id=sid))

    if conflicts:
        raise Exception(
            f"[b2c3d4e5f6a7] question_embeddings backfill conflict: "
            f"question relation vs subject alias disagree: {conflicts}"
        )
    if unmatched:
        raise Exception(
            f"[b2c3d4e5f6a7] question_embeddings: required subject could not "
            f"be resolved for rows: {unmatched}"
        )

    inspector = sa.inspect(bind)

    # ======================= 3. FK + NOT NULL + drop subject + index =======================
    # Drop the plain btree index on `subject` explicitly (defensive; Postgres
    # would auto-drop it with the column).  No UNIQUE constraint references
    # `subject` on this table, so DROP COLUMN is safe on Postgres.
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_question_embeddings_subject"))

    fk_exists = _fk_name(inspector, "question_embeddings") is not None
    existing = {i["name"] for i in inspector.get_indexes("question_embeddings")}
    with op.batch_alter_table("question_embeddings", recreate="auto") as batch_op:
        batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
        if not fk_exists:
            batch_op.create_foreign_key(
                "fk_question_embeddings_subject_id",
                "subjects",
                ["subject_id"],
                ["id"],
                ondelete="NO ACTION",
            )
        batch_op.drop_column("subject")
        if "ix_question_embeddings_subject_id" not in existing:
            batch_op.create_index("ix_question_embeddings_subject_id", ["subject_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, "question_embeddings"):
        return
    if _has_column(inspector, "question_embeddings", "subject") or not _has_column(
        inspector, "question_embeddings", "subject_id"
    ):
        return
    conn = op.get_bind()

    op.add_column("question_embeddings", sa.Column("subject", sa.String(32), nullable=True))
    conn.execute(sa.text(
        "UPDATE question_embeddings SET subject = "
        "(SELECT code FROM subjects WHERE subjects.id = question_embeddings.subject_id) "
        "WHERE subject_id IS NOT NULL"
    ))

    inspector = sa.inspect(op.get_bind())
    fk_name = _fk_name(inspector, "question_embeddings")
    with op.batch_alter_table("question_embeddings", recreate="auto") as batch_op:
        if fk_name:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
        batch_op.alter_column("subject", existing_type=sa.String(32), nullable=False)
        batch_op.drop_index("ix_question_embeddings_subject_id")
        batch_op.drop_column("subject_id")
        batch_op.create_index("ix_question_embeddings_subject", ["subject"])
