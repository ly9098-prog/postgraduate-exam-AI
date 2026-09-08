from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StudyPlan(Base):
    """One long-horizon 408 preparation plan per learner.

    The plan stores only user intent/configuration. Practice, review, exam and
    focus records remain the authoritative learning facts.
    """

    __tablename__ = "study_plans"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_study_plans_user"),
        CheckConstraint(
            "daily_minutes >= 15 AND daily_minutes <= 720",
            name="ck_study_plans_daily_minutes",
        ),
        CheckConstraint(
            "weekly_days >= 1 AND weekly_days <= 7",
            name="ck_study_plans_weekly_days",
        ),
        CheckConstraint(
            "priority_mode IN ('balanced','review','weakness','new','exam')",
            name="ck_study_plans_priority_mode",
        ),
        CheckConstraint("revision >= 1", name="ck_study_plans_revision_positive"),
        Index("ix_study_plans_active_target", "is_active", "target_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    weekly_days: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    priority_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="balanced", server_default="balanced"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    days: Mapped[list["StudyPlanDay"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="noload",
    )


class StudyPlanDay(Base):
    """Stable per-day allocation snapshot for a StudyPlan revision.

    Completion is never stored here. It is projected from the existing learning
    fact tables so users never need a second "check-in" action after studying.
    """

    __tablename__ = "study_plan_days"
    __table_args__ = (
        UniqueConstraint("plan_id", "plan_date", name="uq_study_plan_days_plan_date"),
        CheckConstraint("plan_revision >= 1", name="ck_study_plan_days_revision_positive"),
        CheckConstraint("target_minutes >= 0", name="ck_study_plan_days_target_nonnegative"),
        Index("ix_study_plan_days_plan_date", "plan_id", "plan_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("study_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_rest_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    allocation_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    basis_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    plan: Mapped[StudyPlan] = relationship(back_populates="days", lazy="noload")
