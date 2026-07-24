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
16. Staging directory writable with sufficient free space
17. DB connection pool budget within MAX_CONNECTIONS
18. Queue capacity limits are reasonable
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys

from app.core.config import settings
from app.core.deployment_profile import detect_deployment_profile, DeploymentProfile

logger = logging.getLogger("postgraduate-ai.startup")


def validate_production_config() -> None:
    """Run all production config checks. Raises SystemError on failures.

    Runs when APP_ENV=production OR DeploymentProfile=CLOUD_API
    (whichever is more restrictive).
    """
    if not _is_restricted_environment():
        return

    errors: list[str] = []

    _check_app_secret(errors)
    _check_database_url(errors)
    _check_cors(errors)
    _check_directories(errors)
    _check_deployment_profile(errors)
    _check_process_role(errors)
    _check_ocr_production_rules(errors)
    _check_ocr_no_local_deps(errors)
    _check_staging_production(errors)
    _check_db_pool_budget(errors)
    _check_queue_capacity(errors)

    if errors:
        raise SystemError(
            "Production configuration validation failed:\n  - "
            + "\n  - ".join(errors)
        )

    logger.info("Production configuration validated: sync checks passed")


def _is_restricted_environment() -> bool:
    """Check if the current deployment is production or cloud_api.

    Per current_task.md spec:
        is_restricted_environment = (
            APP_ENV == "production"
            or detect_deployment_profile() == DeploymentProfile.CLOUD_API
        )
    """
    if settings.APP_ENV == "production":
        return True
    try:
        profile = detect_deployment_profile()
        return profile == DeploymentProfile.CLOUD_API
    except Exception:
        return False


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


def _check_process_role(errors: list[str]) -> None:
    """Validate PROCESS_ROLE. Restricted environments must not use 'all'."""
    role = settings.PROCESS_ROLE
    valid_roles = ("web", "worker", "scheduler")
    if role == "all":
        errors.append(
            f"PROCESS_ROLE=all is forbidden in production/cloud_api. "
            f"Must be one of: {', '.join(valid_roles)}"
        )
    elif role not in valid_roles + ("all",):
        errors.append(
            f"PROCESS_ROLE={role!r} is invalid, must be one of: {', '.join(valid_roles + ('all',))}"
        )


def _check_deployment_profile(errors: list[str]) -> None:
    """Production must use cloud_api profile, never local_import."""
    if detect_deployment_profile() != DeploymentProfile.CLOUD_API:
        errors.append(
            f"生产环境的部署配置不是 cloud_api，必须设置 DEPLOYMENT_PROFILE=cloud_api"
        )


def _check_ocr_production_rules(errors: list[str]) -> None:
    """Cloud OCR must use external API or be disabled.

    Even when OCR is disabled, we check GPU and backend settings to
    prevent unsafe configuration drift.

    Banned in production:
    - local_process execution backend
    - unsafe_thread_fallback
    - OCR_USE_GPU=true
    """
    # Always check GPU setting (must be false in restricted environments)
    if settings.OCR_USE_GPU is not False:
        errors.append("生产环境必须设置 OCR_USE_GPU=false")

    exec_backend = (settings.OCR_EXECUTION_BACKEND or "").lower()
    ALLOWED_CLOUD_BACKENDS = {"paddlex_http", "disabled"}
    if exec_backend not in ALLOWED_CLOUD_BACKENDS:
        errors.append(
            f"生产环境 OCR_EXECUTION_BACKEND='{exec_backend}' 不允许。"
            f" 必须为以下之一: {', '.join(sorted(ALLOWED_CLOUD_BACKENDS))}"
        )

    # Check OCR profile GPU consistency
    from app.core.ocr_profile import get_ocr_profile

    try:
        profile = get_ocr_profile()
        if profile.use_gpu:
            errors.append(
                "OCR profile 设置了 use_gpu=True，但生产环境必须 use_gpu=False。"
                " 请检查 ocr_profile.py 的 cloud 配置或设置 OCR_USE_GPU=false"
            )
    except Exception as exc:
        errors.append(f"OCR profile 检查失败: {exc}")

    if not settings.OCR_ENABLED:
        # When OCR is disabled, the above checks on backend/GPU are sufficient
        if settings.OCR_REMOTE_URL and exec_backend == "disabled":
            logger.warning(
                "OCR_REMOTE_URL set but OCR_EXECUTION_BACKEND=disabled — "
                "remote URL config is unused but harmless"
            )
        return

    # OCR enabled — check fallback flags (must be false in production)
    if os.environ.get("OCR_REMOTE_FALLBACK_ENABLED") == "1":
        errors.append(
            "生产环境禁止设置 OCR_REMOTE_FALLBACK_ENABLED=1。"
            " OCR 失败不得回退到本地处理。"
        )

    if os.environ.get("OCR_UNSAFE_THREAD_FALLBACK_ENABLED") == "1":
        errors.append(
            "生产环境禁止设置 OCR_UNSAFE_THREAD_FALLBACK_ENABLED=1。"
            " OCR 必须使用进程隔离 worker。"
        )

    # OCR enabled — additional checks
    # Check external OCR URL is HTTPS
    ocr_url = settings.OCR_REMOTE_URL or ""
    if exec_backend == "paddlex_http" and ocr_url:
        if not ocr_url.startswith("https://"):
            errors.append("外部 OCR URL (OCR_REMOTE_URL) 必须使用 HTTPS")
        if not settings.OCR_REMOTE_TOKEN:
            errors.append(
                "外部 OCR 已启用 (OCR_EXECUTION_BACKEND=paddlex_http) "
                "但 OCR_REMOTE_TOKEN 未设置"
            )


def _check_ocr_no_local_deps(errors: list[str]) -> None:
    """Fail startup if PaddleOCR is installed in cloud_api deployment.

    In cloud_api, the process must never import or initialize local OCR
    packages. Having paddleocr/paddle installed represents a configuration
    hazard that could lead to accidental local fallback on failure.
    """
    profile = detect_deployment_profile()
    if profile != DeploymentProfile.CLOUD_API:
        return

    banned_modules = ["paddleocr", "paddle"]
    for mod in banned_modules:
        try:
            import importlib.util
            if importlib.util.find_spec(mod) is not None:
                errors.append(
                    f"cloud_api 部署检测到 {mod} 已安装。"
                    f" 云端部署不得包含本地 OCR 包。请卸载: pip uninstall {mod}"
                )
        except Exception:
            pass


def _check_staging_production(errors: list[str]) -> None:
    """Verify staging directory exists, is writable, and has free space."""
    staging_dir = settings.STAGING_STORAGE_DIR or ""
    if not staging_dir:
        errors.append("STAGING_STORAGE_DIR is not set — staging is required in production")
        return
    try:
        os.makedirs(staging_dir, exist_ok=True)
        if not os.access(staging_dir, os.W_OK):
            errors.append(f"STAGING_STORAGE_DIR 不可写: {staging_dir}")
            return
        st = os.statvfs(staging_dir)
        free_bytes = st.f_frsize * st.f_bavail
        min_free = settings.STAGING_DISK_QUOTA // 2
        if free_bytes < min_free:
            errors.append(
                f"STAGING_STORAGE_DIR 剩余空间不足: "
                f"{free_bytes / (1024*1024):.0f}MB free, need at least {min_free / (1024*1024):.0f}MB"
            )
    except OSError as exc:
        errors.append(f"STAGING_STORAGE_DIR 检查失败: {staging_dir}: {exc}")


def _check_db_pool_budget(errors: list[str]) -> None:
    """Verify DB pool size * Gunicorn workers does not exceed MAX_CONNECTIONS."""
    workers = settings.GUNICORN_WORKERS or 1
    web_per_worker = settings.DB_POOL_SIZE_WEB + settings.DB_MAX_OVERFLOW_WEB
    web_total = web_per_worker * workers
    worker_total = settings.DB_POOL_SIZE_WORKER + settings.DB_MAX_OVERFLOW_WORKER
    scheduler_total = settings.DB_POOL_SIZE_SCHEDULER + settings.DB_MAX_OVERFLOW_SCHEDULER
    worst_case = web_total + worker_total + scheduler_total
    max_connections = settings.MAX_CONNECTIONS
    if worst_case > max_connections:
        errors.append(
            f"DB 连接预算超限: 预估最大 {worst_case} 连接 "
            f"(web={web_total} worker={worker_total} scheduler={scheduler_total}), "
            f"但 MAX_CONNECTIONS={max_connections}"
        )


def _check_queue_capacity(errors: list[str]) -> None:
    """Verify queue capacity is reasonable in production."""
    from app.services.task_queue_service import MAX_QUEUE_SIZE, MAX_DEAD_SIZE
    if not isinstance(MAX_QUEUE_SIZE, int) or MAX_QUEUE_SIZE < 1:
        errors.append(f"队列容量 MAX_QUEUE_SIZE={MAX_QUEUE_SIZE} 不合理")
    if MAX_QUEUE_SIZE > 10000:
        errors.append(f"队列容量 MAX_QUEUE_SIZE={MAX_QUEUE_SIZE} 过大")
    if not isinstance(MAX_DEAD_SIZE, int) or MAX_DEAD_SIZE < 1:
        errors.append(f"dead-letter 容量 MAX_DEAD_SIZE={MAX_DEAD_SIZE} 不合理")


# ── async checks ──


async def validate_production_config_async() -> None:
    """Run all async production config checks. Raises SystemError on failures."""
    if not _is_restricted_environment():
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
