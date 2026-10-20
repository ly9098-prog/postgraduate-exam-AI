"""Initialize shared resources at their original HTTP lifespan positions."""

import logging

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


async def start_resource_reconciler() -> None:
    try:
        from app.core.resource_guard import resource_guard

        await resource_guard.start_orphan_reconciler()
    except Exception as e:
        logger.warning("Orphan reconciler start failed (non-fatal): %s", e)
