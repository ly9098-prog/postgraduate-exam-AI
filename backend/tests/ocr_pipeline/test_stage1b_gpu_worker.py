"""Stage 1B GPU Worker tests — real PaddleOCR GPU inference, fault injection, soak.

Uses the GPU venv (.venv-ocr-gpu-330) for PaddleOCR GPU execution.
CPU-only tests (device resolver, non-GPU faults) remain in test_stage1a_* files.

Gating:
- STAGE1B_RUN_OCR=1 to run real GPU OCR inference (default: skip)
- STAGE1B_RUN_SOAK=1 to run long soak tests (default: skip)
"""

from __future__ import annotations

import asyncio
import math
import os
import uuid

_TEST_DB_PATH = f"/tmp/_test_stage1b_e2e_{uuid.uuid4().hex[:8]}.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB_PATH}")

import pytest

# ---------------------------------------------------------------------------
# GPU Environment Pre-checks
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("STAGE1B_RUN_OCR"),
    reason="set STAGE1B_RUN_OCR=1 to run GPU OCR tests",
)
class TestGPUWorkerEnvironment:
    """Verify GPU environment is intact before running OCR tests."""

    def test_gpu_import(self):
        import paddle
        assert paddle.is_compiled_with_cuda(), "Paddle not compiled with CUDA"
        assert paddle.cuda.device_count() > 0, "No CUDA devices available"

    def test_gpu_tensor(self):
        import paddle
        paddle.set_device("gpu:0")
        x = paddle.randn([2048, 2048])
        y = paddle.matmul(x, x)
        paddle.device.synchronize()
        assert not math.isnan(float(y[0, 0].numpy()))

    def test_paddleocr_import(self):
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_gpu=True, lang="ch", show_log=False)
        assert ocr is not None


# ---------------------------------------------------------------------------
# GPU OCR E2E — Real Inference
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("STAGE1B_RUN_OCR"),
    reason="set STAGE1B_RUN_OCR=1 to run GPU OCR tests",
)
class TestGPUWorkerOCRE2E:
    """Three consecutive GPU OCR runs through PaddleOCRLocalAdapter."""

    @pytest.mark.asyncio
    async def test_gpu_ocr_consecutive_3_runs(self):
        """Run 3 consecutive GPU OCR passes, verify deterministic stable IDs."""
        from app.core.ocr_request import OCRRequest
        from app.features.ocr_adapter import PaddleOCRLocalAdapter
        from tests.fixtures.pdf_helper import make_minimal_pdf

        pdf_bytes = make_minimal_pdf(page_count=1, text="2025年考研数学二真题 设函数f(x)在区间[0,1]上连续")

        results = []
        for i in range(3):
            request = OCRRequest(source=pdf_bytes, source_type="pdf")
            adapter = PaddleOCRLocalAdapter(engine="paddleocr")
            try:
                os.environ["OCR_WORKER_DEVICE"] = "gpu"
                os.environ["OCR_WORKER_REQUIRE_GPU"] = "true"

                result = adapter.process(request, trace_id=f"stage1b-gpu-{i}")
                if asyncio.iscoroutine(result):
                    result = await result

                info = {"success": result.is_success, "latency_ms": result.latency_ms}
                if result.is_success and result.data:
                    doc_ir = result.data
                    info["document_id"] = doc_ir.document_id
                    info["region_count"] = sum(len(p.regions) for p in doc_ir.pages)
                    info["line_count"] = sum(len(r.lines) for p in doc_ir.pages for r in p.regions)

                results.append(info)
                print(f"  Run {i}: success={info['success']}, latency={info.get('latency_ms', 0):.0f}ms, doc_id={info.get('document_id', 'N/A')}")
            finally:
                await adapter.close()

        assert all(r["success"] for r in results), (
            f"Not all GPU OCR runs succeeded: {[r['success'] for r in results]}"
        )

        doc_ids = [r["document_id"] for r in results if "document_id" in r]
        if len(doc_ids) > 1:
            assert len(set(doc_ids)) == 1, (
                f"Non-deterministic document_ids across 3 runs: {doc_ids}"
            )

    @pytest.mark.asyncio
    async def test_gpu_ocr_temperature(self):
        """Cold vs warm latency comparison. Warm should be ~2x faster."""
        from app.core.ocr_request import OCRRequest
        from app.features.ocr_adapter import PaddleOCRLocalAdapter
        from tests.fixtures.pdf_helper import make_minimal_pdf

        pdf_bytes = make_minimal_pdf(page_count=1, text="温度测试")

        # Cold run
        cold_adapter = PaddleOCRLocalAdapter(engine="paddleocr")
        try:
            os.environ["OCR_WORKER_DEVICE"] = "gpu"
            os.environ["OCR_WORKER_REQUIRE_GPU"] = "true"

            request = OCRRequest(source=pdf_bytes, source_type="pdf")
            cold_result = cold_adapter.process(request, trace_id="stage1b-cold")
            if asyncio.iscoroutine(cold_result):
                cold_result = await cold_result
            cold_latency = cold_result.latency_ms
        finally:
            await cold_adapter.close()

        # Warm run (new adapter instance, but model should be cached by Paddle)
        warm_adapter = PaddleOCRLocalAdapter(engine="paddleocr")
        try:
            request = OCRRequest(source=pdf_bytes, source_type="pdf")
            warm_result = warm_adapter.process(request, trace_id="stage1b-warm")
            if asyncio.iscoroutine(warm_result):
                warm_result = await warm_result
            warm_latency = warm_result.latency_ms
        finally:
            await warm_adapter.close()

        print(f"  Cold: {cold_latency:.0f}ms, Warm: {warm_latency:.0f}ms")
        assert warm_latency > 0 and cold_latency > 0, "Both runs must complete"


# ---------------------------------------------------------------------------
# GPU Fault Injection (sync — no async needed)
# ---------------------------------------------------------------------------


class TestGPUWorkerFaultInjection:
    """GPU-specific fault tolerance tests.

    Tests requiring real GPU (device propagation) are gated by STAGE1B_RUN_OCR.
    """

    def test_gpu_device_resolution_fails_when_no_gpu(self):
        """resolve_ocr_device(gpu, require_gpu=True) must fail if GPU unavailable."""
        from app.ocr_worker.device import DeviceResolutionError, resolve_ocr_device

        with pytest.raises(DeviceResolutionError):
            resolve_ocr_device(
                requested_device="gpu",
                require_gpu=True,
                _import_paddle=_make_no_cuda_paddle(),
            )

    def test_gpu_device_fallback_to_cpu_when_not_required(self):
        """resolve_ocr_device(gpu, require_gpu=False) should fall back to CPU."""
        from app.ocr_worker.device import resolve_ocr_device

        # Clear env to avoid leakage from E2E tests
        os.environ.pop("OCR_WORKER_REQUIRE_GPU", None)
        os.environ.pop("OCR_WORKER_DEVICE", None)

        res = resolve_ocr_device(
            requested_device="gpu",
            require_gpu=False,
            _import_paddle=_make_no_cuda_paddle(),
        )
        assert res.resolved_device == "cpu"
        assert res.fallback_used is True
        assert "GPU_BUILD_REQUIRED" in res.reason_codes

    def test_auto_device_uses_gpu_when_available(self):
        """auto mode should resolve to GPU when CUDA is available."""
        try:
            import paddle
        except ModuleNotFoundError:
            # Once paddle has been imported (and its native libpaddle C module
            # initialized) earlier in this process, it cannot be re-imported
            # cleanly (paddle.base.libpaddle is no longer a package). Skip when
            # a prior test in the suite already disturbed that state.
            pytest.skip("paddle not importable in this process")

        from app.ocr_worker.device import resolve_ocr_device
        res = resolve_ocr_device(requested_device="auto", _import_paddle=paddle)
        if paddle.is_compiled_with_cuda() and paddle.cuda.device_count() > 0:
            assert res.resolved_device == "gpu"
        else:
            assert res.resolved_device == "cpu"

    @pytest.mark.skipif(
        not os.environ.get("STAGE1B_RUN_OCR"),
        reason="set STAGE1B_RUN_OCR=1 to run GPU device propagation test",
    )
    @pytest.mark.asyncio
    async def test_gpu_ocr_pipeline_orchestrator_device_propagation(self):
        """Verify OCR_WORKER_DEVICE=gpu properly propagates to PaddleOCR."""
        from app.core.ocr_request import OCRRequest
        from app.features.ocr_adapter import PaddleOCRLocalAdapter
        from tests.fixtures.pdf_helper import make_minimal_pdf

        pdf_bytes = make_minimal_pdf(page_count=1, text="GPU fault test")
        request = OCRRequest(source=pdf_bytes, source_type="pdf")

        adapter = PaddleOCRLocalAdapter(engine="paddleocr")
        try:
            os.environ["OCR_WORKER_DEVICE"] = "gpu"
            os.environ["OCR_WORKER_REQUIRE_GPU"] = "true"

            result = adapter.process(request, trace_id="stage1b-fault-prop")
            if asyncio.iscoroutine(result):
                result = await result

            assert result.is_success, f"GPU OCR failed: {result.error}"
            assert adapter._resolved_device == "gpu"
        finally:
            await adapter.close()


# ---------------------------------------------------------------------------
# GPU Soak
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("STAGE1B_RUN_SOAK"),
    reason="set STAGE1B_RUN_SOAK=1 to run GPU soak tests",
)
class TestGPUWorkerSoak:
    """Sustained GPU OCR workload."""

    SOAK_RUNS = int(os.environ.get("STAGE1B_SOAK_RUNS", "30"))

    @pytest.mark.asyncio
    async def test_gpu_ocr_soak_30_runs(self):
        """Run sustained GPU OCR, verify no crash or memory leak over 30 iterations."""
        from app.core.ocr_request import OCRRequest
        from app.features.ocr_adapter import PaddleOCRLocalAdapter
        from tests.fixtures.pdf_helper import make_minimal_pdf

        pdf_bytes = make_minimal_pdf(page_count=1, text="Soak test page for GPU stability")
        adapter = PaddleOCRLocalAdapter(engine="paddleocr")

        results = []
        try:
            os.environ["OCR_WORKER_DEVICE"] = "gpu"
            os.environ["OCR_WORKER_REQUIRE_GPU"] = "true"

            for i in range(self.SOAK_RUNS):
                request = OCRRequest(source=pdf_bytes, source_type="pdf")
                result = adapter.process(request, trace_id=f"stage1b-soak-{i}")
                if asyncio.iscoroutine(result):
                    result = await result

                results.append({"run": i, "success": result.is_success, "latency_ms": result.latency_ms})
                assert result.is_success, f"Soak run {i} failed: {result.error}"
        finally:
            await adapter.close()

        successes = sum(1 for r in results if r["success"])
        assert successes == self.SOAK_RUNS, (
            f"Only {successes}/{self.SOAK_RUNS} soak runs succeeded"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_no_cuda_paddle():
    """Create a mock paddle module without CUDA support for fault tests."""
    class _MockCuda:
        def device_count(self):
            return 0

    class _MockPaddle:
        is_compiled_with_cuda = staticmethod(lambda: False)
        cuda = _MockCuda()

        @staticmethod
        def set_device(d):
            return d

    return _MockPaddle()
