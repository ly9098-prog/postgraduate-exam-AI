from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PracticeSession(Base):
    """一次完整刷题会话 — 用户从开始一组练习到成功交卷的一条记录。

    与 PracticeRecord（每道题一条）语义分离：
      PracticeRecord.used_time     → 单题行为分析（平均答题时间 / mastery 等）
      PracticeSession.duration_sec → 学习统计（番茄钟统计页的 duration 指标）

    一次刷题会话只对应一条记录；由 (user_id, request_id) 幂等去重，网络重试
    不会插入重复 session 导致学习时长翻倍。session 元数据在 batch-submit 时
    optional 上报（旧客户端不携带，仅不影响答题）。
    """

    __tablename__ = "practice_sessions"
    __table_args__ = (
        Index("ix_practice_sessions_user_started", "user_id", "started_at"),
        Index("ix_practice_sessions_user_finished", "user_id", "finished_at"),
        # 幂等：同一用户同一 request_id 只允许一条 session。request_id 可空以兼容
        # 旧客户端（不携带 session 时根本不写本表），故用部分唯一索引。
        Index(
            "ux_practice_sessions_user_request",
            "user_id",
            "request_id",
            unique=True,
            sqlite_where=text("request_id IS NOT NULL"),
            postgresql_where=text("request_id IS NOT NULL"),
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

    # 幂等 key。String(256) 上限内原样保存；超长由 service 层做稳定 hash，
    # 保证两个不同的超长 id 绝不因截断而合并成同一个 key（见 practice_service
    # _normalize_practice_session）。
    request_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
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
