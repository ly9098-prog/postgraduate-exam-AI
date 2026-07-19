"""Tests for Phase 2: PipelineExecutionContext + ControlPlaneFacade.

Verifies:
- PipelineExecutionContext creation, serialization, resume
- ExecutionQuota limit enforcement
- OCRControlPlane job lifecycle
- Feature flag freezing
- Trace/Metrics collector behavior
"""

from __future__ import annotations

import os

import pytest

from app.features.control_plane import (
    CancellationContext,
    ExecutionPolicy,
    ExecutionQuota,
    MetricsCollector,
    OCRControlPlane,
    PipelineExecutionContext,
    PipelineOutcome,
    QuotaExceededError,
    QuotaLease,
    ResourceDemand,
    RolloutDecision,
    TraceCollector,
)


# ---------------------------------------------------------------------------
# PipelineExecutionContext
# ---------------------------------------------------------------------------


class TestPipelineExecutionContext:
    def test_create_minimal_context(self):
        ctx = PipelineExecutionContext(
            pipeline_id="pl-test-001",
            request_id="req-001",
            document_id="doc-001",
        )
        assert ctx.pipeline_id == "pl-test-001"
        assert ctx.request_id == "req-001"
        assert ctx.document_id == "doc-001"
        assert ctx.quota.max_pages == 200
        assert ctx.quota.max_input_bytes == 100 * 1024 * 1024

    def test_context_serialization_round_trip(self):
        original = PipelineExecutionContext(
            pipeline_id="pl-roundtrip",
            import_id=42,
            request_id="req-rt",
            document_id="doc-rt",
            document_sha256="abc123",
            source_type="pdf",
            subject="math",
            tenant_id="tenant-1",
            pipeline_fingerprint="fp-001",
            config_fingerprint="cfg-001",
            model_fingerprints={"paddleocr": "v4"},
            feature_flags={"ocr_gateway_mode": "shadow"},
        )
        data = original.to_dict()
        restored = PipelineExecutionContext.from_dict(data)

        assert restored.pipeline_id == original.pipeline_id
        assert restored.import_id == original.import_id
        assert restored.document_sha256 == "abc123"
        assert restored.feature_flags["ocr_gateway_mode"] == "shadow"
        assert restored.quota.max_pages == 200

    def test_context_serialization_excludes_large_blobs(self):
        """Context must not carry large byte blobs."""
        ctx = PipelineExecutionContext(pipeline_id="pl-no-blobs")
        data = ctx.to_dict()
        # Should not contain any bytes or large data fields
        for v in data.values():
            if isinstance(v, bytes):
                pytest.fail(f"Context serialization contains bytes: {v}")

    def test_check_page_limit_ok(self):
        ctx = PipelineExecutionContext(pipeline_id="pl-page-ok")
        ctx.check_page_limit(50)  # should not raise

    def test_check_page_limit_exceeded(self):
        ctx = PipelineExecutionContext(pipeline_id="pl-page-exceed")
        with pytest.raises(QuotaExceededError) as exc:
            ctx.check_page_limit(300)
        assert exc.value.code == "PAGE_LIMIT_EXCEEDED"

    def test_check_input_size_exceeded(self):
        ctx = PipelineExecutionContext(pipeline_id="pl-input-exceed")
        with pytest.raises(QuotaExceededError) as exc:
            ctx.check_input_size(200 * 1024 * 1024)
        assert exc.value.code == "INPUT_TOO_LARGE"

    def test_feature_flags_frozen_at_creation(self):
        """Feature flags must be populated at context creation."""
        ctx = PipelineExecutionContext(pipeline_id="pl-flags")
        flags = ctx.feature_flags
        assert "structure_freeze_mode" in flags
        assert "ocr_gateway_mode" in flags
        assert "unified_safety_mode" in flags

    def test_trace_collector_uses_pipeline_id(self):
        ctx = PipelineExecutionContext(pipeline_id="pl-trace")
        assert ctx.trace._pipeline_id == "pl-trace"

    def test_cancellation_default_not_cancelled(self):
        ctx = PipelineExecutionContext(pipeline_id="pl-cancel")
        assert not ctx.cancellation.is_cancelled

    def test_cancellation_can_be_triggered(self):
        ctx = PipelineExecutionContext(pipeline_id="pl-cancel-2")
        ctx.cancellation.cancel()
        assert ctx.cancellation.is_cancelled


# ---------------------------------------------------------------------------
# ExecutionQuota
# ---------------------------------------------------------------------------


class TestExecutionQuota:
    def test_default_limits(self):
        q = ExecutionQuota()
        assert q.max_pages == 200
        assert q.max_input_bytes == 100 * 1024 * 1024
        assert q.max_ocr_calls == 500
        assert q.max_ai_tokens == 100_000

    def test_quota_frozen(self):
        q = ExecutionQuota(max_pages=50)
        with pytest.raises(AttributeError):
            q.max_pages = 100  # frozen dataclass


# ---------------------------------------------------------------------------
# ResourceDemand / QuotaLease
# ---------------------------------------------------------------------------


class TestResourceDemand:
    def test_create_demand(self):
        d = ResourceDemand(estimated_pages=10, estimated_input_bytes=5000)
        assert d.estimated_pages == 10
        assert d.estimated_input_bytes == 5000

    def test_default_demand(self):
        d = ResourceDemand()
        assert d.estimated_pages == 0
        assert not d.requires_ai


# ---------------------------------------------------------------------------
# TraceCollector / MetricsCollector
# ---------------------------------------------------------------------------


class TestTraceCollector:
    def test_record_and_drain(self):
        tc = TraceCollector("pl-trace-1")
        tc.record("stage1", "success", "ok", 100)
        tc.record("stage2", "failed", "error", 200)
        events = tc.drain()
        assert len(events) == 2
        assert events[0]["step"] == "stage1"
        assert events[1]["step"] == "stage2"
        # drain clears
        assert len(tc.drain()) == 0

    def test_empty_collector(self):
        tc = TraceCollector("pl-empty")
        assert len(tc.drain()) == 0


class TestMetricsCollector:
    def test_gauge_and_increment(self):
        mc = MetricsCollector("pl-metrics-1")
        mc.gauge("pages", 10)
        assert mc.snapshot()["pages"] == 10
        mc.increment("pages", 1)
        assert mc.snapshot()["pages"] == 11

    def test_empty_snapshot(self):
        mc = MetricsCollector("pl-empty")
        assert mc.snapshot() == {}


# ---------------------------------------------------------------------------
# OCRControlPlane
# ---------------------------------------------------------------------------


class TestOCRControlPlane:
    @pytest.mark.asyncio
    async def test_create_job_returns_context(self):
        ctrl = OCRControlPlane(mode="facade")
        ctx = await ctrl.create_or_resume_job(
            request_id="req-cp-1",
            source_type="pdf",
            source_sha256="a" * 64,
        )
        assert ctx.pipeline_id.startswith("pl-")
        assert ctx.request_id == "req-cp-1"
        assert ctx.document_sha256 == "a" * 64
        assert ctx.config_fingerprint  # should be computed
        assert ctx.document_id == ("a" * 64)[:16]

    @pytest.mark.asyncio
    async def test_resolve_execution_policy(self):
        ctrl = OCRControlPlane(mode="facade")
        ctx = await ctrl.create_or_resume_job(request_id="req-ep")
        policy = await ctrl.resolve_execution_policy(ctx)
        assert isinstance(policy, ExecutionPolicy)
        assert policy.structure_freeze_mode == ctx.feature_flags.get("structure_freeze_mode")

    @pytest.mark.asyncio
    async def test_claim_quota_accepts(self):
        ctrl = OCRControlPlane()
        ctx = await ctrl.create_or_resume_job(request_id="req-quota")
        demand = ResourceDemand(estimated_pages=5, estimated_input_bytes=1000)
        lease = await ctrl.claim_quota(ctx, demand)
        assert lease.accepted

    @pytest.mark.asyncio
    async def test_claim_quota_rejects_page_limit(self):
        ctrl = OCRControlPlane()
        ctx = await ctrl.create_or_resume_job(request_id="req-quota-reject")
        demand = ResourceDemand(estimated_pages=9999)
        lease = await ctrl.claim_quota(ctx, demand)
        assert not lease.accepted
        assert lease.error_code == "PAGE_LIMIT_EXCEEDED"

    @pytest.mark.asyncio
    async def test_record_stage_result(self):
        ctrl = OCRControlPlane()
        ctx = await ctrl.create_or_resume_job(request_id="req-record")
        await ctrl.record_stage_result(
            ctx, stage_name="ocr", status="success", duration_ms=150.0,
        )
        assert ctx.metrics.snapshot().get("stage.ocr.latency_ms") == 150.0

    @pytest.mark.asyncio
    async def test_finalize_job(self):
        ctrl = OCRControlPlane()
        ctx = await ctrl.create_or_resume_job(request_id="req-finalize")
        await ctrl.finalize_job(ctx, PipelineOutcome.SUCCESS)
        # Should not raise — trace/metrics updated

    @pytest.mark.asyncio
    async def test_mode_facade_default(self):
        ctrl = OCRControlPlane()
        assert ctrl.mode == "facade"

    @pytest.mark.asyncio
    async def test_create_job_records_trace(self):
        ctrl = OCRControlPlane()
        ctx = await ctrl.create_or_resume_job(request_id="req-trace")
        events = ctx.trace.drain()
        assert any(e["step"] == "job_created" for e in events)


# ---------------------------------------------------------------------------
# CancellationContext
# ---------------------------------------------------------------------------


class TestCancellationContext:
    def test_default_not_cancelled(self):
        cc = CancellationContext()
        assert not cc.is_cancelled

    def test_cancel(self):
        cc = CancellationContext()
        cc.cancel()
        assert cc.is_cancelled

    def test_multiple_cancel_idempotent(self):
        cc = CancellationContext()
        cc.cancel()
        cc.cancel()
        assert cc.is_cancelled
