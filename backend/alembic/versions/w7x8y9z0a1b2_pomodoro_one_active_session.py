"""enforce one active pomodoro session per user

Adds a partial unique index on ``pomodoro_sessions(user_id)`` for rows whose
status is ``running`` or ``paused``.  This closes the race where two concurrent
/start requests both pass the service pre-check and create two active sessions.

The migration is deliberately fail-closed when legacy duplicate active sessions
already exist: choosing which session to terminate is product data, not a schema
migration decision. Resolve the reported users first, then re-run the migration.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "w7x8y9z0a1b2"
down_revision: str | None = "v6w7x8y9z0a1"
branch_labels = None
depends_on = None

INDEX_NAME = "ux_pomodoro_sessions_one_active_per_user"


def _has_index(bind, table: str, name: str) -> bool:
    return name in {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _has_index(bind, "pomodoro_sessions", INDEX_NAME):
        return

    duplicates = bind.execute(
        sa.text(
            "SELECT user_id, COUNT(*) AS active_count "
            "FROM pomodoro_sessions "
            "WHERE status IN ('running', 'paused') "
            "GROUP BY user_id HAVING COUNT(*) > 1 "
            "ORDER BY active_count DESC, user_id LIMIT 20"
        )
    ).fetchall()
    if duplicates:
        preview = [(row[0], row[1]) for row in duplicates]
        raise RuntimeError(
            "Cannot create pomodoro active-session unique index: duplicate active "
            f"sessions exist for users (user_id, count)={preview}. "
            "Resolve duplicate running/paused sessions, then re-run alembic upgrade head."
        )

    op.create_index(
        INDEX_NAME,
        "pomodoro_sessions",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('running', 'paused')"),
        postgresql_where=sa.text("status IN ('running', 'paused')"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_index(bind, "pomodoro_sessions", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="pomodoro_sessions")
