"""Import pipeline checkpoint models（P2-1）。

把每次 PDF/图片导入的整体状态（ImportPipeline）和每个 chunk 的执行
结果（ImportPipelineChunk）落到 DB，用于：

1. 进程重启 / 内存清理后仍可查询历史 pipeline；
2. 中途失败时按 chunk 粒度断点恢复（P2-5 manual resume）；
3. 状态查询接口（P2-6）按 chunk 子表聚合 completed / failed 计数，
   不再依赖把统计塞进单条 JSON。
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ImportPipeline(Base):
    __tablename__ = "import_pipelines"

    pipeline_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportPipelineChunk(Base):
    __tablename__ = "import_pipeline_chunks"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_id", "chunk_index", name="uq_pipeline_chunks_pipeline_index"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("import_pipelines.pipeline_id"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
