"""pgvector / Embedding 配置持久化模型。

表 ``admin_vector_configs`` 以单行存储向量检索与 Embedding 服务的运行时参数，
替代原先通过环境变量配置的方式。环境变量仅作为可选兜底。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AdminVectorConfig(Base):
    """向量检索 & Embedding 配置（单行表）。"""

    __tablename__ = "admin_vector_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Vector Search ──
    vector_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    vector_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="off",
        comment="off | shadow | allowlist | all",
    )
    vector_allowlist: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
        comment='JSON array, e.g. ["exam408-ds","exam408-os"] or user ids [1,2,3]',
    )
    vector_cache_ttl_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    vector_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    vector_similarity_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.15)

    # ── Embedding ──
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_compatible")
    embedding_api_key_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    embedding_base_url: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, default="BAAI/bge-m3")
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    embedding_timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    embedding_batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=16)

    # ── Metadata ──
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )
