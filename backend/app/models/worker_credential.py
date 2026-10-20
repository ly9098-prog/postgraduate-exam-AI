"""Worker credential model — hashed API key with rotation and active/disabled support.

Design:
- Only SHA-256 hashes are stored in the database (never plaintext keys).
- Each worker has its own credential with is_active flag.
- Rotation: old key is disabled (not deleted), new key is created.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm_base import Base


class WorkerCredential(Base):
    __tablename__ = "worker_credentials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
