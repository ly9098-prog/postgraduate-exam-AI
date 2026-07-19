"""Pipeline Stage Coordinators — Thin facades over existing orchestrator sections.

Each coordinator owns a single domain stage. The Orchestrator retains
stage sequencing and state transitions; coordinators encapsulate stage logic.

Design principles:
- Each coordinator is a standalone class with a clear ``run()`` entry point.
- Coordinators accept `PipelineExecutionContext` for logging/tracing.
- Coordinators return ModuleResult for uniform error handling.
- No coordinator accesses raw OCR backend fields directly.
- No coordinator performs DB writes directly (coordinator returns result,
  PersistenceCoordinator handles writes).

Current state: THIN FACADES that delegate to existing orchestrator code.
Over iterations, logic moves from pipeline_orchestrator.py into these classes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.module_result import ModuleError, ModuleResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# InputCoordinator
# ---------------------------------------------------------------------------


class InputCoordinator:
    """Input stage coordinator.

    Responsibilities:
    - Accept source bytes
    - Validate safety
    - Persist to local storage
    - Return InputDocument

    Delegates to:
      InputGateway, InputSafetyValidator, NativeTextProbe
    """

    def __init__(self) -> None:
        pass

    async def run(
        self,
        source: bytes,
        *,
        filename: str = "",
        mime: str = "",
        page_count: int | None = None,
    ) -> ModuleResult[Any]:
        """Run input stage. Returns ModuleResult[InputDocument]."""
        from app.features.input_gateway import InputGateway
        from app.features.input_safety import InputSafetyValidator

        try:
            validator = InputSafetyValidator()
            safety = validator.validate(source, filename=filename, mime=mime)
            if not safety.passed:
                return ModuleResult.failure(
                    ModuleError(
                        code="INPUT_SAFETY_FAILED",
                        message="; ".join(safety.errors),
                        category="input",
                    ),
                    module_name="input_coordinator",
                )

            gateway = InputGateway()
            doc = gateway.accept(source, filename=filename, mime=mime, page_count=page_count)

            return ModuleResult.success(
                data=doc,
                data_type="InputDocument",
                module_name="input_coordinator",
            )
        except Exception as e:
            return ModuleResult.failure(
                ModuleError(code="INPUT_COORDINATOR_ERROR", message=str(e), category="input"),
                module_name="input_coordinator",
            )


# ---------------------------------------------------------------------------
# OCRCoordinator
# ---------------------------------------------------------------------------


class OCRCoordinator:
    """OCR stage coordinator.

    Responsibilities:
    - Route page to OCR backend via OCRGateway (or legacy path in shadow mode)
    - Return DocumentIR with page-level recognition

    Delegates to:
      OCRGateway, AdapterRegistry, AdapterSelector
    """

    def __init__(self) -> None:
        pass

    async def run(
        self,
        document: Any,
        *,
        trace_id: str = "",
        context: Any = None,
    ) -> ModuleResult[Any]:
        """Run OCR stage.

        Receives a ``RenderedPage`` from the page stream.
        Calls ``OCRGateway.recognize_page()`` to run OCR and return
        ``ModuleResult[DocumentIR]``.

        In shadow mode, the Gateway returns only a route decision.
        In gateway mode, it executes via the registered adapters.
        """
        start = time.monotonic()

        try:
            from app.features.ocr_gateway import OCRGateway
            from app.core.ocr_request import OCRRequest

            # Extract VL config from context if available
            vl_api_token = ""
            vl_base_url = ""
            vl_model = "PaddleOCR-VL-1.6"

            if context is not None and hasattr(context, "ai_model_configs"):
                configs = getattr(context, "ai_model_configs", {})
                for cap in ("ocr_vl", "ocr_lightweight"):
                    snap = configs.get(cap, {})
                    if snap and isinstance(snap, dict):
                        vl_model = snap.get("model_name", vl_model)
                        endpoint = snap.get("endpoint", "") or snap.get("api_base_url", "")
                        if endpoint:
                            vl_base_url = endpoint
                        break

            gateway = OCRGateway(
                vl_api_token=vl_api_token,
                vl_base_url=vl_base_url,
                vl_model=vl_model,
            )

            # Actually call the Gateway with the rendered page
            result = await gateway.recognize_page(
                document,
                trace_id=trace_id,
            )

            return result
        except Exception as e:
            return ModuleResult.failure(
                ModuleError(
                    code="OCR_COORDINATOR_ERROR",
                    message=str(e),
                    category="model",
                ),
                module_name="ocr_coordinator",
                trace_id=trace_id,
                latency_ms=round((time.monotonic() - start) * 1000, 2),
            )


# ---------------------------------------------------------------------------
# DocumentStructureCoordinator
# ---------------------------------------------------------------------------


class DocumentStructureCoordinator:
    """Document structure stage coordinator.

    Responsibilities:
    - Reading order resolution
    - Region classification
    - Header/footer/watermark detection

    Delegates to:
      reading_order.py, pipeline_stages/reading_order_stage.py
    """

    async def run(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Run document structure analysis on DocumentIR."""
        start = time.monotonic()
        try:
            # Delegate to existing reading_order_stage
            from app.features.pipeline_stages import reading_order_stage

            result = reading_order_stage.run_reading_order_stage_v2(doc_ir, stage_config=None)
            if result.is_failure:
                return ModuleResult.failure(
                    error=result.error,
                    module_name="doc_structure_coordinator",
                    trace_id=trace_id,
                    latency_ms=round((time.monotonic() - start) * 1000, 2),
                )

            return ModuleResult.success(
                data=doc_ir,
                data_type="DocumentIR",
                module_name="doc_structure_coordinator",
                confidence=result.confidence,
                trace_id=trace_id,
                latency_ms=round((time.monotonic() - start) * 1000, 2),
            )
        except Exception as e:
            return ModuleResult.failure(
                ModuleError(
                    code="DOC_STRUCTURE_ERROR",
                    message=str(e),
                    category="model",
                ),
                module_name="doc_structure_coordinator",
                trace_id=trace_id,
                latency_ms=round((time.monotonic() - start) * 1000, 2),
            )


# ---------------------------------------------------------------------------
# DomainParsingCoordinator
# ---------------------------------------------------------------------------


class DomainParsingCoordinator:
    """Domain parsing stage coordinator.

    Responsibilities:
    - Question splitting
    - Option/answer detection
    - Cross-page linking
    - Numbering resolution
    - Structure analysis

    Delegates to:
      question_splitter, cross_page_linking, question_numbering, structure_analyzer
    """

    async def run(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Run domain parsing on a DocumentIR-structured document."""
        start = time.monotonic()
        try:
            # Cross-page linking runs first
            from app.features.cross_page_linking import detect_cross_page_links

            links = detect_cross_page_links(doc_ir)
            doc_ir.cross_page_links = [l.to_dict() for l in links]

            return ModuleResult.success(
                data=doc_ir,
                data_type="DocumentIR",
                module_name="domain_parsing_coordinator",
                trace_id=trace_id,
                latency_ms=round((time.monotonic() - start) * 1000, 2),
            )
        except Exception as e:
            return ModuleResult.failure(
                ModuleError(
                    code="DOMAIN_PARSING_ERROR",
                    message=str(e),
                    category="model",
                ),
                module_name="domain_parsing_coordinator",
                trace_id=trace_id,
                latency_ms=round((time.monotonic() - start) * 1000, 2),
            )


# ---------------------------------------------------------------------------
# CorrectionCoordinator
# ---------------------------------------------------------------------------


class CorrectionCoordinator:
    """Correction stage coordinator.

    Responsibilities:
    - OCR correction routing
    - AI repair
    - Rule fallback

    Delegates to:
      ocr_correction, ai_repair, vision_fallback, code_detector
    """

    async def run(
        self,
        doc_ir: Any,
        questions: list[Any] | None = None,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Correction: NOT_IMPLEMENTED until P3."""
        return ModuleResult.failure(
            ModuleError(
                code="NOT_IMPLEMENTED",
                message="Correction coordinator not yet implemented",
                category="system",
                recoverable=False,
            ),
            module_name="correction_coordinator",
            trace_id=trace_id,
        )


# ---------------------------------------------------------------------------
# ValidationCoordinator
# ---------------------------------------------------------------------------


class ValidationCoordinator:
    """Validation stage coordinator.

    Responsibilities:
    - Unified safety evaluation
    - Document-level validation
    - Quality gate checks (shadow mode)

    Delegates to:
      candidate_evaluator, ai_safety, code_integrity, quality_gate
    """

    async def run(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Validation: NOT_IMPLEMENTED until P3."""
        return ModuleResult.failure(
            ModuleError(
                code="NOT_IMPLEMENTED",
                message="Validation coordinator not yet implemented",
                category="system",
                recoverable=False,
            ),
            module_name="validation_coordinator",
            trace_id=trace_id,
        )


# ---------------------------------------------------------------------------
# ReviewCoordinator
# ---------------------------------------------------------------------------


class ReviewCoordinator:
    """Review stage coordinator.

    Responsibilities:
    - Build review artifact
    - Prepare review data for human review
    - Provenance tracking for all stages

    Delegates to:
      review_service, pipeline_artifacts, document_ir
    """

    async def run(
        self,
        doc_ir: Any,
        questions: list[Any] | None = None,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Review: build a review-ready artifact from DocumentIR + questions."""
        start = time.monotonic()
        try:
            # Accept both DocumentIR objects and dicts
            if isinstance(doc_ir, dict):
                doc_id = doc_ir.get("document_id", doc_ir.get("doc_id", "unknown"))
                page_count = len(doc_ir.get("pages", []))
                has_regions = any(
                    p.get("regions") or p.get("region_count", 0) > 0
                    for p in doc_ir.get("pages", [])
                )
                item_count = len(questions or [])
            else:
                doc_id = getattr(doc_ir, "document_id", "unknown")
                pages = getattr(doc_ir, "pages", [])
                page_count = len(pages)
                has_regions = any(
                    getattr(p, "regions", []) for p in pages
                )
                item_count = len(questions or [])

            review_artifact = {
                "review_ready": True,
                "document_id": doc_id,
                "page_count": page_count,
                "has_regions": has_regions,
                "question_count": item_count,
                "trace_id": trace_id,
                "review_type": "ocr_import",
                "stages_completed": [
                    "input",
                    "ocr",
                    "doc_structure",
                    "domain_parsing",
                ],
            }

            if questions:
                review_artifact["questions"] = questions
                review_artifact["question_ids"] = [
                    q.get("id", q.get("question_id", idx))
                    for idx, q in enumerate(questions)
                ]

            return ModuleResult.success(
                data=review_artifact,
                data_type="ReviewCoordinatorResult",
                module_name="review_coordinator",
                trace_id=trace_id,
                latency_ms=round((time.monotonic() - start) * 1000, 2),
            )
        except Exception as e:
            return ModuleResult.failure(
                ModuleError(
                    code="REVIEW_COORDINATOR_ERROR",
                    message=str(e),
                    category="system",
                    recoverable=False,
                ),
                module_name="review_coordinator",
                trace_id=trace_id,
                latency_ms=round((time.monotonic() - start) * 1000, 2),
            )


# ---------------------------------------------------------------------------
# PersistenceCoordinator
# ---------------------------------------------------------------------------


class PersistenceCoordinator:
    """Persistence stage coordinator.

    Responsibilities:
    - Transactional DB persistence
    - Asset outbox management
    - Artifact cleanup

    Delegates to:
      question_import_writer, asset_reference_service, pipeline_artifacts
    """

    async def run(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Persistence: NOT_IMPLEMENTED until P3."""
        return ModuleResult.failure(
            ModuleError(
                code="NOT_IMPLEMENTED",
                message="Persistence coordinator not yet implemented",
                category="system",
                recoverable=False,
            ),
            module_name="persistence_coordinator",
            trace_id=trace_id,
        )
