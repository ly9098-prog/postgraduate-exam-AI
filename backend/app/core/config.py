import logging
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("postgraduate-ai.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")
    # Fail closed: local development must opt in with APP_ENV=development.
    APP_ENV: str = "production"
    APP_SECRET: str = "change-me-in-production"
    PROCESS_ROLE: str = "web"  # "web" | "worker" | "scheduler" | "all"
    # Local FastAPI startup is web-only by default, even when an old .env still
    # contains PROCESS_ROLE=all.  Full in-process worker/scheduler startup must
    # be explicitly opted into for local end-to-end debugging.
    LOCAL_ASYNC_RUNTIME_ENABLED: bool = False
    JWT_EXPIRE_DAYS: int = 1
    JWT_ISSUER: str = "memograd-api"
    USER_JWT_AUDIENCE: str = "memograd-user"
    ADMIN_JWT_AUDIENCE: str = "memograd-admin"
    DATABASE_URL: str = "sqlite+aiosqlite:///./postgraduate.db"

    # PostgreSQL backup task center integration.  Production scheduling remains
    # owned by systemd; these settings only control observability/manual runs.
    POSTGRES_BACKUP_ENABLED: bool = True
    POSTGRES_BACKUP_DIR: str = ""
    POSTGRES_BACKUP_SCRIPT: str = ""
    POSTGRES_BACKUP_TIMER_UNIT: str = "postgres-backup.timer"
    POSTGRES_BACKUP_SERVICE_UNIT: str = "postgres-backup.service"
    POSTGRES_BACKUP_TIMEOUT_SEC: int = 1800
    POSTGRES_BACKUP_HISTORY_LIMIT: int = 20

    # CORS — 使用凭证请求时必须是显式 origin，不能使用 "*"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    # Host header allowlist. Production startup validation rejects these
    # development defaults until explicit public hostnames are configured.
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "testserver"]

    # 日志级别
    LOG_LEVEL: str = "INFO"

    # Debug
    DEBUG_MODE: bool = False
    DEBUG_QUESTION_ID: int | None = None

    # DeepSeek (model-specific configs like api_base_url are managed per-model in admin_ai_model_configs)
    AI_TIMEOUT: int = 150
    AI_DAILY_TOKEN_LIMIT: int = 50000
    AI_MONTHLY_TOKEN_LIMIT: int = 500000
    AI_SINGLE_MAX_TOKENS: int = 2000
    # Unified AI admission / cost guard.  These are enforced in the shared
    # OpenAI-compatible client so every feature gets the same protection.
    AI_MAX_CONCURRENCY: int = 3
    AI_QUEUE_WAIT_TIMEOUT_SEC: float = 3.0
    AI_USER_RPM_LIMIT: int = 12
    AI_RATE_LIMIT_FAIL_CLOSED: bool = True
    AI_CIRCUIT_FAILURE_THRESHOLD: int = 5
    AI_CIRCUIT_RECOVERY_SEC: float = 30.0
    AI_MAX_PROMPT_CHARS: int = 50000
    AI_CONFIG_ENCRYPT_KEY: str = ""
    AI_ALLOW_HTTP_BASE_URLS: bool = False

    # 文本导入 LLM 结构化层（仅做格式整理，不补全/不推测）
    TEXT_IMPORT_LLM_ENABLED: bool = True
    TEXT_IMPORT_LLM_MODEL: str = "deepseek-v4-flash"
    TEXT_IMPORT_LLM_DAILY_TOKEN: int = 50000
    TEXT_IMPORT_LLM_MAX_BLOCK_CHARS: int = 6000

    # WeChat (jscode2session)
    WECHAT_APP_ID: str = ""
    WECHAT_APP_SECRET: str = ""

    # 部署档案（留空跟随 APP_ENV）
    DEPLOY_PROFILE: str = ""  # "local" | "production"

    # Deployment Profile (explicit override for dual-environment)
    DEPLOYMENT_PROFILE: str = ""  # "local_import" | "cloud_api" — overrides DEPLOY_PROFILE & APP_ENV

    # OCR
    OCR_ENABLED: bool = False
    OCR_MAX_WORKERS: int = 2
    # OCR executor service — bounded thread pool with concurrency control
    OCR_EXECUTOR_WORKERS: int = 2       # ThreadPoolExecutor max_workers
    OCR_MAX_CONCURRENCY: int = 2        # asyncio.Semaphore limit
    OCR_MAX_QUEUE_SIZE: int = 10        # max waiting tasks before fast-fail
    OCR_TASK_TIMEOUT_SEC: int = 600     # per-task timeout
    OCR_LANGUAGE: str = "ch"
    OCR_USE_GPU: bool = True
    OCR_DET_DB_THRESH: float = 0.2
    OCR_DET_DB_BOX_THRESH: float = 0.4
    OCR_DET_DB_UNCLIP_RATIO: float = 1.8
    OCR_DROP_SCORE: float = 0.3
    OCR_MIN_IMAGE_WIDTH: int = 1500
    MAX_OCR_PAGES: int = 0  # 0 = no limit
    OCR_TIMEOUT_SECONDS: int = 600
    UNIFIED_SAFETY_MODE: str = "shadow"  # "off" | "shadow" | "enforce"
    IMAGE_IMPORT_MAX_BYTES: int = 5 * 1024 * 1024  # 5MB — production default
    PAGE_CLASSIFIER_ENABLED: bool = True
    # 代码块检测 Feature Flag — 关闭后行为与线上完全一致
    CODE_DETECTOR_ENABLED: bool = True

    # --- PaddleX Remote OCR ---
    OCR_EXECUTION_BACKEND: str = "paddlex_http"  # "local_process" | "paddlex_http" | "disabled"
    OCR_REMOTE_URL: str = "http://127.0.0.1:8080/ocr"
    OCR_REMOTE_CONNECT_TIMEOUT_SEC: float = 5.0
    OCR_REMOTE_READ_TIMEOUT_SEC: float = 600.0
    OCR_REMOTE_HEALTH_TIMEOUT_SEC: float = 3.0
    OCR_REMOTE_MAX_CONCURRENCY: int = 1
    OCR_REMOTE_VISUALIZE: bool = False
    OCR_REMOTE_FAIL_FAST: bool = False
    OCR_REMOTE_USE_DOC_ORIENTATION_CLASSIFY: bool = False
    OCR_REMOTE_USE_DOC_UNWARPING: bool = False
    OCR_REMOTE_USE_TEXTLINE_ORIENTATION: bool = False

    # Remote OCR authentication
    OCR_REMOTE_TOKEN: str = ""
    OCR_REMOTE_AUTH_HEADER: str = "Authorization"  # header name for auth token
    OCR_REMOTE_AUTH_SCHEME: str = "Bearer"  # scheme prefix (e.g. "Bearer", "Basic")
    OCR_ALLOW_HTTP: bool = False  # allow HTTP (not HTTPS) for remote OCR in trusted network

    # Artifact migration
    REJECT_LEGACY_ARTIFACTS: bool = False  # reject artifacts without metadata wrapper

    # 批量导题（多图片）
    BATCH_IMAGE_MAX_FILES: int = 100        # 单次最多上传图片数
    BATCH_IMAGE_DEFAULT_CONCURRENCY: int = 2  # 默认并发（仍被 clamp 到 1~4）

    # PDF 导入限制
    PDF_MAX_FILE_SIZE_BYTES: int = 200 * 1024 * 1024   # 200MB
    PDF_MAX_FILE_BYTES: int = 5 * 1024 * 1024  # cloud default: 5MB
    PDF_MAX_PAGES: int = 600
    PDF_MAX_PAGE_PIXELS: int = 4096 * 4096              # max width*height per page
    PDF_MAX_DECODED_BYTES: int = 50 * 1024 * 1024       # 50MB per-page decoded memory budget
    PDF_RENDER_DPI: int = 150
    PDF_MAX_RENDER_PAGES_CONCURRENT: int = 5            # pages rendered per batch
    PDF_RENDER_PAGE_WINDOW: int = 0                      # 0 = all, N = max pages held in memory at once
    PDF_TOTAL_PIXEL_BUDGET: int = 4000 * 4000 * 30       # cloud default: 30 pages at 4k

    # Exercise Region Detection
    EXERCISE_DETECTION_ENABLED: bool = True
    EXERCISE_DETECTION_MAX_EMPTY_PAGES: int = 3
    EXERCISE_DETECTION_MIN_CONFIDENCE: float = 0.5

    # OCR Canary (pre-release verification)
    # 注：canary 配置经 OCRCanaryConfig.from_env() 直接读 os.environ，
    # 不经过 settings，因此不在此声明 Settings 字段（避免双配置源）。

    # Domain Quality Gate
    DOMAIN_QUALITY_GATE_MODE: str = "off"  # "off" | "shadow" | "enforce"
    QUALITY_GATE_ENFORCE_ENABLED: bool = False  # sentinel: must be True to allow enforce mode

    # Structure Freeze mode
    STRUCTURE_FREEZE_MODE: str = "legacy"  # "legacy" | "dual" | "ir"

    # Redis
    REDIS_URL: str = ""

    # Outbox Redis infrastructure backoff.  Redis outages are infrastructure
    # failures, not business-task failures, so they wait indefinitely with
    # bounded exponential backoff and do not consume TaskOutbox.retry_count.
    OUTBOX_REDIS_BACKOFF_INITIAL_SEC: float = 5.0
    OUTBOX_REDIS_BACKOFF_MAX_SEC: float = 60.0

    # Answer projection reconciliation (PracticeRecord -> derived learning state)
    ANSWER_PROJECTION_RECONCILE_INTERVAL_SEC: int = 300
    ANSWER_PROJECTION_RECONCILE_GRACE_SEC: int = 600
    ANSWER_PROJECTION_RECONCILE_BATCH_SIZE: int = 100

    # Async task observability / health thresholds.  These thresholds only
    # produce state-transition alerts; the diagnostics endpoint always exposes
    # the raw values so operators can tune them without losing visibility.
    TASK_HEALTH_MONITOR_INTERVAL_SEC: int = 60
    TASK_HEALTH_OUTBOX_OLDEST_WARN_SEC: int = 120
    TASK_HEALTH_OUTBOX_OLDEST_ERROR_SEC: int = 900
    TASK_HEALTH_QUEUE_OLDEST_WARN_SEC: int = 120
    TASK_HEALTH_QUEUE_OLDEST_ERROR_SEC: int = 900
    TASK_HEALTH_DEAD_WARN_COUNT: int = 1
    TASK_HEALTH_DEAD_ERROR_COUNT: int = 20
    TASK_HEALTH_PROJECTION_WARN_COUNT: int = 1
    TASK_HEALTH_PROJECTION_ERROR_COUNT: int = 50
    TASK_HEALTH_FAILED_OUTBOX_WARN_COUNT: int = 1
    TASK_HEALTH_FAILED_OUTBOX_ERROR_COUNT: int = 20

    # Database connection pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30  # seconds to wait for a connection from pool
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True

    # Per-role connection pool overrides (set individually for production)
    DB_POOL_SIZE_WEB: int = 3
    DB_MAX_OVERFLOW_WEB: int = 5
    DB_POOL_SIZE_WORKER: int = 2
    DB_MAX_OVERFLOW_WORKER: int = 3
    DB_POOL_SIZE_SCHEDULER: int = 1
    DB_MAX_OVERFLOW_SCHEDULER: int = 2

    # SQLAlchemy logging
    SQL_ECHO: bool = False
    SQL_LOG_LEVEL: str = "WARNING"
    SLOW_QUERY_MS: int = 500

    # Gunicorn
    GUNICORN_WORKERS: int = 2  # 2-core server
    GUNICORN_WORKER_CLASS: str = "uvicorn.workers.UvicornWorker"
    MAX_CONNECTIONS: int = 50

    # Internal API (worker auth)
    INTERNAL_API_KEY: str = ""
    INTERNAL_API_FALLBACK_ENABLED: bool = False
    PRODUCTION_THIN_MODE: bool = False

    # Sentry
    SENTRY_DSN: str = ""
    SENTRY_ENV: str = ""

    # 数学公式图片化
    MATH_IMAGE_RENDER_ENABLED: bool = False
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    STORAGE_BACKEND: str = "local"  # "local" 或 "cos"

    # Staging storage for durable task files (Docker volume in prod)
    STAGING_STORAGE_DIR: str = "/opt/2240ai-v2/staging"
    STAGING_DISK_QUOTA: int = 2 * 1024 * 1024 * 1024  # 2 GB
    STAGING_RETENTION_SEC: int = 604800  # 7 days default retention for staging objects
    SCRATCH_QUOTA_BYTES: int = 500 * 1024 * 1024  # 500 MB worker scratch space

    # Resource reservation for pipeline admission
    PIPELINE_RESERVATION_LEASE_SEC: int = 3600  # max pipeline reservation duration
    PIPELINE_RESERVATION_HEARTBEAT_SEC: int = 120  # reservation renewal interval

    # Distributed OCR concurrency
    OCR_GLOBAL_CONCURRENCY: int = 1  # max concurrent OCR requests across all workers
    OCR_DISTRIBUTED_LEASE_SEC: int = 60  # lease duration for distributed OCR slot

    # Task queue — in-memory fallback guard
    ALLOW_IN_MEMORY_TASK_QUEUE: bool = False

    # ── Task queue capacity limits ──
    TASK_QUEUE_MAX_READY_IMPORT: int = 50
    TASK_QUEUE_MAX_READY_OCR: int = 50
    TASK_QUEUE_MAX_READY_AI: int = 20
    TASK_QUEUE_MAX_READY_BATCH_IMAGE: int = 10
    TASK_QUEUE_MAX_READY_FORMULA: int = 20
    # Answer projections are generated once per submitted answer and must not be
    # constrained by the small generic queue default used for admin jobs.
    TASK_QUEUE_MAX_READY_ANSWER_PROJECTION: int = 2000
    # TASK_QUEUE_MAX_RETRY renamed to TASK_QUEUE_RETRY_MAX (kept for backward compat, warning on conflict)
    TASK_QUEUE_MAX_RETRY: int = 500
    TASK_QUEUE_RETRY_MAX: int = 500
    # TASK_QUEUE_MAX_DEAD renamed to TASK_QUEUE_DEAD_MAX (kept for backward compat, warning on conflict)
    TASK_QUEUE_MAX_DEAD: int = 1000
    TASK_QUEUE_DEAD_MAX: int = 1000
    TASK_QUEUE_CORRUPT_MAX: int = 100
    TASK_QUEUE_MAX_READY_DEFAULT: int = 50
    TASK_QUEUE_RETENTION_SEC: int = 604800  # 7 days default retention for task metadata
    TASK_LEASE_SEC: int = 300  # default lease duration for claimed tasks
    TASK_HEARTBEAT_SEC: int = 60  # default heartbeat interval

    # COS (Tencent Cloud Object Storage)
    COS_BUCKET: str = ""
    COS_REGION: str = ""
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = ""
    COS_ENDPOINT: str = ""  # 可选，通常自动从 region 推导
    COS_PREFIX: str = "static/formulas/"  # 对象存储前缀（模拟目录）
    COS_ALLOW_LOCAL_FALLBACK: bool = False  # production: must be explicit

    # 部署
    WORKERS: int = 2
    WORKER_SCRATCH_DIR: str = ""
    WORKER_SHUTDOWN_GRACE_SEC: int = 30
    WORKER_CONCURRENCY: int = 1  # max concurrent heavy tasks per worker process

    # ── Vector Search (pgvector) ──
    VECTOR_ENABLED: bool = False
    VECTOR_MODE: str = "off"  # off | shadow | allowlist | all
    VECTOR_ALLOWLIST: str = ""  # JSON list: '["exam408-ds","exam408-os"]' or user ids '[1,2,3]'
    VECTOR_CACHE_TTL_SEC: int = 300
    VECTOR_TOP_K: int = 100
    VECTOR_SIMILARITY_THRESHOLD: float = 0.15

    # ── Embedding ──
    EMBEDDING_PROVIDER: str = "openai_compatible"
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_TIMEOUT: int = 30
    EMBEDDING_BATCH_SIZE: int = 16

    # ── Audit Log Cleanup ──
    AUDIT_LOG_CLEANUP_ENABLED: bool = True
    AUDIT_LOG_RETENTION_DAYS: int = 180
    AUDIT_LOG_CLEANUP_HOUR_UTC: int = 3
    AUDIT_LOG_CLEANUP_BATCH_SIZE: int = 1000

    # ── Recommendation Metrics ──
    RECOMMENDATION_METRICS_AGG_ENABLED: bool = True
    RECOMMENDATION_METRICS_AGG_HOUR_UTC: int = 4
    RECOMMENDATION_LOG_RETENTION_DAYS: int = 90

    # ── Export / PDF ──
    EXPORT_POLL_INTERVAL_SEC: int = 5
    EXPORT_PROCESSING_TIMEOUT_SEC: int = 900  # zombie recovery threshold
    EXPORT_TASK_TIMEOUT_SEC: int = 600        # per-task wall-clock timeout
    EXPORT_HEARTBEAT_INTERVAL_SEC: int = 30
    EXPORT_MAX_CONCURRENT: int = 2            # global task concurrency
    EXPORT_MAX_PER_USER: int = 2              # pending/processing per user
    EXPORT_MAX_QUESTIONS: int = 100           # per-task question cap
    EXPORT_PDF_CONCURRENCY: int = 1
    EXPORT_DOCX_CONCURRENCY: int = 1
    EXPORT_IMAGE_DOWNLOAD_CONCURRENCY: int = 4
    EXPORT_ALLOW_HTTP_IMAGE_URLS: bool = False
    EXPORT_DIR: str = "var/exports"
    EXPORT_RETENTION_DAYS: int = 7  # how long completed files remain available
    # Optional explicit CJK font files for the exam-paper PDF renderer.
    # Body should preferably be a Song/serif face; heading a Hei/sans face.
    EXPORT_PDF_BODY_FONT: str = ""
    EXPORT_PDF_HEADING_FONT: str = ""
    PRODUCT_NAME: str = "MemoGrad"
    GENERATOR_VERSION: str = "2.1"  # v2.1 = reference-paper layout and export fixes

    # ── Export capabilities (globally available to authenticated users) ──
    EXPORT_DOCX_ENABLED: bool = True
    EXPORT_WEBSOCKET_ENABLED: bool = True
    ALLOW_LEGACY_WEBSOCKET_QUERY_TOKEN: bool = False

    # ── Authentication abuse controls ──
    ADMIN_LOGIN_MAX_FAILURES: int = 5
    ADMIN_LOGIN_WINDOW_SEC: int = 15 * 60
    USER_LOGIN_MAX_FAILURES: int = 20
    USER_LOGIN_WINDOW_SEC: int = 15 * 60

    # ── Adaptive Learning ──
    ADAPTIVE_LEARNING_ENABLED: bool = True
    ADAPTIVE_INTERVAL_ENABLED: bool = True
    ADAPTIVE_DIFFICULTY_ENABLED: bool = True
    ADAPTIVE_PATH_ENABLED: bool = True
    ADAPTIVE_WEIGHT_ENABLED: bool = True
    ADAPTIVE_DRY_RUN: bool = False


    def warn_deprecated_env_vars(self) -> list[str]:
        """Log warnings for deprecated env var names. Returns list of conflicts."""
        conflicts: list[str] = []
        deprecations: list[str] = []

        # TASK_QUEUE_MAX_RETRY → TASK_QUEUE_RETRY_MAX
        if self.TASK_QUEUE_MAX_RETRY != self.TASK_QUEUE_RETRY_MAX:
            conflicts.append(
                f"TASK_QUEUE_MAX_RETRY={self.TASK_QUEUE_MAX_RETRY} != "
                f"TASK_QUEUE_RETRY_MAX={self.TASK_QUEUE_RETRY_MAX}. "
                "Remove TASK_QUEUE_MAX_RETRY from env and use TASK_QUEUE_RETRY_MAX."
            )
        elif self.TASK_QUEUE_MAX_RETRY != 500:
            deprecations.append(
                "TASK_QUEUE_MAX_RETRY is deprecated, use TASK_QUEUE_RETRY_MAX"
            )

        # TASK_QUEUE_MAX_DEAD → TASK_QUEUE_DEAD_MAX
        if self.TASK_QUEUE_MAX_DEAD != self.TASK_QUEUE_DEAD_MAX:
            conflicts.append(
                f"TASK_QUEUE_MAX_DEAD={self.TASK_QUEUE_MAX_DEAD} != "
                f"TASK_QUEUE_DEAD_MAX={self.TASK_QUEUE_DEAD_MAX}. "
                "Remove TASK_QUEUE_MAX_DEAD from env and use TASK_QUEUE_DEAD_MAX."
            )
        elif self.TASK_QUEUE_MAX_DEAD != 1000:
            deprecations.append(
                "TASK_QUEUE_MAX_DEAD is deprecated, use TASK_QUEUE_DEAD_MAX"
            )

        if os.environ.get("DEPLOY_PROFILE"):
            deprecations.append("DEPLOY_PROFILE is deprecated, use DEPLOYMENT_PROFILE")

        for msg in deprecations:
            logger.warning("Configuration deprecation: %s", msg)

        return conflicts


_LOCAL_APP_ENVS = frozenset({"development", "dev", "local", "test", "testing"})


def resolve_effective_process_role(
    app_env: str,
    process_role: str,
    local_async_runtime_enabled: bool = False,
) -> str:
    """Resolve the runtime role used by the FastAPI process.

    Local development historically used ``PROCESS_ROLE=all`` to make a single
    uvicorn process also run workers and schedulers.  That is useful for an
    explicit full-stack debug session, but it is a poor default for ordinary
    API/frontend work: Redis may not be running and production-grade background
    loops then flood local logs.

    In local/test environments, legacy ``all`` therefore degrades to ``web``
    unless ``LOCAL_ASYNC_RUNTIME_ENABLED=true`` is explicitly set.  Production
    role semantics are unchanged.
    """
    env = (app_env or "").strip().lower()
    role = (process_role or "web").strip().lower()
    if role == "all" and env in _LOCAL_APP_ENVS and not local_async_runtime_enabled:
        return "web"
    return role


settings = Settings()
