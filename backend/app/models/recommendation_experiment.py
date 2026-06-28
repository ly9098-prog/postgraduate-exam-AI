"""Phase 4 — A/B 推荐实验定义。"""
from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time_utils import utcnow


class RecommendationExperiment(Base):
    """推荐 A/B 实验。

    variants 示例:
    [
        {"key": "A", "strategy": "random", "ratio": 0.25},
        {"key": "B", "strategy": "weakness_vector", "ratio": 0.25},
        {"key": "C", "strategy": "knowledge_path", "ratio": 0.25},
        {"key": "D", "strategy": "similar_vector", "ratio": 0.25}
    ]
    """

    __tablename__ = "recommendation_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    # practice_smart / similar / knowledge_path
    scene: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    description: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # draft / running / paused / finished
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    start_at = mapped_column(DateTime, nullable=True)
    end_at = mapped_column(DateTime, nullable=True)

    traffic_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    variants: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Phase 4.5: safety valve fields
    max_traffic_percent: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    fallback_strategy_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auto_pause_on_error_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    started_at = mapped_column(DateTime, nullable=True)
    ended_at = mapped_column(DateTime, nullable=True)

    created_at = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def __repr__(self):
        return f"<RecommendationExperiment name={self.name!r} status={self.status!r}>"
