"""Unified DB-backed gateway for OpenAI-compatible chat models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import llm
from app.services.model_config_resolver import (
    AICapability,
    AIModelConfigResolver,
    resolve_active_model,
)


@dataclass(frozen=True)
class LLMRuntimeConfig:
    api_key: str
    base_url: str
    model_name: str
    provider: str
    model_config_id: int | str | None = None
    capabilities: frozenset[str] = frozenset()


def _is_non_chat_provider(provider: str | None, model_name: str | None = None) -> bool:
    value = (provider or "").strip().lower().replace("_", "-")
    model_value = (model_name or "").strip().lower().replace("_", "-")
    # PaddleOCR-VL in this project has a vendor-specific OCR endpoint rather
    # than OpenAI chat/completions. Some deployed DB rows historically used
    # the provider alias ``paddleoce``; model-name detection keeps that typo
    # from leaking into generic chat/analysis routing as well. Other VL chat
    # providers (for example Qwen-VL) remain valid OpenAI-compatible models.
    return (
        value.startswith("paddleocr")
        or value.startswith("paddle-ocr")
        or value.startswith("paddleoce")
        or "paddleocr" in model_value
        or "paddle-ocr" in model_value
    )


async def resolve_llm_runtime_config(
    db: AsyncSession,
    *,
    feature: str | None = None,
    capability: str | AICapability | None = None,
) -> LLMRuntimeConfig | None:
    """Resolve model, endpoint, provider and secret once for an LLM call."""
    capability_value = (
        capability.value if isinstance(capability, AICapability) else str(capability)
    ) if capability is not None else None
    # ``analysis`` is retained as a compatibility capability even though it is
    # not a strict AICapability enum member. This preserves the existing DB-backed
    # analysis routing used by stats/AI services.
    known_capabilities = {item.value for item in AICapability} | {"analysis"}
    if capability_value is None and feature in known_capabilities:
        capability_value = feature

    if capability_value is not None:
        resolver = AIModelConfigResolver(db)
        try:
            resolved = await resolver.resolve_for_capability(capability_value)
            if _is_non_chat_provider(resolved.provider, resolved.model_name) or not resolved.endpoint:
                return None
            secret = await resolver.resolve_secret(resolved)
            return LLMRuntimeConfig(
                api_key=secret,
                base_url=resolved.endpoint,
                model_name=resolved.model_name,
                provider=resolved.provider,
                model_config_id=resolved.model_config_id,
                capabilities=frozenset(resolved.capabilities),
            )
        except (ValueError, TypeError):
            return None

    config = await resolve_active_model(db, feature=feature)
    if not config:
        return None
    if _is_non_chat_provider(config.get("provider"), config.get("model_name")):
        return None
    base_url = str(config.get("api_base_url") or "").strip()
    if not base_url:
        return None
    return LLMRuntimeConfig(
        api_key=str(config["api_key"]),
        base_url=base_url,
        model_name=str(config["model_name"]),
        provider=str(config.get("provider") or "openai_compatible"),
        model_config_id=config.get("id"),
        capabilities=frozenset(str(item) for item in (config.get("features") or []) if item),
    )


async def chat_with_db_model(
    db: AsyncSession,
    messages: list[dict[str, Any]],
    *,
    feature: str | None = None,
    capability: str | AICapability | None = None,
    temperature: float | None = 0.3,
    timeout: float | None = None,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve a configured compatible model and invoke it.

    Returns ``None`` when no suitable enabled chat model is configured. Remote
    API errors are intentionally raised so the caller can choose its existing
    fallback/rollback behaviour.
    """
    runtime = await resolve_llm_runtime_config(
        db,
        feature=feature,
        capability=capability,
    )
    if runtime is None:
        return None
    return await llm.chat(
        messages,
        temperature=temperature,
        model=runtime.model_name,
        api_key=runtime.api_key,
        base_url=runtime.base_url,
        provider=runtime.provider,
        timeout=timeout,
        max_tokens=max_tokens,
        response_format=response_format,
        extra_body=extra_body,
    )
