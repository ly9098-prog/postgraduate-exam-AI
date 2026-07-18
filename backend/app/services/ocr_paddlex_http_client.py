"""PaddleXHttpOcrWorkerClient — OCR via Windows PaddleX General OCR Basic Serving.

Sends Base64-encoded page images to a remote PaddleX HTTP endpoint and maps
the response to the standard ``WorkerResult`` schema.

Design:
- Uses ``httpx.AsyncClient`` (no blocking I/O).
- ``asyncio.Semaphore`` enforces a max-concurrency cap (default 1 for RTX 3050
  4 GB).
- Recognise / recognise_batch implement the ``OcrWorkerClient`` protocol.
- Every response is validated; broken data degrades per-field, not per-page.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
import uuid
from typing import Any

import httpx

from app.core.ocr_runtime_config import OcrRuntimeConfig, sanitize_url
from app.core.ocr_types import STABLE_ERROR_CODES, WorkerResult

logger = logging.getLogger(__name__)


def _compute_engine_fingerprint(config: OcrRuntimeConfig) -> str:
    """Build a stable engine fingerprint for provenance tracking."""
    raw = (
        f"backend=paddlex_http|"
        f"endpoint={sanitize_url(config.remote_url)}|"
        f"version=1|"
        f"connect_timeout={config.remote_connect_timeout_sec}|"
        f"read_timeout={config.remote_read_timeout_sec}|"
        f"det_thresh={config.det_db_thresh}|"
        f"box_thresh={config.det_db_box_thresh}|"
        f"unclip={config.det_db_unclip_ratio}|"
        f"drop={config.drop_score}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class PaddleXHttpOcrWorkerClient:
    """HTTP client for the PaddleX General OCR Basic Serving API."""

    def __init__(self, config: OcrRuntimeConfig) -> None:
        self._config = config
        self._closed = False
        self._fingerprint = _compute_engine_fingerprint(config)
        self._semaphore = asyncio.Semaphore(config.remote_max_concurrency)
        self._health_url = _derive_health_url(config.remote_url)

        # Metrics
        self._metrics = {
            "backend": "paddlex_http",
            "configured": True,
            "accepted": 0,
            "queued": 0,
            "running": 0,
            "finished": 0,
            "failed": 0,
            "timed_out": 0,
            "connection_errors": 0,
            "http_errors": 0,
            "protocol_errors": 0,
            "service_errors": 0,
            "max_concurrency": config.remote_max_concurrency,
            "last_success_time": 0.0,
            "last_error_code": "",
            "last_health_check_time": 0.0,
            "reachable": False,
            "endpoint": sanitize_url(config.remote_url),
        }

        timeout = httpx.Timeout(
            connect=config.remote_connect_timeout_sec,
            read=config.remote_read_timeout_sec,
            write=config.remote_connect_timeout_sec,
            pool=config.remote_connect_timeout_sec,
        )
        limits = httpx.Limits(
            max_keepalive_connections=config.remote_max_concurrency,
            max_connections=config.remote_max_concurrency,
        )
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits)

    # ── Public API ────────────────────────────────────────────────────────────

    async def recognize(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        *,
        mode: str = "boxes",
        options: dict | None = None,
    ) -> WorkerResult:
        """Recognise a single page."""
        if self._closed:
            return self._make_error(
                page_index, STABLE_ERROR_CODES["REMOTE_CLOSED"],
                "Client is shut down",
            )

        self._metrics["accepted"] += 1

        request_id = uuid.uuid4().hex[:16]
        start = time.monotonic()

        try:
            async with self._semaphore:
                self._metrics["running"] += 1
                self._metrics["queued"] += 1
                try:
                    result = await self._do_recognize(
                        image_bytes, page_index, request_id, options,
                    )
                finally:
                    self._metrics["running"] -= 1
                    self._metrics["queued"] -= 1
        except asyncio.CancelledError:
            self._metrics["failed"] += 1
            raise

        elapsed = time.monotonic() - start
        if result.status == "success":
            self._metrics["finished"] += 1
            self._metrics["last_success_time"] = time.time()
            result.started_monotonic = start
            result.finished_monotonic = start + elapsed
        else:
            self._metrics["failed"] += 1

        return result

    async def recognize_batch(
        self,
        images: list[tuple[int, bytes]],
        *,
        mode: str = "boxes",
        options: dict | None = None,
    ) -> list[WorkerResult]:
        """Recognise multiple pages concurrently.

        Results are sorted by ``page_index``.  A single-page failure does
        not affect other pages.
        """
        if not images:
            return []

        async def _task(idx: int, png: bytes) -> WorkerResult:
            return await self.recognize(png, page_index=idx, mode=mode, options=options)

        tasks = [_task(idx, png) for idx, png in images]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        resolved: list[WorkerResult] = []
        for i, r in enumerate(results):
            if isinstance(r, WorkerResult):
                resolved.append(r)
            elif isinstance(r, BaseException):
                resolved.append(self._make_error(
                    images[i][0],
                    STABLE_ERROR_CODES["REMOTE_CANCELLED"],
                    str(r) if str(r) else "Task raised exception",
                ))
            else:
                resolved.append(self._make_error(
                    images[i][0],
                    STABLE_ERROR_CODES["ENGINE_ERROR"],
                    "Unknown error",
                ))

        resolved.sort(key=lambda wr: wr.page_index)
        return resolved

    async def shutdown(self) -> None:
        """Graceful shutdown — idempotent."""
        if self._closed:
            return
        self._closed = True
        await self._client.aclose()
        logger.info("PaddleXHttpOcrWorkerClient shut down")

    @property
    def metrics(self) -> dict:
        return dict(self._metrics)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _do_recognize(
        self,
        image_bytes: bytes,
        page_index: int,
        request_id: str,
        options: dict | None,
    ) -> WorkerResult:
        """Send a single page to PaddleX and map the response."""
        b64_data = base64.b64encode(image_bytes).decode("ascii")

        payload: dict[str, Any] = {
            "file": b64_data,
            "fileType": 1,
        }

        # Threshold mapping from OcrRuntimeConfig
        cfg = self._config
        if cfg.det_db_thresh != 0.2:
            payload["textDetThresh"] = cfg.det_db_thresh
        if cfg.det_db_box_thresh != 0.4:
            payload["textDetBoxThresh"] = cfg.det_db_box_thresh
        if cfg.det_db_unclip_ratio != 1.8:
            payload["textDetUnclipRatio"] = cfg.det_db_unclip_ratio
        if cfg.drop_score != 0.3:
            payload["textRecScoreThresh"] = cfg.drop_score
        if cfg.remote_visualize:
            payload["visualize"] = True
        if cfg.remote_use_doc_orientation_classify:
            payload["useDocOrientationClassify"] = True
        if cfg.remote_use_doc_unwarping:
            payload["useDocUnwarping"] = True
        if cfg.remote_use_textline_orientation:
            payload["useTextlineOrientation"] = True

        try:
            response = await self._client.post(cfg.remote_url, json=payload)
        except httpx.ConnectError as exc:
            self._metrics["connection_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"]
            return self._make_error(
                page_index, STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"],
                f"Connection refused: {exc}",
            )
        except httpx.TimeoutException as exc:
            self._metrics["timed_out"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_TIMEOUT"]
            return self._make_error(
                page_index, STABLE_ERROR_CODES["REMOTE_TIMEOUT"],
                f"Request timed out: {exc}",
            )

        # HTTP status check
        if response.status_code != 200:
            self._metrics["http_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"]
            body_preview = response.text[:500]
            return self._make_error(
                page_index, STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"],
                f"HTTP {response.status_code}: {body_preview}",
            )

        # Parse JSON
        try:
            body = response.json()
        except Exception as exc:
            self._metrics["protocol_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"]
            return self._make_error(
                page_index, STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                f"Non-JSON response: {exc}",
            )

        # Validate top-level structure
        if not isinstance(body, dict):
            self._metrics["protocol_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"]
            return self._make_error(
                page_index, STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                "Response is not a JSON object",
            )

        error_code = body.get("errorCode", -1)
        if error_code != 0:
            self._metrics["service_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_SERVICE_ERROR"]
            error_msg = str(body.get("errorMsg", ""))[:500]
            return self._make_error(
                page_index, STABLE_ERROR_CODES["REMOTE_SERVICE_ERROR"],
                f"Service error (code={error_code}): {error_msg}",
            )

        result_data = body.get("result")
        if not isinstance(result_data, dict):
            self._metrics["protocol_errors"] += 1
            return self._make_error(
                page_index, STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                "result is missing or not an object",
            )

        ocr_results = result_data.get("ocrResults")
        if ocr_results is None:
            ocr_results = []

        if not isinstance(ocr_results, list):
            self._metrics["protocol_errors"] += 1
            return self._make_error(
                page_index, STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                "ocrResults is not a list",
            )

        # Map the first (and typically only) ocrResult to WorkerResult result dict
        mapped_result = _map_pruned_result(
            ocr_results, page_index, request_id, self._fingerprint,
        )

        self._metrics["finished"] += 1
        self._metrics["last_success_time"] = time.time()

        return WorkerResult(
            request_id=request_id,
            page_index=page_index,
            status="success",
            result=mapped_result,
            engine_fingerprint=self._fingerprint,
            stable_error_code=None,
            error_type=None,
        )

    def _make_error(
        self,
        page_index: int,
        stable_error_code: str,
        error_message: str,
    ) -> WorkerResult:
        self._metrics["last_error_code"] = stable_error_code
        return WorkerResult(
            request_id="",
            page_index=page_index,
            status="failed",
            result={
                "page_index": page_index,
                "text": "",
                "lines": [],
                "boxes": [],
                "confidence": 0.0,
                "transforms": None,
                "coordinate_space": "image",
                "engine_fingerprint": self._fingerprint,
                "failed": True,
                "error": error_message[:1000],
            },
            stable_error_code=stable_error_code,
            error_type=stable_error_code.split(".")[-1] if "." in stable_error_code else stable_error_code,
        )


# ---------------------------------------------------------------------------
# Response mapping (pure functions — easy to unit test)
# ---------------------------------------------------------------------------


def _derive_health_url(ocr_url: str) -> str:
    """Derive the OpenAPI health URL from the OCR endpoint.

    ``http://host:8080/ocr`` → ``http://host:8080/openapi.json``
    """
    if not ocr_url:
        return ""
    try:
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(ocr_url)
        clean = parsed._replace(path="/openapi.json", query="", fragment="")
        return clean.geturl()
    except Exception:
        return ocr_url


def _map_pruned_result(
    ocr_results: list[Any],
    page_index: int,
    request_id: str,
    fingerprint: str,
) -> dict:
    """Convert the first PaddleX ``prunedResult`` into the standard
    ``WorkerResult.result`` dict.
    """
    if not ocr_results:
        return {
            "page_index": page_index,
            "text": "",
            "lines": [],
            "boxes": [],
            "confidence": 0.0,
            "transforms": None,
            "coordinate_space": "image",
            "engine_fingerprint": fingerprint,
            "failed": False,
            "error": None,
        }

    entry = ocr_results[0]
    if not isinstance(entry, dict):
        return _empty_result(page_index, fingerprint)

    pruned = entry.get("prunedResult")
    if not isinstance(pruned, dict):
        return _empty_result(page_index, fingerprint)

    rec_texts = pruned.get("rec_texts")
    rec_scores = pruned.get("rec_scores")
    rec_polys = pruned.get("rec_polys")
    rec_boxes = pruned.get("rec_boxes")

    if not isinstance(rec_texts, list):
        rec_texts = []
    if not isinstance(rec_scores, list):
        rec_scores = []
    if not isinstance(rec_polys, list):
        rec_polys = []
    if not isinstance(rec_boxes, list):
        rec_boxes = []

    text_parts: list[str] = []
    lines: list[dict] = []
    boxes: list[dict] = []
    confidence_sum = 0.0
    valid_conf_count = 0
    degraded_count = 0

    n = max(len(rec_texts), len(rec_scores), len(rec_polys), len(rec_boxes))

    for i in range(n):
        raw_text = _safe_str(rec_texts[i] if i < len(rec_texts) else "")
        if not raw_text:
            continue  # skip empty text (matches existing OcrEngine behaviour)

        text_parts.append(raw_text)

        raw_score = _safe_score(rec_scores[i] if i < len(rec_scores) else None)
        if raw_score is not None:
            confidence_sum += raw_score
            valid_conf_count += 1

        # Polygon
        polygon = _normalize_polygon(rec_polys[i] if i < len(rec_polys) else None)
        if polygon is None:
            degraded_count += 1

        # BBox
        bbox = _normalize_bbox(rec_boxes[i] if i < len(rec_boxes) else None)
        if bbox is None and polygon is not None:
            # Derive bbox from polygon
            xs = polygon[0::2]
            ys = polygon[1::2]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
        elif bbox is not None and polygon is None:
            # Generate polygon from bbox
            polygon = [bbox[0], bbox[1], bbox[2], bbox[1], bbox[2], bbox[3], bbox[0], bbox[3]]

        line: dict[str, Any] = {
            "text": raw_text,
            "polygon": polygon if polygon is not None else [],
            "bbox": bbox if bbox is not None else [],
            "confidence": raw_score if raw_score is not None else 0.0,
        }
        lines.append(line)

        if bbox is not None:
            boxes.append({
                "bbox": bbox,
                "conf": raw_score if raw_score is not None else 0.0,
            })

    avg_confidence = round(confidence_sum / valid_conf_count, 6) if valid_conf_count > 0 else 0.0

    if degraded_count > 0:
        logger.debug(
            "Page %d: %d/%d lines have degraded geometry",
            page_index, degraded_count, n,
        )

    return {
        "page_index": page_index,
        "text": "\n".join(text_parts),
        "lines": lines,
        "boxes": boxes,
        "confidence": avg_confidence,
        "transforms": None,
        "coordinate_space": "image",
        "engine_fingerprint": fingerprint,
        "failed": False,
        "error": None,
    }


def _empty_result(page_index: int, fingerprint: str) -> dict:
    return {
        "page_index": page_index,
        "text": "",
        "lines": [],
        "boxes": [],
        "confidence": 0.0,
        "transforms": None,
        "coordinate_space": "image",
        "engine_fingerprint": fingerprint,
        "failed": False,
        "error": None,
    }


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None
    if not _isfinite(v):
        return None
    return max(0.0, min(1.0, v))


def _isfinite(v: float) -> bool:
    import math
    return math.isfinite(v)


def _normalize_polygon(poly: Any) -> list[float] | None:
    """Normalise a polygon to ``[x0,y0,x1,y1,x2,y2,x3,y3]``.

    Accepted shapes:
    - ``[[x,y],[x,y],[x,y],[x,y]]``  (nested list)
    - ``[x0,y0,x1,y1,...,x3,y3]``    (flat list, ≥8 values)
    """
    if poly is None:
        return None
    if not isinstance(poly, (list, tuple)):
        return None

    result: list[float] = []

    # Nested: [[x,y], ...]
    if poly and isinstance(poly[0], (list, tuple)):
        for pt in poly[:4]:  # at most 4 points
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                return None
            x, y = pt[0], pt[1]
            try:
                result.append(float(x))
                result.append(float(y))
            except (ValueError, TypeError):
                return None
        if len(result) >= 8:
            return _clamp_coords(result)
        return None

    # Flat: [x0,y0,x1,y1,...]
    if not all(isinstance(v, (int, float)) for v in poly[:8]):
        return None
    for v in poly[:8]:
        try:
            result.append(float(v))
        except (ValueError, TypeError):
            return None
    if len(result) >= 8:
        return _clamp_coords(result)
    return None


def _normalize_bbox(bbox: Any) -> list[float] | None:
    """Normalise a bbox to ``[xmin, ymin, xmax, ymax]``."""
    if bbox is None:
        return None
    if not isinstance(bbox, (list, tuple)):
        return None
    if len(bbox) < 4:
        return None
    try:
        vals = [float(v) for v in bbox[:4]]
    except (ValueError, TypeError):
        return None
    if not all(_isfinite(v) for v in vals):
        return None
    return [
        min(vals[0], vals[2]),
        min(vals[1], vals[3]),
        max(vals[0], vals[2]),
        max(vals[1], vals[3]),
    ]


def _clamp_coords(coords: list[float]) -> list[float]:
    """Replace NaN / Inf with 0.0."""
    return [0.0 if not _isfinite(v) else v for v in coords]


async def health_check(
    client: PaddleXHttpOcrWorkerClient,
) -> dict:
    """Check whether the remote PaddleX service is reachable.

    Sends a lightweight GET to ``<scheme>://<host>:<port>/openapi.json``.
    Does **not** trigger GPU inference.  Uses the client's own
    ``AsyncClient`` so that callers can provide a mock transport for tests.
    """
    if not client._health_url:
        return {"reachable": False, "error": "No health URL configured"}

    try:
        resp = await client._client.get(
            client._health_url,
            timeout=httpx.Timeout(client._config.remote_health_timeout_sec),
        )
        ok = resp.status_code < 500
        client._metrics["reachable"] = ok
        client._metrics["last_health_check_time"] = time.time()
        if ok:
            client._metrics["last_success_time"] = time.time()
        else:
            client._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"]
        return {
            "reachable": ok,
            "status_code": resp.status_code,
            "error": None,
        }
    except httpx.ConnectError as exc:
        client._metrics["reachable"] = False
        client._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"]
        client._metrics["last_health_check_time"] = time.time()
        return {"reachable": False, "error": f"Connection refused: {exc}"}
    except httpx.TimeoutException as exc:
        client._metrics["reachable"] = False
        client._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_TIMEOUT"]
        client._metrics["last_health_check_time"] = time.time()
        return {"reachable": False, "error": f"Health check timed out: {exc}"}
    except Exception as exc:
        client._metrics["reachable"] = False
        client._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"]
        client._metrics["last_health_check_time"] = time.time()
        return {"reachable": False, "error": str(exc)[:300]}
