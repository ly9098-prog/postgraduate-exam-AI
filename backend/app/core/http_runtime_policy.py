"""HTTP startup role, OCR isolation and component failure policies."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("postgraduate-ai")


def prepare_http_runtime_role(
    config: Settings,
    resolve_role: Callable[[str, str, bool], str],
) -> str:
    configured_role = config.PROCESS_ROLE
    role = resolve_role(
        config.APP_ENV, configured_role, config.LOCAL_ASYNC_RUNTIME_ENABLED
    )
    if role != configured_role:
        logger.info(
            "Local async runtime disabled: configured PROCESS_ROLE=%s -> effective role=%s. "
            "Set LOCAL_ASYNC_RUNTIME_ENABLED=true only for full local worker/scheduler debugging.",
            configured_role,
            role,
        )
        config.PROCESS_ROLE = role
        os.environ["PROCESS_ROLE"] = role
    if role in ("worker", "scheduler"):
        raise SystemError(
            f"PROCESS_ROLE={role} must not start the FastAPI HTTP application; "
            f"use python -m app.{role}_main"
        )
    return role


def assert_http_ocr_isolation(
    loaded_modules: Callable[[], list[str]],
    is_restricted: Callable[[], bool],
) -> None:
    try:
        from app.core.deployment_profile import (
            DeploymentProfile,
            detect_deployment_profile,
        )

        if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
            loaded = loaded_modules()
            if loaded:
                logger.critical(
                    "cloud_api deployment detected banned modules in sys.modules: %s",
                    loaded,
                )
                raise SystemError(
                    f"Banned local OCR modules loaded in cloud_api: {loaded}"
                )
    except SystemError:
        raise
    except Exception as e:
        if is_restricted():
            raise SystemError(f"OCR module isolation check failed: {e}") from e
        logger.warning("OCR module isolation check failed: %s", e)


def report_http_startup_failure(
    component: str,
    exc: Exception,
    production_mode: bool,
) -> None:
    """Log component startup failure.

    In production, any core component startup failure is fatal.
    """
    from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

    try:
        is_prod = (
            detect_deployment_profile() == DeploymentProfile.CLOUD_API
            or production_mode
        )
    except Exception:
        is_prod = False
    if is_prod:
        logger.critical("%s start failed \u2014 fatal in production", component)
        raise SystemError(f"{component} start failed: {exc}") from exc
    logger.warning("%s start failed (non-fatal): %s", component, exc)
