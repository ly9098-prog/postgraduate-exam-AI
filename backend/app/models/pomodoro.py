from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.orm_base import Base


class PomodoroSession(Base):
    __tablename__ = "pomodoro_sessions"
    __table_args__ = (
        Index(
            "ix_pomodoro_sessions_user_status_start", "user_id", "status", "start_time"
        ),
        Index("ix_pomodoro_sessions_user_status_end", "user_id", "status", "end_time"),
        Index(
            "ux_pomodoro_sessions_user_client_start_id",
            "user_id",
            "client_start_id",
            unique=True,
            sqlite_where=text("client_start_id IS NOT NULL"),
            postgresql_where=text("client_start_id IS NOT NULL"),
        ),
        # Database-level concurrency guard: a user can have at most one active
        # session across both running and paused states.
        Index(
            "ux_pomodoro_sessions_one_active_per_user",
            "user_id",
            unique=True,
            sqlite_where=text("status IN ('running', 'paused')"),
            postgresql_where=text("status IN ('running', 'paused')"),
        ),
        # Post-migration invariant: a completed session always has a non-negative
        # actual_duration within its wall clock.
        CheckConstraint(
            "status != 'completed' OR (end_time >= start_time AND actual_duration >= 0)",
            name="ck_pomodoro_sessions_completed_duration",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    chapter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Client-generated idempotency key for /start. It lets a mobile client retry an
    # uncertain start without guessing which cross-device active session is its own.
    client_start_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    subject_ref = relationship("Subject", back_populates="pomodoro_sessions")
    # Default lazy load: every code path that needs intervals eager-loads them via
    # selectinload, so hot queries (history/active) do not pay an extra SELECT IN.
    pause_intervals = relationship(
        "PomodoroPauseInterval",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    subject_allocations = relationship(
        "PomodoroSubjectAllocation",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    preset: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    work_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    break_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expected_end_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    actual_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    notification_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    notification_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    notification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    notification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    openid_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Derived cache for the active-timer UI, not authoritative: pause totals are
    # computed from pomodoro_pause_intervals (the single source of truth).
    total_paused_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PomodoroSubjectAllocation(Base):
    __tablename__ = "pomodoro_subject_allocations"
    __table_args__ = (
        Index(
            "ux_pomodoro_subject_allocations_session_subject",
            "session_id",
            "subject_id",
            unique=True,
        ),
        Index(
            "ux_pomodoro_subject_allocations_session_code",
            "session_id",
            "subject_code_snapshot",
            unique=True,
        ),
        Index("ix_pomodoro_subject_allocations_subject", "subject_id"),
        CheckConstraint("weight_basis_points > 0", name="ck_pomodoro_allocation_weight_positive"),
        CheckConstraint("subject_code_snapshot <> ''", name="ck_pomodoro_allocation_code_present"),
        CheckConstraint("subject_name_snapshot <> ''", name="ck_pomodoro_allocation_name_present"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("pomodoro_sessions.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    weight_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_code_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_name_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    session = relationship("PomodoroSession", back_populates="subject_allocations")
    subject_ref = relationship("Subject")


class PomodoroPauseInterval(Base):
    __tablename__ = "pomodoro_pause_intervals"
    __table_args__ = (
        Index(
            "ix_pomodoro_pause_intervals_session_started", "session_id", "started_at"
        ),
        # At most one open pause interval per session.
        Index(
            "ux_pomodoro_pause_intervals_one_open",
            "session_id",
            unique=True,
            sqlite_where=text("ended_at IS NULL"),
            postgresql_where=text("ended_at IS NULL"),
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name="ck_pomodoro_pause_intervals_ended_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("pomodoro_sessions.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session = relationship("PomodoroSession", back_populates="pause_intervals")


class UserPomodoroSettings(Base):
    __tablename__ = "user_pomodoro_settings"

    # user_id is the primary key: one settings row per user.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day_start_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
