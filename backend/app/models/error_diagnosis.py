from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WrongQuestionErrorDiagnosis(Base):
    """One immutable wrong-answer occurrence plus its evolving error diagnosis.

    ``WrongQuestion`` intentionally remains a de-duplicated wrong-book row per
    user/question. This table is the occurrence-level fact source used by
    408-ERROR so repeated mistakes can carry different causes and can be
    aggregated over real time windows.
    """

    __tablename__ = "wrong_question_error_diagnoses"
    __table_args__ = (
        UniqueConstraint(
            "practice_record_id",
            name="uq_wrong_error_diagnoses_practice_record",
        ),
        UniqueConstraint(
            "exam_answer_id",
            name="uq_wrong_error_diagnoses_exam_answer",
        ),
        CheckConstraint(
            "source_context IN ('practice','exam','legacy')",
            name="ck_wrong_error_diagnoses_source_context",
        ),
        CheckConstraint(
            "ai_status IN ('not_requested','pending','suggested','failed')",
            name="ck_wrong_error_diagnoses_ai_status",
        ),
        CheckConstraint(
            "classification_version >= 1",
            name="ck_wrong_error_diagnoses_classification_version",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ck_wrong_error_diagnoses_ai_confidence",
        ),
        Index(
            "ix_wrong_error_diagnoses_user_occurred",
            "user_id",
            "occurred_at",
        ),
        Index(
            "ix_wrong_error_diagnoses_wq_occurred",
            "wrong_question_id",
            "occurred_at",
        ),
        Index(
            "ix_wrong_error_diagnoses_user_primary",
            "user_id",
            "user_primary_type",
        ),
        Index(
            "ix_wrong_error_diagnoses_ai_primary",
            "user_id",
            "ai_primary_type",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wrong_question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wrong_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    question_version_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("question_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    practice_record_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("practice_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    exam_answer_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("exam_answers.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_context: Mapped[str] = mapped_column(String(16), nullable=False)
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    taxonomy_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="408-error-v1",
        server_default="408-error-v1",
    )
    classification_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    # AI suggestion is deliberately separate from the learner-confirmed truth.
    ai_primary_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_secondary_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="not_requested",
        server_default="not_requested",
    )
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_suggested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Learner confirmation always wins when an effective diagnosis is resolved.
    user_primary_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_secondary_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    user_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )
