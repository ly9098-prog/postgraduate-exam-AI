"""Production startup configuration validation — fail-fast on misconfiguration.

Each check raises ``SystemError`` (caught by lifespan) with a clear message.
Checks are skipped in development/test environments.
"""

from __future__ import annotations

import logging
import os
import re

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.startup")


def validate_production_config() -> None:
    """Run all production config checks. Raises SystemError on first failure."""
    if settings.APP_ENV != "production":
        return

    errors: list[str] = []

    # 1. APP_SECRET must not be default and must have sufficient entropy
    _check_app_secret(errors)

    # 2. DATABASE_URL must be PostgreSQL (not SQLite)
    _check_database(errors)

    # 3. REDIS_URL is required in production
    _check_redis(errors)

    # 4. CORS_ORIGINS must not contain localhost, wildcard, or invalid origins
    _check_cors(errors)

    # 5. Required directories must be writable
    _check_directories(errors)

    # 6. If OCR enabled, verify profile respects OCR_USE_GPU
    _check_ocr_profile(errors)

    if errors:
        msg = "\n".join(f"  [{i+1}] {e}" for i, e in enumerate(errors))
        raise SystemError(
            f"Production configuration failed {len(errors)} check(s):\n{msg}"
        )

    logger.info("Production configuration validated: %d checks passed", 5)


def _check_app_secret(errors: list[str]) -> None:
    secret = settings.APP_SECRET
    if secret == "change-me-in-production":
        errors.append("APP_SECRET 仍为默认值 'change-me-in-production'，请设置为随机字符串（至少 32 字符）")
    elif len(secret) < 32:
        errors.append(f"APP_SECRET 长度不足（当前 {len(secret)} 字符），至少需要 32 字符")


def _check_database(errors: list[str]) -> None:
    url = settings.DATABASE_URL
    if not url or "sqlite" in url:
        errors.append(
            "生产环境 DATABASE_URL 必须使用 PostgreSQL（当前为 SQLite）。"
            " 示例: postgresql+asyncpg://user:password@host:5432/dbname"
        )
    elif "asyncpg" not in url:
        errors.append("生产环境 DATABASE_URL 必须使用 asyncpg 驱动（postgresql+asyncpg://）")


def _check_redis(errors: list[str]) -> None:
    if not settings.REDIS_URL:
        errors.append("生产环境必须配置 REDIS_URL")


def _check_cors(errors: list[str]) -> None:
    origins = settings.CORS_ORIGINS
    if not origins:
        errors.append("生产环境 CORS_ORIGINS 不能为空")
        return
    for origin in origins:
        if origin == "*":
            errors.append("生产环境 CORS_ORIGINS 不允许使用通配符 '*'")
        elif "localhost" in origin or "127.0.0.1" in origin:
            errors.append(f"生产环境 CORS_ORIGINS 不得包含 localhost/127.0.0.1: {origin}")
        elif not _is_valid_origin(origin):
            errors.append(f"CORS_ORIGINS 包含非法 origin: {origin}")


def _check_directories(errors: list[str]) -> None:
    paths = ["static/formulas"]
    for path in paths:
        try:
            os.makedirs(path, exist_ok=True)
            if not os.access(path, os.W_OK):
                errors.append(f"目录不可写: {path}")
        except OSError as exc:
            errors.append(f"目录创建/检查失败: {path}: {exc}")


def _check_ocr_profile(errors: list[str]) -> None:
    if not settings.OCR_ENABLED:
        return
    # Profile must respect OCR_USE_GPU, not hardcode
    if settings.OCR_USE_GPU is False:
        from app.core.ocr_profile import get_ocr_profile

        profile = get_ocr_profile()
        if profile.use_gpu is True:
            errors.append(
                "OCR profile 设置了 use_gpu=True，但 OCR_USE_GPU=false。"
                " 请检查 ocr_profile.py 的生产配置。"
            )


def _is_valid_origin(origin: str) -> bool:
    """Basic origin validation: must be http:// or https:// with a host."""
    return bool(re.match(r"^https?://[a-zA-Z0-9._:-]+(?::\d{1,5})?$", origin))
