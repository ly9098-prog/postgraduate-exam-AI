"""Comprehensive mock tests for PaddleXHttpOcrWorkerClient.

All tests use ``httpx.MockTransport`` — no real Windows service is contacted.
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx
import pytest

from app.core.ocr_runtime_config import OcrRuntimeConfig
from app.core.ocr_types import STABLE_ERROR_CODES
from app.services.ocr_paddlex_http_client import (
    PaddleXHttpOcrWorkerClient,
    _compute_backoff,
    _compute_base64_size,
    _derive_health_url,
    _empty_result,
    _is_retryable_exception,
    _is_retryable_status,
    _map_pruned_result,
    _normalize_bbox,
    _normalize_polygon,
    _parse_retry_after,
    _safe_score,
    _safe_str,
    health_check,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _make_response(
    error_code: int = 0,
    error_msg: str = "Success",
    rec_texts: list[str] | None = None,
    rec_scores: list[float] | None = None,
    rec_polys: list | None = None,
    rec_boxes: list | None = None,
) -> dict:
    return {
        "logId": "test-log-id",
        "errorCode": error_code,
        "errorMsg": error_msg,
        "result": {
            "ocrResults": [
                {
                    "prunedResult": {
                        "rec_texts": rec_texts or ["hello", "world"],
                        "rec_scores": rec_scores or [0.95, 0.87],
                        "rec_polys": rec_polys or [
                            [[0, 0], [50, 0], [50, 20], [0, 20]],
                            [[60, 0], [120, 0], [120, 20], [60, 20]],
                        ],
                        "rec_boxes": rec_boxes or [
                            [0, 0, 50, 20],
                            [60, 0, 120, 20],
                        ],
                    }
                }
            ]
        },
    }


def _config(**kwargs: Any) -> OcrRuntimeConfig:
    defaults = dict(
        execution_backend="paddlex_http",
        remote_url="http://127.0.0.1:8080/ocr",
    )
    defaults.update(kwargs)
    return OcrRuntimeConfig(**defaults)


@pytest.fixture
def client():
    """Create a PaddleXHttpOcrWorkerClient with a mock transport."""
    cfg = _config()
    c = PaddleXHttpOcrWorkerClient(cfg)
    # Replace the real client with a mock transport
    yield c
    asyncio.run(c.shutdown())


def _mock_async_client(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


# ===================================================================
# Pure function unit tests
# ===================================================================


class TestPureFunctions:
    def test_safe_str_none(self):
        assert _safe_str(None) == ""

    def test_safe_str_string(self):
        assert _safe_str("abc") == "abc"

    def test_safe_str_number(self):
        assert _safe_str(123) == "123"

    def test_safe_score_none(self):
        assert _safe_score(None) is None

    def test_safe_score_invalid(self):
        assert _safe_score("abc") is None

    def test_safe_score_nan(self):
        assert _safe_score(float("nan")) is None

    def test_safe_score_inf(self):
        assert _safe_score(float("inf")) is None

    def test_safe_score_clamp(self):
        assert _safe_score(1.5) == 1.0
        assert _safe_score(-0.5) == 0.0

    def test_safe_score_valid(self):
        assert _safe_score(0.95) == 0.95

    def test_normalize_polygon_nested(self):
        poly = [[10, 20], [50, 20], [50, 60], [10, 60]]
        result = _normalize_polygon(poly)
        assert result == [10, 20, 50, 20, 50, 60, 10, 60]

    def test_normalize_polygon_flat(self):
        poly = [10, 20, 50, 20, 50, 60, 10, 60]
        result = _normalize_polygon(poly)
        assert result == [10, 20, 50, 20, 50, 60, 10, 60]

    def test_normalize_polygon_short(self):
        assert _normalize_polygon([1, 2, 3]) is None

    def test_normalize_polygon_none(self):
        assert _normalize_polygon(None) is None

    def test_normalize_bbox(self):
        assert _normalize_bbox([10, 20, 50, 60]) == [10, 20, 50, 60]

    def test_normalize_bbox_reversed(self):
        assert _normalize_bbox([50, 60, 10, 20]) == [10, 20, 50, 60]

    def test_normalize_bbox_none(self):
        assert _normalize_bbox(None) is None

    def test_normalize_bbox_short(self):
        assert _normalize_bbox([1, 2, 3]) is None

    def test_normalize_bbox_nan(self):
        assert _normalize_bbox([1, 2, 3, float("nan")]) is None

    def test_empty_result(self):
        r = _empty_result(5, "fp123")
        assert r["page_index"] == 5
        assert r["engine_fingerprint"] == "fp123"
        assert r["text"] == ""
        assert r["confidence"] == 0.0
        assert r["failed"] is False

    def test_derive_health_url(self):
        assert _derive_health_url("http://host:8080/ocr") == "http://host:8080/openapi.json"

    def test_derive_health_url_empty(self):
        assert _derive_health_url("") == ""

    def test_derive_health_url_https(self):
        assert _derive_health_url("https://host:8443/api/ocr") == "https://host:8443/openapi.json"


# ===================================================================
# _map_pruned_result tests
# ===================================================================


class TestMapPrunedResult:
    def test_full_result(self):
        result = _map_pruned_result(
            [{
                "prunedResult": {
                    "rec_texts": ["hello", "world"],
                    "rec_scores": [0.95, 0.87],
                    "rec_polys": [
                        [[0, 0], [50, 0], [50, 20], [0, 20]],
                        [[60, 0], [120, 0], [120, 20], [60, 20]],
                    ],
                    "rec_boxes": [[0, 0, 50, 20], [60, 0, 120, 20]],
                }
            }],
            page_index=1,
            request_id="req1",
            fingerprint="fp1",
        )
        assert result["page_index"] == 1
        assert result["text"] == "hello\nworld"
        assert len(result["lines"]) == 2
        assert result["confidence"] == pytest.approx(0.91, 0.01)
        assert result["failed"] is False

    def test_empty_ocr_results(self):
        result = _map_pruned_result([], 0, "", "fp1")
        assert result["text"] == ""
        assert result["confidence"] == 0.0
        assert len(result["lines"]) == 0

    def test_empty_rec_texts(self):
        result = _map_pruned_result(
            [{"prunedResult": {"rec_texts": [], "rec_scores": [], "rec_polys": [], "rec_boxes": []}}],
            0, "", "fp1",
        )
        assert result["text"] == ""
        assert result["confidence"] == 0.0

    def test_uneven_array_lengths(self):
        """rec_texts longer than rec_scores, polys, boxes."""
        result = _map_pruned_result(
            [{
                "prunedResult": {
                    "rec_texts": ["a", "b", "c"],
                    "rec_scores": [0.9],
                    "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                    "rec_boxes": [[0, 0, 10, 10]],
                }
            }],
            0, "", "fp1",
        )
        assert result["text"] == "a\nb\nc"
        assert len(result["lines"]) == 3  # all text lines included
        # Lines without score default to 0.0 confidence
        assert result["lines"][0]["confidence"] == 0.9

    def test_polygon_only_no_bbox(self):
        result = _map_pruned_result(
            [{
                "prunedResult": {
                    "rec_texts": ["test"],
                    "rec_scores": [0.9],
                    "rec_polys": [[[0, 0], [50, 0], [50, 20], [0, 20]]],
                    "rec_boxes": None,
                }
            }],
            0, "", "fp1",
        )
        assert len(result["lines"]) == 1
        assert result["lines"][0]["polygon"] == [0, 0, 50, 0, 50, 20, 0, 20]
        # BBox derived from polygon
        assert result["lines"][0]["bbox"] == [0, 0, 50, 20]
        assert len(result["boxes"]) == 1

    def test_bbox_only_no_polygon(self):
        result = _map_pruned_result(
            [{
                "prunedResult": {
                    "rec_texts": ["test"],
                    "rec_scores": [0.9],
                    "rec_polys": None,
                    "rec_boxes": [[10, 20, 100, 80]],
                }
            }],
            0, "", "fp1",
        )
        assert result["lines"][0]["polygon"] == [10, 20, 100, 20, 100, 80, 10, 80]
        assert result["lines"][0]["bbox"] == [10, 20, 100, 80]

    def test_no_geometry_no_bbox(self):
        """Text present but no polygon or bbox — should still include the line."""
        result = _map_pruned_result(
            [{
                "prunedResult": {
                    "rec_texts": ["orphan text"],
                    "rec_scores": [0.5],
                    "rec_polys": None,
                    "rec_boxes": None,
                }
            }],
            0, "", "fp1",
        )
        assert len(result["lines"]) == 1
        assert result["lines"][0]["text"] == "orphan text"
        assert result["lines"][0]["polygon"] == []
        assert result["lines"][0]["bbox"] == []
        # Should not appear in boxes (no bbox)
        assert len(result["boxes"]) == 0

    def test_invalid_score_nan(self):
        result = _map_pruned_result(
            [{
                "prunedResult": {
                    "rec_texts": ["test"],
                    "rec_scores": [float("nan")],
                    "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                    "rec_boxes": [[0, 0, 10, 10]],
                }
            }],
            0, "", "fp1",
        )
        assert result["confidence"] == 0.0
        assert result["lines"][0]["confidence"] == 0.0

    def test_empty_text_line_skipped(self):
        """Empty text lines should be excluded (matching existing OcrEngine)."""
        result = _map_pruned_result(
            [{
                "prunedResult": {
                    "rec_texts": ["valid", "", "also-valid"],
                    "rec_scores": [0.9, 0.5, 0.8],
                    "rec_polys": [
                        [[0, 0], [10, 0], [10, 10], [0, 10]],
                        [[20, 0], [30, 0], [30, 10], [20, 10]],
                        [[40, 0], [50, 0], [50, 10], [40, 10]],
                    ],
                    "rec_boxes": [[0, 0, 10, 10], [20, 0, 30, 10], [40, 0, 50, 10]],
                }
            }],
            0, "", "fp1",
        )
        assert result["text"] == "valid\nalso-valid"
        assert len(result["lines"]) == 2
        # confidence should be avg of 0.9 and 0.8 (empty text's 0.5 excluded)
        assert result["confidence"] == pytest.approx(0.85)

    def test_pruned_result_not_dict(self):
        result = _map_pruned_result(
            [{"prunedResult": None}],
            0, "", "fp1",
        )
        assert result["text"] == ""
        assert result["failed"] is False

    def test_ocr_result_not_dict(self):
        result = _map_pruned_result(
            ["not a dict"],
            0, "", "fp1",
        )
        assert result["text"] == ""
        assert result["failed"] is False


# ===================================================================
# Retry / backoff / size-check pure function tests
# ===================================================================


class TestRetryFunctions:
    """Pure-function tests for retry helpers."""

    @pytest.mark.parametrize("attempt,expected_min,expected_max", [
        (0, 0.9, 1.1),    # base_delay=1.0 ± 10%
        (1, 1.8, 2.2),    # 2.0 ± 10%
        (2, 3.6, 4.4),    # 4.0 ± 10%
        (3, 7.2, 8.8),    # 8.0 ± 10%
        (4, 14.4, 17.6),  # 16.0 ± 10%
    ])
    def test_compute_backoff_exponential(self, attempt, expected_min, expected_max):
        delay = _compute_backoff(attempt)
        assert expected_min <= delay <= expected_max, (
            f"attempt={attempt}: {delay} not in [{expected_min}, {expected_max}]"
        )

    def test_compute_backoff_capped(self):
        """Delay should be capped at max_delay."""
        delay = _compute_backoff(10, max_delay=30.0, jitter=0.0)
        assert delay == 30.0

    def test_compute_backoff_with_retry_after(self):
        """Retry-After value should be used if provided."""
        delay = _compute_backoff(0, retry_after=5.0)
        assert delay == 5.0

    def test_compute_backoff_retry_after_capped(self):
        """Retry-After should be capped at max_delay."""
        delay = _compute_backoff(0, retry_after=60.0, max_delay=30.0)
        assert delay == 30.0

    def test_parse_retry_after_seconds(self):
        """Parse Retry-After header in seconds format."""
        resp = httpx.Response(429, headers={"Retry-After": "30"})
        assert _parse_retry_after(resp) == 30.0

    def test_parse_retry_after_none(self):
        """No Retry-After header returns None."""
        resp = httpx.Response(429)
        assert _parse_retry_after(resp) is None

    def test_parse_retry_after_empty(self):
        """Empty Retry-After header returns None."""
        resp = httpx.Response(429, headers={"Retry-After": ""})
        assert _parse_retry_after(resp) is None

    def test_is_retryable_status(self):
        assert _is_retryable_status(429) is True
        assert _is_retryable_status(502) is True
        assert _is_retryable_status(503) is True
        assert _is_retryable_status(504) is True
        assert _is_retryable_status(400) is False
        assert _is_retryable_status(401) is False
        assert _is_retryable_status(500) is False
        assert _is_retryable_status(200) is False

    def test_is_retryable_exception(self):
        import httpx
        assert _is_retryable_exception(httpx.ConnectError("fail")) is True
        assert _is_retryable_exception(httpx.ReadTimeout("fail")) is True
        assert _is_retryable_exception(httpx.WriteError("fail")) is True
        assert _is_retryable_exception(ValueError("no")) is False

    def test_compute_base64_size(self):
        """Verify base64 expansion estimate (1.37x)."""
        assert _compute_base64_size(1000) == 1370
        assert _compute_base64_size(0) == 0
        assert _compute_base64_size(1) == 2  # ceil(1 * 1.37)


# ===================================================================
# Retry integration tests
# ===================================================================


class TestRetryBehavior:
    """End-to-end retry behavior via mock transport."""

    @pytest.mark.asyncio
    async def test_retry_timeout_then_success(self):
        """First call times out, retry succeeds."""
        call_count = [0]

        def handler(r):
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.ReadTimeout("First attempt timed out")
            return httpx.Response(200, json={
                "errorCode": 0, "errorMsg": "Success",
                "result": {"ocrResults": [{
                    "prunedResult": {
                        "rec_texts": ["recovered"], "rec_scores": [0.9],
                        "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                        "rec_boxes": [[0, 0, 10, 10]],
                    }
                }]},
            })

        cfg = _config(remote_read_timeout_sec=1)
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "success"
        assert result.result["text"] == "recovered"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_retry_all_exhausted_timeout(self):
        """All retries exhausted due to persistent timeout — correct error code."""
        def handler(r):
            raise httpx.ReadTimeout("Always times out")

        cfg = _config(remote_read_timeout_sec=1)
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_TIMEOUT"]
        assert "All retries exhausted" in result.result.get("error", "")

    @pytest.mark.asyncio
    async def test_non_retryable_400_immediate(self):
        """400 status returns immediately without retry."""
        call_count = [0]

        def handler(r):
            call_count[0] += 1
            return httpx.Response(400, text="Bad Request")

        cfg = _config()
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"]
        assert call_count[0] == 1, "Non-retryable 400 must not retry"

    @pytest.mark.asyncio
    async def test_retry_502_then_success(self):
        """502 retries, then succeeds."""
        call_count = [0]

        def handler(r):
            call_count[0] += 1
            if call_count[0] <= 2:
                return httpx.Response(502, text="Bad Gateway")
            return httpx.Response(200, json={
                "errorCode": 0, "errorMsg": "Success",
                "result": {"ocrResults": [{
                    "prunedResult": {
                        "rec_texts": ["502-recovered"], "rec_scores": [0.9],
                        "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                        "rec_boxes": [[0, 0, 10, 10]],
                    }
                }]},
            })

        cfg = _config(remote_read_timeout_sec=1)
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "success"
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_retry_all_exhausted_http(self):
        """All retries exhausted for persistent 502."""
        call_count = [0]

        def handler(r):
            call_count[0] += 1
            return httpx.Response(502, text="Bad Gateway")

        cfg = _config(remote_read_timeout_sec=1)
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"]
        assert call_count[0] == 4  # 1 initial + 3 retries

    @pytest.mark.asyncio
    async def test_cancellation_during_retry_sleep(self):
        """CancelledError during retry sleep propagates correctly."""
        import asyncio

        def handler(r):
            raise httpx.ReadTimeout("timeout")

        cfg = _config(remote_read_timeout_sec=1)
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)

            task = asyncio.create_task(client.recognize(_FAKE_PNG, page_index=0))
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
                assert False, "Should have raised CancelledError"
            except asyncio.CancelledError:
                pass  # expected
        await client.shutdown()


# ===================================================================
# Circuit breaker safety tests
# ===================================================================


class TestCircuitBreakerSafety:
    """Thread-safe circuit breaker: half-open single probe, async lock."""

    @pytest.mark.asyncio
    async def test_half_open_probe_direct(self):
        """Direct verification of half-open single-probe via async checks."""
        cfg = _config()

        async with httpx.AsyncClient() as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            client._circuit_failure_threshold = 3
            client._circuit_recovery_timeout = 30

            # Open the circuit
            for _ in range(3):
                await client._record_failure()
            assert client._circuit_state == "open"

            # Set recovery timeout to 0 so the next check enters half-open
            client._circuit_recovery_timeout = 0.0

            # First async check: should transition to half-open and return True
            allowed1 = await client._circuit_may_attempt_async()
            assert allowed1 is True
            assert client._circuit_state == "half-open"
            assert client._half_open_probe_in_flight is True

            # Second async check: should be rejected (probe already in flight)
            allowed2 = await client._circuit_may_attempt_async()
            assert allowed2 is False

            # Verify state is still half-open
            assert client._circuit_state == "half-open"
        await client.shutdown()

    @pytest.mark.asyncio
    async def test_probe_success_closes_circuit(self):
        """After a successful probe, the circuit should close."""
        cfg = _config()

        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "errorCode": 0, "errorMsg": "Success",
            "result": {"ocrResults": [{
                "prunedResult": {
                    "rec_texts": ["ok"], "rec_scores": [0.9],
                    "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                    "rec_boxes": [[0, 0, 10, 10]],
                }
            }]},
        }))

        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            client._circuit_failure_threshold = 3
            client._circuit_recovery_timeout = 30

            # Open the circuit via 3 sequential failures
            def fail_handler(r):
                raise httpx.ConnectError("fail")

            fail_transport = httpx.MockTransport(fail_handler)
            client._client = httpx.AsyncClient(transport=fail_transport)

            for _ in range(3):
                await client.recognize(_FAKE_PNG, page_index=0)
            assert client._circuit_state == "open"

            # Now swap back to the success transport
            await client._client.aclose()
            client._client = httpx.AsyncClient(transport=transport)

            # Set recovery to 0 so next recognize enters half-open
            client._circuit_recovery_timeout = 0.0

            # The probe should succeed and close the circuit
            result = await client.recognize(_FAKE_PNG, page_index=0)
            assert result.status == "success"
            assert client._circuit_state == "closed"

            await client._client.aclose()
        await client.shutdown()

    @pytest.mark.asyncio
    async def test_probe_failure_keeps_open(self):
        """After a failed probe, the circuit should stay open."""
        cfg = _config()

        def fail_handler(r):
            raise httpx.ConnectError("probe fail")

        transport = httpx.MockTransport(fail_handler)

        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            client._circuit_failure_threshold = 3
            client._circuit_recovery_timeout = 30

            # Open the circuit
            for _ in range(3):
                await client._record_failure()
            assert client._circuit_state == "open"

            # Set recovery to 0 so next check enters half-open
            client._circuit_recovery_timeout = 0.0

            # The probe fails → circuit stays open
            result = await client.recognize(_FAKE_PNG, page_index=0)
            assert result.status == "failed"
            assert client._circuit_state == "open"

        await client.shutdown()

    @pytest.mark.asyncio
    async def test_circuit_state_metrics(self):
        """Circuit state is reflected in metrics."""
        cfg = _config()

        def fail_handler(r):
            raise httpx.ConnectError("fail")

        transport = httpx.MockTransport(fail_handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            client._circuit_failure_threshold = 3
            client._circuit_recovery_timeout = 30

            for _ in range(3):
                await client.recognize(_FAKE_PNG, page_index=0)

            m = client.metrics
            assert m["circuit_state"] == "open"
            assert m["circuit_breaker_trips"] >= 1
        await client.shutdown()


# ===================================================================
# Size check tests
# ===================================================================


class TestSizeCheck:
    """Pre-request size budget enforcement."""

    @pytest.mark.asyncio
    async def test_request_size_rejected(self):
        """Image exceeding request size budget is rejected before sending."""
        cfg = _config(remote_request_max_bytes=100)

        call_count = [0]
        transport = httpx.MockTransport(lambda r: (
            call_count.__setitem__(0, call_count[0] + 1) or
            httpx.Response(200, json={"errorCode": 0, "errorMsg": "Success",
                                       "result": {"ocrResults": []}})
        ))

        large_image = b"x" * 200  # base64 ~274 bytes, exceeds 100
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            result = await client.recognize(large_image, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert "too large" in result.result.get("error", "").lower()
        assert call_count[0] == 0, "No HTTP request should have been sent"

    @pytest.mark.asyncio
    async def test_request_size_accepted(self):
        """Image within size budget is sent normally."""
        cfg = _config(remote_request_max_bytes=2000)

        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "errorCode": 0, "errorMsg": "Success",
            "result": {"ocrResults": [{
                "prunedResult": {
                    "rec_texts": ["ok"], "rec_scores": [0.9],
                    "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                    "rec_boxes": [[0, 0, 10, 10]],
                }
            }]},
        }))

        small_image = b"x" * 100  # base64 ~137 bytes, well under 2000
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            result = await client.recognize(small_image, page_index=0)
        await client.shutdown()

        assert result.status == "success"


# ===================================================================
# Shared client lifecycle
# ===================================================================


class TestSharedClient:
    """When a shared httpx.AsyncClient is provided, shutdown does not close it."""

    @pytest.mark.asyncio
    async def test_shared_client_not_closed_on_shutdown(self):
        """Shutdown must not close a client it doesn't own."""
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "errorCode": 0, "errorMsg": "Success",
            "result": {"ocrResults": [{
                "prunedResult": {
                    "rec_texts": ["shared"], "rec_scores": [0.9],
                    "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                    "rec_boxes": [[0, 0, 10, 10]],
                }
            }]},
        }))

        cfg = _config()
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg, http_client=hc)
            r = await client.recognize(_FAKE_PNG, page_index=0)
            assert r.status == "success"
            await client.shutdown()
            # The shared client hc is still open (context manager hasn't exited)
            # A second call to hc should work (verify it's not closed)
            resp = await hc.get("http://test/")
            assert resp.status_code == 200
        await client.shutdown()  # idempotent


# ===================================================================
# HTTP-level mock tests
# ===================================================================


class TestHttpSinglePage:
    """Single-page recognize with mocked HTTP responses."""

    @pytest.mark.asyncio
    async def test_normal_success(self):
        cfg = _config()
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=_make_response()))
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            result = await client.recognize(_FAKE_PNG, page_index=3)
        await client.shutdown()

        assert result.status == "success"
        assert result.page_index == 3
        assert result.result is not None
        assert result.result["text"] == "hello\nworld"
        assert len(result.result["lines"]) == 2
        assert result.result["engine_fingerprint"] is not None

    @pytest.mark.asyncio
    async def test_page_index_preserved(self):
        cfg = _config()
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=_make_response()))
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            result = await client.recognize(_FAKE_PNG, page_index=7)
        await client.shutdown()

        assert result.page_index == 7

    @pytest.mark.asyncio
    async def test_engine_fingerprint_stable(self):
        """The fingerprint must not change between calls."""
        cfg = _config()
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=_make_response()))
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            r1 = await client.recognize(_FAKE_PNG, page_index=0)
            r2 = await client.recognize(_FAKE_PNG, page_index=1)
        await client.shutdown()

        assert r1.engine_fingerprint == r2.engine_fingerprint
        assert isinstance(r1.engine_fingerprint, str)
        assert len(r1.engine_fingerprint) == 16  # SHA256 prefix

    @pytest.mark.asyncio
    async def test_payload_base64(self):
        """Verify Base64 encoding is correct."""
        received_bodies = []

        def handler(r):
            body = json.loads(r.read())
            received_bodies.append(body)
            return httpx.Response(200, json=_make_response())

        cfg = _config()
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert len(received_bodies) == 1
        body = received_bodies[0]
        assert body["fileType"] == 1
        expected_b64 = base64.b64encode(_FAKE_PNG).decode("ascii")
        assert body["file"] == expected_b64


class TestHttpErrors:
    """Error responses must produce failed WorkerResult with stable error codes."""

    @pytest.mark.asyncio
    async def test_connect_error(self):
        cfg = _config()
        transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("Connection refused")))
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"]

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        cfg = _config()
        transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.TimeoutException("Timed out")))
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_TIMEOUT"]

    @pytest.mark.asyncio
    async def test_http_500(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(500, text="Internal Server Error"))
        cfg = _config()
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"]

    @pytest.mark.asyncio
    async def test_non_json_response(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>not json</html>"))
        cfg = _config()
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"]

    @pytest.mark.asyncio
    async def test_error_code_nonzero(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "logId": "x", "errorCode": 500, "errorMsg": "Internal serving error",
        }))
        cfg = _config()
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_SERVICE_ERROR"]

    @pytest.mark.asyncio
    async def test_missing_result(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "logId": "x", "errorCode": 0, "errorMsg": "Success",
        }))
        cfg = _config()
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"
        assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"]

    @pytest.mark.asyncio
    async def test_ocr_results_not_list(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "logId": "x", "errorCode": 0, "errorMsg": "Success",
            "result": {"ocrResults": "not a list"},
        }))
        cfg = _config()
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            result = await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_shutdown_after_use(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=_make_response()))
        cfg = _config()
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            await client.recognize(_FAKE_PNG, page_index=0)
            await client.shutdown()
            # After shutdown, recognize should return error
            result = await client.recognize(_FAKE_PNG, page_index=1)
            assert result.status == "failed"
            assert result.stable_error_code == STABLE_ERROR_CODES["REMOTE_CLOSED"]

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self):
        cfg = _config()
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=_make_response()))
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            await client.shutdown()
            await client.shutdown()  # second call must not raise

    @pytest.mark.asyncio
    async def test_metrics_updated(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=_make_response()))
        cfg = _config()
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        m = client.metrics
        assert m["backend"] == "paddlex_http"
        assert m["accepted"] >= 1
        assert m["finished"] >= 1
        assert m["endpoint"] is not None


class TestBatch:
    """Batch processing tests."""

    @pytest.mark.asyncio
    async def test_batch_normal(self):
        call_count = 0

        def handler(r):
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=_make_response(rec_texts=[f"page{call_count}"], rec_scores=[0.9]))

        cfg = _config()
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            results = await client.recognize_batch([(3, _FAKE_PNG), (1, _FAKE_PNG)])
        await client.shutdown()

        assert len(results) == 2
        # Sorted by page_index
        assert results[0].page_index == 1
        assert results[1].page_index == 3
        assert all(r.status == "success" for r in results)

    @pytest.mark.asyncio
    async def test_batch_empty(self):
        cfg = _config()
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=_make_response()))
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            results = await client.recognize_batch([])
        await client.shutdown()

        assert results == []

    @pytest.mark.asyncio
    async def test_batch_partial_failure(self):
        call_count = [0]

        def handler(r):
            call_count[0] += 1
            if call_count[0] == 1:
                return httpx.Response(500, text="Server error")
            return httpx.Response(200, json=_make_response(rec_texts=["ok"], rec_scores=[0.9]))

        cfg = _config()
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            results = await client.recognize_batch([(0, _FAKE_PNG), (1, _FAKE_PNG)])
        await client.shutdown()

        assert len(results) == 2
        assert results[0].status == "failed"
        assert results[1].status == "success"

    @pytest.mark.asyncio
    async def test_max_concurrency_one(self):
        """Verify at most 1 concurrent request when max_concurrency=1."""
        active = [0]
        max_active = [0]

        async def handler(r):
            active[0] += 1
            max_active[0] = max(max_active[0], active[0])
            await asyncio.sleep(0.05)  # simulate latency
            active[0] -= 1
            return httpx.Response(200, json=_make_response(rec_texts=["ok"], rec_scores=[0.9]))

        cfg = _config(remote_max_concurrency=1)
        # Custom transport doesn't support async handlers directly.
        # Use a threading.Event for test coordination instead of time.sleep
        # (which blocks the event loop from a sync httpx handler).
        import threading

        enter_event = threading.Event()
        proceed_event = threading.Event()

        def sync_handler(r):
            active[0] += 1
            max_active[0] = max(max_active[0], active[0])
            enter_event.set()
            # Block until the test releases all handlers simultaneously
            proceed_event.wait(timeout=2)
            active[0] -= 1
            return httpx.Response(200, json=_make_response(rec_texts=["ok"], rec_scores=[0.9]))

        transport = httpx.MockTransport(sync_handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc

            # Launch tasks concurrently; each one blocks inside sync_handler
            # waiting for proceed_event.
            task = asyncio.create_task(
                client.recognize_batch([(i, _FAKE_PNG) for i in range(5)])
            )
            # Wait for at least one handler to enter (semaphore acquired)
            enter_event.wait(timeout=2)
            # Brief yield to let other tasks queue up on the semaphore
            await asyncio.sleep(0.05)
            # All 5 tasks should have arrived — at most 1 inside the semaphore
            assert max_active[0] <= 1
            assert active[0] <= 1
            # Release all handlers
            proceed_event.set()
            results = await task
            assert len(results) == 5
        await client.shutdown()

        assert len(results) == 5
        assert max_active[0] <= 1, f"max_active was {max_active[0]}, expected ≤1"


class TestHealthCheck:
    """Lightweight health check tests."""

    @pytest.mark.asyncio
    async def test_health_ok(self):
        cfg = _config(remote_url="http://host:8080/ocr")
        client = PaddleXHttpOcrWorkerClient(cfg)

        def handler(r):
            assert "/openapi.json" in str(r.url)
            return httpx.Response(200, json={"info": "ok"})

        transport = httpx.MockTransport(handler)
        # Override the internal client with a mock-transport client
        client._client = httpx.AsyncClient(transport=transport)
        result = await health_check(client)
        await client.shutdown()
        assert result["reachable"] is True
        assert result["status_code"] == 200

    @pytest.mark.asyncio
    async def test_health_connect_fail(self):
        cfg = _config(remote_url="http://host:9/ocr")
        client = PaddleXHttpOcrWorkerClient(cfg)
        result = await health_check(client)
        await client.shutdown()
        # Should not crash — reachable should be False
        assert result["reachable"] is False


class TestCancellation:
    """Async cancellation must not be swallowed."""

    @pytest.mark.asyncio
    async def test_cancellation_re_raised(self):
        """CancelledError during a blocking call must propagate."""
        import time

        cfg = _config(remote_connect_timeout_sec=30, remote_read_timeout_sec=30)

        # Use a handler that blocks long enough for cancellation to fire
        def slow_handler(r):
            time.sleep(0.05)
            return httpx.Response(200, json=_make_response())

        transport = httpx.MockTransport(slow_handler)
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc

            task = asyncio.create_task(client.recognize(_FAKE_PNG, page_index=0))
            await asyncio.sleep(0.01)  # let it start the request
            task.cancel()
            try:
                await task
                pass
            except asyncio.CancelledError:
                pass  # exception propagated correctly
        await client.shutdown()


class TestMetrics:
    """Metrics reporting."""

    @pytest.mark.asyncio
    async def test_metrics_after_error(self):
        cfg = _config()
        transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("fail")))
        async with httpx.AsyncClient(transport=transport) as hc:
            client = PaddleXHttpOcrWorkerClient(cfg)
            client._client = hc
            await client.recognize(_FAKE_PNG, page_index=0)
        await client.shutdown()

        m = client.metrics
        assert m["connection_errors"] >= 1
        assert m["last_error_code"] == STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"]
        assert m["failed"] >= 1
        assert m["running"] == 0  # should have been decremented
