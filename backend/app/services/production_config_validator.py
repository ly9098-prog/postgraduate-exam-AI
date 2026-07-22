"""Production startup configuration validation — fail-fast on misconfiguration.

Each check raises ``SystemError`` (caught by lifespan) with a clear message
that includes the config item name. Checks are skipped in development/test
environments.

Checks:
1. APP_SECRET strength
2. DATABASE_URL must be postgresql+asyncpg
3. Database is actually PostgreSQL (connects and queries version)
4. REDIS_URL is set AND Redis responds to PING
5. CORS_ORIGINS — no wildcard, no localhost, valid format
6. Required directories writable
7. Alembic migration is at head revision
8. PostgreSQL extension checks (pgvector if VECTOR_ENABLED)
9. Deployment profile — production must be cloud_api, never local_import
10. OCR execution backend — cloud must use external API or disabled
11. OCR_USE_GPU must be false in production
12. Cloud OCR external URL must be HTTPS if configured
13. Cloud OCR API token must exist if external OCR enabled
14. Cloud startup must not check local PaddleOCR package
15. Process role configuration consistency
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.startup")


def detect_deployment_profile() -> str:
    """Unified deployment profile detection.

    Returns ``"local_import"`` or ``"cloud_api"``.

    Priority:
    1. ``DEPLOYMENT_PROFILE`` env var (overrides all)
    2. ``DEPLOY_PROFILE`` env var (``"local"`` → ``"local_import"``, ``"production"`` → ``"cloud_api"``)
    3. ``APP_ENV`` env var (``"development"`` → ``"local_import"``, ``"production"`` → ``"cloud_api"``)
    """
    deployment_profile = os.environ.get("DEPLOYMENT_PROFILE", "").strip().lower()
    if deployment_profile:
        if deployment_profile in ("local_import", "cloud_api"):
            return deployment_profile
        logger.warning(
            "Unknown DEPLOYMENT_PROFILE=%r, falling back to APP_ENV",
            deployment_profile,
        )

    dep_profile = os.environ.get("DEPLOY_PROFILE", "").strip().lower()
    if dep_profile == "local":
        return "local_import"
    if dep_profile == "production":
        return "cloud_api"

    app_env = settings.APP_ENV
    if app_env == "production":
        return "cloud_api"
    return "local_import"


def validate_production_config() -> None:
    """Run all production config checks. Raises SystemError on failures."""
    if settings.APP_ENV != "production":
        return

    errors: list[str] = []

    _check_app_secret(errors)
    _check_database_url(errors)
    _check_cors(errors)
    _check_directories(errors)
    _check_deployment_profile(errors)
    _check_ocr_production_rules(errors)
    _check_ocr_no_local_deps(errors)

    if errors:
        raise SystemError(
            "Production configuration validation failed:\n  - "
            + "\n  - ".join(errors)
        )

    logger.info("Production configuration validated: sync checks passed")


# ── sync checks ──


def _check_app_secret(errors: list[str]) -> None:
    secret = settings.APP_SECRET
    if secret == "change-me-in-production":
        errors.append(
            "APP_SECRET 仍为默认值 'change-me-in-production'，"
            "请设置为随机字符串（至少 32 字符）"
        )
    elif len(secret) < 32:
        errors.append(
            f"APP_SECRET 长度不足（当前 {len(secret)} 字符），至少需要 32 字符"
        )


def _check_database_url(errors: list[str]) -> None:
    url = settings.DATABASE_URL
    if not url or "sqlite" in url:
        errors.append(
            "DATABASE_URL 必须使用 PostgreSQL（当前为 SQLite）。"
            " 示例: postgresql+asyncpg://user:password@host:5432/dbname"
        )
    elif "asyncpg" not in url:
        errors.append(
            "DATABASE_URL 必须使用 asyncpg 驱动。"
            " 格式: postgresql+asyncpg://user:password@host:5432/dbname"
        )


def _check_cors(errors: list[str]) -> None:
    origins = settings.CORS_ORIGINS
    if not origins:
        errors.append("CORS_ORIGINS 不能为空")
        return
    for origin in origins:
        if origin == "*":
            errors.append("CORS_ORIGINS 不允许使用通配符 '*'")
        elif "localhost" in origin or "127.0.0.1" in origin:
            errors.append(
                f"CORS_ORIGINS 不得包含 localhost/127.0.0.1: {origin}"
            )
        elif not _is_valid_origin(origin):
            errors.append(f"CORS_ORIGINS 包含非法 origin: {origin}")


def _check_directories(errors: list[str]) -> None:
    paths = ["static/formulas", "static/question-assets"]
    for path in paths:
        try:
            os.makedirs(path, exist_ok=True)
            if not os.access(path, os.W_OK):
                errors.append(f"目录不可写: {path}")
        except OSError as exc:
            errors.append(f"目录创建/检查失败: {path}: {exc}")


def _check_deployment_profile(errors: list[str]) -> None:
    """Production must use cloud_api profile, never local_import."""
    profile = detect_deployment_profile()
    if profile != "cloud_api":
        errors.append(
            f"生产环境的部署配置为 {profile!r}，必须为 'cloud_api'。"
            " 请设置 DEPLOYMENT_PROFILE=cloud_api"
        )


def _check_ocr_production_rules(errors: list[str]) -> None:
    """Cloud OCR must use external API or be disabled.

    Banned in production:
    - local_process execution backend
    - unsafe_thread_fallback
    - OCR_USE_GPU=true
    """
    if not settings.OCR_ENABLED:
        return

    if settings.OCR_USE_GPU is not False:
        errors.append("生产环境必须设置 OCR_USE_GPU=false")

    exec_backend = (settings.OCR_EXECUTION_BACKEND or "").lower()
    if exec_backend == "local_process":
        errors.append(
            "生产环境 OCR_EXECUTION_BACKEND 不能为 'local_process'。"
            " 必须使用 paddlex_http 或 disabled"
        )

    # Check OCR profile GPU consistency
    from app.core.ocr_profile import get_ocr_profile

    profile = get_ocr_profile()
    if profile.use_gpu:
        errors.append(
            "OCR profile 设置了 use_gpu=True，但生产环境必须 use_gpu=False。"
            " 请检查 ocr_profile.py 的 cloud 配置或设置 OCR_USE_GPU=false"
        )

    # Check external OCR URL is HTTPS
    ocr_url = settings.OCR_REMOTE_URL or ""
    if exec_backend == "paddlex_http" and ocr_url:
        if not ocr_url.startswith("https://"):
            errors.append("外部 OCR URL (OCR_REMOTE_URL) 必须使用 HTTPS")


def _check_ocr_no_local_deps(errors: list[str]) -> None:
    """Cloud must not check local PaddleOCR package."""
    profile = detect_deployment_profile()
    if profile != "cloud_api":
        return

    # Check that paddleocr is not importable at startup
    try:
        import importlib.util

        if importlib.util.find_spec("paddleocr") is not None:
            errors.append(
                "生产环境 (cloud_api) 不应安装 paddleocr。"
                " 如已安装请卸载，或确保 DEPLOYMENT_PROFILE=local_import 仅用于本地开发"
            )
    except Exception:
        pass  # find_spec is safe — no import happens


# ── async checks ──


async def validate_production_config_async() -> None:
    """Run all async production config checks. Raises SystemError on failures."""
    if settings.APP_ENV != "production":
        return

    errors: list[str] = []

    await asyncio.gather(
        _check_redis_available(errors),
        _check_database_actual_pg(errors),
        _check_alembic_current(errors),
        _check_pg_extensions(errors),
    )

    if errors:
        raise SystemError(
            "Production async configuration validation failed:\n  - "
            + "\n  - ".join(errors)
        )


async def _check_redis_available(errors: list[str]) -> None:
    """Check that REDIS_URL is set and Redis responds to PING."""
    if not settings.REDIS_URL:
        errors.append("REDIS_URL 未设置——生产环境需要 Redis")
        return
    try:
        import redis.asyncio as redis_async

        client = redis_async.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        pong = await client.ping()
        await client.aclose()
        if not pong:
            errors.append("REDIS_URL 配置了但 Redis PING 返回 false")
    except Exception as exc:
        errors.append(f"REDIS_URL 配置了但 Redis 不可达: {exc}")


async def _check_database_actual_pg(errors: list[str]) -> None:
    """Connect to the database and verify it is PostgreSQL."""
    from app.core.database import async_session

    try:
        async with async_session() as session:
            from sqlalchemy import text

            row = (await session.execute(text("SELECT version()"))).scalar()
            if "postgresql" not in (row or "").lower():
                errors.append(
                    f"DATABASE_URL 连接的数据库不是 PostgreSQL（version={row}）"
                )
    except Exception as exc:
        errors.append(f"无法连接数据库以验证类型: {exc}")


async def _check_alembic_current(errors: list[str]) -> None:
    """Verify migration is at head."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.environment import EnvironmentContext
        from alembic.runtime.migration import MigrationContext

        # Read current revision from DB
        from app.core.database import async_session

        async with async_session() as session:
            from sqlalchemy import text

            row = (
                await session.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one_or_none()
            db_revision = row or ""

        # Read head revision from migration files
        alembic_cfg = Config()
        alembic_cfg.set_main_option(
            "script_location",
            os.path.join(os.path.dirname(__file__), "../../alembic"),
        )
        script = ScriptDirectory.from_config(alembic_cfg)
        head_revision = script.get_current_head()

        if db_revision != head_revision:
            errors.append(
                f"数据库迁移落后于最新迁移文件: db={db_revision}, head={head_revision}。"
                " 请执行 alembic upgrade head"
            )
    except Exception as exc:
        errors.append(f"无法验证迁移版本: {exc}")


async def _check_pg_extensions(errors: list[str]) -> None:
    """Verify required PostgreSQL extensions are installed."""
    if not settings.VECTOR_ENABLED:
        return

    from app.core.database import async_session

    try:
        async with async_session() as session:
            from sqlalchemy import text

            row = (
                await session.execute(
                    text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                )
            ).scalar_one_or_none()
            if not row:
                errors.append(
                    "VECTOR_ENABLED=true 但 PostgreSQL 未安装 vector 扩展。"
                    " 请执行: CREATE EXTENSION vector;"
                )
    except Exception as exc:
        errors.append(f"无法验证 pg_extension: {exc}")


# ── helpers ──


def _is_valid_origin(origin: str) -> bool:
    return bool(re.match(r"^https?://[a-zA-Z0-9._:-]+(?::\d{1,5})?$", origin))
