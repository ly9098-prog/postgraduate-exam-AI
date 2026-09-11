from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.features.question_type import QT_SINGLE_CHOICE


class PracticeRecord(Base):
    """用户做题记录 — 每道题一条记录"""

    __tablename__ = "practice_records"
    __table_args__ = (
        Index("idx_practice_records_user_subject_id", "user_id", "subject_id"),
        # 与 alembic v1_no_repeat_idx 对齐：覆盖 "用户最近 N 天做题" 统计窗口
        Index(
            "idx_practice_records_user_answered_question",
            "user_id",
            "answered_at",
            "question_id",
        ),
        Index(
            "ix_practice_records_projection_state_answered",
            "projection_state",
            "answered_at",
        ),
        CheckConstraint(
            "projection_state IN ('pending','completed','revision_only','archived')",
            name="ck_practice_records_projection_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    question_version_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("question_versions.id"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id"), nullable=False
    )
    subject_ref = relationship(
        "Subject", back_populates="practice_records", lazy="noload"
    )
    question_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=QT_SINGLE_CHOICE
    )
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    used_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # Durable projection lifecycle. Reconciliation only repairs ``pending``.
    # ``revision_only`` means immutable revision projections were applied but
    # mutable question-state projections were intentionally skipped because the
    # question has since advanced to another revision. ``archived`` is the
    # migration terminal state for pre-revision records whose async lifecycle
    # cannot be reconstructed safely.
    projection_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )

    # Session type is meaningful per answer and is used by behavior analytics.
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
