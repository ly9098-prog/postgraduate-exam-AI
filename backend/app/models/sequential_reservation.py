"""Durable reservations for concurrent sequential-practice starts."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SequentialReservation(Base):
    """A short-lived, database-owned claim on one sequential question.

    Rows are created by an atomic ``INSERT ... SELECT`` and removed when the
    batch is committed or when their lease expires.  The unique key is scoped
    to the user, leaf subject, and knowledge-point filter, so reservations from
    different users or independent practice scopes do not interfere.
    """

    __tablename__ = "sequential_reservations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject_id",
            "scope_key",
            "question_id",
            name="uq_sequential_reservation_question",
        ),
        Index(
            "ix_sequential_reservations_lookup",
            "user_id",
            "subject_id",
            "scope_key",
            "expires_at",
        ),
        Index(
            "ix_sequential_reservations_request",
            "user_id",
            "start_request_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    start_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
