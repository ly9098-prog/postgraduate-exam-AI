"""Phase 4 — 推荐指标每日聚合。"""

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.orm_base import Base
from app.core.time_utils import utcnow


class RecommendationMetricsDaily(Base):
    """按日聚合的推荐指标，避免每次查询扫原始日志。"""

    __tablename__ = "recommendation_metrics_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    date = mapped_column(Date, nullable=False, index=True)
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subject_ref = relationship(
        "Subject", back_populates="recommendation_metrics_daily", lazy="noload"
    )

    # practice_smart / similar / knowledge_path
    scene: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # random / weakness_vector / knowledge_path / smart_vector / ...
    strategy: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    variant_key: Mapped[str | None] = mapped_column(
        String(16), nullable=True, index=True
    )

    # 曝光 / 点击 / 答题
    exposure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 平均分 / 相似度 / 掌握度
    avg_recommend_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    avg_similarity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_mastery_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_mastery_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_mastery_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 派生指标
    completion_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ctr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "date",
            "subject_id",
            "scene",
            "strategy",
            "variant_key",
            name="uq_rmd_date_subject_id_scene_strategy_variant",
        ),
    )

    def __repr__(self):
        return (
            f"<RecommendationMetricsDaily date={self.date} "
            f"subject_id={self.subject_id} scene={self.scene!r} strategy={self.strategy!r}>"
        )
