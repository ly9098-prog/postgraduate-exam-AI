from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_SECRET: str = "change-me-in-production"
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
    AI_TIMEOUT: int = 60
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

    # 部署档案（留空跟随 APP_ENV）
    DEPLOY_PROFILE: str = ""  # "local" | "production"

    # OCR
    OCR_ENABLED: bool = False
    OCR_MAX_WORKERS: int = 2
    OCR_LANGUAGE: str = "ch"
    OCR_USE_GPU: bool = False
    OCR_DET_DB_THRESH: float = 0.2
    OCR_DET_DB_BOX_THRESH: float = 0.4
    OCR_DET_DB_UNCLIP_RATIO: float = 1.8
    OCR_DROP_SCORE: float = 0.3
    OCR_MIN_IMAGE_WIDTH: int = 1500
    MAX_OCR_PAGES: int = 0  # 0 = no limit
    OCR_TIMEOUT_SECONDS: int = 600
    IMAGE_IMPORT_MAX_BYTES: int = 10 * 1024 * 1024
    PAGE_CLASSIFIER_ENABLED: bool = True
    # 代码块检测 Feature Flag — 关闭后行为与线上完全一致
    CODE_DETECTOR_ENABLED: bool = False

    # 批量导题（多图片）
    BATCH_IMAGE_MAX_FILES: int = 100        # 单次最多上传图片数
    BATCH_IMAGE_DEFAULT_CONCURRENCY: int = 2  # 默认并发（仍被 clamp 到 1~4）

    # Exercise Region Detection
    EXERCISE_DETECTION_ENABLED: bool = True
    EXERCISE_DETECTION_DPI: int = 72
    EXERCISE_DETECTION_MAX_EMPTY_PAGES: int = 3
    EXERCISE_DETECTION_MIN_CONFIDENCE: float = 0.5
    # 采样步长：1 = 扫描每一页（旧行为）；>1 = 每 N 页扫一页 + 边界宽容
    # 默认 3 表示 lightweight OCR 工作量降为 1/3，再对找到的 region 边界 ±2 页扩展避免漏题
    EXERCISE_DETECTION_SAMPLE_STEP: int = 3

    # Redis
    REDIS_URL: str = ""

    # Database connection pool
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600

    # Gunicorn
    GUNICORN_WORKERS: int = 4
    GUNICORN_WORKER_CLASS: str = "uvicorn.workers.UvicornWorker"

    # Sentry
    SENTRY_DSN: str = ""
    SENTRY_ENV: str = ""

    # 数学公式图片化
    MATH_IMAGE_RENDER_ENABLED: bool = False
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    STORAGE_BACKEND: str = "local"  # "local" 或 "cos"

    # 部署
    WORKERS: int = 4
    MAX_CONNECTIONS: int = 100

    class Config:
        env_file = ".env"


settings = Settings()
