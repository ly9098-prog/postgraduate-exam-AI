"""Phase 4 — 推荐策略权重配置。"""

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time_utils import utcnow


class RecommendationStrategyConfig(Base):
    """推荐策略配置 — 存储各场景下的权重向量。"""

    __tablename__ = "recommendation_strategy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # practice_smart / similar / knowledge_path / wrong_variant
    scene: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 权重向量
    weight_vector_similarity: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5
    )
    weight_knowledge_overlap: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.2
    )
    weight_difficulty_match: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.1
    )
    weight_mastery_gap: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.1
    )
    weight_path_priority: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.1
    )

    exploration_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)

    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self):
        return f"<RecommendationStrategyConfig name={self.name!r} scene={self.scene!r}>"
