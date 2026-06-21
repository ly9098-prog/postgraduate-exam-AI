"""Model config resolver — ties DB-stored model config to the runtime DeepSeek client.

Call ``ensure_db_model_configured(db, feature)`` before any AI call that
should obey the admin-configured model enable/disable, API key settings,
and model name.

Each feature (ocr / completion / analysis) can have its own dedicated model.
A model tagged with ``features=None`` serves as the default fallback for all
features when no feature-specific model is configured.

Returns ``(api_key, base_url, model_name)`` — all three come from the
first enabled ``AdminAiModelConfig`` row.  Returns ``None`` when no
enabled model is found or the key cannot be decrypted (caller falls back
to env-var defaults).
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_ai_config import AdminAiModelConfig, decrypt_api_key

logger = logging.getLogger(__name__)


def _get_model_features(model: AdminAiModelConfig) -> list[str]:
    """从模型获取 features 列表，兼容新旧数据。"""
    if model.features is not None:
        if isinstance(model.features, list):
            return model.features
        # 旧数据可能是 JSON 字符串
        if isinstance(model.features, str):
            try:
                parsed = json.loads(model.features)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
    # 回退到旧字段
    if model.feature:
        return [model.feature]
    return []


async def resolve_active_model(db: AsyncSession, feature: str | None = None) -> dict | None:
    """Return the first enabled model matching *feature*.

    Resolution order:
    1. An enabled model whose ``features`` array contains the requested feature.
    2. An enabled model with no features (``features IS NULL`` or empty) — the default.
    3. An enabled model with any feature (last resort).

    Within each tier, priority is: ``is_default DESC, sort_order ASC``.

    Returns ``None`` when no enabled model is found or the API key cannot
    be decrypted.
    """
    # 查出所有已启用模型，在 Python 层按序匹配
    result = await db.execute(
        select(AdminAiModelConfig)
        .where(AdminAiModelConfig.is_enabled == True)
        .order_by(
            AdminAiModelConfig.is_default.desc(),
            AdminAiModelConfig.sort_order.asc(),
        )
    )
    all_enabled = result.scalars().all()

    if feature:
        for model in all_enabled:
            if feature in _get_model_features(model):
                return _decrypt_model(model)

    # Fallback: untagged default model (features is None or empty)
    for model in all_enabled:
        if not _get_model_features(model):
            return _decrypt_model(model)

    # Last resort: any enabled model
    for model in all_enabled:
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
        "features": _get_model_features(model),
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
