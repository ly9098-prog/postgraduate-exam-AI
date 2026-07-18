"""Coordinator Pipeline Production Entry — Wraps the existing pipeline entry point.

Provides:
- ImportPipelineEntry: Shadow/coordinator mode switching
- PIPELINE_COORDINATOR_MODE: legacy | shadow | coordinator
- Shadow mode: runs old pipeline (real) + coordinator (plan-only)
- Coordinator mode: CoordinatorPipeline is primary execution path

Rules:
- In shadow mode, coordinator does NOT execute real OCR/AI/persistence
- In coordinator mode, old orchestrator is bypassed (legacy wrapper remains for rollback)
- Same public/admin API I/O, same status enums, same artifact resume
"""

from __future__ import annotations

import logging
import os
import time
from enum import Enum
from typing import Any

from app.core.module_result import ModuleResult

logger = logging.getLogger(__name__)

_PIPELINE_COORDINATOR_MODE = os.environ.get("PIPELINE_COORDINATOR_MODE", "shadow")


class PipelineCoordinatorMode(str, Enum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    COORDINATOR = "coordinator"


def get_coordinator_mode() -> str:
    """Return the effective pipeline coordinator mode."""
    return os.environ.get("PIPELINE_COORDINATOR_MODE", "shadow")


# ── Shadow Result ───────────────────────────────────────────────────────────


class ShadowPlan:
    """Shadow mode plan — what the coordinator pipeline WOULD do.

    No real execution — only routing decisions and stage planning.
    """

    def __init__(self) -> None:
        self.stages: list[dict[str, Any]] = []
        self.ocr_route: str = ""
        self.document_ir_plan: bool = False
        self.pages_planned: int = 0

    def add_stage(self, name: str, plan: dict[str, Any]) -> None:
        self.stages.append({"stage": name, **plan})


async def run_coordinator_pipeline_shadow(
    request: Any = None,
    context: Any = None,
    policy: Any = None,
) -> ShadowPlan:
    """Run CoordinatorPipeline in shadow mode.

    Creates a ShadowPlan with stage routing decisions.
    Does NOT execute real OCR, AI, or persistence.
    """
    from app.features.coordinator_orchestrator import CoordinatorPipeline

    plan = ShadowPlan()

    pipeline = CoordinatorPipeline(context=context)
    profile = pipeline.profile

    plan.add_stage("input", {"planned": True, "profile": profile})
    plan.ocr_route = "gateway" if pipeline.is_cloud else "local"
    plan.add_stage("page_stream", {
        "planned": True,
        "window_size": 1 if pipeline.is_cloud else 3,
    })
    plan.add_stage("ocr", {
        "planned": True,
        "route": plan.ocr_route,
        "forbidden_fallback": pipeline.is_cloud,
    })
    plan.add_stage("doc_structure", {"planned": True})
    plan.add_stage("domain_parsing", {"planned": True})
    plan.add_stage("correction", {"planned": True})
    plan.add_stage("validation", {"planned": True})
    plan.add_stage("review", {"planned": True})
    plan.add_stage("persistence", {"planned": True, "mode": "lightweight" if pipeline.is_cloud else "full"})

    logger.info("CoordinatorPipeline[shadow]: profile=%s stages=%d", profile, len(plan.stages))
    return plan


async def run_coordinator_pipeline(
    request: Any = None,
    context: Any = None,
    policy: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run CoordinatorPipeline as the primary execution path."""
    from app.features.coordinator_orchestrator import CoordinatorPipeline

    pipeline = CoordinatorPipeline(context=context)

    # Build source bytes from request or kwargs
    if request is not None:
        source = getattr(request, "source", b"") or b""
        filename = getattr(request, "filename", "") or ""
        mime = getattr(request, "mime", "") or ""
    else:
        source = kwargs.get("file_content", b"") or b""
        filename = kwargs.get("filename", "") or kwargs.get("original_filename", "") or ""
        mime = kwargs.get("mime", "") or ""

    result = await pipeline.run_all(source, filename=filename, mime=mime)

    logger.info(
        "CoordinatorPipeline[coordinator]: profile=%s status=%s",
        pipeline.profile, result.get("status"),
    )
    return result


# ── Legacy wrappers for rollback ────────────────────────────────────────────


_LEGACY_ORCHESTRATOR_IMPORTED = False


def _import_legacy_orchestrator():
    """Lazy import of the legacy orchestrator for rollback compatibility."""
    global _LEGACY_ORCHESTRATOR_IMPORTED
    try:
        from app.features import pipeline_orchestrator  # noqa: F401
        _LEGACY_ORCHESTRATOR_IMPORTED = True
    except ImportError:
        logger.warning("Legacy orchestrator not available for rollback")
        _LEGACY_ORCHESTRATOR_IMPORTED = False


def is_legacy_available() -> bool:
    """Check if the legacy orchestrator is available for rollback."""
    if not _LEGACY_ORCHESTRATOR_IMPORTED:
        _import_legacy_orchestrator()
    return _LEGACY_ORCHESTRATOR_IMPORTED


# ── Unified Pipeline Entry ──────────────────────────────────────────────────


async def run_pipeline(
    request: Any = None,
    *,
    context: Any = None,
    policy: Any = None,
    ai_model_configs: dict[str, dict] | None = None,
    **kwargs: Any,
) -> Any:
    """Unified pipeline entry point.

    Routes to legacy, shadow, or coordinator mode based on
    PIPELINE_COORDINATOR_MODE env var.

    Args:
        request: Import request (carries source bytes, filename, etc.).
            When None, keyword arguments are forwarded to run_import_pipeline.
        context: Optional PipelineExecutionContext (created if None)
        policy: Optional ExecutionPolicy (resolved if None)
        ai_model_configs: Optional pre-resolved AI model config snapshots

    Returns:
        Pipeline outcome (same type/struct as old orchestrator output).
    """
    mode = get_coordinator_mode()
    logger.info("UnifiedPipeline[%s]: entering", mode)

    # Freeze AI config snapshots into context if provided
    if ai_model_configs and context is not None:
        try:
            context.ai_model_configs = ai_model_configs
        except Exception:
            logger.debug("UnifiedPipeline: could not freeze ai_model_configs into context")

    # Shadow mode: old orchestrator runs, coordinator plans only
    if mode == "shadow":
        # Create shadow plan
        shadow_plan = await run_coordinator_pipeline_shadow(
            request=request, context=context, policy=policy,
        )
        logger.info(
            "UnifiedPipeline[shadow]: plan complete stages=%d route=%s",
            len(shadow_plan.stages), shadow_plan.ocr_route,
        )
        return await _run_legacy_pipeline(request, context=context, policy=policy, **kwargs)

    # Coordinator mode: CoordinatorPipeline is primary
    if mode == "coordinator":
        result = await run_coordinator_pipeline(
            request=request, context=context, policy=policy, **kwargs,
        )
        return result

    # Legacy mode: pure legacy
    return await _run_legacy_pipeline(request, context=context, policy=policy, **kwargs)


async def _run_legacy_pipeline(
    request: Any = None,
    *,
    context: Any = None,
    policy: Any = None,
    **kwargs: Any,
) -> Any:
    """Run the legacy orchestrator pipeline (rollback path).

    When request is None, passes kwargs directly to run_import_pipeline,
    supporting the caller pattern::

        run_pipeline(file_content=..., source_type="pdf", ...)
    """
    from app.features.pipeline_orchestrator import run_import_pipeline
    if request is not None:
        return await run_import_pipeline(request)
    return await run_import_pipeline(**kwargs)
