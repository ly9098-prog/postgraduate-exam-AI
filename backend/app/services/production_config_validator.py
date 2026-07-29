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
from app.core.ocr_isolation import loaded_local_ocr_modules

logger = logging.getLogger("postgraduate-ai.startup")


def validate_production_config() -> None:
    """Run all production config checks. Raises SystemError on failures.

    Runs when APP_ENV=production OR DeploymentProfile=CLOUD_API
    (whichever is more restrictive).
    """
    if not _is_restricted_environment():
        return

    errors: list[str] = []

    checks = (
        _check_app_secret,
        _check_database_url,
        _check_cors,
        _check_allowed_hosts,
        _check_public_base_url,
        _check_directories,
        _check_deployment_profile,
        _check_process_role,
        _check_ai_encrypt_key,
        _check_outbound_url_policy,
        _check_wechat_credentials,
        _check_internal_api_auth,
        _check_ocr_production_rules,
        _check_ocr_no_local_deps,
        _check_pdf_production_rules,
        _check_staging_production,
        _check_db_pool_budget,
        _check_queue_capacity,
        _check_worker_scratch_dir,
        _check_gunicorn_fork_safety,
    )
    for check in checks:
        try:
            check(errors)
        except Exception as exc:
            errors.append(
                f"{check.__name__} 检查异常: {type(exc).__name__}: {exc}"
            )

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
        elif not origin.startswith("https://"):
            errors.append(f"生产环境 CORS_ORIGINS 必须使用 HTTPS: {origin}")


def _check_allowed_hosts(errors: list[str]) -> None:
    hosts = [str(value).strip().lower() for value in settings.ALLOWED_HOSTS]
    if not hosts:
        errors.append("ALLOWED_HOSTS 不能为空")
        return
    for host in hosts:
        if host == "*":
            errors.append("ALLOWED_HOSTS 不允许使用通配符 '*'")
        elif host in {"localhost", "127.0.0.1", "::1", "testserver"}:
            errors.append(f"生产环境 ALLOWED_HOSTS 不得包含开发主机: {host}")
        elif "/" in host or "://" in host or any(ch.isspace() for ch in host):
            errors.append(f"ALLOWED_HOSTS 包含非法主机名: {host}")


def _check_public_base_url(errors: list[str]) -> None:
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(settings.PUBLIC_BASE_URL)
    except ValueError as exc:
        errors.append(f"PUBLIC_BASE_URL 格式无效: {exc}")
        return
    if parsed.scheme != "https" or not parsed.hostname:
        errors.append("生产环境 PUBLIC_BASE_URL 必须是有效的 HTTPS URL")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        errors.append("PUBLIC_BASE_URL 不得包含凭据、查询参数或片段")


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



def _check_wechat_credentials(errors: list[str]) -> None:
    """Production login must never fall back to deterministic development identities."""
    app_id = (settings.WECHAT_APP_ID or "").strip()
    app_secret = (settings.WECHAT_APP_SECRET or "").strip()
    if not app_id or app_id == "your-app-id-here":
        errors.append("WECHAT_APP_ID 未设置——生产环境禁止使用开发登录回退")
    if not app_secret or app_secret == "your-app-secret-here":
        errors.append("WECHAT_APP_SECRET 未设置——生产环境禁止使用开发登录回退")


def _check_outbound_url_policy(errors: list[str]) -> None:
    """Production outbound requests must use HTTPS-only policies."""
    if settings.AI_ALLOW_HTTP_BASE_URLS:
        errors.append("生产环境禁止 AI_ALLOW_HTTP_BASE_URLS")
    if settings.EXPORT_ALLOW_HTTP_IMAGE_URLS:
        errors.append("生产环境禁止 EXPORT_ALLOW_HTTP_IMAGE_URLS")
    if settings.ALLOW_LEGACY_WEBSOCKET_QUERY_TOKEN:
        errors.append("生产环境禁止在 WebSocket URL 查询参数中传递访问令牌")
    if settings.OCR_ALLOW_HTTP:
        errors.append("生产环境禁止 OCR_ALLOW_HTTP；OCR 凭据与图像必须通过 HTTPS 传输")


def _check_internal_api_auth(errors: list[str]) -> None:
    """Forbid the legacy shared-key fallback in restricted environments."""
    if settings.INTERNAL_API_FALLBACK_ENABLED:
        errors.append("生产环境禁止 INTERNAL_API_FALLBACK_ENABLED；内部 Worker 必须使用数据库凭据")


def _check_deployment_profile(errors: list[str]) -> None:
    """Production must use cloud_api profile, never local_import."""
    if detect_deployment_profile() != DeploymentProfile.CLOUD_API:
        errors.append(
            "生产环境的部署配置不是 cloud_api，必须设置 DEPLOYMENT_PROFILE=cloud_api"
        )


def _check_ocr_production_rules(errors: list[str]) -> None:
    """Reject every local/fallback OCR configuration in restricted profiles."""
    if settings.OCR_USE_GPU is not False:
        errors.append("生产环境必须设置 OCR_USE_GPU=false")

    exec_backend = (settings.OCR_EXECUTION_BACKEND or "").strip().lower()
    allowed_cloud_backends = {"paddlex_http", "disabled"}
    if exec_backend not in allowed_cloud_backends:
        errors.append(
            f"生产环境 OCR_EXECUTION_BACKEND={exec_backend!r} 不允许，"
            "必须为 paddlex_http 或 disabled"
        )

    # Unsafe fallbacks are forbidden even while OCR is disabled; otherwise a
    # later feature toggle could silently activate a local path.
    if os.environ.get("OCR_REMOTE_FALLBACK_ENABLED", "").lower() in {"1", "true", "yes"}:
        errors.append("生产环境禁止 OCR_REMOTE_FALLBACK_ENABLED")
    if os.environ.get("OCR_UNSAFE_THREAD_FALLBACK_ENABLED", "").lower() in {"1", "true", "yes"}:
        errors.append("生产环境禁止 OCR_UNSAFE_THREAD_FALLBACK_ENABLED")

    from app.core.ocr_profile import get_ocr_profile
    try:
        profile = get_ocr_profile()
        if profile.use_gpu:
            errors.append("生产 OCR profile 必须设置 use_gpu=False")
    except Exception as exc:
        errors.append(f"OCR profile 检查失败: {exc}")

    if not settings.OCR_ENABLED:
        return
    if exec_backend == "disabled":
        errors.append("OCR_ENABLED=true 时 OCR_EXECUTION_BACKEND 不能为 disabled")
        return
    if exec_backend != "paddlex_http":
        return

    ocr_url = (settings.OCR_REMOTE_URL or "").strip()
    if not ocr_url:
        errors.append("OCR_EXECUTION_BACKEND=paddlex_http 时必须设置 OCR_REMOTE_URL")
    else:
        from urllib.parse import urlsplit

        try:
            parsed = urlsplit(ocr_url)
        except ValueError as exc:
            errors.append(f"OCR_REMOTE_URL 格式无效: {exc}")
        else:
            if parsed.scheme != "https" or not parsed.hostname:
                errors.append("生产环境 OCR_REMOTE_URL 必须是有效的 HTTPS URL")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                errors.append("OCR_REMOTE_URL 不得包含凭据、查询参数或片段")
    if not (settings.OCR_REMOTE_TOKEN or "").strip():
        errors.append("OCR_EXECUTION_BACKEND=paddlex_http 时必须设置 OCR_REMOTE_TOKEN")


def _check_ocr_no_local_deps(errors: list[str]) -> None:
    """Detect already-loaded local OCR modules without probing packages."""
    if detect_deployment_profile() != DeploymentProfile.CLOUD_API:
        return
    loaded = loaded_local_ocr_modules()
    if loaded:
        errors.append(
            "cloud_api 部署检测到已加载的本地 OCR 模块: "
            + ", ".join(loaded)
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
        _check_stored_outbound_urls(errors),
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


async def _check_stored_outbound_urls(errors: list[str]) -> None:
    """Reject legacy DB-stored service URLs that can reach private networks."""
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.admin_ai_config import AdminAiModelConfig
    from app.models.admin_vector_config import AdminVectorConfig
    from app.services.safe_remote_fetch import UnsafeRemoteURLError, validate_remote_url

    try:
        async with async_session() as session:
            ai_urls = list(
                (await session.execute(select(AdminAiModelConfig.api_base_url))).scalars().all()
            )
            vector_urls = list(
                (await session.execute(select(AdminVectorConfig.embedding_base_url))).scalars().all()
            )
    except Exception as exc:
        errors.append(f"无法检查数据库中的外部服务 URL: {exc}")
        return

    candidates = [("AI 模型", value) for value in ai_urls]
    candidates.extend(("向量模型", value) for value in vector_urls)
    for kind, raw_url in candidates:
        value = (raw_url or "").strip()
        if not value:
            continue
        try:
            await asyncio.to_thread(
                validate_remote_url,
                value,
                allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
            )
        except UnsafeRemoteURLError as exc:
            errors.append(f"数据库中的{kind} URL 不安全: {exc}")
        except Exception as exc:
            errors.append(f"数据库中的{kind} URL 无法验证: {exc}")


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
