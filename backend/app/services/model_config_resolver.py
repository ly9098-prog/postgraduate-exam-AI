"""Model config resolver — ties DB-stored model config to the runtime DeepSeek client.

Call ``ensure_db_model_configured(db, feature)`` before any AI call that
should obey the admin-configured model enable/disable, API key settings,
and model name.

Each feature (ocr / completion / analysis) can have its own dedicated model.
A model tagged with ``feature=None`` serves as the default fallback for all
features when no feature-specific model is configured.

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


async def resolve_active_model(db: AsyncSession, feature: str | None = None) -> dict | None:
    """Return the first enabled model matching *feature*.

    Resolution order:
    1. An enabled model whose ``feature`` matches the requested feature.
    2. An enabled model with no feature tag (``feature IS NULL``) — the default.
    3. An enabled model with any feature tag (last resort).

    Within each tier, priority is: ``is_default DESC, sort_order ASC``.

    Returns ``None`` when no enabled model is found or the API key cannot
    be decrypted.
    """
    if feature:
        result = await db.execute(
            select(AdminAiModelConfig)
            .where(AdminAiModelConfig.is_enabled == True)
            .where(AdminAiModelConfig.feature == feature)
            .order_by(
                AdminAiModelConfig.is_default.desc(),
                AdminAiModelConfig.sort_order.asc(),
            )
        )
        model = result.scalars().first()
        if model:
            return _decrypt_model(model)

    # Fallback: untagged default model
    result = await db.execute(
        select(AdminAiModelConfig)
        .where(AdminAiModelConfig.is_enabled == True)
        .where(AdminAiModelConfig.feature.is_(None))
        .order_by(
            AdminAiModelConfig.is_default.desc(),
            AdminAiModelConfig.sort_order.asc(),
        )
    )
    model = result.scalars().first()
    if model:
        return _decrypt_model(model)

    # Last resort: any enabled model
    result = await db.execute(
        select(AdminAiModelConfig)
        .where(AdminAiModelConfig.is_enabled == True)
        .order_by(
            AdminAiModelConfig.is_default.desc(),
            AdminAiModelConfig.sort_order.asc(),
        )
    )
    model = result.scalars().first()
    if model:
        logger.info(
            "No feature='%s' or untagged model found — using '%s' as last resort",
            feature, model.name,
        )
        return _decrypt_model(model)

    logger.info("No enabled AI model found in DB — will fall back to env vars")
    return None


def _decrypt_model(model: AdminAiModelConfig) -> dict | None:
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
        "provider": model.provider,
        "feature": model.feature,
        "display_name": model.display_name,
    }


async def ensure_db_model_configured(
    db: AsyncSession, feature: str | None = None,
) -> tuple[str, str, str] | None:
    """Read the enabled model matching *feature* from DB and return credentials.

    Returns ``(api_key, base_url, model_name)`` when a DB model is available,
    ``None`` when falling back to environment variables.

    Does NOT modify the global ``DeepSeekClient`` singleton — callers
    must pass the returned credentials to ``deepseek.chat()`` explicitly.
    """
    config = await resolve_active_model(db, feature=feature)
    if config:
        logger.info(
            "Resolved DB model credentials (feature=%s, model=%s, base_url=%s)",
            feature, config["model_name"], config["api_base_url"],
        )
        return (config["api_key"], config["api_base_url"], config["model_name"])

    logger.info("No DB model configured — will use env vars")
    return None
