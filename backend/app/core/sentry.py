"""Sentry 异常监控集成。

仅在生产环境且配置了 SENTRY_DSN 时启用。
"""

import logging

from app.core.config import settings

logger = logging.getLogger("2240ai.sentry")


def init_sentry():
    if settings.APP_ENV != "production":
        logger.info("Sentry 跳过（非生产环境）")
        return

    dsn = settings.SENTRY_DSN
    if not dsn:
        logger.info("Sentry 跳过（未配置 SENTRY_DSN）")
        return

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=settings.APP_ENV,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.05,
        )
        logger.info("Sentry 初始化成功")
    except ImportError:
        logger.warning("Sentry 跳过（sentry-sdk 未安装）")
    except Exception as e:
        logger.error("Sentry 初始化失败: %s", e)
