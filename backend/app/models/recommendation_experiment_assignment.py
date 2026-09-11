"""Phase 4 — 实验用户分组分配。"""

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time_utils import utcnow


class RecommendationExperimentAssignment(Base):
    """记录用户在某实验中的分组分配。"""

    __tablename__ = "recommendation_experiment_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    experiment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("recommendation_experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    variant_key: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    assigned_at = mapped_column(DateTime, nullable=False, default=utcnow)
    created_at = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "user_id",
            name="uq_rea_experiment_user",
        ),
    )

    def __repr__(self):
        return (
            f"<RecommendationExperimentAssignment "
            f"exp={self.experiment_id} user={self.user_id} variant={self.variant_key!r}>"
        )
