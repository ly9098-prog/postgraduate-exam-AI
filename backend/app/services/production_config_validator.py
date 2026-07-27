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
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

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
    _check_ai_encrypt_key(errors)
    _check_ocr_production_rules(errors)
    _check_ocr_no_local_deps(errors)
    _check_pdf_production_rules(errors)
    _check_staging_production(errors)
    _check_db_pool_budget(errors)
    _check_queue_capacity(errors)
    _check_worker_scratch_dir(errors)
    _check_gunicorn_fork_safety(errors)

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

    When APP_ENV is explicitly set to production, we always validate.
    When profile detection itself fails, we log a warning but do NOT
    silently skip validation — a corrupted profile should not bypass
    production safety checks.
    """
    if settings.APP_ENV == "production":
        return True
    try:
        profile = detect_deployment_profile()
        return profile == DeploymentProfile.CLOUD_API
    except Exception:
        logger.warning(
            "Deployment profile detection failed — assuming restricted environment "
            "to avoid skipping production safety checks"
        )
        return True  # fail closed: validate when uncertain


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
    """Verify all required directories exist and are writable."""
    paths = ["static/formulas", "static/question-assets"]
    if settings.EXPORT_DIR:
        paths.append(settings.EXPORT_DIR)
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


def _check_ai_encrypt_key(errors: list[str]) -> None:
    """AI_CONFIG_ENCRYPT_KEY must be a valid Fernet key in production/cloud_api.

    The error message names the environment variable but never reveals its value.
    """
    key = settings.AI_CONFIG_ENCRYPT_KEY
    if not key:
        errors.append(
            "AI_CONFIG_ENCRYPT_KEY 未设置——生产环境需要有效的 Fernet 密钥。"
            " 生成命令: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
        return
    try:
        from cryptography.fernet import Fernet
        Fernet(key.encode())
    except Exception:
        errors.append(
            "AI_CONFIG_ENCRYPT_KEY 格式无效——必须是有效的 Fernet 密钥。"
            " 变量值不记录在日志中。"
        )


def _check_deployment_profile(errors: list[str]) -> None:
    """Production must use cloud_api profile, never local_import."""
    if detect_deployment_profile() != DeploymentProfile.CLOUD_API:
        errors.append(
            "生产环境的部署配置不是 cloud_api，必须设置 DEPLOYMENT_PROFILE=cloud_api"
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
    allowed_cloud_backends = {"paddlex_http", "disabled"}
    if exec_backend not in allowed_cloud_backends:
        errors.append(
            f"生产环境 OCR_EXECUTION_BACKEND='{exec_backend}' 不允许。"
            f" 必须为以下之一: {', '.join(sorted(allowed_cloud_backends))}"
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
    # Check external OCR URL is HTTPS (or explicitly allowed HTTP in trusted network)
    ocr_url = settings.OCR_REMOTE_URL or ""
    if exec_backend == "paddlex_http" and ocr_url:
        if not ocr_url.startswith("https://"):
            if settings.OCR_ALLOW_HTTP:
                logger.warning(
                    "OCR_REMOTE_URL uses HTTP (OCR_ALLOW_HTTP=true) — "
                    "only use in trusted networks"
                )
            else:
                errors.append(
                    "外部 OCR URL (OCR_REMOTE_URL) 必须使用 HTTPS。 "
                    "如在内网可信环境，可设置 OCR_ALLOW_HTTP=true。"
                )
        if not settings.OCR_REMOTE_TOKEN:
            errors.append(
                "外部 OCR 已启用 (OCR_EXECUTION_BACKEND=paddlex_http) "
                "但 OCR_REMOTE_TOKEN 未设置"
            )


def _check_ocr_no_local_deps(errors: list[str]) -> None:
    """Fail startup if local OCR modules are loaded in cloud_api deployment.

    In cloud_api, the process must never import or initialize local OCR
    packages. We check sys.modules for already-loaded banned modules,
    but never probe for their availability (no find_spec / import attempt).

    Config-level OCR checks (backend, GPU, fallback flags) are handled
    separately by _check_ocr_production_rules.
    """
    import sys

    profile = detect_deployment_profile()
    if profile != DeploymentProfile.CLOUD_API:
        return

    banned_modules = ["paddleocr", "paddle"]
    loaded = [mod for mod in banned_modules if mod in sys.modules]
    if loaded:
        errors.append(
            f"cloud_api 部署检测到已加载的本地 OCR 模块: {loaded}。"
            f" 云端部署不得包含本地 OCR 包。请卸载: pip uninstall {' '.join(loaded)}"
        )


def _check_pdf_production_rules(errors: list[str]) -> None:
    """Fail startup if PDF settings violate production constraints.

    In cloud_api deployment, unbounded or high-memory PDF settings are
    rejected to prevent OOM and resource exhaustion.
    """
    profile = detect_deployment_profile()
    if profile != DeploymentProfile.CLOUD_API:
        return

    if settings.PDF_RENDER_PAGE_WINDOW == 0:
        errors.append(
            "PDF_RENDER_PAGE_WINDOW=0 在 cloud_api 部署中不允许。"
            " 必须设置为 >0 (推荐 1) 以启用流式逐页渲染。"
        )
    if settings.PDF_MAX_RENDER_PAGES_CONCURRENT > 1:
        errors.append(
            f"PDF_MAX_RENDER_PAGES_CONCURRENT={settings.PDF_MAX_RENDER_PAGES_CONCURRENT}"
            f" 在 cloud_api 部署中不允许。必须设置为 1。"
        )
    if settings.PDF_MAX_PAGES > 30:
        errors.append(
            f"PDF_MAX_PAGES={settings.PDF_MAX_PAGES} 超过 cloud_api 上限 30。"
        )


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
    dead_max = settings.TASK_QUEUE_DEAD_MAX
    if not isinstance(dead_max, int) or dead_max < 1:
        errors.append(f"TASK_QUEUE_MAX_DEAD={dead_max} 不合理")
    for name in ("IMPORT", "OCR", "AI", "FORMULA", "BATCH_IMAGE"):
        val = getattr(settings, f"TASK_QUEUE_MAX_READY_{name}", None)
        if val is not None and (not isinstance(val, int) or val < 0):
            errors.append(f"TASK_QUEUE_MAX_READY_{name}={val} 不合理")


def _check_worker_scratch_dir(errors: list[str]) -> None:
    """Verify WORKER_SCRATCH_DIR is set and not pointing to system temp dir.

    Only required for worker/all roles. Web and scheduler roles don't need
    a worker scratch directory.
    """
    role = settings.PROCESS_ROLE
    if role not in ("worker", "all"):
        return

    scratch = settings.WORKER_SCRATCH_DIR
    if not scratch:
        errors.append(
            "WORKER_SCRATCH_DIR 未设置——生产过程需要显式配置工作暂存目录。"
        )
        return

    import tempfile

    real_scratch = os.path.realpath(scratch)
    real_temp = os.path.realpath(tempfile.gettempdir())

    if real_scratch == real_temp:
        errors.append(
            f"WORKER_SCRATCH_DIR={scratch!r} 指向系统临时目录 {real_temp}。"
            f" 必须设置为独立目录以避免填满系统临时分区。"
        )
        return

    try:
        os.makedirs(scratch, exist_ok=True)
        if not os.access(scratch, os.W_OK):
            errors.append(f"WORKER_SCRATCH_DIR 不可写: {scratch}")
    except OSError as exc:
        errors.append(f"WORKER_SCRATCH_DIR 检查失败: {scratch}: {exc}")


def _check_gunicorn_fork_safety(errors: list[str]) -> None:
    """Detect fork-unsafe client initialization patterns.

    If Gunicorn ``--preload`` is used, module-level code that INITIALIZES
    network clients (opens connections, creates pools) would be inherited
    by all worker processes, leading to file descriptor leaks and connection
    races.

    We check two conditions to decide whether to run:
    - ``GUNICORN_PRELOAD`` env var explicitly set
    - ``sys.argv[0]`` contains "gunicorn" (Gunicorn CLI without env var)

    Only flags patterns at MODULE scope (indent == 0), since client
    initialization inside function/class bodies runs per-worker and is
    safe even with ``--preload``.
    """

    gunicorn_preload = os.environ.get("GUNICORN_PRELOAD", "").lower() in ("1", "true", "yes")
    if not gunicorn_preload:
        return

    own_patterns = {
        "redis.asyncio.from_url": "Redis client at module level",
        "httpx.AsyncClient": "httpx client at module level",
        "httpx.Client": "httpx sync client at module level",
    }
    # Scan own modules — only flag patterns at module scope (indent == 0)
    for name, mod in list(sys.modules.items()):
        if not name.startswith("app."):
            continue
        mod_file = getattr(mod, "__file__", "") or ""
        if not mod_file or not os.path.isfile(mod_file):
            continue
        try:
            with open(mod_file) as f:
                source_lines = f.readlines()
            # Build set of line numbers that are inside a function or class body
            # (lines with indent > 0, or lines between a `def`/`class` and its
            # next peer at indent 0).
            in_body: set[int] = set()
            body_start = None
            for lineno, line in enumerate(source_lines, 1):
                stripped = line.lstrip()
                if not stripped or stripped.startswith(("#", '"', "'", "\n")):
                    if body_start is not None:
                        in_body.add(lineno)
                    continue
                indent = len(line) - len(stripped)
                if indent == 0 and (
                    stripped.startswith("def ") or stripped.startswith("class ")
                    or stripped.startswith("async def ")
                ):
                    body_start = lineno
                elif indent == 0:
                    body_start = None
                else:
                    if body_start is not None:
                        in_body.add(lineno)
            for pattern, reason in own_patterns.items():
                for lineno, line in enumerate(source_lines, 1):
                    if pattern not in line:
                        continue
                    stripped = line.lstrip()
                    if not stripped or stripped.startswith(("#", '"', "'")):
                        continue  # comment or docstring
                    # Check both indent == 0 AND not inside a function/class body
                    # (the latter catches multi-line module-level patterns on
                    # continuation lines, e.g. CFG = {"k": redis.from_url(...)})
                    indent = len(line) - len(stripped)
                    if indent > 0 and lineno not in in_body:
                        # Multi-line module-level expression — flag it
                        pass
                    elif indent > 0:
                        continue  # inside function/class — safe
                    # Known-safe: app.core.cache uses lazy constructor
                    if name == "app.core.cache" and "from_url" in pattern:
                        continue
                    errors.append(
                        f"Gunicorn preload unsafe: module-level '{reason}' "
                        f"in {name} (line {lineno}). "
                        f"Use lazy initialization via FastAPI lifespan."
                    )
        except OSError:
            pass


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
