"""RuntimeCapabilities — Frozen capability snapshot for a deployment profile.

Frozen at pipeline creation time by ControlPlane. Business modules must not
read server CPU/memory/GPU state directly — always go through this context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

# ── Default resource policies ──────────────────────────────────────────────

_LOCAL_IMPORT_DEFAULTS = {
    "cpu_count": 16,
    "memory_limit_bytes": 32 * 1024 * 1024 * 1024,  # 32 GB
    "gpu_available": True,
    "gpu_memory_bytes": 4 * 1024 * 1024 * 1024,  # 4 GB
    "local_ocr_allowed": True,
    "remote_ocr_allowed": True,
    "batch_import_allowed": True,
    "database_sync_allowed": True,
    "max_concurrent_documents": 1,
    "max_concurrent_pages": 1,
    "page_stream_window_size": 3,
    "page_stream_overlap": 1,
    "gpu_ocr_batch_size": 1,
    "gpu_memory_budget_bytes": 3200 * 1024 * 1024,  # 3200 MB budget
    "max_rendered_page_cache": 3,
    "max_remote_ocr_calls_per_document": 500,
}

_CLOUD_API_DEFAULTS = {
    "cpu_count": 2,
    "memory_limit_bytes": 2 * 1024 * 1024 * 1024,  # 2 GB
    "gpu_available": False,
    "gpu_memory_bytes": None,
    "local_ocr_allowed": False,
    "remote_ocr_allowed": True,
    "batch_import_allowed": False,
    "database_sync_allowed": False,
    "max_concurrent_documents": 1,
    "max_concurrent_pages": 1,
    "page_stream_window_size": 1,
    "page_stream_overlap": 0,
    "gpu_ocr_batch_size": 0,
    "gpu_memory_budget_bytes": 0,
    "max_rendered_page_cache": 1,
    "max_remote_ocr_calls_per_document": 100,
}


@dataclass(frozen=True)
class RuntimeCapabilities:
    """Frozen capability snapshot of the deployment environment.

    All values are determined at creation time and MUST NOT change during
    a pipeline run. Business modules use this to decide:
    - Which OCR adapters to register
    - PageStream window configuration
    - Concurrency limits
    - Resource budgets
    """

    # ── Profile ──
    profile: DeploymentProfile

    # ── CPU ──
    cpu_count: int
    memory_limit_bytes: int

    # ── GPU ──
    gpu_available: bool
    gpu_memory_bytes: int | None

    # ── Feature Allowances ──
    local_ocr_allowed: bool
    remote_ocr_allowed: bool
    batch_import_allowed: bool
    database_sync_allowed: bool

    # ── Concurrency ──
    max_concurrent_documents: int
    max_concurrent_pages: int

    # ── PageStream ──
    page_stream_window_size: int
    page_stream_overlap: int

    # ── GPU / Local OCR ──
    gpu_ocr_batch_size: int
    gpu_memory_budget_bytes: int

    # ── Caching ──
    max_rendered_page_cache: int

    # ── API Budgets ──
    max_remote_ocr_calls_per_document: int

    # ── Serialization ──

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict (for pipeline artifacts)."""
        return {
            "profile": self.profile.value,
            "cpu_count": self.cpu_count,
            "memory_limit_bytes": self.memory_limit_bytes,
            "gpu_available": self.gpu_available,
            "gpu_memory_bytes": self.gpu_memory_bytes,
            "local_ocr_allowed": self.local_ocr_allowed,
            "remote_ocr_allowed": self.remote_ocr_allowed,
            "batch_import_allowed": self.batch_import_allowed,
            "database_sync_allowed": self.database_sync_allowed,
            "max_concurrent_documents": self.max_concurrent_documents,
            "max_concurrent_pages": self.max_concurrent_pages,
            "page_stream_window_size": self.page_stream_window_size,
            "page_stream_overlap": self.page_stream_overlap,
            "gpu_ocr_batch_size": self.gpu_ocr_batch_size,
            "gpu_memory_budget_bytes": self.gpu_memory_budget_bytes,
            "max_rendered_page_cache": self.max_rendered_page_cache,
            "max_remote_ocr_calls_per_document": self.max_remote_ocr_calls_per_document,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeCapabilities:
        """Deserialize from dict (for resume from artifact)."""
        return cls(
            profile=DeploymentProfile(data.get("profile", DeploymentProfile.LOCAL_IMPORT.value)),
            cpu_count=data.get("cpu_count", 2),
            memory_limit_bytes=data.get("memory_limit_bytes", 2 * 1024 * 1024 * 1024),
            gpu_available=data.get("gpu_available", False),
            gpu_memory_bytes=data.get("gpu_memory_bytes"),
            local_ocr_allowed=data.get("local_ocr_allowed", False),
            remote_ocr_allowed=data.get("remote_ocr_allowed", True),
            batch_import_allowed=data.get("batch_import_allowed", False),
            database_sync_allowed=data.get("database_sync_allowed", False),
            max_concurrent_documents=data.get("max_concurrent_documents", 1),
            max_concurrent_pages=data.get("max_concurrent_pages", 1),
            page_stream_window_size=data.get("page_stream_window_size", 1),
            page_stream_overlap=data.get("page_stream_overlap", 0),
            gpu_ocr_batch_size=data.get("gpu_ocr_batch_size", 0),
            gpu_memory_budget_bytes=data.get("gpu_memory_budget_bytes", 0),
            max_rendered_page_cache=data.get("max_rendered_page_cache", 1),
            max_remote_ocr_calls_per_document=data.get("max_remote_ocr_calls_per_document", 100),
        )


# ── Factory ────────────────────────────────────────────────────────────────


def build_runtime_capabilities(
    profile: DeploymentProfile | None = None,
    *,
    cpu_count: int | None = None,
    memory_limit_bytes: int | None = None,
    gpu_available: bool | None = None,
    gpu_memory_bytes: int | None = None,
    **overrides: Any,
) -> RuntimeCapabilities:
    """Build RuntimeCapabilities, applying overrides from env & explicit params.

    Resolution order (highest priority first):
      1. Explicit keyword arguments
      2. Environment variable overrides (``CLOUD_MAX_CONCURRENT_PAGES``, etc.)
      3. Profile defaults

    Args:
        profile: Deployment profile. Auto-detected if None.
        cpu_count: Override CPU count.
        memory_limit_bytes: Override memory limit.
        gpu_available: Override GPU availability.
        gpu_memory_bytes: Override GPU memory.

    Returns:
        Frozen RuntimeCapabilities.
    """
    profile = profile or detect_deployment_profile()

    defaults = _LOCAL_IMPORT_DEFAULTS if profile == DeploymentProfile.LOCAL_IMPORT else _CLOUD_API_DEFAULTS

    # Build from defaults, then apply env overrides, then explicit overrides
    values: dict[str, Any] = dict(defaults)
    _apply_env_overrides(values, profile)
    values["profile"] = profile

    # Explicit keyword overrides
    for key, val in [
        ("cpu_count", cpu_count),
        ("memory_limit_bytes", memory_limit_bytes),
        ("gpu_available", gpu_available),
        ("gpu_memory_bytes", gpu_memory_bytes),
    ]:
        if val is not None:
            values[key] = val

    # Remaining overrides
    for key, val in overrides.items():
        if key in values:
            values[key] = val

    return RuntimeCapabilities(
        profile=values["profile"],
        cpu_count=values["cpu_count"],
        memory_limit_bytes=values["memory_limit_bytes"],
        gpu_available=values["gpu_available"],
        gpu_memory_bytes=values["gpu_memory_bytes"],
        local_ocr_allowed=values["local_ocr_allowed"],
        remote_ocr_allowed=values["remote_ocr_allowed"],
        batch_import_allowed=values["batch_import_allowed"],
        database_sync_allowed=values["database_sync_allowed"],
        max_concurrent_documents=values["max_concurrent_documents"],
        max_concurrent_pages=values["max_concurrent_pages"],
        page_stream_window_size=values["page_stream_window_size"],
        page_stream_overlap=values["page_stream_overlap"],
        gpu_ocr_batch_size=values["gpu_ocr_batch_size"],
        gpu_memory_budget_bytes=values["gpu_memory_budget_bytes"],
        max_rendered_page_cache=values["max_rendered_page_cache"],
        max_remote_ocr_calls_per_document=values["max_remote_ocr_calls_per_document"],
    )


_PROFILE_ENV_PREFIX_MAP = {
    DeploymentProfile.LOCAL_IMPORT: "LOCAL_",
    DeploymentProfile.CLOUD_API: "CLOUD_",
}

_ENV_KEY_MAP: dict[str, str] = {
    "MAX_CONCURRENT_DOCUMENTS": "max_concurrent_documents",
    "MAX_CONCURRENT_PAGES": "max_concurrent_pages",
    "PAGE_STREAM_WINDOW_SIZE": "page_stream_window_size",
    "PAGE_STREAM_OVERLAP": "page_stream_overlap",
    "GPU_OCR_BATCH_SIZE": "gpu_ocr_batch_size",
    "GPU_MEMORY_BUDGET_MB": None,  # special: bytes conversion
    "MAX_RENDERED_PAGE_CACHE": "max_rendered_page_cache",
    "MAX_REMOTE_OCR_CALLS_PER_DOCUMENT": "max_remote_ocr_calls_per_document",
    "MAX_INPUT_BYTES": None,  # special: maps to quota
    "MAX_PAGES": None,  # special: maps to quota
}


def _apply_env_overrides(values: dict[str, Any], profile: DeploymentProfile) -> None:
    """Apply environment variable overrides for the given profile."""
    prefix = _PROFILE_ENV_PREFIX_MAP[profile]
    for env_suffix, key in _ENV_KEY_MAP.items():
        env_var = f"{prefix}{env_suffix}"
        raw = os.environ.get(env_var)
        if raw is None:
            continue
        if key is None:
            continue  # quota values handled separately
        try:
            if env_suffix == "GPU_MEMORY_BUDGET_MB":
                values[key] = int(raw) * 1024 * 1024
            else:
                values[key] = int(raw)
        except (ValueError, TypeError):
            pass

    # Apply non-prefixed generic overrides (CLOUD_* OR LOCAL_*)
    for env_var, key in [("CLOUD_PAGE_STREAM_WINDOW_SIZE", "page_stream_window_size"),
                          ("CLOUD_PAGE_STREAM_OVERLAP", "page_stream_overlap"),
                          ("CLOUD_MAX_CONCURRENT_PAGES", "max_concurrent_pages"),
                          ("CLOUD_MAX_RENDERED_PAGE_CACHE", "max_rendered_page_cache"),
                          ("CLOUD_MAX_REMOTE_OCR_CALLS_PER_DOCUMENT", "max_remote_ocr_calls_per_document")]:
        raw = os.environ.get(env_var)
        if raw is not None:
            try:
                values[key] = int(raw)
            except (ValueError, TypeError):
                pass
