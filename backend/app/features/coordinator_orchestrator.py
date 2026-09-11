"""Coordinator Pipeline — Thin integration layer wiring Coordinators into production.

This module provides ``CoordinatorPipeline``, a sequential coordinator runner
that replaces the monolithic orchestrator stage branching with modular
coordinator calls.

Design:
- Each coordinator is called in sequence with the same PipelineExecutionContext.
- Orchestrator (this module) only handles stage sequencing and state transitions.
- Coordinators encapsulate stage logic.
- Existing ImportPipeline is still reachable for legacy/resume paths.
- Public/Admin API endpoints are unchanged (delegated through here or legacy).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
from app.core.module_result import ModuleError, ModuleResult
from app.core.resource_guard import ResourceGuard
from app.features.coordinators import (
    CorrectionCoordinator,
    DocumentStructureCoordinator,
    DomainParsingCoordinator,
    InputCoordinator,
    OCRCoordinator,
    PersistenceCoordinator,
    ReviewCoordinator,
    ValidationCoordinator,
)
from app.features.page_stream import PageStream, RenderedPage

logger = logging.getLogger(__name__)


class CoordinatorPipeline:
    """Sequential coordinator pipeline.

    Runs coordinators in the defined order. Skips stages based on profile
    and feature flags. Each stage receives the same PipelineExecutionContext.

    Stage order:
        1. InputCoordinator — accept & validate source
        2. PageStream — render pages (windowed)
        3. OCRCoordinator — recognize pages
        4. DocumentStructureCoordinator — reading order
        5. DomainParsingCoordinator — question splitting
        6. CorrectionCoordinator — AI repair
        7. ValidationCoordinator — validate results
        8. ReviewCoordinator — build review artifact
        9. PersistenceCoordinator — persist to DB
    """

    def __init__(
        self,
        *,
        context: Any = None,
        resource_guard: ResourceGuard | None = None,
    ):
        self._context = context
        self._guard = resource_guard
        self._results: list[dict[str, Any]] = []

    @property
    def profile(self) -> DeploymentProfile:
        if self._context and hasattr(self._context, "deployment_profile"):
            val = self._context.deployment_profile
            if isinstance(val, DeploymentProfile):
                return val
            if isinstance(val, str):
                try:
                    return DeploymentProfile(val)
                except ValueError:
                    pass
        return detect_deployment_profile()

    @property
    def is_cloud(self) -> bool:
        return self.profile == DeploymentProfile.CLOUD_API

    async def run_input_stage(
        self,
        source: bytes,
        *,
        filename: str = "",
        mime: str = "",
        page_count: int | None = None,
    ) -> ModuleResult:
        """Stage 1: Input."""
        result = await InputCoordinator().run(
            source,
            filename=filename,
            mime=mime,
            page_count=page_count,
        )
        self._results.append(
            {"stage": "input", "status": "ok" if result.is_success else "failed"}
        )
        return result

    async def run_page_stream(
        self,
        document: Any,
    ):
        """Stage 2: Page rendering via PageStream."""
        profile_caps = {}
        if self._context and hasattr(self._context, "runtime_capabilities"):
            profile_caps = self._context.runtime_capabilities
        window_size = profile_caps.get(
            "page_stream_window_size", 3 if not self.is_cloud else 1
        )
        overlap = profile_caps.get("page_stream_overlap", 1 if not self.is_cloud else 0)

        stream = PageStream.for_profile(
            self.profile,
            window_size=window_size,
            overlap=overlap,
        )
        pages: list[RenderedPage] = []
        async for page in stream.pages(document):
            pages.append(page)
        return pages

    async def run_ocr_stage(
        self,
        pages: list[RenderedPage],
        *,
        trace_id: str = "",
    ) -> list[ModuleResult]:
        """Stage 3: OCR recognition via OCRCoordinator."""
        results = []
        coordinator = OCRCoordinator(profile=self.profile)
        try:
            for page in pages:
                result = await coordinator.run(
                    page,
                    trace_id=trace_id,
                    context=self._context,
                )
                results.append(result)
        finally:
            # A temporary fallback Gateway (when no application-level Gateway
            # exists) is shared for the whole page batch and closed once.
            await coordinator.close()

        self._results.append(
            {
                "stage": "ocr",
                "pages": len(pages),
                "success": sum(1 for r in results if r.is_success),
            }
        )
        return results

    async def run_doc_structure_stage(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult:
        """Stage 4: Document structure analysis."""
        result = await DocumentStructureCoordinator().run(doc_ir, trace_id=trace_id)
        self._results.append(
            {
                "stage": "doc_structure",
                "status": "ok" if result.is_success else "failed",
            }
        )
        return result

    async def run_domain_parsing_stage(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult:
        """Stage 5: Domain parsing."""
        result = await DomainParsingCoordinator().run(doc_ir, trace_id=trace_id)
        self._results.append(
            {
                "stage": "domain_parsing",
                "status": "ok" if result.is_success else "failed",
            }
        )
        return result

    async def run_correction_stage(
        self,
        doc_ir: Any,
        questions: list[Any] | None = None,
        *,
        trace_id: str = "",
    ) -> ModuleResult:
        """Stage 6: OCR correction / AI repair."""
        result = await CorrectionCoordinator().run(
            doc_ir, questions=questions, trace_id=trace_id
        )
        self._results.append(
            {"stage": "correction", "status": "ok" if result.is_success else "failed"}
        )
        return result

    async def run_validation_stage(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult:
        """Stage 7: Validation."""
        result = await ValidationCoordinator().run(doc_ir, trace_id=trace_id)
        self._results.append(
            {"stage": "validation", "status": "ok" if result.is_success else "failed"}
        )
        return result

    async def run_review_stage(
        self,
        doc_ir: Any,
        questions: list[Any] | None = None,
        *,
        trace_id: str = "",
    ) -> ModuleResult:
        """Stage 8: Review artifact."""
        result = await ReviewCoordinator().run(
            doc_ir, questions=questions, trace_id=trace_id
        )
        self._results.append(
            {"stage": "review", "status": "ok" if result.is_success else "failed"}
        )
        return result

    async def run_persistence_stage(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult:
        """Stage 9: Persistence.

        For cloud_api, this only writes task status / lightweight results.
        For local_import, this delegates to the existing question import writer.
        """
        if self.is_cloud:
            logger.info(
                "CoordinatorPipeline[cloud_api]: persistence not yet implemented"
            )
            return ModuleResult.failure(
                ModuleError(
                    code="NOT_IMPLEMENTED",
                    message="Persistence coordinator not yet implemented",
                    category="system",
                    recoverable=False,
                ),
                module_name="coordinator_pipeline",
            )

        result = await PersistenceCoordinator().run(doc_ir, trace_id=trace_id)
        self._results.append(
            {"stage": "persistence", "status": "ok" if result.is_success else "failed"}
        )
        return result

    async def run_all(
        self,
        source: bytes,
        *,
        filename: str = "",
        mime: str = "",
        page_count: int | None = None,
        trace_id: str = "",
    ) -> dict[str, Any]:
        """Run the full coordinator pipeline.

        Returns a summary dict with stage results.
        """
        start = time.monotonic()
        stages_summary: dict[str, Any] = {}
        overall_status = "success"

        # Stage 1: Input
        input_result = await self.run_input_stage(
            source, filename=filename, mime=mime, page_count=page_count
        )
        stages_summary["input"] = "ok" if input_result.is_success else "failed"
        if not input_result.is_success:
            return self._finalize(start, stages_summary, "input_failed")

        # Stage 2: PageStream
        try:
            pages = await self.run_page_stream(input_result.data)
            stages_summary["pages"] = len(pages)
        except Exception:
            stages_summary["page_stream"] = "failed"
            return self._finalize(start, stages_summary, "page_stream_failed")

        # Stage 3: OCR
        ocr_results = await self.run_ocr_stage(pages, trace_id=trace_id)
        ocr_ok = all(r.is_success for r in ocr_results)
        stages_summary["ocr"] = "ok" if ocr_ok else "partial"

        # Stages 4-9: NOT_IMPLEMENTED until P3+
        # These return ModuleResult.failure(NOT_IMPLEMENTED) which is expected.
        for stage_name, stage_fn in [
            ("doc_structure", self.run_doc_structure_stage),
            ("domain_parsing", self.run_domain_parsing_stage),
            ("correction", self.run_correction_stage),
            ("validation", self.run_validation_stage),
            ("review", self.run_review_stage),
        ]:
            result = await stage_fn(None, trace_id=trace_id)
            stages_summary[stage_name] = (
                "not_implemented"
                if (
                    result.is_failure
                    and result.error
                    and "NOT_IMPLEMENTED" in result.error.code
                )
                else ("ok" if result.is_success else "failed")
            )

        # Stage 9: Persistence
        persist = await self.run_persistence_stage(None, trace_id=trace_id)
        stages_summary["persistence"] = (
            "not_implemented"
            if (
                persist.is_failure
                and persist.error
                and "NOT_IMPLEMENTED" in persist.error.code
            )
            else ("ok" if persist.is_success else "failed")
        )

        return self._finalize(start, stages_summary, overall_status)

    def _finalize(
        self,
        start: float,
        stages: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "profile": self.profile,
            "stages": stages,
            "total_latency_ms": round((time.monotonic() - start) * 1000, 2),
            "stage_results": self._results,
        }
