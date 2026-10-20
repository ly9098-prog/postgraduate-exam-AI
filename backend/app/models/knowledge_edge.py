"""Phase 3 — 知识图谱边模型。"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.orm_base import Base
from app.core.time_utils import utcnow


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subject_id = Column(
        Integer,
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    subject_ref = relationship(
        "Subject", back_populates="knowledge_edges", lazy="noload"
    )

    source_knowledge_point_id = Column(
        Integer,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_knowledge_point_id = Column(
        Integer,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # prerequisite / parent / related / next
    relation_type = Column(String(16), nullable=False, index=True)

    weight = Column(Float, nullable=False, default=1.0)
    confidence = Column(Float, nullable=False, default=1.0)

    # manual / imported / ai / inferred
    source = Column(String(16), nullable=False, default="manual")

    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # relationships
    source_kp = relationship(
        "KnowledgePoint",
        foreign_keys=[source_knowledge_point_id],
        lazy="selectin",
    )
    target_kp = relationship(
        "KnowledgePoint",
        foreign_keys=[target_knowledge_point_id],
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "source_knowledge_point_id",
            "target_knowledge_point_id",
            "relation_type",
            name="uq_ke_source_target_relation",
        ),
        Index("ix_ke_subject_id_relation", "subject_id", "relation_type"),
    )

    def __repr__(self):
        return (
            f"<KnowledgeEdge id={self.id} subject_id={self.subject_id} "
            f"{self.source_knowledge_point_id} --[{self.relation_type}]--> "
            f"{self.target_knowledge_point_id}>"
        )
