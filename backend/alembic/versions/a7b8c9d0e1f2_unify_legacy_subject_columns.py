"""Unify legacy string `subject` columns to `subject_id -> subjects.id`.

Revision ID: a7b8c9d0e1f2
Revises: c9d8e7f6a5b4
Create Date: 2026-08-02

Business tables that still carry a string `subject` column as subject identifier
are migrated to a real `subject_id` foreign key:

    answer_behaviors
    practice_records
    review_schedules
    knowledge_points
    knowledge_edges
    recommendation_logs
    recommendation_metrics_daily
    tags
    user_knowledge_states

Data backfill precedence (per task spec):
  1. Existing subject_id (none on these tables yet).
  2. Derive from relations (question_id -> questions.subject_id, etc.).
  3. Legacy string alias mapping against the current `subjects` table
     (no hardcoded subject ids — ids are resolved through subjects.code).

Conflict / unmatched handling:
  * relation-derived id disagrees with alias-derived id  -> abort
  * required (NOT NULL) field with no resolvable source  -> abort
  * originally-nullable field with no resolvable source  -> keep NULL + report

Known data exception (audited, user-approved 2026-08-02):
  5 practice_records have subject='' and question_id pointing at questions that
  were deleted when the question set was replaced by the co/os import.  Backups
  (postgraduate.db.repair_bak_20260729) show the entire pre-import question set
  (ids 1..565) was subject_id=9 (os), and every other practice_record referencing
  those old ids carries subject='os'.  These 5 rows are therefore resolved as os
  (looked up through subjects.code='os', never hardcoded as 9).

Also adds the missing real SQLite foreign keys on tables that already carried
subject_id (questions, question_imports, pomodoro_sessions).
"""

from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "c9d8e7f6a5b4"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


# Legacy string aliases -> canonical subjects.code (spec §5.2).
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


class _Resolver:
    """Resolve legacy subject strings to subject ids from the live subjects table.

    Mirrors the runtime chain in app/models/subject_resolver.py
    (resolve_subject_id_from_legacy): exact subjects.code match -> exact
    subjects.name match -> legacy alias map -> canonical code.  Keeping the two
    aligned means a legacy value the app accepts can never make the migration
    abort with an "unresolved subject" error on a fresh database.
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


# ---------------------------------------------------------------------------
# actual migration
# ---------------------------------------------------------------------------

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    resolver = _Resolver(bind)

    # ======================= 0. add subject_id columns =======================
    for table in (
        "answer_behaviors", "practice_records", "review_schedules",
        "knowledge_points", "knowledge_edges", "recommendation_logs",
        "recommendation_metrics_daily", "tags", "user_knowledge_states",
    ):
        if _has_table(inspector, table) and not _has_column(inspector, table, "subject_id"):
            op.add_column(table, sa.Column("subject_id", sa.Integer(), nullable=True))
    inspector = sa.inspect(bind)

    # ======================= 1. backfill legacy tables =======================
    _backfill_practice_records(bind, resolver)
    _backfill_answer_behaviors(bind, resolver)
    _backfill_review_schedules(bind, resolver)
    _backfill_knowledge_points(bind, resolver)
    _backfill_knowledge_edges(bind, resolver)
    _backfill_recommendation_logs(bind, resolver)
    _backfill_recommendation_metrics_daily(bind, resolver)
    _backfill_tags(bind, resolver)
    _backfill_user_knowledge_states(bind, resolver)

    inspector = sa.inspect(bind)

    # ======================= 2. rebuild tables =======================
    _rebuild_answer_behaviors(inspector)
    _rebuild_practice_records(inspector)
    _rebuild_review_schedules(inspector)
    _rebuild_knowledge_points(inspector)
    _rebuild_knowledge_edges(inspector)
    _rebuild_recommendation_logs(inspector)
    _rebuild_recommendation_metrics_daily(inspector)
    _rebuild_tags(inspector)
    _rebuild_user_knowledge_states(inspector)

    inspector = sa.inspect(bind)

    # ======================= 3. real FK on already-migrated tables =======================
    _add_real_fk_questions(inspector)
    _add_real_fk_question_imports(inspector)
    _add_real_fk_pomodoro(inspector)


# --- backfill implementations ---

def _backfill_practice_records(bind, resolver):
    if not _has_table(sa.inspect(bind), "practice_records"):
        return
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "practice_records", "subject"):
        return
    conn = bind
    t = sa.table("practice_records",
                 sa.column("id", sa.Integer()),
                 sa.column("question_id", sa.Integer()),
                 sa.column("subject", sa.String()),
                 sa.column("subject_id", sa.Integer()))
    questions = sa.table("questions",
                         sa.column("id", sa.Integer()),
                         sa.column("subject_id", sa.Integer()))
    rows = conn.execute(sa.select(t.c.id, t.c.question_id, t.c.subject)).fetchall()

    conflicts, unmatched = [], []
    for rid, qid, legacy in rows:
        qrow = None
        rel_id = None
        if qid is not None:
            qrow = conn.execute(
                sa.select(questions.c.subject_id).where(questions.c.id == qid)
            ).fetchone()
            rel_id = int(qrow[0]) if qrow and qrow[0] is not None else None
        alias_id = resolver.resolve(legacy)
        # Only the audited exception qualifies: an empty subject whose question
        # row no longer exists (question set replaced by the co/os import).
        # A present question with a NULL subject is a data problem, not a reason
        # to blanket-assign os.
        empty_fallback = (
            legacy in ("", None) and qid is not None and qrow is None
        )

        if empty_fallback:
            alias_id = resolver.resolve("os")  # audited evidence (see module docstring)

        if rel_id is not None and alias_id is not None and rel_id != alias_id:
            conflicts.append((rid, legacy, rel_id, alias_id))
            continue
        sid = rel_id if rel_id is not None else alias_id
        if sid is None:
            unmatched.append((rid, legacy))
            continue
        conn.execute(
            sa.update(t).where(t.c.id == rid).values(subject_id=sid)
        )
        if empty_fallback:
            print(f"[a7b8c9d0e1f2] practice_records id={rid} empty subject -> os (evidence-based)")
        elif rel_id is not None:
            print(f"[a7b8c9d0e1f2] practice_records id={rid} mapped via question relation -> subject_id={sid}")
        else:
            print(f"[a7b8c9d0e1f2] practice_records id={rid} mapped via alias '{legacy}' -> subject_id={sid}")

    if conflicts:
        raise Exception(
            f"[a7b8c9d0e1f2] practice_records backfill conflict: "
            f"relation vs alias disagree: {conflicts}"
        )
    if unmatched:
        raise Exception(
            f"[a7b8c9d0e1f2] practice_records: required subject could not be "
            f"resolved for rows: {unmatched}"
        )


def _backfill_answer_behaviors(bind, resolver):
    if not _has_table(sa.inspect(bind), "answer_behaviors"):
        return
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "answer_behaviors", "subject"):
        return
    conn = bind
    t = sa.table("answer_behaviors",
                 sa.column("id", sa.Integer()),
                 sa.column("question_id", sa.Integer()),
                 sa.column("practice_record_id", sa.Integer()),
                 sa.column("subject", sa.String()),
                 sa.column("subject_id", sa.Integer()))
    questions = sa.table("questions", sa.column("id", sa.Integer()), sa.column("subject_id", sa.Integer()))
    pr = sa.table("practice_records", sa.column("id", sa.Integer()), sa.column("subject", sa.String()))
    rows = conn.execute(sa.select(t.c.id, t.c.question_id, t.c.practice_record_id, t.c.subject)).fetchall()

    conflicts, unmatched = [], []
    for rid, qid, prid, legacy in rows:
        rel_id = None
        if qid is not None:
            qrow = conn.execute(sa.select(questions.c.subject_id).where(questions.c.id == qid)).fetchone()
            if qrow and qrow[0] is not None:
                rel_id = int(qrow[0])
        if rel_id is None and prid is not None:
            prow = conn.execute(sa.select(pr.c.subject).where(pr.c.id == prid)).fetchone()
            if prow and prow[0]:
                rel_id = resolver.resolve(prow[0])
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
        raise Exception(f"[a7b8c9d0e1f2] answer_behaviors backfill conflict: {conflicts}")
    # answer_behaviors.subject is nullable -> unmatched stay NULL
    if unmatched:
        print(f"[a7b8c9d0e1f2] answer_behaviors kept NULL subject_id (nullable) for rows: {unmatched}")


def _backfill_review_schedules(bind, resolver):
    if not _has_table(sa.inspect(bind), "review_schedules"):
        return
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "review_schedules", "subject"):
        return
    conn = bind
    t = sa.table("review_schedules",
                 sa.column("id", sa.Integer()),
                 sa.column("question_id", sa.Integer()),
                 sa.column("subject", sa.String()),
                 sa.column("subject_id", sa.Integer()))
    questions = sa.table("questions", sa.column("id", sa.Integer()), sa.column("subject_id", sa.Integer()))
    rows = conn.execute(sa.select(t.c.id, t.c.question_id, t.c.subject)).fetchall()

    conflicts, unmatched = [], []
    for rid, qid, legacy in rows:
        rel_id = None
        if qid is not None:
            qrow = conn.execute(sa.select(questions.c.subject_id).where(questions.c.id == qid)).fetchone()
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
        raise Exception(f"[a7b8c9d0e1f2] review_schedules backfill conflict: {conflicts}")
    if unmatched:
        print(f"[a7b8c9d0e1f2] review_schedules kept NULL subject_id (nullable) for rows: {unmatched}")


def _backfill_knowledge_points(bind, resolver):
    if not _has_table(sa.inspect(bind), "knowledge_points"):
        return
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "knowledge_points", "subject"):
        return
    conn = bind
    t = sa.table("knowledge_points",
                 sa.column("id", sa.Integer()),
                 sa.column("subject", sa.String()),
                 sa.column("subject_id", sa.Integer()))
    rows = conn.execute(sa.select(t.c.id, t.c.subject)).fetchall()
    unmatched = []
    for rid, legacy in rows:
        sid = resolver.resolve(legacy)
        if sid is None:
            unmatched.append((rid, legacy))
            continue
        conn.execute(sa.update(t).where(t.c.id == rid).values(subject_id=sid))
    if unmatched:
        raise Exception(f"[a7b8c9d0e1f2] knowledge_points: required subject unresolved: {unmatched}")


def _backfill_knowledge_edges(bind, resolver):
    if not _has_table(sa.inspect(bind), "knowledge_edges"):
        return
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "knowledge_edges", "subject"):
        return
    conn = bind
    t = sa.table("knowledge_edges",
                 sa.column("id", sa.Integer()),
                 sa.column("source_knowledge_point_id", sa.Integer()),
                 sa.column("target_knowledge_point_id", sa.Integer()),
                 sa.column("subject", sa.String()),
                 sa.column("subject_id", sa.Integer()))
    kp = sa.table("knowledge_points", sa.column("id", sa.Integer()), sa.column("subject_id", sa.Integer()))
    rows = conn.execute(
        sa.select(t.c.id, t.c.source_knowledge_point_id, t.c.target_knowledge_point_id, t.c.subject)
    ).fetchall()
    conflicts, unmatched = [], []
    for rid, src, tgt, legacy in rows:
        src_id = dst_id = None
        for kp_id in (src, tgt):
            if kp_id is not None:
                krow = conn.execute(sa.select(kp.c.subject_id).where(kp.c.id == kp_id)).fetchone()
                if krow and krow[0] is not None:
                    if src_id is None:
                        src_id = int(krow[0])
                    else:
                        dst_id = int(krow[0])
        alias_id = resolver.resolve(legacy)
        if src_id is not None and dst_id is not None and src_id != dst_id:
            raise Exception(
                f"[a7b8c9d0e1f2] knowledge_edges id={rid}: source/target kp subject disagree "
                f"({src_id} vs {dst_id})"
            )
        rel_id = src_id if src_id is not None else dst_id
        if rel_id is not None and alias_id is not None and rel_id != alias_id:
            conflicts.append((rid, legacy, rel_id, alias_id))
            continue
        sid = rel_id if rel_id is not None else alias_id
        if sid is None:
            unmatched.append((rid, legacy))
            continue
        conn.execute(sa.update(t).where(t.c.id == rid).values(subject_id=sid))
    if conflicts:
        raise Exception(f"[a7b8c9d0e1f2] knowledge_edges backfill conflict: {conflicts}")
    if unmatched:
        raise Exception(f"[a7b8c9d0e1f2] knowledge_edges: required subject unresolved: {unmatched}")


def _backfill_recommendation_logs(bind, resolver):
    if not _has_table(sa.inspect(bind), "recommendation_logs"):
        return
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "recommendation_logs", "subject"):
        return
    conn = bind
    t = sa.table("recommendation_logs",
                 sa.column("id", sa.Integer()),
                 sa.column("question_id", sa.Integer()),
                 sa.column("subject", sa.String()),
                 sa.column("subject_id", sa.Integer()))
    questions = sa.table("questions", sa.column("id", sa.Integer()), sa.column("subject_id", sa.Integer()))
    rows = conn.execute(sa.select(t.c.id, t.c.question_id, t.c.subject)).fetchall()
    conflicts, unmatched = [], []
    for rid, qid, legacy in rows:
        rel_id = None
        if qid is not None:
            qrow = conn.execute(sa.select(questions.c.subject_id).where(questions.c.id == qid)).fetchone()
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
        raise Exception(f"[a7b8c9d0e1f2] recommendation_logs backfill conflict: {conflicts}")
    if unmatched:
        raise Exception(f"[a7b8c9d0e1f2] recommendation_logs: required subject unresolved: {unmatched}")


def _backfill_recommendation_metrics_daily(bind, resolver):
    if not _has_table(sa.inspect(bind), "recommendation_metrics_daily"):
        return
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "recommendation_metrics_daily", "subject"):
        return
    conn = bind
    t = sa.table("recommendation_metrics_daily",
                 sa.column("id", sa.Integer()),
                 sa.column("subject", sa.String()),
                 sa.column("subject_id", sa.Integer()))
    rows = conn.execute(sa.select(t.c.id, t.c.subject)).fetchall()
    unmatched = []
    for rid, legacy in rows:
        sid = resolver.resolve(legacy)
        if sid is None:
            unmatched.append((rid, legacy))
            continue
        conn.execute(sa.update(t).where(t.c.id == rid).values(subject_id=sid))
    if unmatched:
        raise Exception(f"[a7b8c9d0e1f2] recommendation_metrics_daily: required subject unresolved: {unmatched}")


def _backfill_tags(bind, resolver):
    if not _has_table(sa.inspect(bind), "tags"):
        return
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "tags", "subject"):
        return
    conn = bind
    t = sa.table("tags", sa.column("id", sa.Integer()), sa.column("subject", sa.String()),
                 sa.column("subject_id", sa.Integer()))
    rows = conn.execute(sa.select(t.c.id, t.c.subject)).fetchall()
    unmatched = []
    for rid, legacy in rows:
        sid = resolver.resolve(legacy)
        if sid is None:
            unmatched.append((rid, legacy))
            continue
        conn.execute(sa.update(t).where(t.c.id == rid).values(subject_id=sid))
    if unmatched:
        raise Exception(f"[a7b8c9d0e1f2] tags: required subject unresolved: {unmatched}")


def _backfill_user_knowledge_states(bind, resolver):
    if not _has_table(sa.inspect(bind), "user_knowledge_states"):
        return
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "user_knowledge_states", "subject"):
        return
    conn = bind
    t = sa.table("user_knowledge_states",
                 sa.column("id", sa.Integer()),
                 sa.column("knowledge_point_id", sa.Integer()),
                 sa.column("subject", sa.String()),
                 sa.column("subject_id", sa.Integer()))
    kp = sa.table("knowledge_points", sa.column("id", sa.Integer()), sa.column("subject_id", sa.Integer()))
    rows = conn.execute(sa.select(t.c.id, t.c.knowledge_point_id, t.c.subject)).fetchall()
    conflicts, unmatched = [], []
    for rid, kpid, legacy in rows:
        rel_id = None
        if kpid is not None:
            krow = conn.execute(sa.select(kp.c.subject_id).where(kp.c.id == kpid)).fetchone()
            if krow and krow[0] is not None:
                rel_id = int(krow[0])
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
        raise Exception(f"[a7b8c9d0e1f2] user_knowledge_states backfill conflict: {conflicts}")
    if unmatched:
        raise Exception(f"[a7b8c9d0e1f2] user_knowledge_states: required subject unresolved: {unmatched}")


# --- rebuild implementations (add subject_id col -> already added? add here) ---

def _ensure_subject_id_column(inspector, table):
    if not _has_column(inspector, table, "subject_id"):
        op.add_column(table, sa.Column("subject_id", sa.Integer(), nullable=True))


def _drop_subject_indexes(conn, table):
    """Drop every index (incl. UNIQUE autoindexes) whose columns include `subject`.

    Index names differ between runtime `create_all` builds
    (ix_recommendation_metrics_daily_subject) and migration-only fresh builds
    (ix_rmd_subject), so drops are matched on column coverage, never by name.
    """
    inspector = sa.inspect(conn)
    for idx in inspector.get_indexes(table):
        cols = idx.get("column_names") or []
        if "subject" in cols:
            name = idx.get("name")
            if name:
                conn.execute(sa.text(f'DROP INDEX IF EXISTS "{name}"'))


def _existing_index_names(inspector, table):
    return {i["name"] for i in inspector.get_indexes(table)}


def _existing_unique_names(inspector, table):
    return {u["name"] for u in inspector.get_unique_constraints(table)}


def _subject_unique_name(inspector, table):
    """Name of the unique constraint whose columns include `subject`, if any."""
    for uc in inspector.get_unique_constraints(table):
        if "subject" in (uc.get("column_names") or []):
            return uc.get("name")
    return None


def _rebuild_answer_behaviors(inspector):
    if not _has_table(inspector, "answer_behaviors"):
        return
    _ensure_subject_id_column(inspector, "answer_behaviors")
    if not _has_column(inspector, "answer_behaviors", "subject"):
        return
    conn = op.get_bind()
    _drop_subject_indexes(conn, "answer_behaviors")
    existing = _existing_index_names(inspector, "answer_behaviors")
    with op.batch_alter_table("answer_behaviors", recreate="auto") as batch_op:
        batch_op.create_foreign_key("fk_answer_behaviors_subject_id", "subjects", ["subject_id"], ["id"], ondelete="SET NULL")
        batch_op.drop_column("subject")
        if "ix_answer_behaviors_subject_id" not in existing:
            batch_op.create_index("ix_answer_behaviors_subject_id", ["subject_id"])


def _rebuild_practice_records(inspector):
    if not _has_table(inspector, "practice_records"):
        return
    _ensure_subject_id_column(inspector, "practice_records")
    if not _has_column(inspector, "practice_records", "subject"):
        return
    conn = op.get_bind()
    _drop_subject_indexes(conn, "practice_records")
    existing = _existing_index_names(inspector, "practice_records")
    with op.batch_alter_table("practice_records", recreate="auto") as batch_op:
        batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_practice_records_subject_id", "subjects", ["subject_id"], ["id"], ondelete="RESTRICT")
        batch_op.drop_column("subject")
        if "idx_practice_records_user_subject_id" not in existing:
            batch_op.create_index("idx_practice_records_user_subject_id", ["user_id", "subject_id"])


def _rebuild_review_schedules(inspector):
    if not _has_table(inspector, "review_schedules"):
        return
    _ensure_subject_id_column(inspector, "review_schedules")
    if not _has_column(inspector, "review_schedules", "subject"):
        return
    conn = op.get_bind()
    _drop_subject_indexes(conn, "review_schedules")
    existing = _existing_index_names(inspector, "review_schedules")
    with op.batch_alter_table("review_schedules", recreate="auto") as batch_op:
        batch_op.create_foreign_key("fk_review_schedules_subject_id", "subjects", ["subject_id"], ["id"], ondelete="SET NULL")
        batch_op.drop_column("subject")
        if "ix_review_schedules_user_subject_id" not in existing:
            batch_op.create_index("ix_review_schedules_user_subject_id", ["user_id", "subject_id"])


def _rebuild_knowledge_points(inspector):
    if not _has_table(inspector, "knowledge_points"):
        return
    _ensure_subject_id_column(inspector, "knowledge_points")
    if not _has_column(inspector, "knowledge_points", "subject"):
        return
    conn = op.get_bind()
    if not _is_sqlite():
        # Postgres refuses to DROP COLUMN subject while uq_kp_subject_normalized_name
        # still references it (and refuses to DROP INDEX on the constraint's backing
        # index), so drop the constraint first; SQLite's batch recreate handles it.
        old_uniq = _subject_unique_name(inspector, "knowledge_points")
        if old_uniq:
            op.drop_constraint(old_uniq, "knowledge_points", type_="unique")
            inspector = sa.inspect(conn)
    _drop_subject_indexes(conn, "knowledge_points")
    existing = _existing_index_names(inspector, "knowledge_points")
    existing_unique = _existing_unique_names(inspector, "knowledge_points")
    with op.batch_alter_table("knowledge_points", recreate="auto") as batch_op:
        batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_knowledge_points_subject_id", "subjects", ["subject_id"], ["id"], ondelete="RESTRICT")
        batch_op.drop_column("subject")
        if "ix_knowledge_points_subject_id" not in existing:
            batch_op.create_index("ix_knowledge_points_subject_id", ["subject_id"])
        if "uq_kp_subject_id_normalized_name" not in existing | existing_unique:
            batch_op.create_unique_constraint("uq_kp_subject_id_normalized_name", ["subject_id", "normalized_name"])


def _rebuild_knowledge_edges(inspector):
    if not _has_table(inspector, "knowledge_edges"):
        return
    _ensure_subject_id_column(inspector, "knowledge_edges")
    if not _has_column(inspector, "knowledge_edges", "subject"):
        return
    conn = op.get_bind()
    _drop_subject_indexes(conn, "knowledge_edges")
    existing = _existing_index_names(inspector, "knowledge_edges")
    with op.batch_alter_table("knowledge_edges", recreate="auto") as batch_op:
        batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_knowledge_edges_subject_id", "subjects", ["subject_id"], ["id"], ondelete="RESTRICT")
        batch_op.drop_column("subject")
        if "ix_knowledge_edges_subject_id" not in existing:
            batch_op.create_index("ix_knowledge_edges_subject_id", ["subject_id"])
        if "ix_ke_subject_id_relation" not in existing:
            batch_op.create_index("ix_ke_subject_id_relation", ["subject_id", "relation_type"])


def _rebuild_recommendation_logs(inspector):
    if not _has_table(inspector, "recommendation_logs"):
        return
    _ensure_subject_id_column(inspector, "recommendation_logs")
    if not _has_column(inspector, "recommendation_logs", "subject"):
        return
    conn = op.get_bind()
    _drop_subject_indexes(conn, "recommendation_logs")
    existing = _existing_index_names(inspector, "recommendation_logs")
    with op.batch_alter_table("recommendation_logs", recreate="auto") as batch_op:
        batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_recommendation_logs_subject_id", "subjects", ["subject_id"], ["id"], ondelete="RESTRICT")
        batch_op.drop_column("subject")
        if "ix_recommendation_logs_subject_id" not in existing:
            batch_op.create_index("ix_recommendation_logs_subject_id", ["subject_id"])


def _rebuild_recommendation_metrics_daily(inspector):
    if not _has_table(inspector, "recommendation_metrics_daily"):
        return
    _ensure_subject_id_column(inspector, "recommendation_metrics_daily")
    if not _has_column(inspector, "recommendation_metrics_daily", "subject"):
        return
    conn = op.get_bind()
    if not _is_sqlite():
        # Same reasoning as _rebuild_knowledge_points: drop the unique constraint
        # that references `subject` before Postgres will let us drop the column.
        old_uniq = _subject_unique_name(inspector, "recommendation_metrics_daily")
        if old_uniq:
            op.drop_constraint(old_uniq, "recommendation_metrics_daily", type_="unique")
            inspector = sa.inspect(conn)
    _drop_subject_indexes(conn, "recommendation_metrics_daily")
    existing = _existing_index_names(inspector, "recommendation_metrics_daily")
    existing_unique = _existing_unique_names(inspector, "recommendation_metrics_daily")
    with op.batch_alter_table("recommendation_metrics_daily", recreate="auto") as batch_op:
        batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_recommendation_metrics_daily_subject_id", "subjects", ["subject_id"], ["id"], ondelete="RESTRICT")
        batch_op.drop_column("subject")
        if "ix_recommendation_metrics_daily_subject_id" not in existing:
            batch_op.create_index("ix_recommendation_metrics_daily_subject_id", ["subject_id"])
        if "uq_rmd_date_subject_id_scene_strategy_variant" not in existing | existing_unique:
            batch_op.create_unique_constraint(
                "uq_rmd_date_subject_id_scene_strategy_variant",
                ["date", "subject_id", "scene", "strategy", "variant_key"],
            )


def _rebuild_tags(inspector):
    if not _has_table(inspector, "tags"):
        return
    _ensure_subject_id_column(inspector, "tags")
    if not _has_column(inspector, "tags", "subject"):
        return
    conn = op.get_bind()
    _drop_subject_indexes(conn, "tags")
    existing = _existing_index_names(inspector, "tags")
    with op.batch_alter_table("tags", recreate="auto") as batch_op:
        batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_tags_subject_id", "subjects", ["subject_id"], ["id"], ondelete="RESTRICT")
        batch_op.drop_column("subject")
        if "ix_tags_subject_id" not in existing:
            batch_op.create_index("ix_tags_subject_id", ["subject_id"])


def _rebuild_user_knowledge_states(inspector):
    if not _has_table(inspector, "user_knowledge_states"):
        return
    _ensure_subject_id_column(inspector, "user_knowledge_states")
    if not _has_column(inspector, "user_knowledge_states", "subject"):
        return
    conn = op.get_bind()
    _drop_subject_indexes(conn, "user_knowledge_states")
    existing = _existing_index_names(inspector, "user_knowledge_states")
    with op.batch_alter_table("user_knowledge_states", recreate="auto") as batch_op:
        batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_user_knowledge_states_subject_id", "subjects", ["subject_id"], ["id"], ondelete="RESTRICT")
        batch_op.drop_column("subject")
        if "ix_user_knowledge_states_subject_id" not in existing:
            batch_op.create_index("ix_user_knowledge_states_subject_id", ["subject_id"])
        if "ix_uks_user_subject_id" not in existing:
            batch_op.create_index("ix_uks_user_subject_id", ["user_id", "subject_id"])


def _add_real_fk_questions(inspector):
    if not _has_table(inspector, "questions"):
        return
    if not _has_column(inspector, "questions", "subject_id"):
        return
    # safety: NOT NULL requires all rows populated
    conn = op.get_bind()
    null_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM questions WHERE subject_id IS NULL")
    ).scalar()
    orphan_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM questions WHERE subject_id IS NOT NULL AND subject_id NOT IN (SELECT id FROM subjects)")
    ).scalar()
    if null_count or orphan_count:
        raise Exception(
            f"[a7b8c9d0e1f2] questions.subject_id invalid: nulls={null_count} orphans={orphan_count}"
        )
    with op.batch_alter_table("questions", recreate="auto") as batch_op:
        batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_questions_subject_id", "subjects", ["subject_id"], ["id"], ondelete="NO ACTION")


def _add_real_fk_question_imports(inspector):
    if not _has_table(inspector, "question_imports"):
        return
    if not _has_column(inspector, "question_imports", "subject_id"):
        return
    with op.batch_alter_table("question_imports", recreate="auto") as batch_op:
        batch_op.create_foreign_key("fk_question_imports_subject_id", "subjects", ["subject_id"], ["id"], ondelete="SET NULL")


def _add_real_fk_pomodoro(inspector):
    if not _has_table(inspector, "pomodoro_sessions"):
        return
    if not _has_column(inspector, "pomodoro_sessions", "subject_id"):
        return
    with op.batch_alter_table("pomodoro_sessions", recreate="auto") as batch_op:
        batch_op.create_foreign_key("fk_pomodoro_sessions_subject_id", "subjects", ["subject_id"], ["id"], ondelete="SET NULL")


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def _downgrade_restore_subject(inspector, table, old_len, old_nullable, old_indexes,
                                old_uniques=None, new_uniques=None, new_fk=True, new_indexes=None):
    """Re-add legacy subject column, backfill from subjects.code, drop subject_id."""
    if not _has_table(inspector, table):
        return
    if _has_column(inspector, table, "subject") or not _has_column(inspector, table, "subject_id"):
        return
    conn = op.get_bind()
    st = sa.table(table, sa.column("id", sa.Integer()), sa.column("subject_id", sa.Integer()))
    op.add_column(table, sa.Column("subject", sa.String(old_len), nullable=True))
    # backfill subject from subjects.code
    conn.execute(sa.text(
        f"UPDATE {table} SET subject = (SELECT code FROM subjects WHERE subjects.id = {table}.subject_id) "
        f"WHERE subject_id IS NOT NULL"
    ))

    inspector = sa.inspect(op.get_bind())
    fk_name = _fk_name(inspector, table)
    with op.batch_alter_table(table, recreate="auto") as batch_op:
        if fk_name:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
        if not old_nullable:
            batch_op.alter_column("subject", existing_type=sa.String(old_len), nullable=False)
        for idx in (new_indexes or []):
            batch_op.drop_index(idx)
        for uq in (new_uniques or []):
            batch_op.drop_constraint(uq, type_="unique")
        batch_op.drop_column("subject_id")
        for idx in old_indexes:
            batch_op.create_index(idx[0], idx[1])
        for uq in (old_uniques or []):
            batch_op.create_unique_constraint(uq[0], uq[1])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # questions: revert NOT NULL + drop FK
    if _has_table(inspector, "questions") and _has_column(inspector, "questions", "subject_id"):
        fk_name = _fk_name(inspector, "questions")
        with op.batch_alter_table("questions", recreate="auto") as batch_op:
            if fk_name:
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.alter_column("subject_id", existing_type=sa.Integer(), nullable=True)

    # question_imports / pomodoro: drop FK
    for table in ("question_imports", "pomodoro_sessions"):
        if _has_table(inspector, table) and _has_column(inspector, table, "subject_id"):
            fk_name = _fk_name(inspector, table)
            with op.batch_alter_table(table, recreate="auto") as batch_op:
                if fk_name:
                    batch_op.drop_constraint(fk_name, type_="foreignkey")

    inspector = sa.inspect(bind)

    _downgrade_restore_subject(
        inspector, "answer_behaviors", 16, old_nullable=True,
        old_indexes=[], new_indexes=["ix_answer_behaviors_subject_id"],
    )
    _downgrade_restore_subject(
        inspector, "practice_records", 32, old_nullable=False,
        old_indexes=[("idx_practice_records_user_subject", ["user_id", "subject"])],
        new_indexes=["idx_practice_records_user_subject_id"],
    )
    _downgrade_restore_subject(
        inspector, "review_schedules", 16, old_nullable=True,
        old_indexes=[("ix_review_schedules_user_subject", ["user_id", "subject"])],
        new_indexes=["ix_review_schedules_user_subject_id"],
    )
    _downgrade_restore_subject(
        inspector, "knowledge_points", 32, old_nullable=False,
        old_indexes=[("ix_knowledge_points_subject", ["subject"])],
        old_uniques=[("uq_kp_subject_normalized_name", ["subject", "normalized_name"])],
        new_uniques=["uq_kp_subject_id_normalized_name"],
        new_indexes=["ix_knowledge_points_subject_id"],
    )
    _downgrade_restore_subject(
        inspector, "knowledge_edges", 32, old_nullable=False,
        old_indexes=[("ix_knowledge_edges_subject", ["subject"]),
                     ("ix_ke_subject_relation", ["subject", "relation_type"])],
        new_indexes=["ix_knowledge_edges_subject_id", "ix_ke_subject_id_relation"],
    )
    _downgrade_restore_subject(
        inspector, "recommendation_logs", 32, old_nullable=False,
        old_indexes=[("ix_recommendation_logs_subject", ["subject"])],
        new_indexes=["ix_recommendation_logs_subject_id"],
    )
    _downgrade_restore_subject(
        inspector, "recommendation_metrics_daily", 32, old_nullable=False,
        old_indexes=[("ix_recommendation_metrics_daily_subject", ["subject"])],
        old_uniques=[("uq_rmd_date_subject_scene_strategy_variant",
                      ["date", "subject", "scene", "strategy", "variant_key"])],
        new_uniques=["uq_rmd_date_subject_id_scene_strategy_variant"],
        new_indexes=["ix_recommendation_metrics_daily_subject_id"],
    )
    _downgrade_restore_subject(
        inspector, "tags", 16, old_nullable=False,
        old_indexes=[("ix_tags_subject", ["subject"])],
        new_indexes=["ix_tags_subject_id"],
    )
    _downgrade_restore_subject(
        inspector, "user_knowledge_states", 32, old_nullable=False,
        old_indexes=[("ix_user_knowledge_states_subject", ["subject"]),
                     ("ix_uks_user_subject", ["user_id", "subject"])],
        new_indexes=["ix_user_knowledge_states_subject_id", "ix_uks_user_subject_id"],
    )
