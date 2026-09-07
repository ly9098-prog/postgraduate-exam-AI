from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SyllabusVersion(Base):
    """Versioned 408 syllabus definition.

    Subject remains the stable product taxonomy. A syllabus version only decides
    which canonical knowledge points are in scope and freezes their display
    semantics for that version.
    """

    __tablename__ = "syllabus_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    root_subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    effective_year: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    knowledge_points: Mapped[list["SyllabusKnowledgePoint"]] = relationship(
        back_populates="syllabus_version", cascade="all, delete-orphan", lazy="noload"
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft','active','archived')", name="ck_syllabus_versions_status"),
        CheckConstraint("effective_year >= 2000 AND effective_year <= 2200", name="ck_syllabus_versions_year"),
        Index(
            "uq_syllabus_versions_one_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )


class SyllabusKnowledgePoint(Base):
    """Membership + immutable semantic snapshot of one KP in one syllabus."""

    __tablename__ = "syllabus_knowledge_points"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    syllabus_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("syllabus_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_point_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_points.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    description_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty_level_snapshot: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    syllabus_version: Mapped[SyllabusVersion] = relationship(back_populates="knowledge_points", lazy="noload")
    knowledge_point = relationship("KnowledgePoint", lazy="noload")

    __table_args__ = (
        UniqueConstraint("syllabus_version_id", "knowledge_point_id", name="uq_syllabus_version_kp"),
        CheckConstraint("difficulty_level_snapshot >= 1 AND difficulty_level_snapshot <= 5", name="ck_syllabus_kp_difficulty"),
    )


class SyllabusKnowledgePointMapping(Base):
    """Trace how old syllabus semantics map into a new syllabus version."""

    __tablename__ = "syllabus_knowledge_point_mappings"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    from_syllabus_knowledge_point_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("syllabus_knowledge_points.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    to_syllabus_knowledge_point_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("syllabus_knowledge_points.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "relation_type IN ('unchanged','renamed','added','removed','merged','split','replaced')",
            name="ck_syllabus_kp_mapping_type",
        ),
        CheckConstraint(
            "from_syllabus_knowledge_point_id IS NOT NULL OR to_syllabus_knowledge_point_id IS NOT NULL",
            name="ck_syllabus_kp_mapping_endpoint",
        ),
    )
