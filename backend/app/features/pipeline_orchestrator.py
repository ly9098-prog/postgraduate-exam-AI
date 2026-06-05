"""Stage 8 导入流水线编排 — 串联 Stage 1-7 模块。

Pipeline stages:
    extract → normalize_text → split → match → normalize_schema → [repair] → review

Features:
- Task state tracking per stage
- Error isolation (single question failure doesn't block others)
- AI repair toggle via config
- Background execution with in-memory state store
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any

from app.features.ai_repair import repair_questions
from app.features.ai_validation import validate_ai_results
from app.features.answer_matcher import match_answers
from app.features.batch_validation import validate_batch_structure
from app.features.import_mode import ImportMode, detect_import_mode, get_strategy
from app.features.ocr_correction import correct_ocr_blocks
from app.features.page_classifier import classify_pages, filter_blocks_by_classification
from app.features.question_normalizer import normalize_questions
from app.features.question_splitter import split_questions
from app.features.similarity_matcher import match_similar_questions
from app.features.structure_analyzer import analyze_structure
from app.features.text_normalizer import ImportTextNormalizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# in-memory pipeline state store
# ---------------------------------------------------------------------------

_pipeline_store: dict[str, dict] = {}
_pipeline_diagnostics_store: dict[str, dict] = {}
_ocr_progress: dict[str, str] = {}  # pipeline_id -> "32/312 pages"

_MAX_STORE_SIZE = 500  # keep at most N pipelines in memory
_PIPELINE_REDIS_PREFIX = "import:pipeline"
_PIPELINE_DIAGNOSTICS_REDIS_PREFIX = "import:pipeline:diagnostics"
_PIPELINE_STATUS_TTL = 86400  # 24h

# P0-3: 主 store 只保留这些瘦身字段；diagnostics、raw_questions_preview、
# corrections 等大对象走独立 KV 以避免单条记录被占到 1–3 MB。
_PIPELINE_STORE_FIELDS = (
    "pipeline_id",
    "status",
    "source_type",
    "source_file",
    "current_stage",
    "stages",
    "stats",
    "errors",
    "started_at",
    "finished_at",
    "batch_id",
    "raw_text_preview",
    "question_count",
)


def _prune_store() -> None:
    """Remove oldest entries when store exceeds max size."""
    if len(_pipeline_store) > _MAX_STORE_SIZE:
        sorted_ids = sorted(
            _pipeline_store.keys(),
            key=lambda k: _pipeline_store[k].get("started_at", ""),
        )
        for old_id in sorted_ids[: len(_pipeline_store) - _MAX_STORE_SIZE]:
            _pipeline_store.pop(old_id, None)
            _pipeline_diagnostics_store.pop(old_id, None)


def _slim_pipeline_payload(data: dict) -> dict:
    """仅保留 _PIPELINE_STORE_FIELDS 中存在于 data 的字段。

    避免把 diagnostics / 大 result 字段写进主 store。
    """
    return {k: data[k] for k in _PIPELINE_STORE_FIELDS if k in data}


async def _set_pipeline_diagnostics(pipeline_id: str, diagnostics: dict) -> None:
    """diagnostics 单独存（主 store 之外）。"""
    if not diagnostics:
        return
    _pipeline_diagnostics_store[pipeline_id] = diagnostics
    try:
        from app.core.cache import cache
        await cache.set(
            f"{_PIPELINE_DIAGNOSTICS_REDIS_PREFIX}:{pipeline_id}",
            diagnostics,
            ttl=_PIPELINE_STATUS_TTL,
        )
    except Exception:
        pass


async def _get_pipeline_diagnostics(pipeline_id: str) -> dict | None:
    if pipeline_id in _pipeline_diagnostics_store:
        return _pipeline_diagnostics_store[pipeline_id]
    try:
        from app.core.cache import cache
        data = await cache.get(f"{_PIPELINE_DIAGNOSTICS_REDIS_PREFIX}:{pipeline_id}")
        if data:
            _pipeline_diagnostics_store[pipeline_id] = data
            return data
    except Exception:
        pass
    return None


async def _set_pipeline_store(pipeline_id: str, data: dict) -> None:
    """写入流水线状态。

    P0-3: data 中如果含 diagnostics，会被剥离到独立 KV；主 store 仅保留
    _PIPELINE_STORE_FIELDS 字段。前端通过 get_pipeline_status 拿到的
    视图与改造前一致（diagnostics 合并回去）。
    """
    diagnostics = data.get("diagnostics")
    slim = _slim_pipeline_payload(data)
    _pipeline_store[pipeline_id] = slim
    _prune_store()
    try:
        from app.core.cache import cache
        await cache.set(
            f"{_PIPELINE_REDIS_PREFIX}:{pipeline_id}", slim, ttl=_PIPELINE_STATUS_TTL,
        )
    except Exception:
        pass
    if diagnostics:
        await _set_pipeline_diagnostics(pipeline_id, diagnostics)


async def _get_pipeline_store(pipeline_id: str) -> dict | None:
    if pipeline_id in _pipeline_store:
        return _pipeline_store[pipeline_id]
    try:
        from app.core.cache import cache
        data = await cache.get(f"{_PIPELINE_REDIS_PREFIX}:{pipeline_id}")
        if data:
            _pipeline_store[pipeline_id] = data
            return data
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def _open_pdf_doc(source: bytes | str | os.PathLike):
    """统一打开 PDF：bytes 走 stream，path 走 filename。

    传 path 时 PyMuPDF 通过 mmap 加载，避免把整文件复制到 Python heap，
    显著降低 100~400 MB 大文件的内存占用 (P0-1)。
    """
    import fitz

    if isinstance(source, (str, os.PathLike)):
        return fitz.open(str(source), filetype="pdf")
    return fitz.open(stream=source, filetype="pdf")


def _extract_pdf_blocks(
    content_or_path: bytes | str,
    page_start: int = 1,
    page_end: int | None = None,
) -> list[dict]:
    """Extract text blocks from PDF using PyMuPDF.

    Returns list of {page, block_index, text} for use as raw_blocks input
    to ImportTextNormalizer.

    P0-1: content_or_path 接受 bytes 或文件路径，路径优先（mmap）。
    """
    try:
        import fitz  # noqa: F401  (used inside _open_pdf_doc)
    except ImportError:
        raise RuntimeError("PyMuPDF (fitz) 未安装，无法提取 PDF 文本")

    doc = _open_pdf_doc(content_or_path)
    total_pages = len(doc)
    start_idx = max(0, (page_start or 1) - 1)
    end_idx = min(total_pages, page_end or total_pages)

    blocks: list[dict] = []
    try:
        for i in range(start_idx, end_idx):
            text = doc[i].get_text()
            if text.strip():
                blocks.append({
                    "page": i + 1,
                    "block_index": len(blocks),
                    "text": text.strip(),
                })
    finally:
        doc.close()

    return blocks


def _ocr_scanned_pdf(
    content_or_path: bytes | str,
    pipeline_id: str = "",
    page_start: int = 1,
    page_end: int | None = None,
) -> list[dict]:
    """用 PaddleOCR 识别扫描版 PDF 各页。

    分批并发处理，每批 OCR 后释放图像内存以避免累积 OOM。
    超过 MAX_OCR_PAGES 截断，超过 OCR_TIMEOUT_SECONDS 超时中断。
    输出格式：[{page, block_index, text, boxes, page_width, page_height}]
    boxes 为每行的 bbox 坐标和置信度，供后续预处理使用。

    P0-1: content_or_path 接受 bytes 或文件路径，路径优先 (mmap)。
    """
    import gc
    import time

    import fitz  # noqa: F401

    from app.core.config import settings
    from app.core.ocr_profile import get_ocr_profile
    from app.services.ocr_service import clean_ocr_text, ocr_pages_with_boxes

    profile = get_ocr_profile()
    max_pages = settings.MAX_OCR_PAGES
    timeout = profile.timeout_seconds
    batch_size = profile.max_workers

    doc = _open_pdf_doc(content_or_path)
    total_pages = len(doc)

    # Page range: convert 1-based user params to 0-based indices
    start_idx = max(0, (page_start or 1) - 1)
    end_idx = min(total_pages, page_end or total_pages)
    pages_in_range = end_idx - start_idx
    pages_to_process = min(pages_in_range, max_pages) if max_pages > 0 else pages_in_range

    blocks: list[dict] = []
    page_dimensions: dict[int, tuple[int, int]] = {}
    timed_out = False
    start_time = time.monotonic()

    logger.info("OCR 开始：共 %d 页待处理（第 %d-%d 页）", pages_to_process, start_idx + 1, end_idx)
    if pipeline_id:
        _ocr_progress[pipeline_id] = f"0/{pages_to_process} pages"

    try:
        for batch_start in range(0, pages_to_process, batch_size):
            elapsed = time.monotonic() - start_time
            if timeout > 0 and elapsed >= timeout:
                logger.warning(
                    "OCR 超时中断：已用 %.1fs（限制 %ds），处理了 %d/%d 页",
                    elapsed, timeout, batch_start, pages_to_process,
                )
                timed_out = True
                break

            batch_end = min(batch_start + batch_size, pages_to_process)
            batch_images: list[tuple[int, bytes]] = []

            for i in range(batch_start, batch_end):
                page_idx = start_idx + i
                pix = doc[page_idx].get_pixmap(dpi=150)
                png_bytes = pix.tobytes("png")
                page_dimensions[page_idx + 1] = (pix.width, pix.height)
                del pix
                batch_images.append((page_idx + 1, png_bytes))

            results = ocr_pages_with_boxes(batch_images, skip_rotation=True)

            del batch_images
            gc.collect()

            for page_idx in sorted(results.keys()):
                text = clean_ocr_text(results[page_idx].text)
                if text.strip():
                    pw, ph = page_dimensions[page_idx]
                    blocks.append({
                        "page": page_idx,
                        "block_index": len(blocks),
                        "text": text,
                        "boxes": results[page_idx].boxes,
                        "page_width": pw,
                        "page_height": ph,
                    })

            logger.info(
                "OCR 进度：%d/%d 页已处理（%.1fs）",
                batch_end, pages_to_process, time.monotonic() - start_time,
            )
            if pipeline_id:
                _ocr_progress[pipeline_id] = f"{batch_end}/{pages_to_process} pages"
    finally:
        doc.close()

    if timed_out and blocks:
        blocks[0].setdefault("_warnings", [])
        blocks[0]["_warnings"].append(
            f"ocr_timeout: processed {len(blocks)} blocks in {timeout}s limit"
        )
    elif max_pages > 0 and total_pages > max_pages and blocks:
        blocks[0].setdefault("_warnings", [])
        blocks[0]["_warnings"].append(
            f"ocr_pages_truncated: processed {pages_to_process}/{total_pages} pages"
        )

    if pipeline_id:
        _ocr_progress.pop(pipeline_id, None)

    return blocks


def _extract_text_blocks(content_or_path: bytes | str) -> list[dict]:
    """Extract text blocks from plain text content.

    P0-1: 接受 bytes 或文件路径。
    """
    if isinstance(content_or_path, (str, os.PathLike)):
        with open(content_or_path, "rb") as f:
            content = f.read()
    else:
        content = content_or_path
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("文本内容为空")
    return [{"page": 1, "block_index": 0, "text": text}]


# ---------------------------------------------------------------------------
# PipelineStage
# ---------------------------------------------------------------------------


class PipelineStage:
    """单个阶段的执行单元，记录状态、耗时和警告。"""

    def __init__(self, name: str, fn):
        self.name = name
        self.fn = fn
        self.status = "pending"  # pending → running → completed | failed
        self.duration_ms = 0
        self.warnings: list[str] = []
        self.error: str | None = None

    def run(self, **kwargs):
        """同步执行阶段（阻塞）。"""
        self.status = "running"
        start = time.monotonic()
        try:
            result = self.fn(**kwargs)
            self.status = "completed"
            self.duration_ms = round((time.monotonic() - start) * 1000)
            return result
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc)
            self.duration_ms = round((time.monotonic() - start) * 1000)
            raise

    async def run_async(self, **kwargs):
        """异步执行阶段。"""
        self.status = "running"
        start = time.monotonic()
        try:
            if asyncio.iscoroutinefunction(self.fn):
                result = await self.fn(**kwargs)
            else:
                result = await asyncio.to_thread(self.fn, **kwargs)
            self.status = "completed"
            self.duration_ms = round((time.monotonic() - start) * 1000)
            return result
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc)
            self.duration_ms = round((time.monotonic() - start) * 1000)
            raise

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings,
        }
        if self.error:
            d["error"] = self.error
        return d


# ---------------------------------------------------------------------------
# ImportPipeline
# ---------------------------------------------------------------------------


class ImportPipeline:
    """导入流水线，编排 Stage 1-7。

    使用方式::

        pipeline = ImportPipeline(options={"enable_ai_repair": True})
        result = await pipeline.run(
            file_content=pdf_bytes,
            source_type="pdf",
            source_file="exam.pdf",
            subject="math2",
            db=db_session,
        )
    """

    def __init__(self, options: dict | None = None):
        self.options = options or {}
        self.pipeline_id = ""
        self.stages: dict[str, PipelineStage] = {}

    def _build_pipeline(self) -> None:
        """(Re)build the stage list from current options.

        Called during __init__ and whenever options change at runtime.
        """
        stage_specs: list[tuple[str, callable]] = [
            ("extract", self._run_extract),
        ]
        if self.options.get("enable_wangdao_preprocess", False):
            stage_specs.append(("wangdao_preprocess", self._run_wangdao_preprocess))
        stage_specs.append(("normalize_text", self._run_normalize_text))
        if self.options.get("enable_ocr_correction", True):
            stage_specs.append(("ocr_correction", self._run_ocr_correction))
        stage_specs.extend([
            ("analyze_structure", self._run_analyze_structure),
            ("classify_pages", self._run_classify_pages),
            ("split", self._run_split),
            ("match", self._run_match),
            ("normalize_schema", self._run_normalize_schema),
        ])
        stage_specs.append(("batch_validation", self._run_batch_validation))
        if self.options.get("enable_batch_dedup", True):
            stage_specs.append(("batch_dedup", self._run_batch_dedup))
        if self.options.get("enable_ai_repair", True):
            stage_specs.append(("repair", self._run_repair))
            stage_specs.append(("ai_validation", self._run_ai_validation))
        if self.options.get("enable_similarity_match", True):
            stage_specs.append(("similarity_match", self._run_similarity_match))
        stage_specs.append(("review", self._run_review))

        self.stages.clear()
        for name, fn in stage_specs:
            self.stages[name] = PipelineStage(name, fn)

    # ------------------------------------------------------------------
    # stage implementations
    # ------------------------------------------------------------------

    def _run_extract(
        self,
        file_content: bytes | None = None,
        source_type: str = "pdf",
        file_path: str | None = None,
        **_kw,
    ) -> dict:
        """Extract raw text blocks from file content.

        For PDFs with very little extractable text (< 100 chars), triggers OCR
        fallback automatically when OCR_ENABLED is True.

        When EXERCISE_DETECTION_ENABLED is True, performs a lightweight pre-scan
        to locate exercise regions and only OCRs those pages.

        P0-1: 优先使用 file_path（mmap），bytes 仅在调用方未提供 path 时使用。
        """
        # 路径优先：底层 fitz.open 走 mmap，避免把 100~400 MB 拷到 heap
        pdf_source: bytes | str = file_path if file_path else file_content
        if pdf_source is None:
            raise ValueError("either file_path or file_content must be provided")

        if source_type == "pdf":
            opts = _kw.get("options") or {}
            raw_blocks = _extract_pdf_blocks(
                pdf_source,
                page_start=opts.get("page_start") or 1,
                page_end=opts.get("page_end"),
            )

            exercise_regions_result: list[dict] = []

            # Scanned PDF detection: if PyMuPDF extracted very little text,
            # the PDF likely contains only images → trigger OCR fallback.
            total_text = sum(len(b.get("text", "")) for b in raw_blocks)
            if total_text < 100:
                from app.core.config import settings

                if settings.OCR_ENABLED:
                    logger.info(
                        "PDF text only %d chars, attempting PaddleOCR fallback", total_text,
                    )
                    try:
                        exercise_regions = None
                        import_mode_str = opts.get("import_mode", "auto")
                        user_specified_range = opts.get("page_start") or opts.get("page_end")
                        if settings.EXERCISE_DETECTION_ENABLED and import_mode_str != "exam" and not user_specified_range:
                            logger.info("Exercise region detection starting...")
                            from app.features.exercise_region_detector import (
                                detect_exercise_regions_from_pdf,
                            )

                            exercise_regions = detect_exercise_regions_from_pdf(
                                pdf_source,
                                config={
                                    "dpi": settings.EXERCISE_DETECTION_DPI,
                                    "max_empty_pages": settings.EXERCISE_DETECTION_MAX_EMPTY_PAGES,
                                    "min_confidence": settings.EXERCISE_DETECTION_MIN_CONFIDENCE,
                                    "sample_step": settings.EXERCISE_DETECTION_SAMPLE_STEP,
                                },
                            )

                            # 采样模式漏检保护：若 step>1 一无所获，退化为 step=1
                            # 重新探测一次。否则下方 fallback 会跑全本 OCR，整体
                            # 工作量反而比不开检测更高（lightweight 1/N + full 100%
                            # > full 100%）。
                            if (
                                not exercise_regions
                                and settings.EXERCISE_DETECTION_SAMPLE_STEP > 1
                            ):
                                logger.warning(
                                    "Exercise detection found nothing at sample_step=%d; retrying with full coverage to avoid degenerating into full-PDF OCR",
                                    settings.EXERCISE_DETECTION_SAMPLE_STEP,
                                )
                                exercise_regions = detect_exercise_regions_from_pdf(
                                    pdf_source,
                                    config={
                                        "dpi": settings.EXERCISE_DETECTION_DPI,
                                        "max_empty_pages": settings.EXERCISE_DETECTION_MAX_EMPTY_PAGES,
                                        "min_confidence": settings.EXERCISE_DETECTION_MIN_CONFIDENCE,
                                        "sample_step": 1,
                                    },
                                )
                        elif user_specified_range:
                            logger.info("Skipping exercise detection: user specified page range %s-%s",
                                        opts.get("page_start"), opts.get("page_end"))

                        if exercise_regions:
                            exercise_regions_result = [
                                {"start_page": r.start_page, "end_page": r.end_page,
                                 "confidence": r.confidence, "matched_keyword": r.matched_keyword}
                                for r in exercise_regions
                            ]
                            ocr_blocks: list[dict] = []
                            for region in exercise_regions:
                                region_blocks = _ocr_scanned_pdf(
                                    pdf_source,
                                    pipeline_id=self.pipeline_id,
                                    page_start=region.start_page,
                                    page_end=region.end_page,
                                )
                                ocr_blocks.extend(region_blocks)
                            if ocr_blocks:
                                raw_blocks = ocr_blocks
                                logger.info(
                                    "Exercise region OCR succeeded: %d blocks from %d region(s)",
                                    len(ocr_blocks), len(exercise_regions),
                                )
                        else:
                            exercise_regions = None
                            opts = _kw.get("options") or {}
                            ocr_blocks = _ocr_scanned_pdf(
                                pdf_source,
                                pipeline_id=self.pipeline_id,
                                page_start=opts.get("page_start") or 1,
                                page_end=opts.get("page_end"),
                            )
                            if ocr_blocks:
                                raw_blocks = ocr_blocks
                                logger.info(
                                    "OCR fallback succeeded: %d blocks", len(ocr_blocks),
                                )
                    except RuntimeError as exc:
                        logger.warning("OCR fallback unavailable: %s", exc)
                    except Exception as exc:
                        logger.warning(
                            "OCR fallback failed, using original extraction: %s", exc,
                        )
                else:
                    logger.warning(
                        "PDF text only %d chars but OCR_ENABLED=false, cannot extract scanned content",
                        total_text,
                    )

            if not raw_blocks:
                raise ValueError(
                    "PDF 中未提取到文本内容（文本层为空且 OCR 未启用或失败）"
                )
        else:
            raw_blocks = _extract_text_blocks(pdf_source)
            exercise_regions_result = []

        return {
            "raw_blocks": raw_blocks,
            "extracted": len(raw_blocks),
            "exercise_regions": exercise_regions_result,
        }

    def _run_wangdao_preprocess(self, raw_blocks: list[dict], **_kw) -> dict:
        """Pre-processing stage for Wangdao PDF: filter watermarks/headers/footers."""
        from app.features.wangdao_preprocessor import preprocess_wangdao_blocks

        filtered = preprocess_wangdao_blocks(raw_blocks)

        removed = len(raw_blocks) - len(filtered)
        warnings: list[str] = []
        if removed:
            warnings.append(f"wangdao_preprocess: removed {removed} blocks (watermark/header/footer)")

        return {"raw_blocks": filtered, "warnings": warnings}

    def _run_normalize_text(self, raw_blocks: list[dict], **_kw) -> dict:
        """Stage 1: text cleaning via ImportTextNormalizer."""
        extra_patterns = _kw.get("watermark_patterns") or []
        normalizer = ImportTextNormalizer(extra_watermark_patterns=extra_patterns)
        normalized_blocks = normalizer.normalize(raw_blocks)

        warnings: list[str] = []
        empty_count = sum(1 for b in normalized_blocks if not b.get("normalized_text"))
        if empty_count:
            warnings.append(f"{empty_count} blocks empty after normalization")

        return {"normalized_blocks": normalized_blocks, "warnings": warnings}

    async def _run_ocr_correction(self, normalized_blocks: list[dict], options: dict | None = None, **_kw) -> dict:
        """Stage 1.5: AI OCR text correction for noisy blocks."""
        opts = options or {}
        correction_config = {
            "enabled": opts.get("enable_ocr_correction", True),
            "mode": opts.get("ocr_correction_mode", "auto"),
            "noise_threshold": opts.get("ocr_noise_threshold", 0.3),
            "daily_token_limit": opts.get("ocr_correction_daily_token_limit", 50000),
            "monthly_token_limit": opts.get("ocr_correction_monthly_token_limit", 1000000),
        }

        result = await correct_ocr_blocks(normalized_blocks, correction_config)

        warnings: list[str] = []
        stats = result.get("stats", {})
        if stats.get("corrected_blocks", 0) > 0:
            warnings.append(
                f"AI corrected {stats['corrected_blocks']}/{stats['total_blocks']} blocks"
            )
        if result.get("skipped_reason"):
            warnings.append(f"OCR correction skipped: {result['skipped_reason']}")

        return {
            "normalized_blocks": result["corrected_blocks"],
            "ocr_correction_diagnostics": {
                "stats": stats,
                "corrections": result.get("corrections", []),
                "skipped_reason": result.get("skipped_reason"),
            },
            "warnings": warnings,
        }

    def _run_analyze_structure(self, normalized_blocks: list[dict], **_kw) -> dict:
        """Stage 2: detect question/answer document layout."""
        structure = analyze_structure(normalized_blocks)

        # In AUTO mode, refine import mode based on structure analysis
        import_mode = _kw.get("import_mode")
        source_file = _kw.get("source_file", "")
        if import_mode == ImportMode.AUTO:
            detected = detect_import_mode(source_file, structure)
            strategy = get_strategy(detected)
            return {
                "structure": structure,
                "import_mode": detected,
                "strategy": strategy,
                "warnings": [f"auto-detected import_mode: {detected.value}"],
            }

        return {"structure": structure, "warnings": []}

    def _run_classify_pages(self, normalized_blocks: list[dict], structure: dict | None = None, **_kw) -> dict:
        """Stage 2.5: classify each page and filter out non-question pages."""
        from app.core.config import settings

        strategy = _kw.get("strategy") or {}

        if not settings.PAGE_CLASSIFIER_ENABLED and not strategy.get("page_classifier_enabled"):
            return {"page_classifications": [], "warnings": ["page classifier disabled"]}

        section_markers = structure.get("section_markers") if structure else None
        page_classifications = classify_pages(normalized_blocks, section_markers=section_markers)

        # Apply mode-specific filtering rules
        filter_knowledge = strategy.get("filter_knowledge_pages", True)
        filter_catalog = strategy.get("filter_catalog_pages", True)

        allowed_labels = {"QUESTION_PAGE", "ANSWER_PAGE", "ANALYSIS_PAGE"}
        if not filter_knowledge:
            allowed_labels.add("KNOWLEDGE_PAGE")
        if not filter_catalog:
            allowed_labels.add("CATALOG_PAGE")

        filtered = filter_blocks_by_classification(
            normalized_blocks, page_classifications, allowed_labels=allowed_labels,
        )

        warnings: list[str] = []
        removed_pages = len(normalized_blocks) - len(filtered)
        if removed_pages:
            label_summary = {}
            for pc in page_classifications:
                label_summary[pc["label"]] = label_summary.get(pc["label"], 0) + 1
            warnings.append(
                f"page_classifier: {removed_pages} blocks filtered, "
                f"page types: {label_summary}"
            )

        return {
            "normalized_blocks": filtered,
            "page_classifications": page_classifications,
            "warnings": warnings,
        }

    def _run_split(self, normalized_blocks: list[dict], structure: dict | None = None, **_kw) -> dict:
        """Stage 3: split text blocks into individual questions."""
        strategy = _kw.get("strategy") or {}
        gap_tolerance = strategy.get("question_number_gap_tolerance", 10)
        raw_questions = split_questions(normalized_blocks, structure=structure, gap_tolerance=gap_tolerance)

        text_blocks = [
            b for b in normalized_blocks
            if str(b.get("normalized_text") or "").strip()
        ]
        split_diagnostics = {
            "normalized_block_count": len(normalized_blocks),
            "text_block_count": len(text_blocks),
            "raw_question_count": len(raw_questions),
            "raw_questions_preview": raw_questions[:20],
            "failure_reason": None,
        }

        warnings: list[str] = []
        if not raw_questions:
            if text_blocks:
                # 尝试视觉边界检测（需要 boxes 数据）
                has_boxes = any(b.get("boxes") for b in normalized_blocks)
                if has_boxes:
                    try:
                        from app.features.visual_boundary_detector import detect_visual_boundaries
                        from app.features.question_splitter import split_by_visual_boundaries
                        visual_bounds = detect_visual_boundaries(normalized_blocks)
                        if len(visual_bounds) >= 2:
                            raw_questions = split_by_visual_boundaries(normalized_blocks, visual_bounds)
                            warnings.append(f"visual_boundary: split {len(raw_questions)} questions via bbox")
                            split_diagnostics["failure_reason"] = None
                            split_diagnostics["fallback_created"] = False
                            split_diagnostics["detection_method"] = "visual_boundary"
                    except Exception as exc:
                        logger.warning("visual boundary detection failed: %s", exc)

                # 仍然无结果时 fallback 为单条
                if not raw_questions:
                    raw_questions = [{
                        "number": 1,
                        "raw_question_text": "\n".join(
                            str(b.get("normalized_text") or "").strip() for b in text_blocks
                        ),
                        "page_start": text_blocks[0].get("page", 1),
                        "page_end": text_blocks[-1].get("page", text_blocks[0].get("page", 1)),
                        "has_options": False,
                        "option_lines": {},
                        "confidence": 0.2,
                    }]
                    warnings.append("no questions found in document; created low-confidence review item")
                    split_diagnostics["fallback_created"] = True
                    split_diagnostics["failure_reason"] = "text_present_but_no_question_boundary"
            else:
                warnings.append("no questions found in document")
                split_diagnostics["fallback_created"] = False
                split_diagnostics["failure_reason"] = "no_text_blocks"
        elif len(raw_questions) < len(normalized_blocks):
            warnings.append(f"{len(normalized_blocks) - len(raw_questions)} blocks produced no questions")
            split_diagnostics["fallback_created"] = False
            split_diagnostics["failure_reason"] = None
        else:
            split_diagnostics["fallback_created"] = False
            split_diagnostics["failure_reason"] = None

        return {
            "raw_questions": raw_questions,
            "split_count": len(raw_questions),
            "split_diagnostics": split_diagnostics,
            "warnings": warnings,
        }

    def _run_match(
        self,
        raw_questions: list[dict],
        normalized_blocks: list[dict],
        structure: dict | None = None,
        **_kw,
    ) -> dict:
        """Stage 4: match answers and explanations to questions."""
        result = match_answers(raw_questions, normalized_blocks, structure=structure)

        matched = result.get("matched", [])
        unmatched = result.get("unmatched", [])

        warnings: list[str] = []
        if unmatched:
            warnings.append(f"{len(unmatched)} questions have no matched answer")

        return {
            "matched": matched,
            "unmatched": unmatched,
            "matched_count": len(matched),
            "warnings": warnings,
        }

    def _run_normalize_schema(
        self,
        raw_questions: list[dict],
        matched: list[dict],
        source_file: str,
        source_type: str,
        subject: str | None = None,
        **_kw,
    ) -> dict:
        """Stage 5: normalize questions to standard schema."""
        source_info = {
            "file": source_file,
            "type": source_type,
            "subject": subject or "",
        }
        result = normalize_questions(raw_questions, matched, source_info)

        questions = result.get("questions", [])
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])

        invalid_count = sum(1 for q in questions if not q.get("is_valid", True))
        stage_warnings = list(warnings)
        if invalid_count:
            stage_warnings.append(f"{invalid_count} questions marked invalid")

        return {
            "questions": questions,
            "normalized_count": len(questions),
            "errors": list(errors),
            "warnings": stage_warnings,
        }

    def _run_batch_validation(self, questions: list[dict], **_kw) -> dict:
        """Stage 5.6: cross-question structural integrity validation (pure rules)."""
        result = validate_batch_structure(questions)

        warnings: list[str] = []
        stats = result["batch_validation_diagnostics"]["stats"]
        if stats["number_gap_count"] > 0:
            warnings.append(f"{stats['number_gap_count']} question number gaps detected")
        if stats["incomplete_option_count"] > 0:
            warnings.append(f"{stats['incomplete_option_count']} questions with incomplete options")
        if stats["missing_answer_count"] > 0:
            warnings.append(f"{stats['missing_answer_count']} questions missing answers")

        return {
            "questions": result["questions"],
            "batch_validation_diagnostics": result["batch_validation_diagnostics"],
            "warnings": warnings,
        }

    def _run_batch_dedup(self, questions: list[dict], **_kw) -> dict:
        """Stage 5.5: flag batch-internal duplicates to skip expensive repair."""
        from app.features.question_normalizer import dedup_batch

        result = dedup_batch(questions)

        warnings: list[str] = []
        if result["duplicate_count"] > 0:
            warnings.append(f"{result['duplicate_count']} batch-internal duplicates flagged")

        return {
            "questions": result["questions"],
            "batch_dedup_diagnostics": {
                "unique_count": result["unique_count"],
                "duplicate_count": result["duplicate_count"],
                "duplicate_indices": result["duplicate_indices"],
            },
            "warnings": warnings,
        }

    async def _run_repair(self, questions: list[dict], options: dict, **_kw) -> dict:
        """Stage 6: AI repair for low-confidence questions.

        Questions flagged as batch duplicates are skipped to save tokens.
        """
        # Separate batch duplicates from repair candidates
        to_repair: list[dict] = []
        duplicate_indices: set[int] = set()
        for i, q in enumerate(questions):
            if q.get("is_batch_duplicate"):
                duplicate_indices.add(i)
            else:
                to_repair.append(q)

        repair_config = {
            "confidence_threshold": options.get("confidence_threshold", 0.6),
            "daily_token_limit": options.get("daily_token_limit", 100000),
            "monthly_token_limit": options.get("monthly_token_limit", 2000000),
            "enabled": options.get("enable_ai_repair", True),
        }
        result = await repair_questions(to_repair, repair_config)

        repaired = result.get("repaired", [])
        unrepaired = result.get("unrepaired", [])
        skipped = result.get("skipped", [])
        stats = result.get("stats", {})

        # Build the combined question list for the review stage:
        #   repaired items use their "after" field
        #   unrepaired + skipped items use the original question by index
        #   batch duplicates are passed through unchanged
        repaired_combined: list[dict] = [None] * len(to_repair)  # type: ignore

        for r in repaired:
            idx = r["question_index"]
            repaired_combined[idx] = r["after"]

        for u in unrepaired:
            idx = u["question_index"]
            repaired_combined[idx] = to_repair[idx]

        for s in skipped:
            idx = s["question_index"]
            repaired_combined[idx] = to_repair[idx]

        repaired_combined = [q for q in repaired_combined if q is not None]

        # Merge back: non-duplicates (repaired) + duplicates (unchanged)
        combined: list[dict] = []
        repair_iter = iter(repaired_combined)
        for i, q in enumerate(questions):
            if i in duplicate_indices:
                combined.append(q)
            else:
                combined.append(next(repair_iter))

        warnings: list[str] = []
        if duplicate_indices:
            warnings.append(f"{len(duplicate_indices)} batch duplicates skipped repair")
        if unrepaired:
            warnings.append(f"{len(unrepaired)} questions unrepaired by AI")
        if skipped:
            warnings.append(f"{len(skipped)} questions skipped (above threshold)")

        return {
            "questions": combined,
            "repaired_count": len(repaired),
            "unrepaired_count": len(unrepaired),
            "skipped_count": len(skipped),
            "total_tokens": stats.get("total_tokens", 0),
            "warnings": warnings,
        }

    def _run_ai_validation(self, questions: list[dict], **_kw) -> dict:
        """Stage 6.2: validate AI repair results for anomalies."""
        result = validate_ai_results(questions)

        stats = result["stats"]
        warnings: list[str] = []
        if stats["errors"] > 0:
            warnings.append(f"{stats['errors']} questions have AI validation errors")
        if stats["warnings"] > 0:
            warnings.append(f"{stats['warnings']} questions have AI validation warnings")

        return {
            "questions": result["questions"],
            "ai_validation_diagnostics": stats,
            "warnings": warnings,
        }

    async def _run_similarity_match(
        self,
        questions: list[dict],
        db=None,
        options: dict | None = None,
        **_kw,
    ) -> dict:
        """Stage 6.5: suggest corrections from existing question bank."""
        opts = options or {}
        match_config = {
            "enabled": opts.get("enable_similarity_match", True),
            "similarity_threshold": opts.get("similarity_threshold", 0.85),
        }

        result = await match_similar_questions(questions, db=db, config=match_config)

        warnings: list[str] = []
        stats = result.get("stats", {})
        if stats.get("matched_count", 0) > 0:
            warnings.append(
                f"Found {stats['matched_count']} similar questions in bank "
                f"(avg ratio {stats['avg_similarity']:.2f})"
            )
        if result.get("skipped_reason"):
            warnings.append(f"Similarity match skipped: {result['skipped_reason']}")

        return {
            "questions": result["questions"],
            "similarity_match_diagnostics": {
                "stats": stats,
                "matches": result.get("matches", []),
                "skipped_reason": result.get("skipped_reason"),
            },
            "warnings": warnings,
        }

    async def _run_review(
        self,
        questions: list[dict],
        source_file: str,
        source_type: str,
        subject: str | None = None,
        db=None,
        **_kw,
    ) -> dict:
        """Stage 7: submit questions to review queue."""
        if db is None:
            return {
                "batch_id": "",
                "written": 0,
                "skipped": 0,
                "total": len(questions),
                "warnings": ["no db session provided, review stage skipped"],
            }

        from app.features.review_service import submit_to_review

        batch_meta = {
            "source_type": source_type,
            "source_file": source_file,
            "subject": subject or "",
        }
        result = await submit_to_review(db, questions, batch_meta)

        warnings: list[str] = []
        if result["skipped"] > 0:
            warnings.append(f"{result['skipped']} questions skipped in review")

        return {
            "batch_id": result["batch_id"],
            "written": result["written"],
            "skipped": result["skipped"],
            "total": result["total"],
            "items": result.get("items", []),
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # pipeline runner
    # ------------------------------------------------------------------

    async def run(
        self,
        file_content: bytes | None = None,
        source_type: str = "pdf",
        source_file: str = "",
        subject: str | None = None,
        options: dict | None = None,
        db=None,
        progress_callback=None,
        file_path: str | None = None,
    ) -> dict:
        """Execute all pipeline stages in sequence.

        Args:
            file_content: raw file bytes (PDF, txt, etc.) — fallback when no path
            file_path: tmp path on disk; preferred for PDF (mmap, no heap copy).
                P0-1 changed the entry point to drop bytes immediately and pass
                a path so the 100~400 MB payload doesn't survive 8+ stages.
            source_type: "pdf" | "txt"
            source_file: original filename
            subject: optional subject hint
            options: {"enable_ai_repair": bool, "confidence_threshold": float}
            db: optional AsyncSession for the review stage
            progress_callback: optional async callable(stages_dict, current_stage, errors)

        Returns:
            Pipeline result dict with status, stats, stages, and errors.
        """
        if file_path is None and file_content is None:
            raise ValueError("either file_path or file_content must be provided")
        opts = options or {}
        if options is not None:
            self.options = opts
        self._build_pipeline()

        started_at = datetime.now().isoformat()

        # Resolve import mode and strategy
        mode_str = opts.get("import_mode", "auto")
        try:
            import_mode = ImportMode(mode_str)
        except ValueError:
            import_mode = ImportMode.AUTO
        strategy = get_strategy(import_mode)

        # Load configurable watermark rules from DB
        watermark_patterns: list = []
        if db:
            try:
                from app.services.watermark_service import load_rules
                watermark_patterns = await load_rules(db)
            except Exception as e:
                logger.warning("Failed to load watermark rules from DB, using defaults: %s", e)
        if not watermark_patterns:
            from app.services.watermark_service import get_default_patterns
            watermark_patterns = get_default_patterns()

        # Accumulated data passed between stages
        data: dict[str, Any] = {
            "file_content": file_content,
            "file_path": file_path,
            "source_type": source_type,
            "source_file": source_file,
            "subject": subject,
            "options": opts,
            "db": db,
            "import_mode": import_mode,
            "strategy": strategy,
            "watermark_patterns": watermark_patterns,
            "raw_blocks": [],
            "normalized_blocks": [],
            "raw_questions": [],
            "matched": [],
            "unmatched": [],
            "questions": [],
        }

        pipeline_errors: list[str] = []
        overall_status = "completed"

        for name, stage in self.stages.items():
            if progress_callback:
                try:
                    await progress_callback(
                        {n: s.to_dict() for n, s in self.stages.items()},
                        name,
                        pipeline_errors,
                    )
                except Exception:
                    pass

            try:
                result = await stage.run_async(**data)
                if isinstance(result, dict):
                    if result.get("warnings"):
                        stage.warnings.extend(result["warnings"])
                    data.update(result)
                # P0-1: extract 完成后立即释放原始字节流，避免 100~400 MB 的
                # PDF/图片字节随后续 8+ 个阶段一起驻留内存。
                if name == "extract":
                    data.pop("file_content", None)
                    data.pop("file_path", None)
            except Exception:
                overall_status = "failed"
                pipeline_errors.append(f"stage '{name}' failed: {stage.error}")
                if name in ("extract", "normalize_text"):
                    # 失败路径同样释放
                    data.pop("file_content", None)
                    data.pop("file_path", None)
                    break
                logger.warning("Stage '%s' failed, continuing with partial results", name)

            if progress_callback:
                try:
                    await progress_callback(
                        {n: s.to_dict() for n, s in self.stages.items()},
                        name,
                        pipeline_errors,
                    )
                except Exception:
                    pass

        # Build stats from stage outputs
        stats = {
            "total": data.get("extracted", 0),
            "extracted": data.get("extracted", 0),
            "normalized": data.get("normalized_count", len(data.get("normalized_blocks", []))),
            "analyzed": data.get("split_count", len(data.get("raw_questions", []))),
            "split": data.get("split_count", 0),
            "matched": data.get("matched_count", 0),
            "schema_normalized": data.get("normalized_count", 0),
            "missing_options": sum(
                1
                for q in data.get("questions", [])
                if "missing_options" in q.get("errors", [])
            ),
            "repaired": data.get("repaired_count", 0),
            "to_review": data.get("written", 0),
            "failed": sum(1 for s in self.stages.values() if s.status == "failed"),
        }
        diagnostics = {
            "import_mode": data.get("import_mode", ImportMode.AUTO).value if hasattr(data.get("import_mode", ""), "value") else str(data.get("import_mode", "auto")),
            "exercise_regions": data.get("exercise_regions", []),
            "structure": data.get("structure", {}),
            "page_classifications": data.get("page_classifications", []),
            "ocr_correction": data.get("ocr_correction_diagnostics", {}),
            "split": data.get("split_diagnostics", {}),
            "batch_validation": data.get("batch_validation_diagnostics", {}),
            "schema_errors": data.get("errors", []),
            "ai_validation": data.get("ai_validation_diagnostics", {}),
            "similarity_match": data.get("similarity_match_diagnostics", {}),
        }

        finished_at = datetime.now().isoformat()

        return {
            "pipeline_id": self.pipeline_id,
            "status": overall_status,
            "batch_id": data.get("batch_id", ""),
            "stats": stats,
            "diagnostics": diagnostics,
            "stages": {name: s.to_dict() for name, s in self.stages.items()},
            "errors": pipeline_errors,
            "started_at": started_at,
            "finished_at": finished_at,
        }


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


async def run_import_pipeline(
    file_content: bytes | None = None,
    source_type: str = "pdf",
    source_file: str = "",
    subject: str | None = None,
    options: dict | None = None,
    db=None,
    progress_callback=None,
    pipeline_id: str | None = None,
    file_path: str | None = None,
) -> dict:
    """完整的导入流水线入口。

    串联 Stage 1 (文本清洗) → Stage 3 (题目切分) → Stage 4 (答案匹配)
    → Stage 5 (题目标准化) → Stage 6 (AI 修复, 可选) → Stage 7 (审核入库).

    Args:
        file_content: 文件原始字节（无 file_path 时使用）
        file_path: 已落盘的临时文件路径（PDF 优先走此分支以走 mmap）
        source_type: "pdf" | "txt"
        source_file: 原始文件名
        subject: 科目提示（可选）
        options: {"enable_ai_repair": bool, "confidence_threshold": float}
        db: 异步数据库会话（review 阶段需要）

    Returns:
        Pipeline result dict.
    """
    if file_path is None and file_content is None:
        raise ValueError("either file_path or file_content must be provided")

    if not pipeline_id:
        pipeline_id = f"pl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    # Auto-detect Wangdao preset from filename
    opts = dict(options) if options else {}
    if "enable_wangdao_preprocess" not in opts:
        lower_name = (source_file or "").lower()
        if "王道" in (source_file or "") or "wangdao" in lower_name or re.search(r"(?:^|[_\-\s])408(?:[_\-\s.]|$)", lower_name):
            opts["enable_wangdao_preprocess"] = True

    # EXAM mode disables wangdao preprocessing by default
    mode_str = opts.get("import_mode", "auto")
    try:
        import_mode = ImportMode(mode_str)
    except ValueError:
        import_mode = ImportMode.AUTO
    if import_mode == ImportMode.EXAM and "enable_wangdao_preprocess" not in (options or {}):
        opts["enable_wangdao_preprocess"] = False

    pipeline = ImportPipeline(options=opts)
    pipeline.pipeline_id = pipeline_id

    result = await pipeline.run(
        file_content=file_content,
        file_path=file_path,
        source_type=source_type,
        source_file=source_file,
        subject=subject,
        options=opts,
        db=db,
        progress_callback=progress_callback,
    )
    result["pipeline_id"] = pipeline_id
    return result


async def run_pipeline_background(
    pipeline_id: str,
    source_type: str,
    source_file: str,
    file_content: bytes | None = None,
    file_path: str | None = None,
    subject: str | None = None,
    options: dict | None = None,
    db=None,
) -> None:
    """后台运行流水线，结果写入 Redis + 内存。

    P0-1: file_path 优先（API 入口已落盘 tmp 文件），底层 fitz 走 mmap，
    避免 100~400 MB 的 PDF 字节驻留内存。
    """
    if file_path is None and file_content is None:
        raise ValueError("either file_path or file_content must be provided")

    started_at = datetime.now().isoformat()
    await _set_pipeline_store(pipeline_id, {
        "pipeline_id": pipeline_id,
        "status": "processing",
        "source_type": source_type,
        "current_stage": "extract",
        "stages": {},
        "stats": {},
        "errors": [],
        "started_at": started_at,
    })

    async def _progress(stages_dict, current_stage, errors):
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "processing",
            "source_type": source_type,
            "current_stage": current_stage,
            "stages": stages_dict,
            "stats": {},
            "errors": errors,
            "started_at": started_at,
        })

    try:
        result = await run_import_pipeline(
            file_content=file_content,
            file_path=file_path,
            source_type=source_type,
            source_file=source_file,
            subject=subject,
            options=options,
            db=db,
            progress_callback=_progress,
            pipeline_id=pipeline_id,
        )
        result["pipeline_id"] = pipeline_id
        await _set_pipeline_store(pipeline_id, result)
    except Exception as exc:
        logger.exception("Pipeline %s failed", pipeline_id)
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "failed",
            "source_type": source_type,
            "errors": [str(exc)],
            "started_at": _pipeline_store.get(pipeline_id, {}).get("started_at", ""),
            "finished_at": datetime.now().isoformat(),
        })


async def run_excel_pipeline_background(
    pipeline_id: str,
    file_content: bytes,
    source_file: str,
    import_excel_fn,
) -> None:
    """后台运行 Excel 导入，结果写入 Redis + 内存以支持状态查询。"""
    from app.core.database import async_session

    await _set_pipeline_store(pipeline_id, {
        "pipeline_id": pipeline_id,
        "status": "parsing",
        "source_type": "excel",
        "stages": {"extract": {"status": "running"}},
        "stats": {},
        "errors": [],
        "started_at": datetime.now().isoformat(),
    })

    try:
        async with async_session() as db:
            batch_id, total = await import_excel_fn(db, file_content, source_file)
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "completed",
            "source_type": "excel",
            "batch_id": batch_id,
            "stats": {"total": total, "to_review": total},
            "stages": {"extract": {"status": "completed"}},
            "errors": [],
            "started_at": _pipeline_store[pipeline_id]["started_at"],
            "finished_at": datetime.now().isoformat(),
        })
    except Exception as exc:
        logger.exception("Excel pipeline %s failed", pipeline_id)
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "failed",
            "source_type": "excel",
            "errors": [str(exc)],
            "started_at": _pipeline_store.get(pipeline_id, {}).get("started_at", ""),
            "finished_at": datetime.now().isoformat(),
        })


async def get_pipeline_status(pipeline_id: str) -> dict | None:
    """查询流水线状态（Redis + 内存 fallback）。

    P0-3: 主 store 已瘦身，本函数把 diagnostics 从独立 KV 合并回去，
    对外返回与改造前一致的完整视图。
    """
    data = await _get_pipeline_store(pipeline_id)
    if data is None:
        return None
    # 防御性拷贝：_get_pipeline_store 返回的是 _pipeline_store 内引用，
    # 任何后续字段写入都会直接污染主 store（白名单契约破坏）。
    data = dict(data)
    diagnostics = await _get_pipeline_diagnostics(pipeline_id)
    if diagnostics is not None:
        data["diagnostics"] = diagnostics
    if pipeline_id in _ocr_progress:
        data["ocr_progress"] = _ocr_progress[pipeline_id]
    return data
