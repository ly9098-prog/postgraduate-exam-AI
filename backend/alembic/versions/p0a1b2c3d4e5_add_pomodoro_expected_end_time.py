"""add notification columns to pomodoro_sessions (backfill for deprecated feature)

Revision ID: p0a1b2c3d4e5
Revises: 3a8b7c9d1e2f
Create Date: 2026-06-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "p0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "3a8b7c9d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE pomodoro_sessions ADD COLUMN IF NOT EXISTS expected_end_time TIMESTAMP")
    op.execute("ALTER TABLE pomodoro_sessions ADD COLUMN IF NOT EXISTS notification_enabled BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE pomodoro_sessions ADD COLUMN IF NOT EXISTS notification_sent BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE pomodoro_sessions ADD COLUMN IF NOT EXISTS notification_sent_at TIMESTAMP")
    op.execute("ALTER TABLE pomodoro_sessions ADD COLUMN IF NOT EXISTS notification_error TEXT")
    op.execute("ALTER TABLE pomodoro_sessions ADD COLUMN IF NOT EXISTS openid_snapshot VARCHAR(64)")
    op.execute("ALTER TABLE pomodoro_sessions ADD COLUMN IF NOT EXISTS paused_at TIMESTAMP")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pomodoro_sessions_expected_end_time ON pomodoro_sessions (expected_end_time)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pomodoro_sessions_expected_end_time")
    op.execute("ALTER TABLE pomodoro_sessions DROP COLUMN IF EXISTS expected_end_time")
    op.execute("ALTER TABLE pomodoro_sessions DROP COLUMN IF EXISTS notification_enabled")
    op.execute("ALTER TABLE pomodoro_sessions DROP COLUMN IF EXISTS notification_sent")
    op.execute("ALTER TABLE pomodoro_sessions DROP COLUMN IF EXISTS notification_sent_at")
    op.execute("ALTER TABLE pomodoro_sessions DROP COLUMN IF EXISTS notification_error")
    op.execute("ALTER TABLE pomodoro_sessions DROP COLUMN IF EXISTS openid_snapshot")
    op.execute("ALTER TABLE pomodoro_sessions DROP COLUMN IF EXISTS paused_at")
