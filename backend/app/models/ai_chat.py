from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiChat(Base):
    __tablename__ = "ai_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    session_type: Mapped[str] = mapped_column(String(32), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    ai_response: Mapped[str] = mapped_column(Text, nullable=False)
    context_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(64), default="deepseek-chat")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
