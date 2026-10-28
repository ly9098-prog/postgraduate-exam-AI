"""OCR router configuration from options, model resolver and admin filters."""

from __future__ import annotations

from functools import partial

from app.features.pipeline_ocr_router_state import resolve_router_port


def initialize_router_config(opts: dict, *, namespace: dict | None = None) -> dict:
    """Build the option-owned base before any model or database resolution."""
    namespace = globals() if namespace is None else namespace
    ports = partial(resolve_router_port, namespace)
    config: dict = {
        "mode": opts.get("ocr_correction_mode", "auto"),
        "noise_threshold": opts.get("ocr_noise_threshold", 0.3),
        "daily_token_limit": opts.get("ocr_correction_daily_token_limit", 50000),
        "monthly_token_limit": opts.get("ocr_correction_monthly_token_limit", 1000000),
    }
    for key in ("ocr_fix_model", "ocr_fix_strategy"):
        val = opts.get(key)
        if val is not None:
            config[key] = val

    val = opts.get("ocr_filter_sensitive")
    if val is not None:
        config["ocr_filter_sensitive"] = ports("str")(val).lower() != "false"
    return config


async def resolve_router_models(config: dict, db, *, namespace: dict) -> None:
    """Resolve OCR_FIX and its backward-compatible AI_REPAIR fallback."""
    ports = partial(resolve_router_port, namespace)
    try:
        from app.services.model_config_resolver import (
            AICapability,
            AIModelConfigResolver,
        )

        resolver = AIModelConfigResolver(db)
        await resolve_primary_router_model(
            config, resolver, AICapability, namespace=namespace
        )
        await resolve_fallback_router_model(
            config, resolver, AICapability, namespace=namespace
        )
    except ports("Exception"):
        ports("logger").warning(
            "OCR router: AIModelConfigResolver failed", exc_info=True
        )


async def resolve_primary_router_model(
    config: dict, resolver, ai_capability, *, namespace: dict
) -> None:
    """Resolve OCR_FIX into either PaddleOCR-VL or OpenAI-compatible keys."""
    ports = partial(resolve_router_port, namespace)

    try:
        ocr_fix_config = await resolver.resolve_for_capability(ai_capability.OCR_FIX)
        secret = await resolver.resolve_secret(ocr_fix_config)
        provider = (ocr_fix_config.provider or "").lower().replace("_", "-")

        if provider.startswith("paddleocr"):
            config["paddleocr_vl_api_token"] = secret
            if ocr_fix_config.endpoint:
                config["paddleocr_vl_base_url"] = ocr_fix_config.endpoint
            config["paddleocr_vl_model"] = ocr_fix_config.model_name
        else:
            config["llm_api_key"] = secret
            config["llm_base_url"] = ocr_fix_config.endpoint or ""
            config["llm_model_name"] = ocr_fix_config.model_name
            config["llm_provider"] = ocr_fix_config.provider
    except ports("ValueError"):
        ports("logger").info(
            "OCR router: no OCR_FIX config resolved via AIModelConfigResolver"
        )


async def resolve_fallback_router_model(
    config: dict, resolver, ai_capability, *, namespace: dict
) -> None:
    """Reuse AI_REPAIR when the primary fixer is non-OpenAI-compatible."""
    ports = partial(resolve_router_port, namespace)
    if "llm_api_key" in config:
        return
    try:
        fallback_config = await resolver.resolve_for_capability(ai_capability.AI_REPAIR)
        fallback_provider = (fallback_config.provider or "").lower().replace("_", "-")
        if not fallback_provider.startswith("paddleocr"):
            config["llm_api_key"] = await resolver.resolve_secret(fallback_config)
            config["llm_base_url"] = fallback_config.endpoint or ""
            config["llm_model_name"] = fallback_config.model_name
            config["llm_provider"] = fallback_config.provider
    except ports("ValueError"):
        ports("logger").info(
            "OCR router: no OpenAI-compatible fallback config resolved"
        )


async def apply_admin_filter_config(config: dict, db, *, namespace: dict) -> None:
    """Apply admin_ai_configs filter settings after model resolution."""
    ports = partial(resolve_router_port, namespace)
    try:
        from app.services.admin_ai_config_service import get_all_configs

        db_configs = await get_all_configs(db)
        for key in (
            "ocr_filter_sensitive",
            "ocr_filter_max_chars",
            "ocr_filter_max_tokens",
        ):
            val = db_configs.get(key)
            if val is not None:
                if ports("isinstance")(val, ports("bool")):
                    config[key] = val
                else:
                    config[key] = (
                        ports("str")(val).lower() != "false"
                        if key == "ocr_filter_sensitive"
                        else val
                    )
    except ports("Exception"):
        ports("logger").warning(
            "OCR router: admin_ai_configs read failed", exc_info=True
        )


def apply_legacy_aliases(config: dict) -> None:
    """Retain the rolling-upgrade aliases while new router code reads llm_*."""
    if "deepseek_api_key" not in config:
        config["deepseek_api_key"] = config.get("llm_api_key", "")
    if "deepseek_base_url" not in config:
        config["deepseek_base_url"] = config.get("llm_base_url", "")


async def build_router_config(opts: dict, db, *, namespace: dict) -> dict:
    """Compose the original config stages without reordering their effects."""
    config = initialize_router_config(opts, namespace=namespace)
    if db:
        await resolve_router_models(config, db, namespace=namespace)
        await apply_admin_filter_config(config, db, namespace=namespace)
    apply_legacy_aliases(config)
    return config
