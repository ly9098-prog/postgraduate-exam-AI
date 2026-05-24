from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_SECRET: str = "change-me-in-production"
    JWT_EXPIRE_DAYS: int = 7
    DATABASE_URL: str = "sqlite+aiosqlite:///./postgraduate.db"

    # CORS — 生产环境限制为具体域名
    CORS_ORIGINS: list[str] = ["*"]

    # 日志级别
    LOG_LEVEL: str = "INFO"

    # DeepSeek
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    AI_TIMEOUT: int = 60
    AI_DAILY_TOKEN_LIMIT: int = 50000
    AI_MONTHLY_TOKEN_LIMIT: int = 500000
    AI_SINGLE_MAX_TOKENS: int = 2000

    # WeChat (jscode2session)
    WECHAT_APP_ID: str = ""
    WECHAT_APP_SECRET: str = ""

    # OCR
    OCR_ENABLED: bool = True
    OCR_MAX_WORKERS: int = 4
    OCR_LANGUAGE: str = "ch"
    OCR_USE_GPU: bool = False

    # Redis
    REDIS_URL: str = ""

    # Database connection pool
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600

    # Gunicorn
    GUNICORN_WORKERS: int = 4
    GUNICORN_WORKER_CLASS: str = "uvicorn.workers.UvicornWorker"

    class Config:
        env_file = ".env"


settings = Settings()
