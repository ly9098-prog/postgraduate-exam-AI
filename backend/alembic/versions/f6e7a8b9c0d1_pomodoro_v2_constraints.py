"""pomodoro v2 canonical constraints

Adds the post-normalization integrity constraints (§16) so the V2 canonical model
is enforced by the database:

- ``pomodoro_pause_intervals``: CHECK ``ended_at IS NULL OR ended_at > started_at``
- ``pomodoro_pause_intervals``: partial UNIQUE index ``(session_id) WHERE ended_at
  IS NULL`` -> at most one open pause interval per session
- ``pomodoro_sessions``: CHECK that a completed session has ``end_time >= start_time``
  and ``actual_duration >= 0``

The completed-session CHECK is applied only when no existing row violates it; if
legacy data still violates it, the constraint is skipped with a warning so this
migration never blocks a deployment.  Re-run ``alembic upgrade head`` after the
backfill/repair resolves the violations.

CHECK constraints are added through ``op.batch_alter_table`` because the SQLite
dialect has no ALTER-TABLE-ADD-CONSTRAINT support (copy-and-move strategy);
PostgreSQL executes these directly.  Idempotent: every step is skipped when the
target already exists.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "f6e7a8b9c0d1"
down_revision: str | None = "48e17ed2a3f3"
branch_labels = None
depends_on = None

CK_PAUSE_ENDED = "ck_pomodoro_pause_intervals_ended_at"
UX_ONE_OPEN = "ux_pomodoro_pause_intervals_one_open"
CK_SESSION_COMPLETED = "ck_pomodoro_sessions_completed_duration"


def _has_index(bind, table: str, index: str) -> bool:
    return index in {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def _has_check(bind, table: str, name: str) -> bool:
    return name in {c["name"] for c in sa.inspect(bind).get_check_constraints(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # 1. pause interval CHECK + 2. at most one open interval (partial unique index)
    if not (_has_check(bind, "pomodoro_pause_intervals", CK_PAUSE_ENDED)
            and _has_index(bind, "pomodoro_pause_intervals", UX_ONE_OPEN)):
        with op.batch_alter_table("pomodoro_pause_intervals") as batch_op:
            batch_op.create_check_constraint(
                CK_PAUSE_ENDED, "ended_at IS NULL OR ended_at > started_at"
            )
            batch_op.create_index(
                UX_ONE_OPEN,
                ["session_id"],
                unique=True,
                sqlite_where=sa.text("ended_at IS NULL"),
                postgresql_where=sa.text("ended_at IS NULL"),
            )
    else:
        # both already exist individually (e.g. a partial prior apply)
        if not _has_check(bind, "pomodoro_pause_intervals", CK_PAUSE_ENDED):
            with op.batch_alter_table("pomodoro_pause_intervals") as batch_op:
                batch_op.create_check_constraint(
                    CK_PAUSE_ENDED, "ended_at IS NULL OR ended_at > started_at"
                )
        if not _has_index(bind, "pomodoro_pause_intervals", UX_ONE_OPEN):
            op.create_index(
                UX_ONE_OPEN, "pomodoro_pause_intervals", ["session_id"], unique=True,
                sqlite_where=sa.text("ended_at IS NULL"),
                postgresql_where=sa.text("ended_at IS NULL"),
            )

    # SQLite batch recreate reflects the table and can drop indexes it cannot
    # reflect; re-create the query index if it vanished (PostgreSQL no-op).
    if not _has_index(bind, "pomodoro_pause_intervals", "ix_pomodoro_pause_intervals_session_started"):
        op.create_index(
            op.f("ix_pomodoro_pause_intervals_session_started"),
            "pomodoro_pause_intervals",
            ["session_id", "started_at"],
        )

    # 3. completed session duration CHECK (data-tolerant)
    if not _has_check(bind, "pomodoro_sessions", CK_SESSION_COMPLETED):
        violating = bind.execute(sa.text(
            "SELECT COUNT(*) FROM pomodoro_sessions "
            "WHERE status = 'completed' AND (actual_duration < 0 OR end_time < start_time)"
        )).scalar() or 0
        if violating:
            print(f"WARNING: {violating} completed session(s) violate the duration CHECK; "
                  f"skipping {CK_SESSION_COMPLETED}. Fix the data (backfill --repair-invalid) "
                  f"then re-run `alembic upgrade head`.")
        else:
            with op.batch_alter_table("pomodoro_sessions") as batch_op:
                batch_op.create_check_constraint(
                    CK_SESSION_COMPLETED,
                    "status != 'completed' OR (end_time >= start_time AND actual_duration >= 0)",
                )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_index(bind, "pomodoro_pause_intervals", UX_ONE_OPEN) or _has_check(bind, "pomodoro_pause_intervals", CK_PAUSE_ENDED):
        with op.batch_alter_table("pomodoro_pause_intervals") as batch_op:
            if _has_index(bind, "pomodoro_pause_intervals", UX_ONE_OPEN):
                batch_op.drop_index(UX_ONE_OPEN)
            if _has_check(bind, "pomodoro_pause_intervals", CK_PAUSE_ENDED):
                batch_op.drop_constraint(CK_PAUSE_ENDED, type_="check")

    if _has_check(bind, "pomodoro_sessions", CK_SESSION_COMPLETED):
        with op.batch_alter_table("pomodoro_sessions") as batch_op:
            batch_op.drop_constraint(CK_SESSION_COMPLETED, type_="check")
