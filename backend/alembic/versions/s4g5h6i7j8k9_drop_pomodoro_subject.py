"""Drop pomodoro_sessions.subject column (with safety check).

Revision ID: s4g5h6i7j8k9
Revises: r3g4h5i6j7k8
Create Date: 2026-07-09 22:00:00.000000

Drops the legacy subject string column from pomodoro_sessions.
All subject data now uses subject_id -> subjects.id FK.

Safety: refuses to drop if unmatched legacy values remain.
"""
import sqlalchemy as sa

from alembic import op

revision = "s4g5h6i7j8k9"
down_revision = "r3g4h5i6j7k8"
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

    if not _has_table(inspector, "pomodoro_sessions") or not _has_column(inspector, "pomodoro_sessions", "subject"):
        return

    # Safety: check for unmatched legacy values before dropping
    conn = op.get_bind()
    pomodoro_table = sa.table(
        "pomodoro_sessions",
        sa.column("subject", sa.String()),
        sa.column("subject_id", sa.Integer()),
    )
    unmatched = conn.execute(
        sa.select(pomodoro_table.c.subject, sa.func.count(sa.literal_column("*")))
        .where(pomodoro_table.c.subject_id.is_(None))
        .where(pomodoro_table.c.subject != "")
        .where(pomodoro_table.c.subject.isnot(None))
        .group_by(pomodoro_table.c.subject)
    ).fetchall()

    if unmatched:
        lines = "\n  ".join(f"'{val}' ({cnt} rows)" for val, cnt in unmatched)
        raise Exception(
            f"Cannot drop pomodoro_sessions.subject: unmatched legacy values remain.\n"
            f"  Fix the backfill mapping in r3 migration first, or manually set subject_id.\n"
            f"  Unmatched:\n  {lines}"
        )

    if _is_sqlite():
        with op.batch_alter_table("pomodoro_sessions") as batch_op:
            batch_op.drop_column("subject")
    else:
        op.drop_column("pomodoro_sessions", "subject")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "pomodoro_sessions") and not _has_column(inspector, "pomodoro_sessions", "subject"):
        op.add_column(
            "pomodoro_sessions",
            sa.Column("subject", sa.String(32), nullable=True),
        )
