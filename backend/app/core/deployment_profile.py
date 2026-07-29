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
    """Resolve one deployment profile from the canonical and legacy settings.

    ``DEPLOYMENT_PROFILE`` is canonical and may come from the process
    environment or the Settings object (including ``.env``). Legacy
    ``DEPLOY_PROFILE`` is accepted only for ``local``/``production`` and is
    checked for conflicts. Invalid or conflicting configuration raises instead
    of silently selecting a permissive local profile.
    """
    explicit = (
        os.environ.get("DEPLOYMENT_PROFILE")
        or settings.DEPLOYMENT_PROFILE
        or ""
    ).strip().lower()
    legacy = (settings.DEPLOY_PROFILE or "").strip().lower()
    app_env = (settings.APP_ENV or "").strip().lower()

    legacy_map = {
        "local": DeploymentProfile.LOCAL_IMPORT,
        "production": DeploymentProfile.CLOUD_API,
    }
    if legacy and legacy not in legacy_map:
        raise ValueError(
            f"无效的 DEPLOY_PROFILE={legacy!r}，必须为 {sorted(legacy_map)}"
        )

    if explicit:
        try:
            profile = DeploymentProfile(explicit)
        except ValueError as exc:
            raise ValueError(
                f"无效的 DEPLOYMENT_PROFILE={explicit!r}，"
                f"必须为 {[p.value for p in DeploymentProfile]}"
            ) from exc
        if legacy and profile != legacy_map[legacy]:
            raise ValueError(
                "部署档案冲突: "
                f"DEPLOYMENT_PROFILE={explicit!r} 与 DEPLOY_PROFILE={legacy!r} 不一致"
            )
        if app_env == "production" and profile != DeploymentProfile.CLOUD_API:
            raise ValueError(
                "部署档案冲突: APP_ENV='production' 时 "
                "DEPLOYMENT_PROFILE 必须为 'cloud_api'"
            )
        return profile

    if legacy:
        return legacy_map[legacy]
    if app_env == "production":
        return DeploymentProfile.CLOUD_API
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
