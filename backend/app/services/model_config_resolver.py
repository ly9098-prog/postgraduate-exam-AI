"""Model config resolver for DB-stored AI model configurations.

Use ``AIModelConfigResolver``/``app.ai.gateway`` for new call sites. The legacy
``ensure_db_model_configured`` helper remains for backward compatibility.

Each feature (ocr / completion / analysis) can have its own dedicated model.
A model tagged with ``features=None`` serves as the default fallback for all
features when no feature-specific model is configured.

Returns ``(api_key, base_url, model_name)`` — all three come from the
first enabled ``AdminAiModelConfig`` row.  Returns ``None`` when no
enabled model is found or the key cannot be decrypted (caller falls back
to env-var defaults).

Extended in Sprint 4D with:
- ``AIModelConfigResolver`` class-based resolver with capability support
- ``ResolvedAIModelConfig`` / ``AIModelConfigSnapshot`` frozen data models
- Stable error codes for AI configuration failures
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_crypto import (
    SecretDecryptionError,
    SecretEncryptionError,
    decrypt_secret,
)
from app.models.admin_ai_config import AdminAiModelConfig

logger = logging.getLogger(__name__)

try:
    from app.core.log_context import log_event
except ImportError:  # pragma: no cover
    def log_event(_lg, _ev, **_kw):  # type: ignore[misc]
        pass


# ---------------------------------------------------------------------------
# Capability constants
# ---------------------------------------------------------------------------

class AICapability(StrEnum):
    """AI capability identifiers for model config resolution."""
    OCR_LIGHTWEIGHT = "ocr_lightweight"
    OCR_VL = "ocr_vl"
    OCR_FIX = "ocr_fix"
    AI_REPAIR = "ai_repair"
    TEXT_CORRECTION = "text_correction"
    TEXT_STRUCTURING = "text_structuring"
    COMPLETION = "completion"
    ANALYSIS = "analysis"
    EMBEDDING = "embedding"


# ---------------------------------------------------------------------------
# Stable error codes
# ---------------------------------------------------------------------------

class AIConfigErrorCode(StrEnum):
    """Stable error codes for AI configuration failures."""
    AI_CONFIG_NOT_FOUND = "AI_CONFIG_NOT_FOUND"
    AI_CONFIG_DISABLED = "AI_CONFIG_DISABLED"
    AI_MODEL_CONFIG_NOT_FOUND = "AI_MODEL_CONFIG_NOT_FOUND"
    AI_MODEL_DISABLED = "AI_MODEL_DISABLED"
    AI_CONFIG_CAPABILITY_MISMATCH = "AI_CONFIG_CAPABILITY_MISMATCH"
    AI_CONFIG_PROVIDER_UNSUPPORTED = "AI_CONFIG_PROVIDER_UNSUPPORTED"
    AI_CONFIG_SECRET_MISSING = "AI_CONFIG_SECRET_MISSING"
    AI_CONFIG_ENDPOINT_INVALID = "AI_CONFIG_ENDPOINT_INVALID"
    AI_CONFIG_AMBIGUOUS = "AI_CONFIG_AMBIGUOUS"


def _fmt_error(code: str, message: str) -> str:
    """Unified ValueError format: code: message"""
    return f"{code}: {message}"


# ---------------------------------------------------------------------------
# Unified configuration data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedAIModelConfig:
    """Unified resolved AI model configuration — safe to pass through pipeline.

    Contains all fields needed to configure an adapter, without secrets.
    """
    config_id: int | str
    model_config_id: int | str

    provider: str
    model_name: str
    endpoint: str | None = None

    enabled: bool = True
    capabilities: frozenset[str] = field(default_factory=frozenset)

    timeout_seconds: float = 120.0
    max_retries: int = 3

    config_fingerprint: str = ""
    secret_reference: str | None = None

    metadata: dict[str, object] = field(default_factory=dict)
    # NOTE: dict contents are mutable despite frozen dataclass.
    # Callers must not mutate after construction — no frozenset on dict.
    # Serialization-friendly design choice.


@dataclass(frozen=True)
class AIModelConfigSnapshot:
    """Safe snapshot of AI model config for pipeline context.

    Only non-sensitive fields — never contains api_key, token, or
    any secrets. Frozen at pipeline start for resume safety.
    """
    config_id: int | str
    model_config_id: int | str

    provider: str
    model_name: str
    capability: str

    config_fingerprint: str
    timeout_seconds: float
    max_retries: int

    resolved_at: str = ""

    @classmethod
    def from_resolved(
        cls,
        resolved: ResolvedAIModelConfig,
        capability: str,
        *,
        resolved_at: str | None = None,
    ) -> AIModelConfigSnapshot:
        """Create a safe snapshot from a resolved config."""
        return cls(
            config_id=resolved.config_id,
            model_config_id=resolved.model_config_id,
            provider=resolved.provider,
            model_name=resolved.model_name,
            capability=capability,
            config_fingerprint=resolved.config_fingerprint,
            timeout_seconds=resolved.timeout_seconds,
            max_retries=resolved.max_retries,
            resolved_at=resolved_at or datetime.now().isoformat(),
        )


# ---------------------------------------------------------------------------
# Unified Resolver
# ---------------------------------------------------------------------------


class AIModelConfigResolver:
    """Unified AI model config resolver.

    Resolves the best model configuration for a given capability by querying
    the admin_ai_model_configs table. Supports capability-based resolution,
    config snapshots, and cached resolution within a single pipeline.

    Design:
    - Each pipeline resolves config once per capability, not per page
    - Snapshots are safe for PipelineExecutionContext (no secrets)
    - Secret resolution is deferred to call time via SecretProvider

    Usage::

        resolver = AIModelConfigResolver(db)
        config = await resolver.resolve_for_capability(AICapability.OCR_VL)
        # config is ResolvedAIModelConfig (no secrets)
        snapshot = AIModelConfigSnapshot.from_resolved(config, "ocr_vl")
    """

    # Default timeout/retry by capability when model config has no override
    _DEFAULT_TIMEOUTS: dict[str, float] = {
        "ocr_vl": 300.0,
        "ocr_lightweight": 60.0,
        "ocr_fix": 150.0,
        "ai_repair": 150.0,
        "text_structuring": 120.0,
        "completion": 120.0,
        "analysis": 120.0,
    }

    _DEFAULT_RETRIES: dict[str, int] = {
        "ocr_vl": 3,
        "ocr_lightweight": 3,
        "ocr_fix": 2,
        "ai_repair": 2,
    }

    def __init__(
        self,
        db: AsyncSession,
        *,
        tenant_id: str | None = None,
    ) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._cache: dict[str, ResolvedAIModelConfig | None] = {}

    def clear_cache(self) -> None:
        """Clear per-instance resolution cache."""
        self._cache.clear()

    async def resolve_for_capability(
        self,
        capability: str,
        *,
        requested_config_id: int | str | None = None,
        deployment_profile: str | None = None,
    ) -> ResolvedAIModelConfig:
        """Resolve the best model config for a given capability.

        Resolution order:
        1. Explicit ``requested_config_id`` — use exactly that model
        2. An enabled model whose ``features`` array contains the capability
        3. An enabled model with no features (untagged default)
        4. Any enabled model (last resort)

        Capability mapping to DB features:
        - ``ocr_vl``          → features contains "vision" and provider is PaddleOCR
        - ``ocr_lightweight`` → features contains "ocr"
        - ``ocr_fix``         → "ocr_fix" / "text_correction" / legacy "ocr"
        - ``ai_repair``       → "ai_repair" / legacy "completion"
        - ``analysis``        → "analysis"

        Provider routing is also enforced: proprietary PaddleOCR endpoints are
        never selected as a fallback for OpenAI-compatible chat capabilities.

        Raises ``ValueError`` with an ``AIConfigErrorCode`` on failure.
        """
        capability = capability.value if isinstance(capability, AICapability) else str(capability)

        # Check cache
        cache_key = f"{capability}:{requested_config_id or ''}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if cached is None:
                raise ValueError(
                    f"No enabled model for capability '{capability}' "
                    f"(cached negative result for this pipeline)"
                )
            return cached

        try:
            result = await self._resolve(capability, requested_config_id=requested_config_id)
            self._cache[cache_key] = result
            return result
        except (ValueError, TypeError):
            self._cache[cache_key] = None
            raise

    async def resolve_secret(
        self,
        config: ResolvedAIModelConfig,
    ) -> str:
        """Resolve the API key/secret for a resolved config.

        Only called at the point of actual API invocation — never stored
        in context, artifacts, or logs.
        """
        model = await self._db.get(AdminAiModelConfig, int(config.model_config_id))
        if model is None or not model.api_key_encrypted:
            raise ValueError(
                AIConfigErrorCode.AI_CONFIG_SECRET_MISSING.value,
                f"No secret configured for model config {config.model_config_id}",
            )
        decrypted = decrypt_secret(model.api_key_encrypted)
        if not decrypted:
            raise ValueError(
                AIConfigErrorCode.AI_CONFIG_SECRET_MISSING.value,
                f"Secret for model config {config.model_config_id} cannot be decrypted",
            )
        return decrypted

    async def _resolve(
        self,
        capability: str,
        *,
        requested_config_id: int | str | None = None,
    ) -> ResolvedAIModelConfig:
        """Internal resolution logic."""
        db_features = self._capability_to_db_features(capability)

        if requested_config_id is not None:
            return await self._resolve_by_id(requested_config_id, db_features, capability=capability)

        # Query all enabled models
        result = await self._db.execute(
            select(AdminAiModelConfig)
            .where(AdminAiModelConfig.is_enabled)
            .order_by(
                AdminAiModelConfig.is_default.desc(),
                AdminAiModelConfig.sort_order.asc(),
            )
        )
        all_enabled = result.scalars().all()

        if not all_enabled:
            raise ValueError(
                AIConfigErrorCode.AI_MODEL_CONFIG_NOT_FOUND.value,
                "No enabled AI model configs found in database",
            )

        all_enabled = [
            model for model in all_enabled
            if self._provider_matches_capability(model.provider, capability)
        ]
        if not all_enabled:
            raise ValueError(
                AIConfigErrorCode.AI_CONFIG_PROVIDER_UNSUPPORTED.value,
                f"No provider-compatible model for capability '{capability}'",
            )

        # 1. Capability-specific match. More specific feature labels are
        # checked before legacy coarse labels, e.g. ocr_fix before ocr.
        for db_feature in db_features:
            for model in all_enabled:
                model_features = _get_model_features(model)
                if db_feature in model_features:
                    return self._to_resolved(model, capability)

        # 2. Untagged default (no features)
        for model in all_enabled:
            if not _get_model_features(model):
                return self._to_resolved(model, capability)

        # 3. Any enabled model (last resort)
        for model in all_enabled:
            log_event(
                logger, "ai.model.resolve.fallback", "info",
                capability=capability, model_name=model.name,
                provider=model.provider,
            )
            return self._to_resolved(model, capability)

        raise ValueError(
            AIConfigErrorCode.AI_MODEL_CONFIG_NOT_FOUND.value,
            f"No enabled model for capability '{capability}' and no fallback available",
        )

    async def _resolve_by_id(
        self,
        config_id: int | str,
        db_features: tuple[str, ...],
        capability: str = "unknown",
    ) -> ResolvedAIModelConfig:
        """Resolve a specific model config by ID."""
        model = await self._db.get(AdminAiModelConfig, int(config_id))
        if model is None:
            raise ValueError(
                AIConfigErrorCode.AI_MODEL_CONFIG_NOT_FOUND.value,
                f"Model config with id={config_id} not found",
            )
        if not model.is_enabled:
            raise ValueError(
                AIConfigErrorCode.AI_MODEL_DISABLED.value,
                f"Model config id={config_id} ('{model.name}') is disabled",
            )
        if not self._provider_matches_capability(model.provider, capability):
            raise ValueError(
                AIConfigErrorCode.AI_CONFIG_PROVIDER_UNSUPPORTED.value,
                f"Provider '{model.provider}' cannot serve capability '{capability}'",
            )
        if db_features:
            model_features = _get_model_features(model)
            if model_features and not any(f in model_features for f in db_features):
                raise ValueError(
                    AIConfigErrorCode.AI_CONFIG_CAPABILITY_MISMATCH.value,
                    f"Model config id={config_id} ('{model.name}') does not support "
                    f"features {list(db_features)} (has: {model_features})",
                )
        return self._to_resolved(model, capability)

    def _to_resolved(
        self,
        model: AdminAiModelConfig,
        capability: str,
    ) -> ResolvedAIModelConfig:
        """Convert an ORM model to a ResolvedAIModelConfig (no secrets)."""
        model_features = _get_model_features(model)
        fp = hashlib.sha256(
            json.dumps({
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                "base_url": model.api_base_url,
                "features": sorted(str(f) for f in model_features),
                "is_enabled": model.is_enabled,
                "is_default": model.is_default,
            }, sort_keys=True).encode()
        ).hexdigest()[:16]

        return ResolvedAIModelConfig(
            config_id=model.id,
            model_config_id=model.id,
            provider=model.provider,
            model_name=model.name,
            endpoint=model.api_base_url,
            enabled=model.is_enabled,
            capabilities=frozenset(model_features),
            timeout_seconds=self._DEFAULT_TIMEOUTS.get(capability, 120.0),
            max_retries=self._DEFAULT_RETRIES.get(capability, 3),
            config_fingerprint=fp,
            secret_reference="admin_ai_model_configs.api_key_encrypted",
            metadata={
                "display_name": model.display_name,
                "sort_order": model.sort_order,
                "is_default": model.is_default,
            },
        )

    @staticmethod
    def _provider_matches_capability(provider: str | None, capability: str) -> bool:
        """Keep proprietary OCR endpoints out of generic chat fallback routing."""
        normalized = (provider or "").strip().lower().replace("_", "-")
        is_paddleocr = normalized.startswith("paddleocr")
        if capability == AICapability.OCR_VL.value:
            return is_paddleocr
        if capability in {
            AICapability.OCR_FIX.value,
            AICapability.AI_REPAIR.value,
            AICapability.TEXT_CORRECTION.value,
            AICapability.TEXT_STRUCTURING.value,
            AICapability.COMPLETION.value,
            AICapability.ANALYSIS.value,
        }:
            return not is_paddleocr
        return True

    @staticmethod
    def _capability_to_db_features(capability: str) -> tuple[str, ...]:
        """Map runtime capability to DB feature labels, specific first.

        Legacy coarse labels (ocr/completion) remain fallbacks so existing
        installations continue to work without a data migration.
        """
        mapping: dict[str, tuple[str, ...]] = {
            "ocr_vl": ("vision",),
            "ocr_lightweight": ("ocr_lightweight", "ocr"),
            "ocr_fix": ("ocr_fix", "text_correction", "ocr"),
            "ai_repair": ("ai_repair", "completion"),
            "text_correction": ("text_correction", "ocr_fix", "ocr"),
            "text_structuring": ("text_structuring", "completion"),
            "completion": ("completion",),
            "analysis": ("analysis",),
            "embedding": ("embedding",),
        }
        return mapping.get(capability, (capability,) if capability else ())



# ---------------------------------------------------------------------------
# Pipeline config resolution helper
# ---------------------------------------------------------------------------


async def resolve_pipeline_ai_configs(
    db: AsyncSession,
    capabilities: list[str] | None = None,
    *,
    tenant_id: str | None = None,
) -> dict[str, dict]:
    """Resolve AI model configs for all capabilities needed by a pipeline.

    Returns serialized ``AIModelConfigSnapshot`` dicts keyed by capability,
    safe for ``PipelineExecutionContext.ai_model_configs``.

    Each capability is resolved independently. Missing capabilities are
    silently omitted (no error) — the pipeline will fall back to empty config.

    Args:
        db: Database session.
        capabilities: List of capabilities to resolve. Defaults to
            pipeline-relevant capabilities (ocr_vl, ocr_lightweight, ocr_fix).
        tenant_id: Optional tenant scope.

    Returns:
        Dict mapping capability → serialized AIModelConfigSnapshot dict.
    """
    if capabilities is None:
        capabilities = ["ocr_vl", "ocr_lightweight", "ocr_fix", "ai_repair"]

    resolver = AIModelConfigResolver(db, tenant_id=tenant_id)
    result: dict[str, dict] = {}

    for cap in capabilities:
        try:
            resolved = await resolver.resolve_for_capability(cap)
            snapshot = AIModelConfigSnapshot.from_resolved(resolved, cap)
            # Convert to dict for serialization (no secrets)
            snapshot_dict = {
                "config_id": snapshot.config_id,
                "model_config_id": snapshot.model_config_id,
                "provider": snapshot.provider,
                "model_name": snapshot.model_name,
                "capability": snapshot.capability,
                "config_fingerprint": snapshot.config_fingerprint,
                "timeout_seconds": snapshot.timeout_seconds,
                "max_retries": snapshot.max_retries,
                "resolved_at": snapshot.resolved_at,
            }
            result[cap] = snapshot_dict
            log_event(
                logger, "ai.model.resolve.pipeline", "info",
                capability=cap, model_name=resolved.model_name,
                provider=resolved.provider,
            )
        except ValueError:
            log_event(
                logger, "ai.model.resolve.skipped", "info",
                capability=cap, reason="no_enabled_model",
            )
            continue

    return result


# ---------------------------------------------------------------------------
# Legacy functions — kept for backward compatibility
# ---------------------------------------------------------------------------


# Legacy functions


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
        .where(AdminAiModelConfig.is_enabled)
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
        log_event(
            logger, "ai.model.resolve.fallback", "info",
            feature=feature, model_name=model.name, provider=model.provider,
        )
        return _decrypt_model(model)

    log_event(logger, "ai.model.resolve.fallback", "info", feature=feature, reason="no_enabled_model")
    return None


def _decrypt_model(model: AdminAiModelConfig) -> dict | None:
    try:
        api_key = decrypt_secret(model.api_key_encrypted) if model.api_key_encrypted else ""
    except (SecretDecryptionError, SecretEncryptionError):
        api_key = ""
    if not api_key:
        log_event(
            logger, "ai.model.resolve.error", "warning",
            model_name=model.name, provider=model.provider,
            reason="no_decryptable_api_key",
        )
        return None
    return {
        "api_key": api_key,
        "id": model.id,
        "api_base_url": model.api_base_url or "",
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

    Does not modify any process-global client. New code should prefer
    ``app.ai.gateway.resolve_llm_runtime_config`` so provider metadata is kept.
    """
    config = await resolve_active_model(db, feature=feature)
    if config:
        log_event(
            logger, "ai.model.resolve.finish", "info",
            feature=feature, model_name=config["model_name"],
            display_name=config.get("display_name", ""),
            provider=config.get("provider", ""),
            source="db",
        )
        return (config["api_key"], config["api_base_url"], config["model_name"])

    log_event(logger, "ai.model.resolve.fallback", "info", feature=feature, source="env_vars")
    return None
