import logging
from datetime import datetime

from cryptography.fernet import Fernet
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet | None:
    key = settings.AI_CONFIG_ENCRYPT_KEY
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        return None


def encrypt_api_key(plain: str) -> str:
    f = _get_fernet()
    if f is None:
        logger.warning("AI_CONFIG_ENCRYPT_KEY not configured — API key stored in plain text")
        return plain
    return f.encrypt(plain.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    f = _get_fernet()
    if f is None:
        logger.warning("AI_CONFIG_ENCRYPT_KEY not configured — API key returned as-is")
        return encrypted
    try:
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        logger.error("Failed to decrypt API key — key may have been rotated")
        return ""


class AdminAiModelConfig(Base):
    __tablename__ = "admin_ai_model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    api_base_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 旧字段（单个 feature，向后兼容）
    feature: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    # 新字段（多 feature 支持，JSON 数组如 ["ocr","vision"]）
    features: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AdminAiConfig(Base):
    __tablename__ = "admin_ai_configs"

    config_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    config_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
