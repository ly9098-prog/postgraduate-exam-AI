from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PracticeSession(Base):
    """一次完整刷题会话 — 用户从开始一组练习到成功交卷的一条记录。

    与 PracticeRecord（每道题一条）语义分离：
      PracticeRecord.used_time     → 单题行为分析（平均答题时间 / mastery 等）
      PracticeSession.duration_sec → 学习统计（番茄钟统计页的 duration 指标）

    一次刷题会话只对应一条记录；由 (user_id, request_id) 幂等去重。
    batch-submit 必须携带服务器签发批次与完整 session 元数据。
    """

    __tablename__ = "practice_sessions"
    __table_args__ = (
        Index("ix_practice_sessions_user_started", "user_id", "started_at"),
        Index("ix_practice_sessions_user_finished", "user_id", "finished_at"),
        Index(
            "ix_practice_sessions_user_scope_finished",
            "user_id",
            "scope_type",
            "scope_root_knowledge_point_id",
            "finished_at",
        ),
        # 幂等：同一用户同一 request_id 只允许一条 session。
        Index(
            "ux_practice_sessions_user_request",
            "user_id",
            "request_id",
            unique=True,
        ),
        CheckConstraint(
            "duration_sec >= 0",
            name="ck_practice_sessions_duration_sec",
        ),
        CheckConstraint(
            "finished_at >= started_at",
            name="ck_practice_sessions_finished_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id"), nullable=False, index=True
    )
    subject_ref = relationship("Subject", back_populates="practice_sessions", lazy="noload")

    # 幂等 key；服务层强制非空并限制长度。
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # Canonical idempotency state for batch-submit.  These fields belong to the
    # session rather than an arbitrary PracticeRecord so all-skipped batches and
    # future answer-history cleanup remain recoverable.
    submission_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submission_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Durable semantic scope of the issued batch. ``mode`` below still describes
    # the selection algorithm (random/smart/etc.); scope_type describes user intent
    # such as a single knowledge point or an entire knowledge chapter.  The root id
    # intentionally has no FK: historical sessions remain auditable even if a
    # knowledge-point row is retired or physically removed in a future migration.
    scope_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope_root_knowledge_point_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="random")

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)

    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 只在成功交卷时创建，恒为 completed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
