"""Sentry 异常监控集成 — 初始化配置。

环境区分：
- development: 禁用 Sentry，不初始化、不上报
- production: 低采样率 (0.1 trace, 0.05 profile)
- test/staging: 中等采样率 (0.5 trace, 0.1 profile)
"""

import logging

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.sentry")


def init_sentry():
    # 开发环境直接禁用 Sentry，避免本地调试时产生误报和无谓的网络请求
    if settings.APP_ENV == "development":
        logger.info("Sentry disabled: APP_ENV=development")
        return

    dsn = settings.SENTRY_DSN
    if not dsn:
        logger.info("Sentry disabled: SENTRY_DSN not configured")
        return

    env = settings.SENTRY_ENV or settings.APP_ENV or "development"

    # 按环境设置不同的采样率
    env_lower = env.lower()
    if env_lower in ("production", "prod"):
        traces_sample_rate = 0.1
        profiles_sample_rate = 0.05
    elif env_lower in ("staging", "test", "testing"):
        traces_sample_rate = 0.5
        profiles_sample_rate = 0.1
    else:
        # development: 全量 trace 方便调试，不开启 profile
        traces_sample_rate = 1.0
        profiles_sample_rate = 0.0

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.httpx import HttpxIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=env,
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=profiles_sample_rate,
            send_default_pii=True,
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
                HttpxIntegration(),
            ],
        )
        logger.info(
            "Sentry initialized: env=%s, traces_sample_rate=%s, profiles_sample_rate=%s",
            env, traces_sample_rate, profiles_sample_rate,
        )
    except ImportError:
        logger.warning("Sentry skipped: sentry-sdk not installed")
    except Exception as e:
        logger.error("Sentry init failed: %s", e)
