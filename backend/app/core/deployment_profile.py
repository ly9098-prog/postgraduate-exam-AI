"""Deployment Profile — Environment capability classification.

Defines the two deployment profiles and their default resource policies.
Profile is frozen at pipeline creation time and cannot change mid-pipeline.
"""

from __future__ import annotations

import os
from enum import StrEnum

from app.core.config import settings


class DeploymentProfile(StrEnum):
    LOCAL_IMPORT = "local_import"
    CLOUD_API = "cloud_api"


# ── Profile Detection ──────────────────────────────────────────────────────


def detect_deployment_profile() -> DeploymentProfile:
    """Detect the current deployment profile from environment / config.

    Resolution order:
      1. DEPLOYMENT_PROFILE env var (highest priority)
      2. DEPLOY_PROFILE setting (local → local_import, production → cloud_api)
      3. APP_ENV setting (development → local_import, production → cloud_api)
      4. Default to local_import for development

    Conflict detection:
      If DEPLOYMENT_PROFILE env var AND DEPLOY_PROFILE setting are both set
      AND they disagree, raises ValueError with all conflicting sources.

    Returns:
        DeploymentProfile value.
    """
    # Collect all sources for conflict detection
    sources: dict[str, str | None] = {
        "DEPLOYMENT_PROFILE": os.environ.get("DEPLOYMENT_PROFILE"),
        "DEPLOY_PROFILE": settings.DEPLOY_PROFILE or None,
        "APP_ENV": settings.APP_ENV or None,
    }

    # 1. Explicit DEPLOYMENT_PROFILE env var
    explicit = sources["DEPLOYMENT_PROFILE"]
    if explicit:
        try:
            profile = DeploymentProfile(explicit)
        except ValueError:
            raise ValueError(
                f"无效的 DEPLOYMENT_PROFILE={explicit!r}，"
                f"必须为 {[p.value for p in DeploymentProfile]}"
            )
        # Conflict detection: DEPLOYMENT_PROFILE env var vs DEPLOY_PROFILE setting
        deploy_profile = sources["DEPLOY_PROFILE"]
        if deploy_profile:
            expected = DeploymentProfile.LOCAL_IMPORT if deploy_profile == "local" else DeploymentProfile.CLOUD_API
            if profile != expected:
                raise ValueError(
                    f"部署档案冲突: DEPLOYMENT_PROFILE={explicit!r} "
                    f"与 DEPLOY_PROFILE={deploy_profile!r} 不一致。"
                    f"请只设置其中一个，或确保两者一致。"
                    f"来源: {sources}"
                )
        return profile

    # 2. DEPLOY_PROFILE setting
    deploy = settings.DEPLOY_PROFILE
    if deploy == "local":
        return DeploymentProfile.LOCAL_IMPORT
    if deploy == "production":
        return DeploymentProfile.CLOUD_API

    # 3. APP_ENV setting
    env = settings.APP_ENV
    if env == "production":
        return DeploymentProfile.CLOUD_API

    # 4. Default to local_import for development
    return DeploymentProfile.LOCAL_IMPORT


# ── Profile Validation ─────────────────────────────────────────────────────


ILLEGAL_COMBINATIONS: list[tuple[str, str, str]] = [
    # (profile, feature_flag, error_message)
    ("cloud_api", "OCR_USE_GPU=true", "cloud_api + GPU required is prohibited"),
    ("cloud_api", "STRUCTURE_FREEZE_MODE=ir", "cloud_api + full IR freeze is prohibited"),  # local-only capability
    ("cloud_api", "CONTROL_PLANE_MODE=legacy", "cloud_api must use facade control plane"),
]


def validate_profile_flags(profile: DeploymentProfile) -> list[str]:
    """Validate that the profile + feature flag combination is legal.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []
    for prof, flag, msg in ILLEGAL_COMBINATIONS:
        if profile.value != prof:
            continue
        key, val = flag.split("=", 1)
        env_val = os.environ.get(key, settings.model_dump().get(key.split("_")[0].lower(), ""))
        if str(env_val).lower() == val.lower():
            errors.append(msg)
    return errors
