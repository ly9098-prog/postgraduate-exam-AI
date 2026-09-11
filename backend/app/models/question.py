from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.features.question_type import QT_SINGLE_CHOICE


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        Index(
            "ix_questions_coverage_scope", "subject_id", "review_status", "is_active"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id"), nullable=False, index=True
    )

    subject_ref = relationship("Subject", back_populates="questions", lazy="noload")
    question_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=QT_SINGLE_CHOICE
    )
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    question_hash: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[list | None] = mapped_column(JSON, nullable=True)
    year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    review_status: Mapped[str] = mapped_column(String(16), default="approved")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    sync_uuid: Mapped[str | None] = mapped_column(
        String(36), nullable=True, unique=True, index=True, default=lambda: str(uuid4())
    )
    sync_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Immutable revision currently backing this mutable projection row.
    # Every published/active question must point at one QuestionVersion revision.
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("question_versions.id"),
        nullable=True,
        index=True,
    )

    # 知识点关联（关联表为唯一事实源）。
    # knowledge_point_links 保留 association metadata（role/weight/source/position）。
    # lazy=noload + passive_deletes：硬删题目时交由 DB ON DELETE CASCADE 清理关联行，
    # 而非加载集合触发 delete-orphan（否则该 cascade 在 noload 下永不生效）。
    knowledge_point_links = relationship(
        "QuestionKnowledgePoint",
        back_populates="question",
        lazy="noload",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    kp_links = relationship(
        "KnowledgePoint",
        secondary="question_knowledge_points",
        viewonly=True,
        lazy="noload",
        order_by="(QuestionKnowledgePoint.position, QuestionKnowledgePoint.id)",
    )
