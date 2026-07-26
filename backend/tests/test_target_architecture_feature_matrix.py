"""Feature Matrix Test — Verify all Sprint 4A architecture components.

Confirms each target component exists, has the expected interface,
and operates correctly in its configured mode.
"""
from __future__ import annotations

from app.core.deployment_profile import DeploymentProfile
from app.features.control_plane import (
    ExecutionPolicy,
    ExecutionQuota,
    OCRControlPlane,
    PipelineExecutionContext,
    PipelineOutcome,
    QuotaLease,
    ResourceDemand,
    TraceCollector,
)
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
from app.features.document_validator import DocumentValidationResult, DocumentValidator
from app.features.input_gateway import InputDocument, InputGateway
from app.features.input_safety import InputSafetyValidator, SafetyResult
from app.features.native_text_probe import NativeTextProbe, NativeTextProbeResult
from app.features.ocr_gateway import GatewayRouteDecision, OCRGateway, RequiredOCRCapabilities
from app.features.page_stream import PageRenderer, PageStream, RenderedPage
from app.features.unified_safety import (
    CandidateContext,
    SafetyEvidence,
    UnifiedSafetyDecision,
    UnifiedSafetyEvaluator,
)
from app.services.asset_outbox import AssetOutbox, OutboxEvent, OutboxStatus


class TestFeatureMatrix:
    """Ensure all 18 target components exist and have correct interfaces."""

    # Phase 2: Control Plane
    def test_pipeline_execution_context_exists(self):
        ctx = PipelineExecutionContext(pipeline_id="test")
        assert ctx.pipeline_id == "test"

    def test_execution_quota_exists(self):
        q = ExecutionQuota()
        assert q.max_pages == 200

    def test_control_plane_facade_exists(self):
        ctrl = OCRControlPlane()
        assert ctrl.mode in ("legacy", "facade")

    def test_execution_policy_exists(self):
        p = ExecutionPolicy()
        assert p.canary_enabled is False

    def test_quota_lease_exists(self):
        lease = QuotaLease(accepted=True, quota_name="pages", remaining=50)
        assert lease.accepted

    def test_resource_demand_exists(self):
        d = ResourceDemand(estimated_pages=10)
        assert d.estimated_pages == 10

    def test_trace_collector_exists(self):
        tc = TraceCollector("test")
        tc.record("step", "ok")
        assert len(tc.drain()) == 1

    # Phase 3: Input Gateway
    def test_input_gateway_exists(self):
        gw = InputGateway()
        doc = gw.accept(b"test", filename="t.txt", mime="text/plain")
        assert isinstance(doc, InputDocument)

    def test_input_safety_exists(self):
        v = InputSafetyValidator()
        result = v.validate(b"safe", filename="f.txt")
        assert isinstance(result, SafetyResult)

    def test_native_text_probe_exists(self):
        probe = NativeTextProbe()
        result = probe.analyze_page("Hello", page_index=0)
        assert isinstance(result, NativeTextProbeResult)

    # Phase 4: Page Stream
    def test_page_stream_exists(self):
        stream = PageStream()
        assert stream.window_size == 3

    def test_page_renderer_exists(self):
        renderer = PageRenderer()
        assert renderer is not None

    def test_rendered_page_exists(self):
        page = RenderedPage(page_index=0, page_id="p0")
        assert page.page_index == 0

    # Phase 5: OCR Gateway
    def test_ocr_gateway_exists(self):
        gw = OCRGateway(mode="shadow", profile=DeploymentProfile.LOCAL_IMPORT)
        assert gw.is_shadow

    def test_required_ocr_capabilities_exists(self):
        caps = RequiredOCRCapabilities()
        assert caps.text is True

    def test_gateway_route_decision_exists(self):
        d = GatewayRouteDecision(selected_backend="paddleocr")
        assert d.selected_backend == "paddleocr"

    # Phase 7: Coordinators
    def test_input_coordinator_exists(self):
        assert InputCoordinator is not None

    def test_ocr_coordinator_exists(self):
        assert OCRCoordinator is not None

    def test_doc_structure_coordinator_exists(self):
        assert DocumentStructureCoordinator is not None

    def test_domain_parsing_coordinator_exists(self):
        assert DomainParsingCoordinator is not None

    def test_correction_coordinator_exists(self):
        assert CorrectionCoordinator is not None

    def test_validation_coordinator_exists(self):
        assert ValidationCoordinator is not None

    def test_review_coordinator_exists(self):
        assert ReviewCoordinator is not None

    def test_persistence_coordinator_exists(self):
        assert PersistenceCoordinator is not None

    # Phase 8: Unified Safety
    def test_unified_safety_evaluator_exists(self):
        e = UnifiedSafetyEvaluator()
        assert e.mode in ("off", "shadow")

    def test_safety_evidence_exists(self):
        e = SafetyEvidence(provider="test")
        assert e.provider == "test"

    def test_unified_safety_decision_exists(self):
        d = UnifiedSafetyDecision()
        assert d.requires_review is True

    def test_candidate_context_exists(self):
        ctx = CandidateContext(candidate_id="c1")
        assert ctx.candidate_id == "c1"

    # Phase 9: DocumentValidator
    def test_document_validator_exists(self):
        v = DocumentValidator()
        result = v.validate(None, [])
        assert isinstance(result, DocumentValidationResult)

    # Phase 10: Asset Outbox
    def test_asset_outbox_exists(self):
        outbox = AssetOutbox()
        assert outbox.mode in ("legacy", "transactional_shadow", "transactional")

    def test_outbox_event_exists(self):
        e = OutboxEvent(event_type="test", payload={})
        assert e.event_id.startswith("evt-")

    def test_outbox_status_enum(self):
        assert OutboxStatus.PENDING == "pending"
        assert OutboxStatus.DEAD_LETTER == "dead_letter"

    # Pipeline outcome enum
    def test_pipeline_outcome_exists(self):
        assert PipelineOutcome.SUCCESS.value == "success"
        assert PipelineOutcome.FAILED.value == "failed"
