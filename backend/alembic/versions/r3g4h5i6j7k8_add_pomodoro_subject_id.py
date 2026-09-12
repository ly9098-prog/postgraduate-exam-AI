"""Add subject_id FK column to pomodoro_sessions (self-sufficient).

Revision ID: r3g4h5i6j7k8
Revises: v7_import_review_source_metadata
Create Date: 2026-07-09 21:00:00.000000

Self-sufficient migration: creates pomodoro_sessions if missing,
adds subject_id FK, backfills from legacy subject column.

Formerly branched from q2g3h4i5j6k7; rebased onto v7_import_review_source_metadata
to eliminate the multi-head fork. The orphaned o0/q2/p1 chain is superseded.
"""
import sqlalchemy as sa

from alembic import op

revision = "r3g4h5i6j7k8"
down_revision = "v7_import_review_source_metadata"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- 0. Create pomodoro_sessions if missing (self-sufficient for fresh DB) ---
    if not _has_table(inspector, "pomodoro_sessions"):
        _create_pomodoro_table()
        return  # Fresh table has all columns, no backfill needed

    # --- 1. Add subject_id column ---
    if not _has_column(inspector, "pomodoro_sessions", "subject_id"):
        op.add_column("pomodoro_sessions", sa.Column("subject_id", sa.Integer(), nullable=True))

    inspector = sa.inspect(bind)  # refresh

    # --- 2. Create FK constraint + index (skip for SQLite) ---
    if _has_column(inspector, "pomodoro_sessions", "subject_id") and not _is_sqlite():
        op.create_foreign_key(
            "fk_pomodoro_sessions_subject_id",
            "pomodoro_sessions", "subjects",
            ["subject_id"], ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_pomodoro_sessions_subject_id",
            "pomodoro_sessions", ["subject_id"],
        )

    # --- 3. Backfill subject_id from old subject string ---
    if _has_column(inspector, "pomodoro_sessions", "subject") and _has_table(inspector, "subjects"):
        _backfill_subject_ids()

    # --- 4. Report backfill status ---
    _report_unmatched_subjects()


def _create_pomodoro_table() -> None:
    """Create pomodoro_sessions with the full current schema.

    Used when the table doesn't exist yet (fresh DB). Covers all columns
    that were formerly in the o0/p1/q2 chain plus the new subject_id FK.
    """
    op.create_table(
        "pomodoro_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chapter_id", sa.String(64), nullable=True),
        sa.Column("preset", sa.String(16), nullable=False, server_default="standard"),
        sa.Column("work_duration", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("break_duration", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("expected_end_time", sa.DateTime(), nullable=True, index=True),
        sa.Column("actual_duration", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("notification_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("notification_sent", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("notification_sent_at", sa.DateTime(), nullable=True),
        sa.Column("notification_error", sa.Text(), nullable=True),
        sa.Column("openid_snapshot", sa.String(64), nullable=True),
        sa.Column("paused_at", sa.DateTime(), nullable=True),
        sa.Column("total_paused_sec", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_pomodoro_sessions_subject_id", "pomodoro_sessions", ["subject_id"])


def _backfill_subject_ids() -> None:
    conn = op.get_bind()
    subjects_table = sa.table(
        "subjects",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    rows = conn.execute(sa.select(subjects_table.c.id, subjects_table.c.code, subjects_table.c.name)).fetchall()
    code_to_id: dict[str, int] = {r[1]: r[0] for r in rows if r[1]}
    name_to_id: dict[str, int] = {r[2]: r[0] for r in rows if r[2]}

    # Comprehensive old-value → target code mapping
    legacy_map: dict[str, str] = {
        # math
        "math": "math2",
        "数学": "math2",
        "数学二": "math2",
        "math2": "math2",
        # 408
        "computer": "exam408",
        "计算机": "exam408",
        "408": "exam408",
        "408计算机综合": "exam408",
        "exam408": "exam408",
        # english
        "english": "english",
        "英语": "english",
        # politics
        "politics": "pol",
        "political": "pol",
        "pol": "pol",
        "政治": "pol",
        # advanced_math
        "advanced_math": "math2-calculus",
        "calculus": "math2-calculus",
        "math2-calculus": "math2-calculus",
        "高数": "math2-calculus",
        "高等数学": "math2-calculus",
        # linear_algebra
        "linear_algebra": "math2-linalg",
        "linalg": "math2-linalg",
        "math2-linalg": "math2-linalg",
        "线代": "math2-linalg",
        "线性代数": "math2-linalg",
        # data_structure
        "data_structure": "exam408-ds",
        "ds": "exam408-ds",
        "exam408-ds": "exam408-ds",
        "数据结构": "exam408-ds",
        # operating_system
        "operating_system": "exam408-os",
        "os": "exam408-os",
        "exam408-os": "exam408-os",
        "操作系统": "exam408-os",
        # computer_organization
        "computer_organization": "exam408-co",
        "co": "exam408-co",
        "exam408-co": "exam408-co",
        "组成原理": "exam408-co",
        "计算机组成原理": "exam408-co",
        # computer_network
        "computer_network": "exam408-cn",
        "cn": "exam408-cn",
        "exam408-cn": "exam408-cn",
        "计网": "exam408-cn",
        "计算机网络": "exam408-cn",
    }

    pomodoro_table = sa.table(
        "pomodoro_sessions",
        sa.column("id", sa.Integer()),
        sa.column("subject", sa.String()),
        sa.column("subject_id", sa.Integer()),
    )

    result = conn.execute(
        sa.select(pomodoro_table.c.id, pomodoro_table.c.subject)
        .where(pomodoro_table.c.subject_id.is_(None))
        .where(pomodoro_table.c.subject != "")
    )
    matched = 0
    unmatched = 0
    unmatched_values: set[str] = set()
    for row in result.fetchall():
        session_id = row[0]
        old_subject = row[1]
        subject_id = None

        # Priority 1: legacy mapping to target code
        target_code = legacy_map.get(old_subject)
        if target_code and target_code in code_to_id:
            subject_id = code_to_id[target_code]

        # Priority 2: direct code match
        if subject_id is None and old_subject in code_to_id:
            subject_id = code_to_id[old_subject]

        # Priority 3: direct name match
        if subject_id is None and old_subject in name_to_id:
            subject_id = name_to_id[old_subject]

        if subject_id is not None:
            conn.execute(
                pomodoro_table.update()
                .where(pomodoro_table.c.id == session_id)
                .values(subject_id=subject_id)
            )
            matched += 1
        else:
            unmatched += 1
            unmatched_values.add(old_subject)

    print(f"[migration] subject_id backfill: {matched} matched, {unmatched} unmatched")
    if unmatched_values:
        print(f"[migration] unmatched legacy subject values: {sorted(unmatched_values)}")


def _report_unmatched_subjects() -> None:
    """Log any remaining unmatched legacy subjects as a warning."""
    conn = op.get_bind()
    pomodoro_table = sa.table(
        "pomodoro_sessions",
        sa.column("id", sa.Integer()),
        sa.column("subject", sa.String()),
        sa.column("subject_id", sa.Integer()),
    )
    result = conn.execute(
        sa.select(pomodoro_table.c.subject, sa.func.count(pomodoro_table.c.id))
        .where(pomodoro_table.c.subject_id.is_(None))
        .where(pomodoro_table.c.subject != "")
        .where(pomodoro_table.c.subject.isnot(None))
        .group_by(pomodoro_table.c.subject)
    )
    remaining = result.fetchall()
    if remaining:
        print(f"[migration] WARNING: {len(remaining)} subject value(s) still unmatched after backfill:")
        for val, cnt in remaining:
            print(f"  - '{val}': {cnt} row(s)")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "pomodoro_sessions", "subject_id"):
        if not _is_sqlite():
            op.drop_index("ix_pomodoro_sessions_subject_id", table_name="pomodoro_sessions")
            op.drop_constraint("fk_pomodoro_sessions_subject_id", "pomodoro_sessions", type_="foreignkey")
        op.drop_column("pomodoro_sessions", "subject_id")
