"""OCR Adapter 契约与实现 — 统一 OCR 后端接入层。

提供：
- ``OcrAdapter``: 原始 PDF/图片 → ``ModuleResult[DocumentIR]``
- ``DocumentTransformAdapter``: DocumentIR → ``ModuleResult[DocumentIR]``
- ``PaddleOCRLocalAdapter``: 包装本地 PaddleOCR 引擎
- ``PaddleOCRVLDocumentAdapter``: 包装 PaddleOCR-VL 外部 API（不破坏现有 OCRFixerProtocol）
- ``RuleFallbackAdapter``: 直通 fallback
- ``ReadingOrderTransformAdapter``: 包装 reading_order_stage
- ``AdapterRegistry``: 注册与查询
- ``AdapterSelector``: 基于能力、健康、熔断、配置的选择器

Pipeline 通过 AdapterSelector 选择 Adapter，禁止根据 backend 名称写 ``if/elif``。
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.core.module_result import (
    AdapterCapabilities,
    ModuleError,
    ModuleResult,
)
from app.core.ocr_request import OCRRequest

logger = logging.getLogger(__name__)


def _get_image_dimensions(source: bytes) -> tuple[int, int]:
    """Get image width and height from bytes (fast, no Paddle/OCR)."""
    try:
        import io

        from PIL import Image
        with Image.open(io.BytesIO(source)) as img:
            return img.size
    except Exception:
        return 0, 0


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class OcrAdapter(Protocol):
    """原始 PDF/图片 → ``ModuleResult[DocumentIR]``

    将底层 OCR 引擎的输出统一转换为 ``DocumentIR``。
    Pipeline 不直接访问后端私有字段（``rec_texts``、``dt_polys`` 等）。
    """

    @property
    def capabilities(self) -> AdapterCapabilities:
        ...

    async def process(
        self,
        request: OCRRequest,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Process an OCR request and return a DocumentIR.

        The result ``data`` field contains a ``DocumentIR`` instance.
        ``raw`` may contain the original backend response (subject to 100KB
        limit and sensitive-field redaction).
        """
        ...

    async def close(self) -> None:
        """Release resources. Idempotent — safe to call multiple times."""
        ...


@runtime_checkable
class DocumentTransformAdapter(Protocol):
    """DocumentIR → ``ModuleResult[DocumentIR]``

    对已生成的 DocumentIR 执行变换（Reading Order、规则修正等）。
    不改变原始 OCR 识别结果，只增加结构化信息/修正。
    """

    @property
    def capabilities(self) -> AdapterCapabilities:
        ...

    async def transform(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Transform a DocumentIR and return the result.

        The result ``data`` field contains the transformed ``DocumentIR``.
        """
        ...

    async def close(self) -> None:
        """Release resources. Idempotent."""
        ...


# ---------------------------------------------------------------------------
# Adapter: ReadingOrderTransform
# ---------------------------------------------------------------------------


class ReadingOrderTransformAdapter:
    """DocumentTransformAdapter: 对 DocumentIR 所有页面执行 Reading Order 解析。

    包装现有 ``reading_order_stage.run_reading_order_stage()``。
    """

    def __init__(self) -> None:
        self._capabilities = AdapterCapabilities(
            backend="reading_order",
            adapter_type="transform",
            text=False,
            bbox=True,
            reading_order=True,
            offline=True,
            thread_safe=True,
            process_safe=True,
            max_concurrency=10,
        )
        self._closed = False

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def transform(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        if self._closed:
            return ModuleResult.failure(
                ModuleError(code="ADAPTER_CLOSED", message="ReadingOrderTransformAdapter is closed", category="system"),
                module_name="reading_order_transform",
                trace_id=trace_id,
                backend="reading_order",
            )

        start = time.monotonic()

        if doc_ir is None:
            return ModuleResult.failure(
                ModuleError(code="INPUT_NONE", message="doc_ir is None", category="input"),
                module_name="reading_order_transform",
                trace_id=trace_id,
                backend="reading_order",
                latency_ms=0.0,
            )

        try:
            from app.features.pipeline_stages import reading_order_stage

            # Use v2 function — doc_ir is modified in-place
            v2_result = reading_order_stage.run_reading_order_stage_v2(doc_ir, stage_config=None)

            latency_ms = round((time.monotonic() - start) * 1000, 2)

            if v2_result.is_failure:
                return ModuleResult.failure(
                    error=v2_result.error,
                    module_name="reading_order_transform",
                    trace_id=trace_id,
                    backend="reading_order",
                    latency_ms=latency_ms,
                )

            # v2 returns ModuleResult[list[ReadingOrderResult]]
            page_results = v2_result.data or []
            warnings = v2_result.warnings or []

            # Determine confidence from page results
            confidence = v2_result.confidence
            if confidence is None and page_results:
                confs = [r.confidence for r in page_results if r.confidence is not None]
                if confs:
                    confidence = round(sum(confs) / len(confs), 4)

            return ModuleResult.success(
                data=doc_ir,
                data_type="DocumentIR",
                module_name="reading_order_transform",
                module_version="1.0.0",
                confidence=confidence,
                confidence_scope="global",
                confidence_method="average",
                warnings=warnings or None,
                trace_id=trace_id,
                backend="reading_order",
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            return ModuleResult.failure(
                ModuleError(
                    code="READING_ORDER_FAILED",
                    message=str(exc),
                    category="system",
                    recoverable=True,
                    details={"error_type": type(exc).__name__},
                ),
                module_name="reading_order_transform",
                trace_id=trace_id,
                backend="reading_order",
                latency_ms=latency_ms,
            )

    async def close(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# Adapter: PaddleOCRLocal
# ---------------------------------------------------------------------------


class PaddleOCRLocalAdapter:
    """OcrAdapter: 包装本地 PaddleOCR 引擎。

    使用现有 ``app.services.ocr_service.ocr_pages_with_boxes()`` 接口，
    将输出 blocks 转换为 DocumentIR。
    """

    def __init__(self, engine: str = "paddleocr") -> None:
        self._engine = engine
        self._device_resolved = True  # Will be set to False if resolution was done.
        self._resolved_device = ""
        self._capabilities = AdapterCapabilities(
            backend=engine,
            adapter_type="ocr",
            text=True,
            bbox=True,
            polygon=True,
            layout=False,
            reading_order=False,
            table=False,
            formula=False,
            code=False,
            per_line_confidence=True,
            offline=True,
            layout_labels=(),
            region_types=("text", "unknown"),
            supported_mime_types=("application/pdf", "image/png", "image/jpeg", "image/bmp"),
            supported_devices=("cpu", "cuda"),
            multipage=True,
            max_batch=10,
            max_pages=200,
            max_input_bytes=100 * 1024 * 1024,
            requires_network=False,
            thread_safe=False,
            process_safe=False,
            max_concurrency=1,
        )
        self._closed = False

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def process(
        self,
        request: OCRRequest,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        if self._closed:
            return ModuleResult.failure(
                ModuleError(code="ADAPTER_CLOSED", message="PaddleOCRLocalAdapter is closed", category="system"),
                module_name="paddleocr_local",
                trace_id=trace_id,
                backend="paddleocr",
            )

        start = time.monotonic()

        try:
            # Resolve OCR device (GPU/CPU) — cache result to avoid
            # redundant paddle import + CUDA enumeration per page.
            # run in thread pool to avoid blocking event loop.
            if not self._resolved_device:
                from app.ocr_worker.device import resolve_ocr_device
                device_res = await asyncio.to_thread(resolve_ocr_device)
                self._resolved_device = device_res.resolved_device
                self._device_resolved = True

            # Delegate OCR to the worker client / Gateway path
            # instead of importing from legacy pipeline_orchestrator.
            from app.services.ocr_service import ocr_pages_with_boxes

            blocks: list[dict] = []
            is_pdf = request.source_type == "pdf"
            if is_pdf:
                # Render PDF pages via PyMuPDF, then OCR each page image.
                # Run in thread pool to avoid blocking event loop.
                import fitz

                from app.core.config import settings
                from app.core.ocr_profile import get_ocr_profile

                ocr_profile = get_ocr_profile()
                batch_size = max(1, ocr_profile.max_workers)

                def _pdf_ocr(source: bytes) -> list[dict]:
                    import gc

                    doc = fitz.open(stream=source, filetype="pdf")
                    try:
                        max_pages = settings.MAX_OCR_PAGES
                        total_pages = len(doc)
                        pages_to_process = (
                            min(total_pages, max_pages) if max_pages > 0 else total_pages
                        )
                        all_blocks: list[dict] = []
                        # Process pages in batches to manage memory
                        for batch_start in range(0, pages_to_process, batch_size):
                            batch_end = min(batch_start + batch_size, pages_to_process)
                            page_images: list[tuple[int, bytes]] = []
                            page_dims: dict[int, tuple[int, int]] = {}
                            for i in range(batch_start, batch_end):
                                page = doc[i]
                                pix = page.get_pixmap(dpi=150)
                                img_bytes = pix.tobytes("png")
                                page_images.append((i + 1, img_bytes))
                                page_dims[i + 1] = (pix.width, pix.height)

                            results = ocr_pages_with_boxes(page_images, skip_rotation=True)
                            for page_idx, result in results.items():
                                pw, ph = page_dims.get(page_idx, (0, 0))
                                all_blocks.append({
                                    "page": page_idx,
                                    "text": result.text,
                                    "boxes": result.boxes or [],
                                    "page_width": pw,
                                    "page_height": ph,
                                    "source": "ocr",
                                    "has_boxes": bool(result.boxes),
                                    "_ocr_boxes_failed": result.failed,
                                })

                            # Release batch memory before next iteration
                            del page_images, page_dims, results
                            gc.collect()

                        return all_blocks
                    finally:
                        doc.close()

                blocks = await asyncio.to_thread(_pdf_ocr, request.source)
            else:
                # Image: use ocr_pages_with_boxes.
                # Run in thread pool to avoid blocking event loop.
                page_results = await asyncio.to_thread(
                    ocr_pages_with_boxes,
                    [(1, request.source)],
                    True,  # skip_rotation
                )
                for page_idx, result in page_results.items():
                    pw, ph = _get_image_dimensions(request.source)
                    blocks.append({
                        "page": page_idx,
                        "text": result.text,
                        "boxes": result.boxes or [],
                        "page_width": pw or 0,
                        "page_height": ph or 0,
                        "source": "ocr",
                        "has_boxes": bool(result.boxes),
                        "_ocr_boxes_failed": result.failed,
                    })

            latency_ms = round((time.monotonic() - start) * 1000, 2)

            if not blocks:
                return ModuleResult.failure(
                    ModuleError(
                        code="OCR_NO_RESULT",
                        message="PaddleOCR returned no blocks",
                        category="output",
                        recoverable=True,
                    ),
                    module_name="paddleocr_local",
                    trace_id=trace_id,
                    backend="paddleocr",
                    latency_ms=latency_ms,
                )

            # Convert blocks to DocumentIR using standalone builder
            from app.features.document_ir_builder import blocks_to_document_ir

            doc_ir = blocks_to_document_ir(blocks, pipeline_id=trace_id, engine="paddleocr", source_bytes=request.source)

            if doc_ir is None:
                return ModuleResult.failure(
                    ModuleError(
                        code="DOCUMENT_IR_CONVERSION_FAILED",
                        message="Could not convert OCR blocks to DocumentIR",
                        category="output",
                        recoverable=True,
                    ),
                    module_name="paddleocr_local",
                    trace_id=trace_id,
                    backend="paddleocr",
                    latency_ms=latency_ms,
                )

            # Validate DocumentIR
            from app.core.document_ir import validate_document_ir

            violations = validate_document_ir(doc_ir)
            if violations:
                return ModuleResult.failure(
                    ModuleError(
                        code="ADAPTER_OUTPUT_INVALID",
                        message=f"DocumentIR validation failed: {violations[0]}",
                        category="output",
                        recoverable=False,
                        details={"violations": violations[:10]},
                    ),
                    module_name="paddleocr_local",
                    trace_id=trace_id,
                    backend="paddleocr",
                    latency_ms=latency_ms,
                )

            return ModuleResult.success(
                data=doc_ir,
                data_type="DocumentIR",
                data_schema_version=doc_ir.schema_version,
                module_name="paddleocr_local",
                module_version="1.0.0",
                raw=blocks if len(str(blocks)) < 100 * 1024 else None,
                trace_id=trace_id,
                backend="paddleocr",
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            # Catch known error types
            if isinstance(exc, asyncio.CancelledError):
                raise  # never swallow CancelledError
            return ModuleResult.failure(
                ModuleError(
                    code="PADDLE_CRASH",
                    message=str(exc),
                    category="system",
                    recoverable=True,
                    retryable=True,
                    details={"error_type": type(exc).__name__},
                ),
                module_name="paddleocr_local",
                trace_id=trace_id,
                backend="paddleocr",
                latency_ms=latency_ms,
            )

    async def close(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# Adapter: PaddleOCRVLDocument
# ---------------------------------------------------------------------------


class PaddleOCRVLDocumentAdapter:
    """OcrAdapter: 包装 PaddleOCR-VL 外部 API。

    这是一个 **新建的 DocumentIR-原生适配器**，不破坏现有 ``OCRFixerProtocol``
    实现（``PaddleOCRVLAdapter``）。直接调用 ``PaddleOCRVLClient`` 并将结果
    转为 ``DocumentIR``。
    """

    def __init__(
        self,
        api_token: str = "",
        base_url: str = "https://paddleocr.aistudio-app.com",
        model: str = "PaddleOCR-VL-1.6",
    ) -> None:
        self._api_token = api_token
        self._base_url = base_url
        self._model = model
        self._client: Any = None
        self._capabilities = AdapterCapabilities(
            backend="paddleocr-vl",
            adapter_type="ocr",
            text=True,
            bbox=True,
            polygon=True,
            layout=True,
            reading_order=False,
            table=True,
            formula=True,
            code=True,
            per_line_confidence=False,
            offline=False,
            layout_labels=("text", "code", "formula", "table", "figure", "title", "caption"),
            region_types=("text", "code", "formula", "table", "figure", "unknown"),
            supported_mime_types=("image/png", "image/jpeg"),
            supported_devices=("cpu", "cuda"),
            multipage=False,
            max_batch=1,
            max_pages=1,
            max_input_bytes=20 * 1024 * 1024,  # 20 MB per the API limit
            requires_network=True,
            thread_safe=False,
            process_safe=False,
            max_concurrency=2,
        )
        self._closed = False

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def _get_client(self) -> Any:
        """Lazy-initialize the PaddleOCR-VL client."""
        if self._client is None:
            from app.features.ocr_vl.paddleocr_vl_client import PaddleOCRVLClient

            self._client = PaddleOCRVLClient(
                api_token=self._api_token,
                base_url=self._base_url,
                model=self._model,
            )
        return self._client

    async def process(
        self,
        request: OCRRequest,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        if self._closed:
            return ModuleResult.failure(
                ModuleError(code="ADAPTER_CLOSED", message="PaddleOCRVLDocumentAdapter is closed", category="system"),
                module_name="paddleocr_vl_document",
                trace_id=trace_id,
                backend="paddleocr-vl",
            )

        if not self._api_token:
            return ModuleResult.failure(
                ModuleError(
                    code="VL_NOT_CONFIGURED",
                    message="PaddleOCR-VL API token not configured",
                    category="input",
                    recoverable=True,
                ),
                module_name="paddleocr_vl_document",
                trace_id=trace_id,
                backend="paddleocr-vl",
            )

        # VL API expects single-page images
        if request.source_type == "pdf":
            return ModuleResult.failure(
                ModuleError(
                    code="VL_NO_PDF_SUPPORT",
                    message="PaddleOCR-VL adapter does not support PDF input; render to PNG first",
                    category="input",
                    recoverable=True,
                ),
                module_name="paddleocr_vl_document",
                trace_id=trace_id,
                backend="paddleocr-vl",
            )

        start = time.monotonic()

        try:
            client = await self._get_client()

            result = await client.ocr_image(
                image_bytes=request.source,
                filename=request.filename or f"page_{request.page_start}.png",
            )

            latency_ms = round((time.monotonic() - start) * 1000, 2)

            # Convert PaddleOCRVLResult → DocumentIR
            doc_ir = self._vl_result_to_document_ir(
                result=result,
                page_index=request.page_start - 1,
                trace_id=trace_id,
                source_bytes=request.source,
            )

            # Validate DocumentIR
            from app.core.document_ir import validate_document_ir

            violations = validate_document_ir(doc_ir)
            if violations:
                return ModuleResult.failure(
                    ModuleError(
                        code="ADAPTER_OUTPUT_INVALID",
                        message=f"DocumentIR validation failed: {violations[0]}",
                        category="output",
                        recoverable=False,
                        details={"violations": violations[:10]},
                    ),
                    module_name="paddleocr_vl_document",
                    raw=result.raw if result.raw else None,
                    trace_id=trace_id,
                    backend="paddleocr-vl",
                    latency_ms=latency_ms,
                )

            return ModuleResult.success(
                data=doc_ir,
                data_type="DocumentIR",
                data_schema_version=doc_ir.schema_version,
                module_name="paddleocr_vl_document",
                module_version="1.0.0",
                confidence=result.confidence if result.confidence > 0 else None,
                confidence_scope="global",
                confidence_method="model",
                raw=result.raw if result.raw else None,
                trace_id=trace_id,
                model_fingerprint="paddleocr-vl-1.6",
                backend="paddleocr-vl",
                latency_ms=latency_ms,
            )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            latency_ms = round((time.monotonic() - start) * 1000, 2)

            # Classify error
            from app.features.ocr_vl.paddleocr_vl_client import (
                ContractError,
                JobPollingError,
                JobSubmissionError,
                ResultDownloadError,
            )

            category = "system"
            retryable = False
            if isinstance(exc, (JobSubmissionError, JobPollingError, ResultDownloadError)):
                category = "network"
                retryable = True
            elif isinstance(exc, ContractError):
                category = "output"
                retryable = False

            error_code = type(exc).__name__.upper()

            return ModuleResult.failure(
                ModuleError(
                    code=error_code,
                    message=str(exc)[:500],
                    category=category,
                    recoverable=True,
                    retryable=retryable,
                    details={"error_type": type(exc).__name__},
                ),
                module_name="paddleocr_vl_document",
                raw=({"error": str(exc)[:500]}),
                trace_id=trace_id,
                backend="paddleocr-vl",
                latency_ms=latency_ms,
            )

    def _vl_result_to_document_ir(
        self,
        result: Any,
        page_index: int = 0,
        trace_id: str = "",
        source_bytes: bytes | None = None,
    ) -> Any:
        """Convert a PaddleOCRVLResult to a DocumentIR.

        Each ``layout_blocks`` entry becomes a ``RegionIR`` with corresponding
        ``LineIR`` children.
        """
        from app.core.document_ir import (
            BBox,
            LineIR,
            PageIR,
            Point,
            Polygon,
            Provenance,
            RegionIR,
            make_line_id,
            make_page_id,
            make_region_id,
            new_document,
        )

        doc = new_document(source_bytes=source_bytes)
        page_id = make_page_id(doc.document_id, page_index)

        regions: list[RegionIR] = []

        layout_blocks = getattr(result, "layout_blocks", [])
        if not layout_blocks:
            # Fallback: create a single text region from the concatenated text
            text = getattr(result, "text", "") or ""
            if text.strip():
                region_id = make_region_id(page_id, None, "paddleocr-vl", text[:64])
                line_id = make_line_id(region_id, None, text[:200])
                line = LineIR(
                    line_id=line_id,
                    text=text,
                    confidence=getattr(result, "confidence", 0.0),
                    provenance=Provenance(
                        engine="paddleocr-vl",
                        model_version="1.6",
                        adapter="paddleocr_vl_document",
                    ),
                    reading_order=0,
                )
                region = RegionIR(
                    region_id=region_id,
                    region_type="text",
                    confidence=getattr(result, "confidence", 0.0),
                    lines=[line],
                    provenance=Provenance(
                        engine="paddleocr-vl",
                        model_version="1.6",
                        adapter="paddleocr_vl_document",
                    ),
                )
                regions.append(region)
        else:
            for idx, block in enumerate(layout_blocks):
                block_text = block.get("text", "") or block.get("markdown", "") or ""
                block_type = block.get("type", "unknown")

                # Map VL type to RegionIR region_type
                region_type = self._map_vl_type(block_type)

                # Bbox
                bbox_coords = block.get("bbox")
                bbox = BBox(*bbox_coords) if bbox_coords and len(bbox_coords) == 4 else None

                # Polygon (if available)
                polygon_coords = block.get("polygon")
                polygon = None
                if polygon_coords and len(polygon_coords) >= 8:
                    pts = tuple(
                        Point(polygon_coords[i], polygon_coords[i + 1])
                        for i in range(0, len(polygon_coords), 2)
                    )
                    polygon = Polygon(pts)

                conf = block.get("confidence", 1.0)
                if not isinstance(conf, (int, float)) or math.isnan(conf):
                    conf = 0.0

                region_id = make_region_id(
                    page_id, bbox, "paddleocr-vl", block_text[:64],
                )
                line_id = make_line_id(region_id, bbox, block_text[:200])
                line = LineIR(
                    line_id=line_id,
                    text=block_text,
                    bbox=bbox,
                    confidence=conf,
                    provenance=Provenance(
                        engine="paddleocr-vl",
                        model_version="1.6",
                        adapter="paddleocr_vl_document",
                    ),
                    reading_order=0,
                )
                region = RegionIR(
                    region_id=region_id,
                    region_type=region_type,
                    polygon=polygon,
                    bbox=bbox,
                    confidence=conf,
                    lines=[line],
                    provenance=Provenance(
                        engine="paddleocr-vl",
                        model_version="1.6",
                        adapter="paddleocr_vl_document",
                    ),
                )
                regions.append(region)

        page = PageIR(
            page_id=page_id,
            page_index=page_index,
            width=result.raw.get("width", 0) or getattr(result, "image_width", 0) if hasattr(result, "raw") else 0,
            height=result.raw.get("height", 0) or getattr(result, "image_height", 0) if hasattr(result, "raw") else 0,
            regions=regions,
        )
        doc.pages = [page]
        doc.pipeline_fingerprint = trace_id

        return doc

    @staticmethod
    def _map_vl_type(vl_type: str) -> str:
        """Map PaddleOCR-VL block type to RegionIR region_type."""
        mapping = {
            "text": "text",
            "code": "code",
            "formula": "formula",
            "table": "table",
            "figure": "figure",
            "title": "text",
            "caption": "text",
            "header": "header",
            "footer": "footer",
            "page_number": "page_number",
            "option": "option",
            "question_stem": "question_stem",
        }
        return mapping.get(vl_type.lower(), "unknown")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._closed = True


# ---------------------------------------------------------------------------
# Adapter: RuleFallback
# ---------------------------------------------------------------------------


class RuleFallbackAdapter:
    """DocumentTransformAdapter: 直通 fallback。

    当所有 OCR/transform 适配器失败时，将输入 DocumentIR 直接返回
    （不执行任何实际变换）。
    """

    def __init__(self) -> None:
        self._capabilities = AdapterCapabilities(
            backend="rule_fallback",
            adapter_type="transform",
            text=False,
            bbox=False,
            offline=True,
            thread_safe=True,
            process_safe=True,
            max_concurrency=100,
        )
        self._closed = False

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def transform(
        self,
        doc_ir: Any,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        if self._closed:
            return ModuleResult.failure(
                ModuleError(code="ADAPTER_CLOSED", message="RuleFallbackAdapter is closed", category="system"),
                module_name="rule_fallback",
                trace_id=trace_id,
                backend="rule_fallback",
            )

        start = time.monotonic()

        if doc_ir is None:
            return ModuleResult.failure(
                ModuleError(code="INPUT_NONE", message="doc_ir is None", category="input"),
                module_name="rule_fallback",
                trace_id=trace_id,
                backend="rule_fallback",
                latency_ms=0.0,
            )

        latency_ms = round((time.monotonic() - start) * 1000, 2)
        return ModuleResult.success(
            data=doc_ir,
            data_type="DocumentIR",
            module_name="rule_fallback",
            module_version="1.0.0",
            trace_id=trace_id,
            backend="rule_fallback",
            latency_ms=latency_ms,
        )

    async def close(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class AdapterRegistry:
    """注册所有可用 Adapter。

    在应用程序启动时初始化，为 ``AdapterSelector`` 提供数据源。
    """

    def __init__(self) -> None:
        self._ocr_adapters: dict[str, OcrAdapter] = {}
        self._transform_adapters: dict[str, DocumentTransformAdapter] = {}

    def register_ocr(self, adapter: OcrAdapter) -> None:
        """Register an OcrAdapter by its backend name."""
        name = adapter.capabilities.backend
        self._ocr_adapters[name] = adapter

    def register_transform(self, adapter: DocumentTransformAdapter) -> None:
        """Register a DocumentTransformAdapter by its backend name."""
        name = adapter.capabilities.backend
        self._transform_adapters[name] = adapter

    def get_ocr(self, backend: str) -> OcrAdapter | None:
        """Get a registered OcrAdapter by backend name."""
        return self._ocr_adapters.get(backend)

    def get_transform(self, backend: str) -> DocumentTransformAdapter | None:
        """Get a registered DocumentTransformAdapter by backend name."""
        return self._transform_adapters.get(backend)

    def list_ocr(self) -> list[OcrAdapter]:
        """List all registered OcrAdapters."""
        return list(self._ocr_adapters.values())

    def list_transform(self) -> list[DocumentTransformAdapter]:
        """List all registered DocumentTransformAdapters."""
        return list(self._transform_adapters.values())

    def close_all(self) -> None:
        """Close all registered adapters.

        Attempts to call ``close()`` on each adapter. Async close methods
        are scheduled via ``asyncio.ensure_future`` if an event loop is running.
        """
        import asyncio as _asyncio

        for adapter in list(self._ocr_adapters.values()) + list(self._transform_adapters.values()):
            try:
                close_fn = getattr(adapter, "close", None)
                if close_fn is None:
                    continue
                coro = close_fn()
                try:
                    loop = _asyncio.get_running_loop()
                    _asyncio.ensure_future(coro)
                except RuntimeError:
                    # No running loop — close synchronously via asyncio.run
                    try:
                        _asyncio.run(coro)
                    except Exception:
                        pass
            except Exception:
                pass
        self._ocr_adapters.clear()
        self._transform_adapters.clear()

    def __len__(self) -> int:
        return len(self._ocr_adapters) + len(self._transform_adapters)


# ---------------------------------------------------------------------------
# Selector — capability and health-based adapter selection
# ---------------------------------------------------------------------------


@dataclass
class AdapterHealth:
    """Per-adapter health tracking."""
    healthy: bool = True
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    circuit_open_until: float = 0.0
    concurrent_calls: int = 0


class AdapterSelector:
    """基于能力、健康状态、熔断和配置选择 Adapter。

    选择优先级：
    1. 能力匹配（是否支持 PDF/PNG、multipage、layout 等）
    2. 配置优先级（pipeline 配置中指定的首选 Adapter）
    3. 健康状态（circuit breaker）
    4. 熔断状态（最近失败率）
    5. 本地数据限制（max_input_bytes、max_pages 等）
    6. 最大并发（当前活跃调用数）
    """

    def __init__(self, registry: AdapterRegistry) -> None:
        self._registry = registry
        self._health: dict[str, AdapterHealth] = {}

    def register_backend(self, backend: str) -> None:
        """Register a backend for health tracking."""
        if backend not in self._health:
            self._health[backend] = AdapterHealth()

    def select_ocr(
        self,
        request: OCRRequest,
        *,
        preferred_backend: str | None = None,
        require_layout: bool = False,
        require_formula: bool = False,
        require_code: bool = False,
        require_offline: bool = False,
    ) -> OcrAdapter | None:
        """Select the best available OcrAdapter for the given request."""
        candidates = self._registry.list_ocr()
        if not candidates:
            return None

        # Score each candidate
        scored: list[tuple[float, OcrAdapter]] = []
        for adapter in candidates:
            cap = adapter.capabilities
            health = self._health.get(cap.backend, AdapterHealth())

            # Skip circuit-broken adapters
            if not health.healthy or time.time() < health.circuit_open_until:
                continue

            # Skip if max concurrency reached
            if health.concurrent_calls >= cap.max_concurrency:
                continue

            # Required capability checks
            if require_layout and not cap.layout:
                continue
            if require_formula and not cap.formula:
                continue
            if require_code and not cap.code:
                continue
            if require_offline and not cap.offline:
                continue

            # MIME type check
            if request.mime not in cap.supported_mime_types:
                continue

            # Input size check
            if len(request.source) > cap.max_input_bytes:
                continue

            # Multipage check
            if request.estimated_pages() > 1 and not cap.multipage:
                continue

            # Scoring: higher = better
            score = 0.0
            if cap.backend == preferred_backend:
                score += 10.0
            if cap.layout:
                score += 3.0
            if cap.formula:
                score += 2.0
            if cap.code:
                score += 1.0
            if cap.offline:
                score += 2.0
            if cap.multipage:
                score += 2.0
            if health.consecutive_failures == 0:
                score += 5.0
            # Penalize high concurrency
            score -= health.concurrent_calls * 0.5

            scored.append((score, adapter))

        if not scored:
            return None

        # Return highest-scored adapter
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def select_transform(
        self,
        *,
        preferred_backend: str | None = None,
        require_reading_order: bool = False,
    ) -> DocumentTransformAdapter | None:
        """Select the best available DocumentTransformAdapter."""
        candidates = self._registry.list_transform()
        if not candidates:
            return None

        for adapter in candidates:
            cap = adapter.capabilities
            health = self._health.get(cap.backend, AdapterHealth())

            if not health.healthy:
                continue
            if time.time() < health.circuit_open_until:
                continue
            if require_reading_order and not cap.reading_order:
                continue

            if cap.backend == preferred_backend or not preferred_backend:
                return adapter

        # Fallback: return first healthy adapter (ignoring circuit state since
        # no adapter passed the strict selection above).
        for adapter in candidates:
            cap = adapter.capabilities
            health = self._health.get(cap.backend, AdapterHealth())
            if health.healthy:
                return adapter

        return None

    def record_success(self, backend: str) -> None:
        """Record a successful call, resetting failure counter."""
        if backend in self._health:
            self._health[backend].consecutive_failures = 0
            self._health[backend].healthy = True
            self._health[backend].concurrent_calls = max(0, self._health[backend].concurrent_calls - 1)

    def record_failure(self, backend: str, retryable: bool = True) -> None:
        """Record a failure, potentially opening the circuit breaker."""
        if backend not in self._health:
            self.register_backend(backend)

        h = self._health[backend]
        h.consecutive_failures += 1
        h.last_failure_time = time.time()
        h.concurrent_calls = max(0, h.concurrent_calls - 1)

        # Open circuit after 3 consecutive failures (5s cooldown for retryable, 30s for non-retryable)
        if h.consecutive_failures >= 3:
            cooldown = 5.0 if retryable else 30.0
            h.circuit_open_until = time.time() + cooldown
            h.healthy = False

    def increment_concurrent(self, backend: str) -> None:
        """Increment the concurrent call counter for a backend."""
        if backend in self._health:
            self._health[backend].concurrent_calls += 1

    def all_adapters(self) -> dict[str, AdapterCapabilities]:
        """Return a summary dict of all registered adapters and their capabilities."""
        result: dict[str, AdapterCapabilities] = {}
        capacity = self._registry.list_ocr() + self._registry.list_transform()
        for adapter in capacity:
            try:
                cap = adapter.capabilities
                result[cap.backend] = cap
            except Exception:
                pass
        return result


# ---------------------------------------------------------------------------
# Default registry factory
# ---------------------------------------------------------------------------


def create_default_adapter_registry(
    vl_api_token: str = "",
    vl_base_url: str = "https://paddleocr.aistudio-app.com",
) -> AdapterRegistry:
    """Create an AdapterRegistry with the standard set of adapters.

    Args:
        vl_api_token: PaddleOCR-VL API token (empty = VL adapter registered but will fail with VL_NOT_CONFIGURED)
        vl_base_url: PaddleOCR-VL base URL

    Returns:
        Configured AdapterRegistry
    """
    registry = AdapterRegistry()

    # Local PaddleOCR (registered even if Paddle may not be installed — fail at call time)
    registry.register_ocr(PaddleOCRLocalAdapter(engine="paddleocr"))

    # PaddleOCR-VL (registered even without token — fail with a clear error)
    registry.register_ocr(PaddleOCRVLDocumentAdapter(
        api_token=vl_api_token,
        base_url=vl_base_url,
    ))

    # Transforms
    registry.register_transform(ReadingOrderTransformAdapter())
    registry.register_transform(RuleFallbackAdapter())

    return registry
