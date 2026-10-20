"""Startup seeding and model diagnostics with explicit session ownership."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

SessionFactory = Callable[[], AbstractAsyncContextManager["AsyncSession"]]
AdminInitializer = Callable[["AsyncSession", str], Awaitable[bool]]

logger = logging.getLogger("postgraduate-ai")


async def initialize_dev_admin(
    session_factory: SessionFactory, ensure_admin: AdminInitializer, config: Settings,
) -> None:
    try:
        async with session_factory() as db:
            created_admin = await ensure_admin(db, config.APP_ENV)
            await db.commit()
            if created_admin:
                logger.info("Development super admin initialized")
    except Exception as e:
        logger.warning("Development super admin init failed (non-fatal): %s", e)


async def seed_recommendation_strategies(session_factory: SessionFactory) -> None:
    try:
        from app.services.recommendation_seed_service import (
            seed_default_recommendation_strategies,
        )

        async with session_factory() as db:
            seed_result = await seed_default_recommendation_strategies(db, force=False)
            await db.commit()
            if any(v for v in seed_result.values()):
                logger.info(
                    "Recommendation strategies seeded: created=%s updated=%s skipped=%s",
                    seed_result.get("created"),
                    seed_result.get("updated"),
                    seed_result.get("skipped"),
                )
    except Exception as e:
        logger.warning("Recommendation strategy seed failed (non-fatal): %s", e)


async def log_ai_model_configuration(session_factory: SessionFactory) -> None:
    try:
        from app.services.health_check_service import check_ai_model_config

        async with session_factory() as db:
            ai_check = await check_ai_model_config(db)
            if ai_check.severity == "error":
                logger.error(
                    "AI_MODEL_NOT_CONFIGURED: admin_ai_model_configs has no enabled model; "
                    "OCR AI repair / VL fallback may be unavailable"
                )
            elif ai_check.severity == "warning":
                logger.warning(
                    "AI_MODEL_DEFAULT_MISSING: enabled AI models exist (%d) but no default model is configured; "
                    "providers=%s features=%s",
                    ai_check.enabled_count,
                    ai_check.providers,
                    ai_check.features,
                )
            else:
                logger.info(
                    "AI model config healthy: enabled_count=%d default_count=%d providers=%s features=%s",
                    ai_check.enabled_count,
                    ai_check.default_count,
                    ai_check.providers,
                    ai_check.features,
                )
    except Exception as e:
        logger.warning(
            "AI model config self-check failed (non-fatal, DB may not be ready): %s", e
        )
