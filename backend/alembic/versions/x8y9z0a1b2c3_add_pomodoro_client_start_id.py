"""add idempotent client start id to pomodoro sessions

A client-generated start key lets mobile clients retry an uncertain /start request
without guessing which cross-device active session belongs to that request.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "x8y9z0a1b2c3"
down_revision: str | None = "w7x8y9z0a1b2"
branch_labels = None
depends_on = None

INDEX_NAME = "ux_pomodoro_sessions_user_client_start_id"


def _has_column(bind, table: str, name: str) -> bool:
    return name in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _has_index(bind, table: str, name: str) -> bool:
    return name in {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "pomodoro_sessions", "client_start_id"):
        op.add_column(
            "pomodoro_sessions",
            sa.Column("client_start_id", sa.String(length=64), nullable=True),
        )
    if not _has_index(bind, "pomodoro_sessions", INDEX_NAME):
        op.create_index(
            INDEX_NAME,
            "pomodoro_sessions",
            ["user_id", "client_start_id"],
            unique=True,
            sqlite_where=sa.text("client_start_id IS NOT NULL"),
            postgresql_where=sa.text("client_start_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_index(bind, "pomodoro_sessions", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="pomodoro_sessions")
    if _has_column(bind, "pomodoro_sessions", "client_start_id"):
        op.drop_column("pomodoro_sessions", "client_start_id")
