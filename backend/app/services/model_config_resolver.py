"""Model config resolver — ties DB-stored model config to the runtime DeepSeek client.

Call `ensure_db_model_configured(db)` before any AI call that should obey
the admin-configured model enable/disable, API key settings, and model name.

Returns ``(api_key, base_url, model_name)`` — all three come from the
first enabled ``AdminAiModelConfig`` row.  Returns ``None`` when no
enabled model is found or the key cannot be decrypted (caller falls back
to env-var defaults).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_ai_config import AdminAiModelConfig, decrypt_api_key

logger = logging.getLogger(__name__)


async def resolve_active_model(db: AsyncSession) -> dict | None:
    """Return the first enabled model's decrypted credentials from the DB.

    Priority: default → sort_order.  Returns ``None`` when no enabled model
    is found or the API key cannot be decrypted.
    """
    result = await db.execute(
        select(AdminAiModelConfig)
        .where(AdminAiModelConfig.is_enabled == True)
        .order_by(
            AdminAiModelConfig.is_default.desc(),
            AdminAiModelConfig.sort_order.asc(),
        )
    )
    model = result.scalars().first()
    if model is None:
        logger.info("No enabled AI model found in DB — will fall back to env vars")
        return None

    api_key = decrypt_api_key(model.api_key_encrypted) if model.api_key_encrypted else ""
    if not api_key:
        logger.warning(
            "Enabled model '%s' has no decryptable API key — falling back to env vars",
            model.name,
        )
        return None

    return {
        "api_key": api_key,
        "api_base_url": model.api_base_url or "https://api.deepseek.com",
        "model_name": model.name,
    }


async def ensure_db_model_configured(db: AsyncSession) -> tuple[str, str, str] | None:
    """Read the enabled model from DB and return its credentials.

    Returns ``(api_key, base_url, model_name)`` when a DB model is available,
    ``None`` when falling back to environment variables.

    Does NOT modify the global ``DeepSeekClient`` singleton — callers
    must pass the returned credentials to ``deepseek.chat()`` explicitly.
    """
    config = await resolve_active_model(db)
    if config:
        logger.info(
            "Resolved DB model credentials (model=%s, base_url=%s)",
            config["model_name"],
            config["api_base_url"],
        )
        return (config["api_key"], config["api_base_url"], config["model_name"])

    logger.info("No DB model configured — will use env vars")
    return None
