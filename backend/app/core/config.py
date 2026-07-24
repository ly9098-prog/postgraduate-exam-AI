from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_SECRET: str = "change-me-in-production"
    PROCESS_ROLE: str = "web"  # "web" | "worker" | "scheduler" | "all"
    JWT_EXPIRE_DAYS: int = 30
    DATABASE_URL: str = "sqlite+aiosqlite:///./postgraduate.db"

    # CORS — 使用凭证请求时必须是显式 origin，不能使用 "*"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # 日志级别
    LOG_LEVEL: str = "INFO"

    # Debug
    DEBUG_MODE: bool = False
    DEBUG_QUESTION_ID: int | None = None

    # DeepSeek
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"
    AI_TIMEOUT: int = 150
    AI_DAILY_TOKEN_LIMIT: int = 50000
    AI_MONTHLY_TOKEN_LIMIT: int = 500000
    AI_SINGLE_MAX_TOKENS: int = 2000
    AI_CONFIG_ENCRYPT_KEY: str = ""

    # 文本导入 LLM 结构化层（仅做格式整理，不补全/不推测）
    TEXT_IMPORT_LLM_ENABLED: bool = True
    TEXT_IMPORT_LLM_MODEL: str = "deepseek-v4-flash"
    TEXT_IMPORT_LLM_DAILY_TOKEN: int = 50000
    TEXT_IMPORT_LLM_MAX_BLOCK_CHARS: int = 6000

    # WeChat (jscode2session)
    WECHAT_APP_ID: str = ""
    WECHAT_APP_SECRET: str = ""

    # 微信订阅消息（番茄钟完成提醒）
    WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID: str = ""
    POMODORO_NOTIFY_ENABLED: bool = False
    POMODORO_NOTIFY_PAGE: str = "pages/pomodoro/pomodoro"
    POMODORO_SCHEDULER_INTERVAL_SEC: int = 60

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
    OCR_USE_PROCESS_POOL: bool = False  # true = process-isolated OCR (crash-safe)
    OCR_TIMEOUT_SECONDS: int = 600
    UNIFIED_SAFETY_MODE: str = "shadow"  # "off" | "shadow" | "enforce"
    IMAGE_IMPORT_MAX_BYTES: int = 10 * 1024 * 1024
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

    # Artifact migration
    REJECT_LEGACY_ARTIFACTS: bool = False  # reject artifacts without metadata wrapper

    # 批量导题（多图片）
    BATCH_IMAGE_MAX_FILES: int = 100        # 单次最多上传图片数
    BATCH_IMAGE_DEFAULT_CONCURRENCY: int = 2  # 默认并发（仍被 clamp 到 1~4）

    # PDF 导入限制
    PDF_MAX_FILE_SIZE_BYTES: int = 200 * 1024 * 1024   # 200MB
    PDF_MAX_PAGES: int = 600
    PDF_MAX_PAGE_PIXELS: int = 4096 * 4096              # max width*height per page
    PDF_RENDER_DPI: int = 150
    PDF_MAX_RENDER_PAGES_CONCURRENT: int = 5            # pages rendered per batch
    PDF_RENDER_PAGE_WINDOW: int = 0                      # 0 = all, N = max pages held in memory at once

    # Exercise Region Detection
    EXERCISE_DETECTION_ENABLED: bool = True
    EXERCISE_DETECTION_MAX_EMPTY_PAGES: int = 3
    EXERCISE_DETECTION_MIN_CONFIDENCE: float = 0.5

    # OCR Canary (pre-release verification)
    OCR_CANARY_ENABLED: bool = False
    IR_FREEZE_CANARY_PERCENT: float = 0.0
    CANARY_SUBJECTS: str = ""
    CANARY_SOURCE_TYPES: str = ""
    CANARY_TENANT_ALLOWLIST: str = ""
    CANARY_TENANT_DENYLIST: str = ""
    CANARY_MAX_PAGES: int = 0
    CANARY_FAIL_OPEN: bool = False
    CANARY_REQUIRE_REVIEW: bool = True
    CANARY_CONFIG_VERSION: str = "s3f-v1"

    # Domain Quality Gate
    DOMAIN_QUALITY_GATE_MODE: str = "off"  # "off" | "shadow" | "enforce"
    QUALITY_GATE_ENFORCE_ENABLED: bool = False  # sentinel: must be True to allow enforce mode

    # Structure Freeze mode
    STRUCTURE_FREEZE_MODE: str = "legacy"  # "legacy" | "dual" | "ir"

    # Redis
    REDIS_URL: str = ""

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

    # Task queue — in-memory fallback guard
    ALLOW_IN_MEMORY_TASK_QUEUE: bool = False

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

    # ── Vector Search (pgvector) ──
    VECTOR_ENABLED: bool = False
    VECTOR_MODE: str = "off"  # off | shadow | allowlist | all
    VECTOR_ALLOWLIST: str = ""  # JSON list: '["exam408-ds","exam408-os"]' or user ids '[1,2,3]'
    VECTOR_CACHE_TTL_SEC: int = 300
    VECTOR_TOP_K: int = 100
    VECTOR_SIMILARITY_THRESHOLD: float = 0.15

    # ── Embedding ──
    EMBEDDING_PROVIDER: str = "openai_compatible"
    EMBEDDING_API_KEY: str = ""
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

    # ── V6 Adaptive Learning ──
    ADAPTIVE_LEARNING_ENABLED: bool = True
    ADAPTIVE_INTERVAL_ENABLED: bool = True
    ADAPTIVE_DIFFICULTY_ENABLED: bool = True
    ADAPTIVE_PATH_ENABLED: bool = True
    ADAPTIVE_WEIGHT_ENABLED: bool = True
    ADAPTIVE_DRY_RUN: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
