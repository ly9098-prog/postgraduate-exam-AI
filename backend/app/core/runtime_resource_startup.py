"""Initialize shared resources at their original HTTP lifespan positions."""

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("postgraduate-ai")


def initialize_role_executors(role: str) -> None:
    from app.core.deployment_profile import (
        DeploymentProfile,
        detect_deployment_profile,
    )
    from app.core.executor_registry import init_executor_registry
    from app.core.executors import init_executors_for_role

    _deploy_profile = detect_deployment_profile()
    _executors = init_executors_for_role(
        role,
        is_production=(_deploy_profile == DeploymentProfile.CLOUD_API),
    )
    init_executor_registry(_executors)
    logger.info(
        "Executors initialized for role=%s: %s",
        role,
        {k: v.name for k, v in _executors.items()},
    )


def initialize_worker_executors(*, is_production: bool) -> None:
    from app.core.executor_registry import init_executor_registry
    from app.core.executors import init_executors_for_role

    executors = init_executors_for_role(
        "worker",
        is_production=is_production,
    )
    init_executor_registry(executors)
    logger.info(
        "Worker executors initialized: %s", {k: v.name for k, v in executors.items()}
    )


async def start_resource_reconciler() -> None:
    try:
        from app.core.resource_guard import resource_guard

        await resource_guard.start_orphan_reconciler()
    except Exception as e:
        logger.warning("Orphan reconciler start failed (non-fatal): %s", e)


def ensure_http_runtime_directories(config: "Settings") -> None:
    """Create HTTP asset and export directories in the original order."""
    os.makedirs("static/formulas", exist_ok=True)
    os.makedirs("static/question-assets", exist_ok=True)
    os.makedirs("static/avatars", exist_ok=True)
    os.makedirs(config.EXPORT_DIR, exist_ok=True)
