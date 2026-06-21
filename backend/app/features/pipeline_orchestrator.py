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
from app.features.ocr_correction_common import (
    TIER_HIGH_THRESHOLD,
    _detect_noise, _detect_structure_abnormal, _filter_sensitive, _should_correct,
)
from app.features.page_classifier import classify_pages, filter_blocks_by_classification
from app.features.question_normalizer import normalize_questions
from app.features.question_splitter import split_questions
from app.features.similarity_matcher import match_similar_questions
from app.features.structure_analyzer import analyze_structure
from app.features.text_normalizer import ImportTextNormalizer
from app.utils.sentry_utils import capture_exception, set_tag, start_span

logger = logging.getLogger(__name__)


def _is_book_import_mode(import_mode) -> bool:
    if isinstance(import_mode, ImportMode):
        return import_mode == ImportMode.BOOK
    return str(import_mode or "").lower() == ImportMode.BOOK.value


_BOOK_PDF_PROSE_MARKER_RE = re.compile(
    r"定义|定理|知识点|证明如下|证毕|解法|例题|例如|如下|因此可得|由此可知|综上|性质|推论|注意|本节|本章|算法|图\s*\d|表\s*\d"
)
_BOOK_PDF_QUESTION_SIGNAL_RE = re.compile(
    r"下列|以下|正确|错误|的是|哪|选择|计算|判断|已知|设|若|试述|简述|回答|为什么|(?:^|[，。；;：:\s])(?:求|问)[：:\s]|\?|？"
)
_BOOK_PDF_SENTENCE_END_RE = re.compile(r"[。；;！!？?]")


def _looks_like_book_pdf_prose_candidate(question: dict) -> bool:
    text = str(question.get("raw_question_text") or "").strip()
    if len(text) < 90:
        return False
    if question.get("has_options") or question.get("option_lines"):
        return False
    marker_count = len(_BOOK_PDF_PROSE_MARKER_RE.findall(text))
    if marker_count < 2:
        return False
    sentence_count = len(_BOOK_PDF_SENTENCE_END_RE.findall(text))
    if sentence_count < 2:
        return False
    if _BOOK_PDF_QUESTION_SIGNAL_RE.search(text):
        return len(text) > 360 and marker_count >= 4 and sentence_count >= 4
    return True


def _count_risk_flags(questions: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for question in questions:
        for flag in question.get("risk_flags") or []:
            counts[str(flag)] = counts.get(str(flag), 0) + 1
    return counts


def _build_raw_questions_preview(raw_questions: list[dict]) -> list[dict]:
    preview: list[dict] = []
    for question in raw_questions[:20]:
        item = dict(question)
        raw_text = item.get("raw_question_text")
        if isinstance(raw_text, str) and len(raw_text) > 300:
            item["raw_question_text"] = raw_text[:300]
            item["raw_question_text_truncated"] = True
        preview.append(item)
    return preview


def _blank_option_group_summary(groups: Any) -> list[dict]:
    if not isinstance(groups, list):
        return []
    summary = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        options = group.get("options") or {}
        if isinstance(options, dict):
            option_keys = sorted(str(key).upper() for key in options.keys() if str(key).strip())
            first_a_preview = str(options.get("A") or options.get("a") or "")[:40]
        elif isinstance(options, list):
            option_keys = sorted(
                str(option.get("key") or "").upper()
                for option in options
                if isinstance(option, dict) and str(option.get("key") or "").strip()
            )
            first_a_preview = ""
            for option in options:
                if isinstance(option, dict) and str(option.get("key") or "").upper() == "A":
                    first_a_preview = str(option.get("text") or "")[:40]
                    break
        else:
            option_keys = []
            first_a_preview = ""
        summary.append({
            "id": group.get("id") or group.get("blank_id") or group.get("label") or index + 1,
            "option_keys": option_keys,
            "has_a": "A" in option_keys,
            "first_a_preview": first_a_preview,
        })
    return summary


def _log_multi_blank_stage(stage: str, questions: list[dict], **context: Any) -> None:
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        groups = question.get("blank_option_groups")
        if groups is None:
            parsed_content = question.get("parsed_content")
            if isinstance(parsed_content, dict):
                groups = parsed_content.get("blank_option_groups")
        summary = _blank_option_group_summary(groups)
        if question.get("question_type") != "multi_blank_choice" and not summary:
            continue
        logger.warning(
            "multi_blank_choice pipeline stage",
            extra={
                "stage": stage,
                "question_index": index,
                "question_type": question.get("question_type"),
                "stem_preview": str(question.get("stem") or question.get("raw_question_text") or "")[:80],
                "blank_option_group_count": len(summary),
                "blank_option_groups": summary,
                **context,
            },
        )


# ---------------------------------------------------------------------------
# in-memory pipeline state store
# ---------------------------------------------------------------------------

_pipeline_store: dict[str, dict] = {}
_pipeline_diagnostics_store: dict[str, dict] = {}
_ocr_progress: dict[str, str] = {}  # pipeline_id -> "32/312 pages"

_MAX_STORE_SIZE = 500  # keep at most N pipelines in memory
_MAX_DIAGNOSTICS_SIZE = 100  # keep at most N diagnostics snapshots in memory
_PIPELINE_REDIS_PREFIX = "import:pipeline"
_PIPELINE_DIAGNOSTICS_REDIS_PREFIX = "import:pipeline:diagnostics"
_PIPELINE_STATUS_TTL = 86400  # 24h
# P3-2: per-stage checkpoint (lightweight, only completed stage names + small metadata)
# Key: pipeline_id, Value: dict with completed_stages, current_stage, diagnostics, etc.
_CHECKPOINT_REDIS_PREFIX = "import:pipeline:stage_ckpt"
_CHECKPOINT_TTL = 86400  # 24h — same as pipeline status

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


def _prune_diagnostics_store() -> None:
    """Prune diagnostics store independently from main store.

    Diagnostics entries lack started_at timestamps; evict oldest by
    insertion order which is a reasonable heuristic.
    """
    if len(_pipeline_diagnostics_store) > _MAX_DIAGNOSTICS_SIZE:
        excess = len(_pipeline_diagnostics_store) - _MAX_DIAGNOSTICS_SIZE
        for key in list(_pipeline_diagnostics_store.keys())[:excess]:
            _pipeline_diagnostics_store.pop(key, None)


# P3-2: per-stage checkpoint store — lightweight, only stage names + small metadata
_pipeline_stage_checkpoints: dict[str, dict] = {}
_MAX_STAGE_CKPT_SIZE = 200


def _prune_stage_checkpoints() -> None:
    """Evict oldest stage checkpoints by insertion order."""
    if len(_pipeline_stage_checkpoints) > _MAX_STAGE_CKPT_SIZE:
        excess = len(_pipeline_stage_checkpoints) - _MAX_STAGE_CKPT_SIZE
        for key in list(_pipeline_stage_checkpoints.keys())[:excess]:
            _pipeline_stage_checkpoints.pop(key, None)


async def _write_stage_checkpoint(
    pipeline_id: str,
    *,
    completed_stages: list[str],
    current_stage: str,
    stage_statuses: dict,
    failed_stage: str | None = None,
    error: str | None = None,
    source_type: str | None = None,
    source_file: str | None = None,
    subject: str | None = None,
    options: dict | None = None,
) -> None:
    """Write lightweight per-stage checkpoint after each stage completes/fails.

    Only small metadata is stored — no large stage outputs. The checkpoint
    serves to track progress and enable resume (which re-derives large data
    from the source file).
    """
    ckpt: dict = {
        "completed_stages": completed_stages,
        "current_stage": current_stage,
        "stage_statuses": stage_statuses,
        "failed_stage": failed_stage,
        "error": error,
        "source_type": source_type,
        "source_file": source_file,
        "subject": subject,
        "options": options,
        "updated_at": datetime.now().isoformat(),
    }
    # Strip large fields to keep checkpoint lightweight
    if "stage_statuses" in ckpt and ckpt["stage_statuses"]:
        ckpt["stage_statuses"] = {
            k: {"status": v.get("status"), "duration_ms": v.get("duration_ms"),
                "error": v.get("error")}
            for k, v in ckpt["stage_statuses"].items()
            if isinstance(v, dict)
        }
    _pipeline_stage_checkpoints[pipeline_id] = ckpt
    _prune_stage_checkpoints()
    try:
        from app.core.cache import cache
        await cache.set(
            f"{_CHECKPOINT_REDIS_PREFIX}:{pipeline_id}",
            ckpt,
            ttl=_CHECKPOINT_TTL,
        )
    except Exception:
        pass


async def _get_stage_checkpoint(pipeline_id: str) -> dict | None:
    """Read per-stage checkpoint from memory or Redis. Returns None if missing."""
    if pipeline_id in _pipeline_stage_checkpoints:
        return _pipeline_stage_checkpoints[pipeline_id]
    try:
        from app.core.cache import cache
        data = await cache.get(f"{_CHECKPOINT_REDIS_PREFIX}:{pipeline_id}")
        if data:
            _pipeline_stage_checkpoints[pipeline_id] = data
            return data
    except Exception:
        pass
    return None


async def _clear_stage_checkpoint(pipeline_id: str) -> None:
    """Remove checkpoint — called when pipeline completes successfully."""
    _pipeline_stage_checkpoints.pop(pipeline_id, None)
    try:
        from app.core.cache import cache
        await cache.delete(f"{_CHECKPOINT_REDIS_PREFIX}:{pipeline_id}")
    except Exception:
        pass


def _slim_ocr_diagnostics(diag: dict) -> dict:
    """Truncate large arrays in OCR diagnostics to bound memory."""
    if not diag:
        return diag
    corrections = diag.get("corrections", [])
    if len(corrections) > 50:
        diag = {**diag, "corrections": corrections[:50],
                "corrections_truncated": len(corrections) - 50}
    return diag


def _summarize_ocr_diffs(corrections: list[dict]) -> dict:
    """Summarize OCR correction diffs for diagnostics stage_diffs."""
    corrected = [c for c in corrections if c.get("corrected")]
    rejected = [c for c in corrections if c.get("reason", "").startswith("safety_rejected")]
    all_safety = [c["safety"] for c in corrections if c.get("safety")]
    return {
        "total_corrected": len(corrected),
        "safety_rejected": len(rejected),
        "models_used": list({c.get("model_used", "unknown") for c in corrected}),
        "risk_flags": list({f for s in all_safety for f in s.get("risk_flags", [])}),
        "details": corrected[:30],  # cap at 30 to bound diagnostics
    }


def _build_repair_diffs(
    repaired: list[dict], unrepaired: list[dict], skipped: list[dict],
) -> list[dict]:
    """Build per-question repair diff records for diagnostics stage_diffs."""
    diffs: list[dict] = []
    for r in repaired:
        before = r.get("before") or {}
        after = r.get("after") or {}
        safety = r.get("safety") or {}
        diffs.append({
            "question_index": r.get("question_index"),
            "actions": r.get("repair_actions", []),
            "confidence": r.get("confidence"),
            "tokens_used": r.get("token_used", 0),
            "before_stem": str(before.get("stem", ""))[:200],
            "after_stem": str(after.get("stem", ""))[:200],
            "options_changed": (
                str(before.get("options", "")) != str(after.get("options", ""))
            ),
            "answer_changed": (
                str(before.get("answer", "")) != str(after.get("answer", ""))
            ),
            "safety": safety,
        })
    for u in unrepaired:
        diffs.append({
            "question_index": u.get("question_index"),
            "actions": [],
            "reason": u.get("reason", "unrepaired"),
        })
    for s in skipped:
        diffs.append({
            "question_index": s.get("question_index"),
            "actions": [],
            "reason": s.get("reason", "skipped"),
        })
    return diffs


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
    _prune_diagnostics_store()
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


def _render_page_images(
    *,
    file_content: bytes | None = None,
    file_path: str | None = None,
    source_type: str = "pdf",
    max_dimension: int = 2048,
) -> dict[int, bytes] | None:
    """Render PDF pages to PNG images keyed by page number (1-based).

    Only renders when source is PDF and content/path is available.
    Images are limited to *max_dimension* on the longest side.
    Returns None for non-PDF sources or when rendering fails.
    """
    if source_type != "pdf":
        return None

    pdf_source = file_path or file_content
    if pdf_source is None:
        return None

    try:
        import fitz

        doc = fitz.open(pdf_source) if isinstance(pdf_source, str) else fitz.open(stream=pdf_source, filetype="pdf")
        page_images: dict[int, bytes] = {}
        for i in range(len(doc)):
            page = doc[i]
            dpi = 150
            pix = page.get_pixmap(dpi=dpi)
            png = pix.tobytes("png")
            # Resize if exceeds max dimension
            if max(pix.width, pix.height) > max_dimension:
                scale = max_dimension / max(pix.width, pix.height)
                pix = page.get_pixmap(dpi=int(dpi * scale))
                png = pix.tobytes("png")
            page_images[i + 1] = png
        doc.close()
        return page_images
    except Exception:
        return None


def _render_page_image_refs(
    file_path: str | None,
    temp_dir: str,
    source_type: str = "pdf",
    max_dimension: int = 2048,
) -> dict[int, str] | None:
    """P2-2: 渲染 PDF 页为 PNG 并写入临时文件，返回 {page_num: filepath}。

    与 _render_page_images 功能相同但输出为文件路径而非 bytes。
    供 math_detect stage 用于公式截图裁剪。
    """
    if source_type != "pdf" or not file_path:
        return None

    try:
        import fitz

        doc = fitz.open(file_path, filetype="pdf")
        refs: dict[int, str] = {}
        for i in range(len(doc)):
            page = doc[i]
            dpi = 150
            pix = page.get_pixmap(dpi=dpi)
            if max(pix.width, pix.height) > max_dimension:
                scale = max_dimension / max(pix.width, pix.height)
                pix = page.get_pixmap(dpi=int(dpi * scale))
            png_path = os.path.join(temp_dir, f"page_{i + 1}.png")
            pix.save(png_path)
            refs[i + 1] = png_path
        doc.close()
        return refs
    except Exception as e:
        logger.warning("page image refs render failed: %s", e)
        return None


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
    from app.services.ocr_service import ocr_pages, ocr_pages_with_boxes

    profile = get_ocr_profile()
    max_pages = settings.MAX_OCR_PAGES
    timeout = profile.timeout_seconds
    batch_size = profile.max_workers

    doc = _open_pdf_doc(content_or_path)
    total_pages = len(doc)

    # Sentry OCR monitoring
    set_tag("ocr.engine", "PaddleOCR")
    ocr_source = str(content_or_path) if isinstance(content_or_path, (str, os.PathLike)) else pipeline_id
    set_tag("ocr.source", ocr_source[:200])

    # Page range: convert 1-based user params to 0-based indices
    start_idx = max(0, (page_start or 1) - 1)
    end_idx = min(total_pages, page_end or total_pages)
    pages_in_range = end_idx - start_idx
    pages_to_process = min(pages_in_range, max_pages) if max_pages > 0 else pages_in_range

    blocks: list[dict] = []
    page_dimensions: dict[int, tuple[int, int]] = {}
    ocr_text_fallback_unavailable_pages: set[int] = set()
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
            batch_image_map = {idx: png for idx, png in batch_images}
            failed_images = [
                (idx, batch_image_map[idx])
                for idx, result in results.items()
                if result.failed and idx in batch_image_map
            ]
            try:
                fallback_results = ocr_pages(failed_images) if failed_images else {}
            except RuntimeError as exc:
                logger.warning("OCR text fallback unavailable: %s", exc)
                fallback_results = {}
                ocr_text_fallback_unavailable_pages.update(idx for idx, _ in failed_images)

            del batch_images
            gc.collect()

            for page_idx in sorted(results.keys()):
                result = results[page_idx]
                pw, ph = page_dimensions[page_idx]
                if result.failed:
                    text = fallback_results.get(page_idx, "")
                    if text.strip():
                        blocks.append({
                            "page": page_idx,
                            "page_index": page_idx,
                            "block_index": len(blocks),
                            "text": text,
                            "boxes": [],
                            "page_width": pw,
                            "page_height": ph,
                            "source": "ocr_text_fallback",
                            "has_boxes": False,
                            "_ocr_boxes_failed": True,
                        })
                    else:
                        ocr_text_fallback_unavailable_pages.add(page_idx)
                    continue

                text = result.text
                if text.strip():
                    boxes = result.boxes or []
                    blocks.append({
                        "page": page_idx,
                        "page_index": page_idx,
                        "block_index": len(blocks),
                        "text": text,
                        "boxes": boxes,
                        "page_width": pw,
                        "page_height": ph,
                        "source": "ocr_boxes",
                        "has_boxes": bool(boxes),
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

    if ocr_text_fallback_unavailable_pages and blocks:
        pages = sorted(ocr_text_fallback_unavailable_pages)
        blocks[0]["_ocr_text_fallback_unavailable_pages"] = pages
        blocks[0]["_ocr_runtime_failed_pages"] = pages

    if pipeline_id:
        _ocr_progress.pop(pipeline_id, None)

    # Sentry OCR summary
    ocr_duration = time.monotonic() - start_time
    set_tag("ocr.pages_total", pages_to_process)
    set_tag("ocr.pages_processed", len(set(b.get("page") for b in blocks)))
    set_tag("ocr.blocks", len(blocks))
    set_tag("ocr.duration_ms", int(ocr_duration * 1000))
    if timed_out:
        set_tag("ocr.timed_out", True)
    failed_count = len(ocr_text_fallback_unavailable_pages)
    if failed_count:
        set_tag("ocr.failed_pages", failed_count)

    return blocks


def _extract_page_texts_from_blocks(blocks: list[dict]) -> dict[int, str]:
    """Extract per-page concatenated text from full OCR blocks.

    Used by exercise detection to reuse the single full OCR pass instead of
    running a separate lightweight OCR scan.
    """
    page_texts: dict[int, str] = {}
    for block in blocks:
        page = block.get("page", 0)
        text = block.get("text", "")
        if not text.strip():
            continue
        if page not in page_texts:
            page_texts[page] = text
        else:
            page_texts[page] += "\n" + text
    return page_texts


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
# P2-2 chunk planning helpers
# ---------------------------------------------------------------------------


_DEFAULT_CHUNK_SIZE = 40


def _resolve_chunk_size() -> int:
    """Read chunk size from env, default 40. 0 disables chunking."""
    raw = os.environ.get("IMPORT_PIPELINE_CHUNK_SIZE")
    if raw is None:
        return _DEFAULT_CHUNK_SIZE
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_CHUNK_SIZE


_DEFAULT_CHUNK_OVERLAP = 3


def _resolve_chunk_overlap() -> int:
    """Read chunk-overlap pages from env, default 3. 0 disables overlap."""
    raw = os.environ.get("IMPORT_PIPELINE_CHUNK_OVERLAP")
    if raw is None:
        return _DEFAULT_CHUNK_OVERLAP
    try:
        val = int(raw)
        return max(0, val)
    except ValueError:
        return _DEFAULT_CHUNK_OVERLAP


def _split_into_chunks(total_pages: int, chunk_size: int) -> list[tuple[int, int]]:
    """Split page count into 1-based closed intervals [(start, end), ...].

    Example: total_pages=100, chunk_size=40 → [(1,40), (41,80), (81,100)].
    """
    if total_pages <= 0 or chunk_size <= 0:
        return []
    ranges: list[tuple[int, int]] = []
    start = 1
    while start <= total_pages:
        end = min(start + chunk_size - 1, total_pages)
        ranges.append((start, end))
        start = end + 1
    return ranges


def _read_pdf_page_count(source: bytes | str | None) -> int:
    """Open the PDF just long enough to read len(doc); close immediately."""
    if source is None:
        return 0
    doc = _open_pdf_doc(source)
    try:
        return len(doc)
    finally:
        doc.close()


def _compute_overlap_hash(raw_question: dict) -> str | None:
    """P1-3: 把 split 阶段的原始题目 dict 折算成稳定的 overlap-dedup key。

    复用 ``QuestionNormalizer`` 的口径（去除空白/控制字符 + 选项排序），
    保证同一物理题在两个 chunk 里折出同一个 hash，OCR 把 ``1`` 误识成 ``I``
    或截留前缀页码不再影响判断。

    与 ``review_service.build_question_hash`` 的差别：split 阶段没有匹配到
    答案，因此 answer 端始终为空——这只影响 hash 值本身、不影响稳定性，
    且 chunk 间 overlap 的同一物理题答案侧也都为空，仍然命中。

    返回 None 表示题干和选项都为空（异常 OCR），调用方按"无 hash"处理，
    保留 P2-3 兜底（page_start>logical_end 时仍按 number 兜底丢弃）。
    """
    from app.features.question_normalizer import _extract_stem
    from app.features.question_pipeline import QuestionNormalizer

    raw_text = raw_question.get("raw_question_text") or ""
    option_lines = raw_question.get("option_lines") or {}

    stem = _extract_stem(str(raw_text), option_lines)
    if not stem and not option_lines:
        return None

    normalizer = QuestionNormalizer()
    return normalizer.build_question_hash(stem, option_lines, None) or None


def _serialize_watermark_patterns(patterns: list) -> list[dict]:
    """P0-3: 把已编译的 ``re.Pattern`` 列表转成 JSON 可序列化的快照。

    每条记录保留 pattern 源字符串与 flags，足以在 resume 时重建出
    与首次导入字节级一致的 ``re.Pattern``。非 Pattern 对象保守地
    跳过——load_rules 偶发 fallback 路径理论上不会混入异类。
    """
    out: list[dict] = []
    for pat in patterns or []:
        try:
            out.append({"pattern": pat.pattern, "flags": int(pat.flags)})
        except AttributeError:
            # 兜底：dict 形式直接收，字符串当 pattern
            if isinstance(pat, dict) and "pattern" in pat:
                out.append({"pattern": pat["pattern"], "flags": int(pat.get("flags", 0))})
            elif isinstance(pat, str):
                out.append({"pattern": pat, "flags": 0})
    return out


def _deserialize_watermark_patterns(snapshot: list | dict | None) -> list:
    """P0-3: 把 watermark_snapshot JSON 反序列化回 ``re.Pattern`` 列表。

    snapshot 损坏 / 元素无法编译时跳过该条而不抛错——首次导入时已通过
    ``_validate_pattern`` 校验，这里属于纵深防御。
    """
    if not snapshot:
        return []
    items = snapshot if isinstance(snapshot, list) else [snapshot]
    compiled: list = []
    for item in items:
        if not isinstance(item, dict):
            continue
        src = item.get("pattern")
        if not isinstance(src, str):
            continue
        flags = item.get("flags") or 0
        try:
            compiled.append(re.compile(src, int(flags)))
        except re.error:
            continue
    return compiled


def _derive_session_factory(db):
    """P0-3: 从一个已有的 ``AsyncSession`` 推导出 sessionmaker，便于 chunk
    循环里开"独立 session、独立事务"的子上下文。

    生产路径：``imports.py`` 用全局 ``async_session()`` 开 session 后传入，
    ``db.bind`` 即全局 engine，等价于直接拿全局工厂。
    测试路径：测试用 tmp_path SQLite 建独立 engine + sessionmaker，传入的
    ``db`` 绑到该 engine，从这里派生出的工厂指向同一个 DB，避免污染全局。

    任何异常 / db 为 None 时回退到全局 ``async_session``，保留向后兼容。
    """
    from app.core.database import async_session as _global_async_session

    if db is None:
        return _global_async_session
    try:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        bind = getattr(db, "bind", None)
        if bind is None:
            return _global_async_session
        return async_sessionmaker(bind, expire_on_commit=False, class_=AsyncSession)
    except Exception:
        logger.debug("derive session factory failed; using global async_session", exc_info=True)
        return _global_async_session


def _build_stats(data: dict, stages: dict) -> dict:
    """Aggregate per-stage outputs into the legacy stats dict."""
    return {
        "total": data.get("extracted", 0),
        "extracted": data.get("extracted", 0),
        "normalized": data.get(
            "normalized_count",
            data.get("normalized_block_count", 0),
        ),
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
        "failed": sum(1 for s in stages.values() if s.status == "failed"),
    }


def _build_diagnostics(data: dict) -> dict:
    mode = data.get("import_mode", ImportMode.AUTO)
    raw = {
        "import_mode": mode.value if hasattr(mode, "value") else str(mode),
        "exercise_regions": data.get("exercise_regions", []),
        "exercise_regions_missing": bool(data.get("exercise_regions_missing")),
        "structure": data.get("structure", {}),
        "page_classifications": data.get("page_classifications", []),
        "ocr_boxes_failed_pages": data.get("ocr_boxes_failed_pages", []),
        "ocr_text_fallback_pages": data.get("ocr_text_fallback_pages", []),
        "ocr_text_fallback_unavailable_pages": data.get("ocr_text_fallback_unavailable_pages", []),
        "ocr_runtime_failed_pages": data.get("ocr_runtime_failed_pages", []),
        "ocr_correction": _slim_ocr_diagnostics(data.get("ocr_correction_diagnostics", {})),
        "split": data.get("split_diagnostics", {}),
        "risk_flag_counts": data.get("risk_flag_counts", {}),
        "batch_validation": data.get("batch_validation_diagnostics", {}),
        "schema_errors": data.get("errors", []),
        "ai_validation": data.get("ai_validation_diagnostics", {}),
        "similarity_match": data.get("similarity_match_diagnostics", {}),
        "stage_diffs": {
            "ocr_correction": _summarize_ocr_diffs(
                data.get("ocr_correction_diagnostics", {}).get("corrections", [])
            ),
            "ai_repair": data.get("repair_diffs", []),
            "ai_repair_stats": data.get("repair_stats", {}),
        },
        # P3-7: shared token budget snapshot for monitoring
        "token_usage": _get_token_usage_snapshot_safe(),
    }
    return _slim_diagnostics_arrays(raw)


def _get_token_usage_snapshot_safe() -> dict:
    """Safe wrapper around token_budget.get_token_usage_snapshot()."""
    try:
        from app.features.token_budget import get_token_usage_snapshot
        return get_token_usage_snapshot()
    except Exception:
        return {"daily": 0, "monthly": 0}


def _slim_diagnostics_arrays(diagnostics: dict) -> dict:
    """P0-3: 截断 diagnostics 中的大数组，限制每条诊断记录的内存占用。

    对于 400 页 PDF 的单 pass 路径，page_classifications、exercise_regions
    等数组可达数百条。本函数为所有数组类字段统一设上限，超出的部分截断并注
    记 truncated 计数。
    """
    if not diagnostics:
        return diagnostics

    array_caps = {
        "page_classifications": 50,
        "exercise_regions": 100,
        "ocr_boxes_failed_pages": 50,
        "ocr_text_fallback_pages": 50,
        "ocr_text_fallback_unavailable_pages": 50,
        "ocr_runtime_failed_pages": 50,
    }

    for key, cap in array_caps.items():
        arr = diagnostics.get(key)
        if isinstance(arr, list) and len(arr) > cap:
            diagnostics = {
                **diagnostics,
                key: arr[:cap],
                f"{key}_truncated": len(arr) - cap,
            }

    # structure 内的列表字段也截断
    structure = diagnostics.get("structure")
    if isinstance(structure, dict):
        slim_structure: dict[str, Any] = {}
        for skey in ("question_pages", "answer_pages", "explanation_pages",
                       "content_pages", "section_markers"):
            val = structure.get(skey)
            if isinstance(val, list) and len(val) > 50:
                slim_structure[skey] = val[:50]
                slim_structure[f"{skey}_truncated"] = len(val) - 50
            elif val is not None:
                slim_structure[skey] = val
        # 保留其他非列表字段
        for skey, sval in structure.items():
            if skey not in slim_structure:
                slim_structure[skey] = sval
        diagnostics = {**diagnostics, "structure": slim_structure}

    # split 内的 layout_filter.region_signals 截断
    split = diagnostics.get("split")
    if isinstance(split, dict):
        lf = split.get("layout_filter")
        if isinstance(lf, dict):
            signals = lf.get("region_signals")
            if isinstance(signals, list) and len(signals) > 50:
                split = {
                    **split,
                    "layout_filter": {
                        **lf,
                        "region_signals": signals[:50],
                        "region_signals_truncated": len(signals) - 50,
                    },
                }
                diagnostics = {**diagnostics, "split": split}

    return diagnostics


def _slim_chunk_diagnostics(diagnostics: dict) -> dict:
    split = diagnostics.get("split") or {}
    slim_split: dict[str, Any] = {}
    for key in ("layout_filter", "visual_boundary", "failure_reason"):
        if key in split:
            slim_split[key] = split[key]
    return {
        "split": slim_split,
        "risk_flag_counts": diagnostics.get("risk_flag_counts") or {},
    }


def _merge_risk_flag_counts(chunks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in chunks:
        chunk_counts = (chunk.get("diagnostics") or {}).get("risk_flag_counts") or {}
        for flag, count in chunk_counts.items():
            counts[str(flag)] = counts.get(str(flag), 0) + int(count or 0)
    return counts


def _visual_boundary_preview(blocks: list[dict], boundary: dict) -> str:
    block_index = boundary.get("block_index")
    line_index = boundary.get("line_index")
    if not isinstance(block_index, int) or not isinstance(line_index, int):
        return ""
    for block in blocks:
        if block.get("block_index", 0) != block_index:
            continue
        text = block.get("normalized_text") or block.get("text") or ""
        lines = str(text).split("\n")
        if 0 <= line_index < len(lines):
            return "".join(line.strip() for line in lines[line_index:line_index + 2])[:80]
    return ""


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

        # Stage → 业务阶段映射（用于 Sentry 导题链路埋点）
        _STAGE_BUSINESS_MAP = {
            "extract": "ocr",
            "normalize_text": "parse",
            "ocr_correction": "ai_correct",
            "analyze_structure": "parse",
            "classify_pages": "parse",
            "split": "parse",
            "match": "parse",
            "normalize_schema": "parse",
            "batch_validation": "parse",
            "batch_dedup": "parse",
            "repair": "ai_correct",
            "ai_validation": "parse",
            "similarity_match": "parse",
            "review": "save",
        }
        set_tag("stage", _STAGE_BUSINESS_MAP.get(self.name, "unknown"))
        set_tag("pipeline.stage", self.name)

        with start_span(op=f"pipeline.{self.name}", description=f"stage={self.name}"):
            try:
                if asyncio.iscoroutinefunction(self.fn):
                    result = await self.fn(**kwargs)
                else:
                    result = await asyncio.to_thread(self.fn, **kwargs)
                self.status = "completed"
                self.duration_ms = round((time.monotonic() - start) * 1000)
                set_tag("pipeline.stage_status", "completed")
                set_tag("pipeline.stage_duration_ms", self.duration_ms)
                return result
            except Exception as exc:
                self.status = "failed"
                self.error = str(exc)
                self.duration_ms = round((time.monotonic() - start) * 1000)
                set_tag("pipeline.stage_status", "failed")
                capture_exception(
                    exc,
                    tags={"pipeline.stage": self.name, "stage": _STAGE_BUSINESS_MAP.get(self.name, "unknown")},
                )
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
        # P0-1 / P0-2: 透传到 ckpt.create_pipeline_record，落到
        # import_pipelines.created_by / source_sha256，让 resume endpoint 能
        # 校验创建者身份与原始 PDF 字节摘要。仅 chunked PDF 路径设值，单 pass
        # 路径不创建 pipeline 行因此无需透传。
        self.created_by: str | None = None
        self.source_sha256: str | None = None

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
        if self.options.get("enable_math_detect", True):
            stage_specs.append(("math_detect", self._run_math_detect))
        if self.options.get("enable_table_detect", True):
            stage_specs.append(("table_detect", self._run_table_detect))
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

        Single OCR pass: _ocr_scanned_pdf runs once at full quality. Exercise
        detection (when enabled) reuses the same OCR text — no separate
        lightweight scan (Task 2: 消除双 OCR).

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
            # P1-2: 仅当 exercise_regions 检测真正跑了但返回为空时设为 True；
            # 用户指定 page_start/page_end、exam 模式、OCR 未启用等场景下保持
            # False，避免误打 no_exercise_regions 风险标。
            exercise_regions_missing = False

            # Scanned PDF detection: if PyMuPDF extracted very little text,
            # the PDF likely contains only images → trigger OCR fallback.
            #
            # Single OCR pass: _ocr_scanned_pdf at normal DPI with full
            # PaddleOCR box-level output. Exercise detection reuses the
            # same OCR text — no separate lightweight pass (Task 2).
            total_text = sum(len(b.get("text", "")) for b in raw_blocks)
            if total_text < 100:
                from app.core.config import settings

                if settings.OCR_ENABLED:
                    logger.info(
                        "PDF text only %d chars, attempting PaddleOCR fallback", total_text,
                    )
                    try:
                        import_mode_str = opts.get("import_mode", "auto")
                        user_specified_range = opts.get("page_start") or opts.get("page_end")

                        # ── Single OCR pass (the ONLY PaddleOCR call) ──
                        ocr_page_start = opts.get("page_start") or 1
                        ocr_page_end = opts.get("page_end")
                        ocr_blocks = _ocr_scanned_pdf(
                            pdf_source,
                            pipeline_id=self.pipeline_id,
                            page_start=ocr_page_start,
                            page_end=ocr_page_end,
                        )

                        if ocr_blocks:
                            raw_blocks = ocr_blocks

                            # Exercise detection reuses the full OCR text —
                            # no separate lightweight OCR pass (Task 2)
                            if (settings.EXERCISE_DETECTION_ENABLED
                                    and import_mode_str != "exam"
                                    and not user_specified_range):
                                from app.features.exercise_region_detector import (
                                    detect_exercise_regions,
                                )

                                page_texts = _extract_page_texts_from_blocks(raw_blocks)
                                exercise_regions = detect_exercise_regions(
                                    page_texts,
                                    config={
                                        "max_empty_pages": settings.EXERCISE_DETECTION_MAX_EMPTY_PAGES,
                                        "min_confidence": settings.EXERCISE_DETECTION_MIN_CONFIDENCE,
                                    },
                                )

                                if exercise_regions:
                                    exercise_regions_result = [
                                        {"start_page": r.start_page, "end_page": r.end_page,
                                         "confidence": r.confidence, "matched_keyword": r.matched_keyword}
                                        for r in exercise_regions
                                    ]
                                    # Filter blocks to exercise region pages
                                    region_pages: set[int] = set()
                                    for r in exercise_regions:
                                        for p in range(r.start_page, r.end_page + 1):
                                            region_pages.add(p)
                                    raw_blocks = [b for b in raw_blocks if b.get("page", 0) in region_pages]
                                    logger.info(
                                        "Exercise region detection found %d region(s), filtered to %d blocks",
                                        len(exercise_regions), len(raw_blocks),
                                    )
                                    del exercise_regions
                                else:
                                    exercise_regions_missing = True
                                    logger.info(
                                        "Exercise detection found no regions, keeping all %d OCR blocks",
                                        len(raw_blocks),
                                    )
                            elif user_specified_range:
                                logger.info(
                                    "Skipping exercise detection: user specified page range %s-%s",
                                    opts.get("page_start"), opts.get("page_end"),
                                )

                            logger.info("OCR succeeded: %d blocks", len(raw_blocks))
                        else:
                            logger.warning("OCR returned no blocks")
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
            exercise_regions_missing = False

        return {
            "raw_blocks": raw_blocks,
            "extracted": len(raw_blocks),
            "exercise_regions": exercise_regions_result,
            "exercise_regions_missing": exercise_regions_missing,
            "ocr_boxes_failed_pages": sorted({
                int(b.get("page") or b.get("page_index") or 0)
                for b in raw_blocks
                if b.get("_ocr_boxes_failed") and (b.get("page") or b.get("page_index"))
            }),
            "ocr_text_fallback_pages": sorted({
                int(b.get("page") or b.get("page_index") or 0)
                for b in raw_blocks
                if b.get("source") == "ocr_text_fallback" and (b.get("page") or b.get("page_index"))
            }),
            "ocr_text_fallback_unavailable_pages": sorted({
                int(page)
                for b in raw_blocks
                for page in (b.get("_ocr_text_fallback_unavailable_pages") or [])
                if page
            }),
            "ocr_runtime_failed_pages": sorted({
                int(page)
                for b in raw_blocks
                for page in (b.get("_ocr_runtime_failed_pages") or [])
                if page
            }),
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

    async def _run_normalize_text(self, raw_blocks: list[dict], **_kw) -> dict:
        """Stage 1: text cleaning via ImportTextNormalizer."""
        extra_patterns = _kw.get("watermark_patterns") or []

        # 从 DB admin_ai_configs 加载 ocr_strategy_* 开关
        db = _kw.get("db")
        enabled_strategies = await self._load_ocr_strategies(db)

        normalizer = ImportTextNormalizer(
            extra_watermark_patterns=extra_patterns,
            enabled_strategies=enabled_strategies,
        )
        normalized_blocks = normalizer.normalize(raw_blocks)

        for b in normalized_blocks:
            raw = b.get("text") or ""
            norm = b.get("normalized_text") or ""
            if raw and norm and raw != norm:
                logger.info(
                    "【OCR-3】text_normalizer 修正 | block=%d page=%s len=%d→%d\n"
                    "  └─ 原始: %.160s\n  └─ 清洗: %.160s",
                    b.get("block_index", 0), b.get("page", "?"),
                    len(raw), len(norm), raw, norm,
                )

        warnings: list[str] = []
        empty_count = sum(1 for b in normalized_blocks if not b.get("normalized_text"))
        if empty_count:
            warnings.append(f"{empty_count} blocks empty after normalization")

        return {"normalized_blocks": normalized_blocks, "warnings": warnings}

    async def _load_ocr_strategies(self, db) -> set[str] | None:
        """从 DB 读取 ocr_strategy_* 配置，返回启用的策略名称集合。
        None = 默认全部启用（无 DB 时）。
        """
        if not db:
            return None
        try:
            from app.services.admin_ai_config_service import get_all_configs

            cfg = await get_all_configs(db)
        except Exception:
            return None

        strategy_map = {
            "math_formula": "ocr_strategy_math_formula",
            "punctuation": "ocr_strategy_punctuation",
            "digit_letter": "ocr_strategy_digit_letter",
            "space_newline": "ocr_strategy_space_newline",
        }
        enabled = set()
        for name, cfg_key in strategy_map.items():
            val = cfg.get(cfg_key) if cfg else None
            if val is None or str(val).lower() == "true":
                enabled.add(name)
        return enabled

    async def _load_structure_features_async(self, db) -> dict[str, bool]:
        """从 DB 读取 ocr_structure_* 配置，返回 feature flags 字典。"""
        features = {"question_type": True, "options": True, "answer": True, "analysis": True}
        if not db:
            return features
        try:
            from app.services.admin_ai_config_service import get_all_configs

            cfg = await get_all_configs(db)
        except Exception:
            return features
        feature_map = {
            "question_type": "ocr_structure_question_type",
            "options": "ocr_structure_options",
            "answer": "ocr_structure_answer",
            "analysis": "ocr_structure_analysis",
        }
        for name, cfg_key in feature_map.items():
            val = cfg.get(cfg_key) if cfg else None
            if val is not None and str(val).lower() == "false":
                features[name] = False
        return features

    async def _run_ocr_correction(self, normalized_blocks: list[dict], options: dict | None = None, **_kw) -> dict:
        """Stage 1.5: AI OCR text correction via multi-model router (Qwen → DeepSeek → rule)."""
        opts = options or {}
        db = _kw.get("db")

        # 合并流水线跳过 AI 纠错：单图文本已纠错，合并只需重新切分+匹配
        if opts.get("skip_ocr_correction"):
            logger.info(
                "【OCR-4】skip_ocr_correction | blocks=%d — 合并流水线复用单图纠错结果",
                len(normalized_blocks),
            )
            return {"normalized_blocks": normalized_blocks, "ocr_correction_diagnostics": {}}

        logger.info(
            "【OCR-4】ocr_correction router | blocks=%d",
            len(normalized_blocks),
        )
        kw = {k: v for k, v in _kw.items() if k != "db"}
        return await self._run_ocr_correction_router(
            normalized_blocks, opts, db, **kw,
        )

    async def _run_ocr_correction_router(
        self, normalized_blocks: list[dict], opts: dict, db, **_kw,
    ) -> dict:
        """通过 OCRFixRouter 执行多模型 OCR 纠错。"""
        from app.features.ocr_fix import OCRFixRouter
        from app.features.ocr_fix.interfaces import OCRFixResult
        from app.features.ocr_fix.metrics import OcrCorrectionMetrics

        # 构建 router 配置
        router_config = await self._build_router_config(opts, db)

        router = OCRFixRouter()
        router.configure(router_config)

        # 页面图像由 run() 预渲染后传入，避免 chunked 模式重复渲染
        page_images = _kw.get("page_images")

        metrics = OcrCorrectionMetrics()

        corrections: list[dict] = []
        corrected_blocks: list[dict] = [None] * len(normalized_blocks)  # type: ignore
        stats = {
            "total_blocks": len(normalized_blocks),
            "noisy_blocks": 0,
            "corrected_blocks": 0,
            "skipped_blocks": 0,
            "model_used": "",
        }

        # Phase 1: classify blocks and collect correction candidates
        to_correct: list[tuple[int, dict, str, float, float]] = []
        for idx, block in enumerate(normalized_blocks):
            text = str(block.get("normalized_text") or "")
            if not text.strip():
                corrected_blocks[idx] = block
                continue

            noise_score = _detect_noise(block)
            structure_score = _detect_structure_abnormal(text)
            has_image = bool(page_images)
            should = _should_correct(noise_score, router_config, structure_score=structure_score, has_image=has_image)

            if not should:
                corrected_blocks[idx] = block
                stats["skipped_blocks"] += 1
                corrections.append({
                    "block_index": block.get("block_index", 0),
                    "page": block.get("page", 1),
                    "noise_score": round(noise_score, 3),
                    "structure_score": round(structure_score, 3),
                    "corrected": False,
                })
                continue

            stats["noisy_blocks"] += 1
            to_correct.append((idx, block, text, noise_score, structure_score))

        metrics.record_classification(
            total=stats["total_blocks"],
            noisy=stats["noisy_blocks"],
            skipped=stats["skipped_blocks"],
        )

        # Phase 2: concurrent fix (same pattern as legacy path)
        from app.features.token_budget import estimate_tokens as _est, check_token_limit, record_token_usage

        sem = asyncio.Semaphore(3)

        async def _fix_one(idx: int, block: dict, text: str):
            async with sem:
                estimated = _est(text) * 3
                if not await check_token_limit(estimated, router_config):
                    return idx, OCRFixResult(
                        fixed_text=text,
                        model_used="skipped_budget",
                        raw_response="token_limit",
                    )

                page_num = block.get("page", 1)
                page_image = page_images.get(page_num) if page_images else None
                logger.info(
                    "【OCR-4】AI纠错输入 | block=%d page=%s noise=%.3f structure=%.3f\n%s",
                    idx, page_num,
                    _detect_noise(block), _detect_structure_abnormal(text),
                    text[:2000],
                )
                result = await router.fix(
                    image=page_image,
                    ocr_text=text,
                    context={"block_index": idx, "page": page_num},
                )

                if result.tokens_used:
                    await record_token_usage(result.tokens_used)

                return idx, result

        fix_results = await asyncio.gather(
            *[_fix_one(idx, block, text) for idx, block, text, _, _ in to_correct],
            return_exceptions=True,
        )

        # Phase 3: process results
        for (idx, block, text, noise_score, structure_score), fix_result in zip(to_correct, fix_results):
            if isinstance(fix_result, BaseException):
                logger.warning("router fix block %d failed: %s", idx, fix_result)
                corrected_blocks[idx] = block
                corrections.append({
                    "block_index": block.get("block_index", 0),
                    "page": block.get("page", 1),
                    "noise_score": round(noise_score, 3),
                    "structure_score": round(structure_score, 3),
                    "corrected": False,
                    "reason": f"exception: {fix_result}",
                    "before_preview": text[:200],
                })
                metrics.record_failure(model="exception", before=text)
                continue

            _, result = fix_result
            new_block = dict(block)
            if result.fixed_text != text and result.confidence and result.confidence > 0:
                # ---- AI safety gate: 评估修改是否可接受 ----
                from app.features.ai_safety import evaluate_and_trace

                safety_trace, safe_text = evaluate_and_trace(
                    stage="ocr_fix",
                    model=result.model_used,
                    before=text,
                    after=result.fixed_text,
                    context={
                        "has_options": bool(re.search(r"[A-D][.、．）)\s]", text)),
                        "stem_context": text[:200],
                    },
                    quality_report={
                        "low_confidence": noise_score > 0.3,
                        "garbled_detected": structure_score > 0.2,
                    },
                    tokens_used=result.tokens_used or 0,
                    duration_ms=getattr(result, "duration_ms", None) or 0,
                )

                if safety_trace.accepted:
                    new_block["normalized_text"] = safe_text
                    new_block["ocr_correction_applied"] = True
                    new_block["ocr_fix_model"] = result.model_used
                    stats["corrected_blocks"] += 1

                    logger.info(
                        "【OCR-5】AI纠错输出 | block=%d page=%d model=%s conf=%.2f\n"
                        "  └─ 纠错前: %.160s\n  └─ 纠错后: %.160s",
                        idx, block.get("page", 1), result.model_used, result.confidence,
                        text, safe_text,
                    )
                    metrics.record_correction(
                        model=result.model_used,
                        before=text,
                        after=safe_text,
                        duration_ms=getattr(result, "duration_ms", None),
                        tokens=result.tokens_used,
                    )
                    corrections.append({
                        "block_index": block.get("block_index", 0),
                        "page": block.get("page", 1),
                        "noise_score": round(noise_score, 3),
                        "structure_score": round(structure_score, 3),
                        "corrected": True,
                        "model_used": result.model_used,
                        "before_preview": text[:200],
                        "after_preview": safe_text[:200],
                        "safety": safety_trace.to_dict(),
                    })
                else:
                    # AI 修改被安全门拒绝，回滚到原文
                    logger.warning(
                        "【OCR-5-SAFETY】纠错被拒绝 | block=%d reason=%s",
                        idx, safety_trace.rollback_reason,
                    )
                    corrections.append({
                        "block_index": block.get("block_index", 0),
                        "page": block.get("page", 1),
                        "noise_score": round(noise_score, 3),
                        "structure_score": round(structure_score, 3),
                        "corrected": False,
                        "reason": f"safety_rejected: {safety_trace.rollback_reason}",
                        "model_used": result.model_used,
                        "before_preview": text[:200],
                        "safety": safety_trace.to_dict(),
                    })
            else:
                corrections.append({
                    "block_index": block.get("block_index", 0),
                    "page": block.get("page", 1),
                    "noise_score": round(noise_score, 3),
                    "structure_score": round(structure_score, 3),
                    "corrected": False,
                    "reason": result.raw_response or "no_change",
                    "before_preview": text[:200],
                })
                metrics.record_unchanged(
                    model=result.model_used,
                    before=text,
                )

            corrected_blocks[idx] = new_block

        # ensure all blocks are filled (defense)
        for idx, b in enumerate(corrected_blocks):
            if b is None:
                corrected_blocks[idx] = normalized_blocks[idx]

        corrected_blocks = [b for b in corrected_blocks if b is not None]

        # 敏感内容过滤
        if router_config.get("ocr_filter_sensitive", True):
            filtered_count = 0
            for b in corrected_blocks:
                text = b.get("normalized_text", "")
                filtered = _filter_sensitive(text)
                if filtered != text:
                    b["normalized_text"] = filtered
                    filtered_count += 1
            if filtered_count:
                logger.debug("ocr_filter_sensitive: filtered %d blocks", filtered_count)

        # 记录使用的模型
        used_models = {c.get("model_used") for c in corrections if c.get("model_used")}
        stats["model_used"] = ", ".join(sorted(used_models)) if used_models else "none"

        warnings: list[str] = []
        if stats["corrected_blocks"] > 0:
            warnings.append(
                f"Router corrected {stats['corrected_blocks']}/{stats['total_blocks']} blocks "
                f"(model: {stats['model_used']})"
            )

        metrics.flush(extra={
            "stats": stats,
            "used_models": sorted(used_models) if used_models else [],
        })

        return {
            "normalized_blocks": corrected_blocks,
            "ocr_correction_diagnostics": {
                "stats": stats,
                "corrections": corrections,
            },
            "warnings": warnings,
        }

    async def _build_router_config(self, opts: dict, db) -> dict:
        """从 options + AdminAiModelConfig 表构建 router 配置。

        所有模型凭据均从 AdminAiModelConfig 表解析（通过 model_config_resolver），
        不依赖硬编码 env var 或 admin_ai_configs 中的独立 key。
        """
        config: dict = {
            "mode": opts.get("ocr_correction_mode", "auto"),
            "noise_threshold": opts.get("ocr_noise_threshold", 0.3),
            "daily_token_limit": opts.get("ocr_correction_daily_token_limit", 50000),
            "monthly_token_limit": opts.get("ocr_correction_monthly_token_limit", 1000000),
        }

        for key in ("ocr_fix_model", "ocr_fix_strategy"):
            val = opts.get(key)
            if val is not None:
                config[key] = val

        # 从 opts 读取过滤开关
        val = opts.get("ocr_filter_sensitive")
        if val is not None:
            config["ocr_filter_sensitive"] = str(val).lower() != "false"

        if db:
            try:
                from app.services.model_config_resolver import resolve_active_model

                # Resolve OCR feature model (could be qwen-vl, deepseek, etc.)
                ocr_model = await resolve_active_model(db, feature="ocr")
                if ocr_model:
                    provider = ocr_model.get("provider", "")
                    if provider in ("qwen-vl", "qwen"):
                        config["qwen_api_key"] = ocr_model["api_key"]
                        config["qwen_base_url"] = ocr_model["api_base_url"]
                        config["qwen_model"] = ocr_model["model_name"]
                    elif provider == "deepseek":
                        config["deepseek_api_key"] = ocr_model["api_key"]
                        config["deepseek_base_url"] = ocr_model["api_base_url"]
                    else:
                        # OpenAI-compatible provider → treat as vision-capable (Qwen path)
                        config["qwen_api_key"] = ocr_model["api_key"]
                        config["qwen_base_url"] = ocr_model["api_base_url"]
                        config["qwen_model"] = ocr_model["model_name"]

                # Resolve a DeepSeek model as fallback for auto chain
                ds_model = await resolve_active_model(db, feature=None)
                if ds_model and ds_model.get("provider") == "deepseek":
                    if "deepseek_api_key" not in config:
                        config["deepseek_api_key"] = ds_model["api_key"]
                    if "deepseek_base_url" not in config:
                        config["deepseek_base_url"] = ds_model["api_base_url"]
            except Exception:
                logger.warning("OCR router: model_config_resolver failed", exc_info=True)

            # 从 DB admin_ai_configs 读取过滤配置
            try:
                from app.services.admin_ai_config_service import get_all_configs
                db_configs = await get_all_configs(db)
                for key in ("ocr_filter_sensitive", "ocr_filter_max_chars", "ocr_filter_max_tokens"):
                    val = db_configs.get(key)
                    if val is not None:
                        if isinstance(val, bool):
                            config[key] = val
                        else:
                            config[key] = str(val).lower() != "false" if key == "ocr_filter_sensitive" else val
            except Exception:
                logger.warning("OCR router: admin_ai_configs read failed", exc_info=True)

        # DeepSeek env var fallback for backward compat only
        import os
        if "deepseek_api_key" not in config:
            config["deepseek_api_key"] = os.environ.get("DEEPSEEK_API_KEY", "")

        return config

    async def _run_analyze_structure(self, normalized_blocks: list[dict], **_kw) -> dict:
        """Stage 2: detect question/answer document layout."""
        db = _kw.get("db")
        features = await self._load_structure_features_async(db)
        structure = analyze_structure(normalized_blocks, features=features)

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
        """Stage 3: split text blocks into individual questions.

        P2-3 / P1-3: when running in chunked mode, ``_kw`` may include
        ``_chunk_seen_hashes`` (a mutable set of overlap-dedup hashes
        already written by earlier chunks) and ``_chunk_logical_end``
        (the chunk's own last page; anything past that is overlap
        territory). The hash is computed via ``_compute_overlap_hash``
        — same payload normalization as ``review_service`` /
        ``QuestionImport.question_hash`` — so OCR jitter on the
        question *number* (e.g. ``1`` vs ``I``) no longer causes
        spurious retains, and section-reset numbers (``1, 2, …``
        appearing twice in one PDF) no longer cause spurious drops.
        Questions whose hash is already in seen_hashes AND whose
        ``page_start`` falls inside the overlap region are dropped here
        so review never sees them. Hashes we keep are added to the set
        so the next chunk sees this update.

        Boundary check: if the chunk's last kept question is within ±1 page
        of ``_chunk_logical_end`` AND its option_lines contain A/B/C but
        miss both D and E, we emit a ``chunk_boundary_unclosed`` warning
        — heuristic for "4-option MCQ truncated by chunk edge" only.
        Two-option / true-false / short-answer questions don't trip this.
        """
        strategy = _kw.get("strategy") or {}
        gap_tolerance = strategy.get("question_number_gap_tolerance", 10)
        # P1-1: 透传 import_mode（统一为小写字符串）给 splitter，
        # 让 book 模式的"软 prose" 检测能给可疑题打 book_pdf_prose_like flag。
        # 其它模式不受影响。
        raw_im = _kw.get("import_mode")
        if isinstance(raw_im, ImportMode):
            import_mode_str = raw_im.value
        else:
            import_mode_str = str(raw_im or "").lower() or None

        split_blocks = normalized_blocks
        layout_filter_diagnostics = {
            "enabled": False,
            "pages_considered": 0,
            "filtered_line_count": 0,
            "kept_line_count": 0,
            "region_signals": [],
        }
        if (
            import_mode_str == "book"
            and str(_kw.get("source_type") or "").lower() == "pdf"
            and any(b.get("boxes") for b in normalized_blocks)
        ):
            try:
                from app.features.visual_boundary_detector import filter_book_layout_blocks

                split_blocks, layout_filter_diagnostics = filter_book_layout_blocks(normalized_blocks)
            except Exception as exc:
                logger.warning("book layout filter failed: %s", exc)

        raw_questions = split_questions(
            split_blocks,
            structure=structure,
            gap_tolerance=gap_tolerance,
            import_mode=import_mode_str,
        )

        text_blocks = [
            b for b in split_blocks
            if str(b.get("normalized_text") or "").strip()
        ]
        split_diagnostics = {
            "normalized_block_count": len(normalized_blocks),
            "text_block_count": len(text_blocks),
            "raw_question_count": len(raw_questions),
            "book_prose_downgraded": sum(
                1 for q in raw_questions
                if "book_pdf_prose_like" in (q.get("risk_flags") or [])
            ),
            "layout_filter": layout_filter_diagnostics,
            "raw_questions_preview": _build_raw_questions_preview(raw_questions),
            "failure_reason": None,
        }

        warnings: list[str] = []

        def _filter_book_pdf_prose() -> None:
            nonlocal raw_questions
            if (
                not raw_questions
                or not _is_book_import_mode(_kw.get("import_mode"))
                or str(_kw.get("source_type") or "").lower() != "pdf"
            ):
                return
            kept_questions = []
            prose_skipped = 0
            prose_preview: list[dict] = []
            for question in raw_questions:
                if _looks_like_book_pdf_prose_candidate(question):
                    prose_skipped += 1
                    if len(prose_preview) < 20:
                        preview_text = re.sub(
                            r"\s+",
                            " ",
                            str(question.get("raw_question_text") or "").strip(),
                        )[:80]
                        prose_preview.append({
                            "page": question.get("page_start"),
                            "number": question.get("number"),
                            "text": preview_text,
                        })
                    continue
                kept_questions.append(question)
            if prose_skipped:
                raw_questions = kept_questions
                warnings.append(f"book_pdf_prose_skipped: {prose_skipped}")
                split_diagnostics["book_pdf_prose_skipped"] = (
                    split_diagnostics.get("book_pdf_prose_skipped", 0) + prose_skipped
                )
                split_diagnostics["prose_skipped_count"] = (
                    split_diagnostics.get("prose_skipped_count", 0) + prose_skipped
                )
                split_diagnostics.setdefault("prose_skipped_preview", []).extend(prose_preview)
                split_diagnostics["raw_question_count_after_prose_filter"] = len(raw_questions)

        def _record_book_pdf_prose_from_blocks() -> None:
            if (
                raw_questions
                or not _is_book_import_mode(_kw.get("import_mode"))
                or str(_kw.get("source_type") or "").lower() != "pdf"
            ):
                return
            previews: list[dict] = []
            for block in text_blocks:
                text = str(block.get("normalized_text") or "").strip()
                first_line = text.split("\n", 1)[0].strip()
                match = re.match(r"^(\d+)\s*[.．、]\s*", first_line)
                if not match:
                    continue
                if _BOOK_PDF_QUESTION_SIGNAL_RE.search(text) or re.search(r"(?:^|\n)\s*[A-D]\s*[.．、:：)）]", text):
                    continue
                marker_count = len(_BOOK_PDF_PROSE_MARKER_RE.findall(text))
                sentence_count = len(_BOOK_PDF_SENTENCE_END_RE.findall(text))
                if marker_count < 2 or sentence_count < 2:
                    continue
                previews.append({
                    "page": block.get("page"),
                    "number": int(match.group(1)),
                    "text": re.sub(r"\s+", " ", text)[:80],
                })
                if len(previews) >= 20:
                    break
            if previews:
                split_diagnostics["prose_skipped_count"] = len(previews)
                split_diagnostics["prose_skipped_preview"] = previews

        _filter_book_pdf_prose()
        _record_book_pdf_prose_from_blocks()

        if not raw_questions:
            if text_blocks:
                # 尝试视觉边界检测（需要 boxes 数据）
                has_boxes = any(b.get("boxes") for b in normalized_blocks)
                if has_boxes:
                    try:
                        from app.features.visual_boundary_detector import detect_visual_boundaries
                        from app.features.question_splitter import split_by_visual_boundaries
                        visual_bounds = detect_visual_boundaries(split_blocks)
                        split_diagnostics["visual_boundary"] = {
                            "boundary_count": len(visual_bounds),
                            "boundaries": [
                                {
                                    "page": b.get("page"),
                                    "signal": b.get("signal"),
                                    "preview": _visual_boundary_preview(split_blocks, b),
                                }
                                for b in visual_bounds[:20]
                            ],
                        }
                        if len(visual_bounds) >= 2:
                            raw_questions = split_by_visual_boundaries(split_blocks, visual_bounds)
                            warnings.append(f"visual_boundary: split {len(raw_questions)} questions via bbox")
                            split_diagnostics["failure_reason"] = None
                            split_diagnostics["fallback_created"] = False
                            split_diagnostics["detection_method"] = "visual_boundary"
                            _filter_book_pdf_prose()
                    except Exception as exc:
                        logger.warning("visual boundary detection failed: %s", exc)

                # 仍然无结果时 fallback 为单条
                if not raw_questions:
                    if _is_book_import_mode(_kw.get("import_mode")) and str(_kw.get("source_type") or "").lower() == "pdf":
                        warnings.append(
                            "no questions found in book import; skipped low-confidence fallback review item"
                        )
                        split_diagnostics["fallback_created"] = False
                        split_diagnostics["failure_reason"] = "book_text_present_but_no_question_boundary"
                        split_diagnostics["non_question_like_skipped"] = True
                    else:
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
                            "risk_flags": ["fallback_low_confidence"],
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

        # P2-3 / P1-3: chunk overlap dedup + boundary unclosed warning.
        # Only kicks in when called from the chunked runner via opts.
        seen_hashes: set | None = _kw.get("_chunk_seen_hashes")
        logical_end: int | None = _kw.get("_chunk_logical_end")
        if seen_hashes is not None and logical_end is not None:
            kept: list[dict] = []
            skipped_numbers: list[int] = []
            for q in raw_questions:
                page_start = q.get("page_start") or 0
                qhash = _compute_overlap_hash(q)
                # Drop only if both: (1) hash was already written by a
                # previous chunk AND (2) the question lives in our overlap
                # zone (page_start > logical_end). Without the page check
                # we would also drop legitimate non-overlap hash collisions
                # (e.g. user pasted same MCQ twice in one PDF).
                if (
                    qhash is not None
                    and qhash in seen_hashes
                    and page_start > logical_end
                ):
                    num = q.get("number")
                    if num is not None:
                        skipped_numbers.append(num)
                    else:
                        skipped_numbers.append(-1)
                    continue
                kept.append(q)
                if qhash is not None:
                    seen_hashes.add(qhash)

            if skipped_numbers:
                warnings.append(
                    f"boundary_overlap_skipped: {sorted(set(skipped_numbers))}"
                )
                split_diagnostics["overlap_skipped_numbers"] = sorted(set(skipped_numbers))
            raw_questions = kept

            # Boundary unclosed: P1-2 收紧为"明显被截断的 4 选题"才警告，
            # 避免对 A/B 双选 / A/C 判断 / 简答题误报。条件：
            # (1) 末题 page_end 距 chunk logical_end ≤ 1 页（贴合边界）
            # (2) has_options=True
            # (3) A/B/C 全部出现但 D/E 都缺 → 像 4 选项被截断
            if raw_questions:
                last = raw_questions[-1]
                last_page_end = last.get("page_end") or 0
                opts = last.get("option_lines") or {}
                opt_keys = {str(k).upper() for k in opts.keys()}
                near_boundary = abs(last_page_end - logical_end) <= 1
                looks_truncated = (
                    "A" in opt_keys
                    and "B" in opt_keys
                    and "C" in opt_keys
                    and "D" not in opt_keys
                    and "E" not in opt_keys
                )
                if (
                    near_boundary
                    and bool(last.get("has_options"))
                    and looks_truncated
                ):
                    warnings.append(
                        f"chunk_boundary_unclosed: q{last.get('number')} "
                        f"may span next chunk (page_end={last_page_end}, "
                        f"logical_end={logical_end})"
                    )
                    split_diagnostics["boundary_unclosed_question"] = last.get("number")

        _log_multi_blank_stage("split", raw_questions, source_type=_kw.get("source_type"), import_mode=import_mode_str)

        # Log each parsed question
        for q in raw_questions:
            opts = q.get("option_lines") or {}
            opt_summary = ", ".join(
                f"{k}: {str(v)[:40]}" for k, v in sorted(opts.items())
            ) or "(无选项)"
            logger.info(
                "【OCR-6】题目解析结果 | number=%s page=%s has_options=%s options=%s\n"
                "  └─ 题干: %.200s",
                q.get("number", "?"), q.get("page_start", "?"),
                q.get("has_options", False),
                opt_summary[:120],
                str(q.get("raw_question_text") or ""),
            )

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
        _log_multi_blank_stage("normalize_schema", questions, source_type=source_type, source_file=source_file)
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])

        invalid_count = sum(1 for q in questions if not q.get("is_valid", True))
        stage_warnings = list(warnings)
        if invalid_count:
            stage_warnings.append(f"{invalid_count} questions marked invalid")

        # P1-2: stage 级风险信号写到每道题的 risk_flags。命名口径见
        # prompts/tasks/ocr_book_pdf_non_question_filter_plan.md §11.3，
        # 前端 import-batch 页面据此打风险徽章；ai_repair / submit_to_review
        # 后续会继续追加 non_question_like / fallback_low_confidence 等 flag。
        exercise_regions_missing = bool(_kw.get("exercise_regions_missing"))
        is_book = _is_book_import_mode(_kw.get("import_mode"))
        no_regions_flagged = 0
        for q in questions:
            flags = list(q.get("risk_flags") or [])
            if exercise_regions_missing and is_book:
                flags.append("no_exercise_regions")
                no_regions_flagged += 1
            if (q.get("confidence_score") or 0) < 0.5:
                flags.append("low_confidence")
            if "garbled_text_detected" in (q.get("ocr_quality_flags") or []):
                flags.append("ocr_garbled_code")
            if flags:
                q["risk_flags"] = list(dict.fromkeys(flags))
        if no_regions_flagged:
            stage_warnings.append(
                f"no_exercise_regions risk flag attached to {no_regions_flagged} questions"
            )

        for q in questions:
            raw_opts = q.get("parsed_options") or q.get("options") or {}
            if isinstance(raw_opts, dict):
                opt_summary = ", ".join(
                    f"{k}: {str(v)[:60]}" for k, v in sorted(raw_opts.items())
                ) or "(无选项)"
            elif isinstance(raw_opts, list):
                opt_summary = ", ".join(
                    f"{o.get('key', '?')}: {str(o.get('text', ''))[:60]}"
                    for o in raw_opts
                ) or "(无选项)"
            else:
                opt_summary = str(raw_opts)[:200]
            logger.info(
                "【OCR-7】schema归一化结果 | number=%s type=%s valid=%s conf=%.2f\n"
                "  └─ 题干: %.200s\n"
                "  └─ 选项: %s\n"
                "  └─ 答案: %s\n"
                "  └─ risk_flags: %s",
                q.get("number", "?"), q.get("question_type", "?"),
                q.get("is_valid", True), q.get("confidence_score", 0),
                str(q.get("stem") or q.get("parsed_content") or "")[:200],
                opt_summary[:200],
                str(q.get("parsed_answer") or "❌"),
                q.get("risk_flags") or [],
            )

        return {
            "questions": questions,
            "normalized_count": len(questions),
            "risk_flag_counts": _count_risk_flags(questions),
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
        if stats.get("roman_numeral_issue_count", 0) > 0:
            warnings.append(f"{stats['roman_numeral_issue_count']} Roman numeral sequence issues detected")
        if stats.get("roman_digit_confusion_count", 0) > 0:
            warnings.append(f"{stats['roman_digit_confusion_count']} Roman digit confusion issues detected")

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
            "high_confidence_threshold": options.get("high_confidence_threshold", 0.95),
            "daily_token_limit": options.get("daily_token_limit", 100000),
            "monthly_token_limit": options.get("monthly_token_limit", 2000000),
            "enabled": options.get("enable_ai_repair", True),
            "low_risk_skip_enabled": options.get("enable_low_risk_skip", True),
        }
        # Pass structured Roman numeral anomalies from batch_validation stage
        batch_diag = _kw.get("batch_validation_diagnostics", {})
        roman_anomalies = batch_diag.get("roman_anomalies", [])
        result = await repair_questions(
            to_repair, repair_config, db=_kw.get("db"),
            roman_diagnostics=roman_anomalies,
        )

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
            original = dict(to_repair[idx])
            if s.get("reason") == "non_question_like":
                flags = list(original.get("risk_flags") or [])
                flags.append("non_question_like")
                original["risk_flags"] = list(dict.fromkeys(flags))
            elif s.get("reason") == "low_risk_high_confidence":
                original["repair_skipped"] = True
                original["repair_skipped_reason"] = "low_risk_high_confidence"
            repaired_combined[idx] = original

        repaired_combined = [q for q in repaired_combined if q is not None]

        # Merge back: non-duplicates (repaired) + duplicates (unchanged)
        combined: list[dict] = []
        repair_iter = iter(repaired_combined)
        for i, q in enumerate(questions):
            if i in duplicate_indices:
                combined.append(q)
            else:
                combined.append(next(repair_iter))
        _log_multi_blank_stage("repair", combined)

        warnings: list[str] = []
        if duplicate_indices:
            warnings.append(f"{len(duplicate_indices)} batch duplicates skipped repair")
        if unrepaired:
            warnings.append(f"{len(unrepaired)} questions unrepaired by AI")
        if skipped:
            reason_counts: dict[str, int] = {}
            for s in skipped:
                reason = str(s.get("reason") or "unknown")
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            if reason_counts == {"above_threshold": len(skipped)}:
                warnings.append(f"{len(skipped)} questions skipped (above threshold)")
            else:
                reason_summary = ", ".join(
                    f"{reason}={count}" for reason, count in sorted(reason_counts.items())
                )
                warnings.append(f"{len(skipped)} questions skipped repair ({reason_summary})")

        # P2-5: compute repair stats for diagnostics
        repair_total = len(to_repair)
        repair_skipped = len(skipped)
        repair_called = len(repaired)
        skip_rate = round(repair_skipped / repair_total, 4) if repair_total > 0 else 0.0
        if repaired:
            avg_tokens_per_repair = int(round(
                sum(r.get("token_used", 0) for r in repaired) / len(repaired)
            ))
            estimated_tokens_saved = avg_tokens_per_repair * repair_skipped
        else:
            avg_tokens_per_repair = 0
            estimated_tokens_saved = 0
        repair_stats = {
            "repair_total": repair_total,
            "repair_skipped": repair_skipped,
            "repair_called": repair_called,
            "skip_rate": skip_rate,
            "estimated_tokens_saved": estimated_tokens_saved,
            "avg_tokens_per_repair": avg_tokens_per_repair,
        }

        return {
            "questions": combined,
            "repaired_count": len(repaired),
            "unrepaired_count": len(unrepaired),
            "skipped_count": len(skipped),
            "total_tokens": stats.get("total_tokens", 0),
            "risk_flag_counts": _count_risk_flags(combined),
            "warnings": warnings,
            "repair_diffs": _build_repair_diffs(repaired, unrepaired, skipped),
            "repair_stats": repair_stats,
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
        hash_index=None,
        **_kw,
    ) -> dict:
        """Stage 6.5: suggest corrections from existing question bank.

        P2-4: chunked 路径下 ``hash_index``（``GlobalHashIndex`` 实例）由
        orchestrator 注入；命中即标 ratio=1.0 强匹配，跳过 difflib 扫描。
        单 pass / 无注入时退化为旧的 subject-级 difflib fallback。
        """
        opts = options or {}
        match_config = {
            "enabled": opts.get("enable_similarity_match", True),
            "similarity_threshold": opts.get("similarity_threshold", 0.85),
        }

        result = await match_similar_questions(
            questions, db=db, config=match_config, hash_index=hash_index,
        )

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

    async def _run_math_detect(
        self,
        questions: list[dict],
        **_kw,
    ) -> dict:
        """Stage 6.8: detect math candidates and apply formula risk flags.

        Runs after all AI stages but before review submission.
        Pure rule engine — no AI calls, no image processing.

        P1-3: 对 math region 生成 math_image segment（仅 metadata，无实际截图）。
        实际截图需要 page image，pipeline 进入此 stage 时 page_images 已释放，
        此时仅写 risk_flags + segment metadata。有 page image 时会进行截图。

        P2-3: 当 ``page_image_refs``（tempfile PNG 路径）可用时，进行真实公式截图
        并上传到 StorageBackend，填充 math_image.url。
        """
        from app.features.math_import_profile import (
            apply_math_risk_flags,
            is_math_candidate,
        )

        if not questions:
            return {"questions": questions, "warnings": ["math_detect: empty questions"]}

        warnings: list[str] = []
        math_count = 0
        excluded_count = 0

        for q in questions:
            diagnosis = is_math_candidate(q)
            if diagnosis["excluded_by"]:
                excluded_count += 1
                continue
            if not diagnosis["is_math"]:
                continue

            math_count += 1
            flags = list(q.get("risk_flags") or [])
            new_flags = apply_math_risk_flags(q, diagnosis)
            for f in new_flags:
                if f not in flags:
                    flags.append(f)

            # P1-3: build math_image segment metadata
            stem = q.get("stem") or q.get("parsed_content", {}).get("text") or ""
            analysis = q.get("analysis") or ""
            full_text = f"{stem} {analysis}"

            segments: list[dict] = list(q.get("segments") or [])
            if diagnosis["has_complex_formula"] or diagnosis.get("low_confidence"):
                math_segment = {
                    "type": "math_image",
                    "url": None,
                    "alt": "公式截图（暂未生成）",
                    "source_page": q.get("page_start") or 1,
                    "bbox": None,
                    "confidence": 0.5,
                    "requires_review": True,
                }
                segments.append(math_segment)
                if diagnosis["has_complex_formula"] and "complex_formula_requires_review" not in flags:
                    flags.append("complex_formula_requires_review")

            if segments:
                q["segments"] = segments
                q["parsed_content"] = {
                    **(q.get("parsed_content") or {}),
                    "render_mode": "segments",
                    "segments": segments,
                }

            if flags:
                q["risk_flags"] = flags

        if math_count:
            warnings.append(f"math_detect: {math_count} math candidates flagged")
        if excluded_count:
            warnings.append(f"math_detect: {excluded_count} code/408 questions excluded")

        # P2-3: 当 page_image_refs 可用时，进行真实公式截图
        page_image_refs: dict[int, str] | None = _kw.get("page_image_refs")
        if page_image_refs and questions:
            from app.services.storage_backend import get_storage

            import hashlib as _hashlib
            from datetime import datetime as _dt
            from pathlib import Path as _Path

            storage = get_storage()
            virtual_import_id = _hashlib.md5(self.pipeline_id.encode()).hexdigest()[:8]

            crop_warnings: list[str] = []
            for q in questions:
                segments = list(q.get("segments") or [])
                updated = False
                for seg in segments:
                    if seg.get("type") != "math_image":
                        continue
                    if seg.get("url") is not None:
                        continue
                    source_page = seg.get("source_page")
                    if not source_page:
                        continue
                    page_path = page_image_refs.get(source_page)
                    if not page_path:
                        continue

                    try:
                        # 读取已渲染 PNG bytes — fitz 直接输出为 PNG，无需 PIL 解码再编码
                        png_bytes = _Path(page_path).read_bytes()

                        content_hash = _hashlib.md5(png_bytes).hexdigest()[:8]
                        month = _dt.now().strftime("%Y%m")
                        filename = f"page_{source_page}_{content_hash}.png"
                        url = await storage.upload(f"{month}/{virtual_import_id}_{filename}", png_bytes)

                        seg["url"] = url
                        seg["alt"] = "公式截图"
                        updated = True
                        crop_warnings.append(f"math_image generated for page {source_page}")
                    except Exception as e:
                        logger.warning("公式截图失败 import=%s page=%s: %s",
                                       self.pipeline_id, source_page, e)
                        seg["crop_failed"] = True
                        seg["alt"] = "公式截图裁剪失败"
                        risk_flags = list(q.get("risk_flags") or [])
                        if "math_image_crop_failed" not in risk_flags:
                            risk_flags.append("math_image_crop_failed")
                            q["risk_flags"] = risk_flags

                if updated:
                    q["segments"] = segments
                    q["parsed_content"] = {
                        **(q.get("parsed_content") or {}),
                        "render_mode": "segments",
                        "segments": segments,
                    }

            if crop_warnings:
                warnings.append(f"math_image: {len(crop_warnings)} formula screenshots generated")

        return {
            "questions": questions,
            "warnings": warnings,
            "risk_flag_counts": _count_risk_flags(questions),
        }

    def _run_table_detect(
        self,
        questions: list[dict],
        **_kw,
    ) -> dict:
        """Stage 6.9: detect table candidates in OCR text and add risk flags.

        Lightweight rule engine — no AI calls. Flags table-like structures
        and builds Markdown representation when column structure is clear.
        """
        from app.features.table_region_detector import detect_table_candidate

        if not questions:
            return {"questions": questions, "warnings": ["table_detect: empty questions"]}

        warnings: list[str] = []
        table_count = 0

        for q in questions:
            stem = q.get("stem") or q.get("parsed_content", {}).get("text") or ""
            if not stem or len(stem) < 40:
                continue

            result = detect_table_candidate(stem)
            if not result["is_table"]:
                continue

            table_count += 1
            flags = list(q.get("risk_flags") or [])
            flags.append("table_detected")
            if result["confidence"] < 0.5 or not result["markdown"]:
                flags.append("table_low_confidence")
            else:
                flags.append("table_requires_review")

            # Write table_markdown segment
            segments: list[dict] = list(q.get("segments") or [])
            segments.append({
                "type": "table_markdown",
                "markdown": result["markdown"],
                "source_page": q.get("page_start") or 1,
                "bbox": None,
                "confidence": result["confidence"],
                "requires_review": result["confidence"] < 0.5 or not result["markdown"],
            })
            q["segments"] = segments
            q["parsed_content"] = {
                **(q.get("parsed_content") or {}),
                "render_mode": "segments",
                "segments": segments,
            }
            q["risk_flags"] = flags

        if table_count:
            warnings.append(f"table_detect: {table_count} table candidates flagged")

        return {
            "questions": questions,
            "warnings": warnings,
            "risk_flag_counts": _count_risk_flags(questions),
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
        _log_multi_blank_stage("review_input", questions, source_type=source_type, source_file=source_file)
        result = await submit_to_review(db, questions, batch_meta, skip_existing=True)

        warnings: list[str] = []
        if result.get("duplicates_filtered", 0) > 0:
            warnings.append(f"{result['duplicates_filtered']} duplicates filtered (already in bank)")
        if result["skipped"] > 0:
            warnings.append(f"{result['skipped']} questions skipped in review")

        # P2-4: 暴露 (subject, hash, import_id) 供 _run_chunked 推到
        # GlobalHashIndex，让后续 chunk 命中本批已写入的题目。subject
        # 优先取 stage 入参（chunk 级 batch_meta），缺失则回落到题目自带的
        # subject（与 review_service 落库口径一致）。
        items = result.get("items", [])
        question_subjects = [
            (q.get("subject") if isinstance(q, dict) else None) for q in questions
        ]
        new_hashes: list[tuple[str, str, int]] = []
        for idx, item in enumerate(items):
            qhash = item.get("question_hash")
            iid = item.get("id")
            if not qhash or not iid:
                continue
            qsubject = subject or (question_subjects[idx] if idx < len(question_subjects) else None) or ""
            if qsubject:
                new_hashes.append((qsubject, qhash, iid))

        logger.info(
            "【OCR-8】数据库入库结果 | batch=%s source=%s total=%d written=%d skipped=%d dup=%d\n"
            "  └─ 题目明细:",
            result["batch_id"], source_file,
            result["total"], result["written"], result["skipped"],
            result.get("duplicates_filtered", 0),
        )
        for idx, item in enumerate(items):
            q = questions[idx] if idx < len(questions) else {}
            opts = q.get("parsed_options") or q.get("options") or {}
            opt_count = len(opts) if isinstance(opts, (dict, list)) else 0
            logger.info(
                "  ▶ import_id=%s hash=%s status=%s type=%s options=%d conf=%.2f answer=%s",
                item.get("id", "?"), item.get("question_hash", "?")[:12],
                item.get("status", "?"), q.get("question_type", "?"),
                opt_count, q.get("confidence_score", 0),
                q.get("parsed_answer") or "❌",
            )

        return {
            "batch_id": result["batch_id"],
            "written": result["written"],
            "skipped": result["skipped"],
            "total": result["total"],
            "items": items,
            "review_new_hashes": new_hashes,
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
        page_images: dict[int, bytes] | None = None,
        # P3-2: resume checkpoint — when set, single-pass skips completed stages
        resume_from_checkpoint: dict | None = None,
    ) -> dict:
        """Execute all pipeline stages in sequence.

        P2-2: when source_type == "pdf" and total_pages > chunk_size, the body
        is split into page-chunks. Each chunk runs the full stage list in
        isolation; a single chunk failure does not abort sibling chunks.
        Single-chunk path retains exact backward compatibility — txt, image
        OCR text, page-range-restricted PDFs, and short PDFs all hit the
        legacy single-pass branch.

        Args:
            file_content: raw file bytes (PDF, txt, etc.) — fallback when no path
            file_path: tmp path on disk; preferred for PDF (mmap, no heap copy).
            source_type: "pdf" | "txt"
            source_file: original filename
            subject: optional subject hint
            options: {"enable_ai_repair": bool, "confidence_threshold": float}
            db: optional AsyncSession for the review stage
            progress_callback: optional async callable(stages_dict, current_stage, errors)
            page_images: pre-rendered page image bytes keyed by 1-based page number.
                         When provided (e.g. from image imports), bypasses
                         _render_page_images so the ocr_correction stage can
                         pass the original image to multimodal models like Qwen-VL.

        Returns:
            Pipeline result dict with status, stats, stages, and errors.
        """
        if file_path is None and file_content is None:
            raise ValueError("either file_path or file_content must be provided")
        opts = options or {}
        if options is not None:
            self.options = opts

        started_at = datetime.now().isoformat()

        # Resolve import mode and strategy (shared across all chunks)
        mode_str = opts.get("import_mode", "auto")
        try:
            import_mode = ImportMode(mode_str)
        except ValueError:
            import_mode = ImportMode.AUTO
        strategy = get_strategy(import_mode)

        # Load watermark rules once (shared across all chunks)
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

        shared = {
            "import_mode": import_mode,
            "strategy": strategy,
            "watermark_patterns": watermark_patterns,
        }

        # Decide chunked vs single-pass
        chunk_ranges = self._plan_chunks(
            file_content=file_content,
            file_path=file_path,
            source_type=source_type,
            opts=opts,
            db=db,
        )

        # Pre-render page images once (expensive — reused across chunks)
        # Caller may pass pre-rendered pages (e.g. image imports keep the
        # original image bytes so multimodal OCR correction can use them).
        if page_images is None:
            page_images = _render_page_images(
                file_content=file_content,
                file_path=file_path,
                source_type=source_type,
            )

        # P2-2: pre-render page image tempfiles for formula cropping.
        # These survive past ocr_correction stage (unlike page_images bytes)
        # so math_detect can use them for real formula screenshots.
        import tempfile as _tempfile
        import shutil as _shutil
        page_image_tempdir: str | None = None
        page_image_refs: dict[int, str] | None = None
        if source_type == "pdf" and file_path:
            page_image_tempdir = _tempfile.mkdtemp(prefix="import_pages_")
            page_image_refs = _render_page_image_refs(
                file_path, page_image_tempdir, source_type=source_type,
            )

        try:
            if len(chunk_ranges) <= 1:
                result = await self._run_single_pass(
                    file_content=file_content,
                    file_path=file_path,
                    source_type=source_type,
                    source_file=source_file,
                    subject=subject,
                    opts=opts,
                    db=db,
                    shared=shared,
                    progress_callback=progress_callback,
                    started_at=started_at,
                    page_images=page_images,
                    page_image_refs=page_image_refs,
                    resume_from_checkpoint=resume_from_checkpoint,
                )
            else:
                result = await self._run_chunked(
                    file_content=file_content,
                    file_path=file_path,
                    source_type=source_type,
                    source_file=source_file,
                    subject=subject,
                    opts=opts,
                    db=db,
                    shared=shared,
                    progress_callback=progress_callback,
                    chunk_ranges=chunk_ranges,
                    started_at=started_at,
                    page_images=page_images,
                    page_image_refs=page_image_refs,
                )
        finally:
            if page_image_tempdir is not None:
                _shutil.rmtree(page_image_tempdir, ignore_errors=True)
        return result

    # ------------------------------------------------------------------
    # P2-2 chunk planning + single-pass extraction
    # ------------------------------------------------------------------

    def _plan_chunks(
        self,
        *,
        file_content: bytes | None,
        file_path: str | None,
        source_type: str,
        opts: dict,
        db,
    ) -> list[tuple[int, int]]:
        """Decide how to split this run into page-chunks.

        Returns:
            [] when chunking is not applicable (txt, no DB, user-pinned page
              range, or PDF page count unavailable). The caller falls back to
              the legacy single-pass branch.
            [(s1, e1), ...] otherwise — 1-based closed page ranges.
        """
        # Chunking only kicks in for PDFs with a DB session (checkpoint needs DB)
        if source_type != "pdf" or db is None:
            return []

        # User-pinned page range bypasses chunking — they explicitly asked
        # for a slice; respecting that takes precedence over auto-chunking.
        if opts.get("page_start") or opts.get("page_end"):
            return []

        chunk_size = _resolve_chunk_size()
        if chunk_size <= 0:
            return []

        try:
            total_pages = _read_pdf_page_count(file_path or file_content)
        except Exception as exc:
            logger.warning("Failed to read PDF page count, falling back to single-pass: %s", exc)
            return []

        if total_pages <= 0:
            return []
        if total_pages <= chunk_size:
            return []  # single chunk = single-pass path

        return _split_into_chunks(total_pages, chunk_size)

    async def _run_single_pass(
        self,
        *,
        file_content: bytes | None,
        file_path: str | None,
        source_type: str,
        source_file: str,
        subject: str | None,
        opts: dict,
        db,
        shared: dict,
        progress_callback,
        started_at: str,
        page_start: int | None = None,
        page_end: int | None = None,
        chunk_seen_hashes: set | None = None,
        chunk_logical_end: int | None = None,
        page_images: dict[int, bytes] | None = None,
        page_image_refs: dict[int, str] | None = None,
        # P3-2: when set, skip already-completed stages. Only used by
        # resume (single-pass). Chunked mode always passes None.
        resume_from_checkpoint: dict | None = None,
    ) -> dict:
        """Execute every stage once for the given (optionally page-restricted) input.

        This is the legacy run() body extracted verbatim — chunked mode calls
        this once per chunk with page_start/page_end injected.

        P2-3 / P1-3: ``chunk_seen_hashes`` (mutable set across chunks) and
        ``chunk_logical_end`` (this chunk's own last page; pages past it are
        overlap territory) are threaded through ``data`` so ``_run_split`` can
        dedupe overlap-region duplicates and emit the unclosed-boundary
        warning. Both are None for legacy single-pass.

        P3-2: ``resume_from_checkpoint`` — when set, completed stages in the
        checkpoint are skipped. Stage outputs for skipped stages are NOT
        restored from checkpoint (they must be re-derived from the source).
        This saves AI call costs for completed stages but not extraction cost.
        """
        # Each pass gets its own stage instances so per-stage status doesn't
        # leak between chunks.
        self._build_pipeline()

        # When called from the chunk loop, override the page range in opts
        # without mutating the caller's dict.
        if page_start is not None or page_end is not None:
            opts = {**opts, "page_start": page_start, "page_end": page_end}

        # Accumulated data passed between stages
        data: dict[str, Any] = {
            "file_content": file_content,
            "file_path": file_path,
            "source_type": source_type,
            "source_file": source_file,
            "subject": subject,
            "options": opts,
            "db": db,
            "import_mode": shared["import_mode"],
            "strategy": shared["strategy"],
            "watermark_patterns": shared["watermark_patterns"],
            "page_images": page_images,
            "page_image_refs": page_image_refs,
            "raw_blocks": [],
            "normalized_blocks": [],
            "raw_questions": [],
            "matched": [],
            "unmatched": [],
            "questions": [],
        }
        # P2-4: chunked 路径在 shared 里挂了 hash_index 实例，透传给
        # similarity_match stage；单 pass 时 shared 没有该 key，stage
        # 默认 hash_index=None 会走旧的 difflib fallback。
        if shared.get("hash_index") is not None:
            data["hash_index"] = shared["hash_index"]
        # P2-3 / P1-3 chunk overlap state — only populated in chunked mode
        if chunk_seen_hashes is not None:
            data["_chunk_seen_hashes"] = chunk_seen_hashes
        if chunk_logical_end is not None:
            data["_chunk_logical_end"] = chunk_logical_end

        pipeline_errors: list[str] = []
        overall_status = "completed"

        # P3-2: per-stage checkpoint tracking
        completed_stages: list[str] = []
        has_resume_ckpt = resume_from_checkpoint is not None
        if has_resume_ckpt:
            completed_stages = list(resume_from_checkpoint.get("completed_stages") or [])
            logger.info(
                "Resuming pipeline %s from checkpoint: %d stages completed",
                self.pipeline_id, len(completed_stages),
            )

        # Write initial checkpoint so we have metadata even if first stage fails
        await _write_stage_checkpoint(
            self.pipeline_id,
            completed_stages=list(completed_stages),
            current_stage="",
            stage_statuses={},
            source_type=source_type,
            source_file=source_file,
            subject=subject,
            options=opts,
        )

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
                    # 隐患① 修复：每次 stage 写入 normalized_blocks 都同步更新
                    # count，确保即便后续 stage 在 match 之前失败，stats 仍能
                    # 反映真实的 block 数（之前只在 match 后缓存，前序失败会
                    # 静默归零）。
                    if "normalized_blocks" in result:
                        data["normalized_block_count"] = len(result["normalized_blocks"])
                # P0-1 / P1-A: 大字段一过最后消费者立即释放，避免随 8+ 个阶段
                # 一起驻留内存。400 页扫描 PDF 下，OCR 后的 normalized_blocks
                # 单独可达 50~200 MB（含 boxes），是仅次于 PDF 字节的大头。
                if name == "extract":
                    # PDF/图片字节保留给 ocr_correction（Qwen-VL 需要原始图像）
                    pass
                elif name == "normalize_text":
                    # raw_blocks 已并入 normalized_blocks，无后续消费者
                    data.pop("raw_blocks", None)
                elif name == "ocr_correction":
                    # OCR correction stage finished, release original bytes
                    # and rendered page images (Qwen-VL was last consumer)
                    data.pop("file_content", None)
                    data.pop("file_path", None)
                    data.pop("page_images", None)
                elif name == "match":
                    # match 后无人再读 normalized_blocks，count 已在写入时缓存
                    data.pop("normalized_blocks", None)
                elif name == "normalize_schema":
                    # questions 已落地，原始题目/匹配结果不再被读取
                    data.pop("raw_questions", None)
                    data.pop("matched", None)
                    data.pop("unmatched", None)

                # P3-2: write checkpoint after each completed stage
                completed_stages.append(name)
                await _write_stage_checkpoint(
                    self.pipeline_id,
                    completed_stages=list(completed_stages),
                    current_stage=name,
                    stage_statuses={n: s.to_dict() for n, s in self.stages.items()},
                    source_type=source_type,
                    source_file=source_file,
                    subject=subject,
                    options=opts,
                )
            except Exception:
                overall_status = "failed"
                pipeline_errors.append(f"stage '{name}' failed: {stage.error}")
                # P3-2: write failure checkpoint
                await _write_stage_checkpoint(
                    self.pipeline_id,
                    completed_stages=list(completed_stages),
                    current_stage=name,
                    stage_statuses={n: s.to_dict() for n, s in self.stages.items()},
                    failed_stage=name,
                    error=stage.error,
                    source_type=source_type,
                    source_file=source_file,
                    subject=subject,
                    options=opts,
                )
                if name in ("extract", "normalize_text", "ocr_correction"):
                    # 失败路径同样释放
                    data.pop("file_content", None)
                    data.pop("file_path", None)
                    data.pop("page_images", None)
                    if name in ("extract", "normalize_text"):
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

        # P3-2: clear checkpoint on successful completion
        if overall_status == "completed":
            await _clear_stage_checkpoint(self.pipeline_id)

        stats = _build_stats(data, self.stages)
        diagnostics = _build_diagnostics(data)
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
            # P2-4: chunked 路径需要拿到本 chunk 已写入的 hash 推到
            # GlobalHashIndex；single-pass 调用方忽略即可。
            "review_new_hashes": data.get("review_new_hashes") or [],
        }

    async def _execute_chunk(
        self,
        *,
        chunk_index: int,
        page_start: int,
        logical_end: int,
        total_pages: int,
        is_last_chunk: bool,
        chunk_overlap: int,
        file_content: bytes | None,
        file_path: str | None,
        source_type: str,
        source_file: str,
        subject: str | None,
        opts: dict,
        db,
        shared: dict,
        progress_callback,
        started_at: str,
        seen_hashes: set,
        hash_index,
        page_images: dict[int, bytes] | None = None,
        page_image_refs: dict[int, str] | None = None,
    ) -> dict:
        """Run one chunk end-to-end with checkpoint writes + failure isolation.

        Shared by ``_run_chunked`` (initial import) and
        ``resume_pipeline_background`` (P2-5 manual resume) so the chunk-level
        contract — mark_running → run_single_pass → update_status →
        push hashes → return outcome dict — stays in one place.

        The returned dict matches the per-chunk diagnostics shape consumed by
        ``diagnostics.chunks`` in the pipeline-level result.
        """
        from app.features import pipeline_checkpoint as ckpt

        await ckpt.mark_chunk_running(db, self.pipeline_id, chunk_index)
        await ckpt.invalidate_progress_cache(self.pipeline_id)

        # P2-3: extend page_end by overlap so the splitter can finish the
        # last question whose tail crosses the chunk boundary. Cap at
        # total_pages so we never read past the document. The final chunk
        # has no overlap (nothing comes after it).
        effective_end = (
            logical_end
            if is_last_chunk
            else min(logical_end + chunk_overlap, total_pages)
        )

        chunk_status = "completed"
        chunk_error: str | None = None
        chunk_result: dict = {}
        try:
            chunk_result = await self._run_single_pass(
                file_content=file_content,
                file_path=file_path,
                source_type=source_type,
                source_file=source_file,
                subject=subject,
                opts=opts,
                db=db,
                shared=shared,
                progress_callback=progress_callback,
                started_at=started_at,
                page_start=page_start,
                page_end=effective_end,
                chunk_seen_hashes=seen_hashes,
                chunk_logical_end=logical_end,
                page_images=page_images,
                page_image_refs=page_image_refs,
            )
            if chunk_result.get("status") != "completed":
                chunk_status = "failed"
                errs = chunk_result.get("errors") or []
                chunk_error = errs[0] if errs else "chunk failed without explicit error"
        except Exception as exc:
            # _run_single_pass should swallow stage errors itself, but if
            # something escapes (e.g. extract crash before stage loop) we
            # must still keep the import alive.
            logger.exception(
                "chunk %d (pages %d-%d) raised unexpectedly",
                chunk_index, page_start, logical_end,
            )
            chunk_status = "failed"
            chunk_error = f"{type(exc).__name__}: {exc}"
            chunk_result = {"errors": [chunk_error]}

        written = (chunk_result.get("stats") or {}).get("to_review", 0)
        batch_id = chunk_result.get("batch_id") or None

        # P2-4: push (subject, hash, import_id) so subsequent chunks can hit
        # this chunk's writes via similarity_match. add_import is a no-op when
        # the index ran into the SQL fallback.
        if hash_index is not None and chunk_status == "completed":
            for subj, qhash, iid in chunk_result.get("review_new_hashes") or []:
                hash_index.add_import(subj, qhash, iid)

        await ckpt.update_chunk_status(
            db,
            self.pipeline_id,
            chunk_index,
            status=chunk_status,
            batch_id=batch_id,
            question_count=written,
            error_message=chunk_error,
        )
        await ckpt.invalidate_progress_cache(self.pipeline_id)

        return {
            "chunk_index": chunk_index,
            "page_start": page_start,
            "page_end": logical_end,
            "effective_page_end": effective_end,
            "status": chunk_status,
            "batch_id": batch_id,
            "question_count": written,
            "error_message": chunk_error,
            "diagnostics": _slim_chunk_diagnostics(chunk_result.get("diagnostics") or {}),
            "stages": chunk_result.get("stages") or {},
        }

    async def _run_chunked(
        self,
        *,
        file_content: bytes | None,
        file_path: str | None,
        source_type: str,
        source_file: str,
        subject: str | None,
        opts: dict,
        db,
        shared: dict,
        progress_callback,
        chunk_ranges: list[tuple[int, int]],
        started_at: str,
        page_images: dict[int, bytes] | None = None,
        page_image_refs: dict[int, str] | None = None,
    ) -> dict:
        """Drive a multi-chunk run with checkpoint persistence and failure isolation.

        For each (page_start, page_end):
            1. mark_chunk_running → run all stages → update_chunk_status
            2. On chunk-level exception (after the catch in _run_single_pass)
               or stage_status == "failed", record error_message and continue
               to the next chunk — never raise out of this method.

        P0-3: 每个 chunk 在自己的 ``AsyncSession`` 上下文里跑，事务边界 =
        chunk 边界。整段循环不再共享单个 session，避免 PG
        ``idle_in_transaction_session_timeout`` 在长 chunked 导入中触发。
        初始化（create_pipeline_record / create_chunk_records / hash_index
        load）也分别用临时 session，跑完即释放连接。

        Pipeline-level status:
            - "completed" iff all chunks completed AND none recorded errors
            - "paused" otherwise (manual resume via P2-5)
        """
        from app.features import pipeline_checkpoint as ckpt
        from app.features.global_hash_index import GlobalHashIndex

        total_pages = chunk_ranges[-1][1]
        chunk_size = _resolve_chunk_size()
        chunk_overlap = _resolve_chunk_overlap()

        # P0-3: 从调用方传入的 db 推导 sessionmaker，生产路径等价于全局
        # async_session；测试路径绑到 tmp_path engine，避免污染全局。
        session_factory = _derive_session_factory(db)

        # P0-3: 把首次实际生效的 watermark patterns 序列化后落库，resume
        # 时直接复用，避免规则漂移。
        watermark_snapshot = _serialize_watermark_patterns(
            shared.get("watermark_patterns") or []
        )

        # Create parent + chunk records up-front (DB authoritative).
        # 每个初始化步骤用独立临时 session，避免长事务。
        async with session_factory() as init_db:
            await ckpt.create_pipeline_record(
                init_db,
                pipeline_id=self.pipeline_id,
                source_type=source_type,
                source_file=source_file or None,
                total_pages=total_pages,
                chunk_size=chunk_size,
                created_by=self.created_by,
                source_sha256=self.source_sha256,
                watermark_snapshot=watermark_snapshot or None,
            )
            await ckpt.create_chunk_records(init_db, self.pipeline_id, chunk_ranges)

        # P2-4: chunked 路径只构造一次 hash 索引，整个 pipeline 共用。失败
        # 不阻断主流程——index_loaded=False 时 similarity_match 退化为
        # subject 全表扫描（旧行为），仅打 warning。
        hash_index: GlobalHashIndex | None = GlobalHashIndex()
        try:
            async with session_factory() as init_db:
                await hash_index.load(init_db)
        except Exception:
            logger.exception("GlobalHashIndex.load failed; chunked similarity match will fallback")
            hash_index = None
        if hash_index is not None:
            shared = {**shared, "hash_index": hash_index}

        chunk_results: list[dict] = []
        pipeline_errors: list[str] = []
        any_chunk_failed = False
        # P2-3 / P1-3: shared across all chunks so dedup sees what siblings already wrote
        seen_hashes: set[str] = set()

        try:
            for chunk_index, (page_start, logical_end) in enumerate(chunk_ranges):
                is_last_chunk = chunk_index == len(chunk_ranges) - 1
                # P0-3: 每个 chunk 一个独立 session（事务边界 = chunk 边界）。
                async with session_factory() as chunk_db:
                    outcome = await self._execute_chunk(
                        chunk_index=chunk_index,
                        page_start=page_start,
                        logical_end=logical_end,
                        total_pages=total_pages,
                        is_last_chunk=is_last_chunk,
                        chunk_overlap=chunk_overlap,
                        file_content=file_content,
                        file_path=file_path,
                        source_type=source_type,
                        source_file=source_file,
                        subject=subject,
                        opts=opts,
                        db=chunk_db,
                        shared=shared,
                        progress_callback=progress_callback,
                        started_at=started_at,
                        seen_hashes=seen_hashes,
                        hash_index=hash_index,
                        page_images=page_images,
                        page_image_refs=page_image_refs,
                    )
                chunk_results.append(outcome)
                if outcome["status"] == "failed":
                    any_chunk_failed = True
                    pipeline_errors.append(
                        f"chunk {chunk_index} (pages {page_start}-{logical_end}) "
                        f"failed: {outcome['error_message']}"
                    )
        finally:
            # P1-1: 清空 hash_index 内部 dict，避免 chunk 异常路径下大字典
            # （最坏 ~50 万条 question + N 条 import）残留在 GlobalHashIndex
            # 实例上。低配 2C2G 服务器友好。
            if hash_index is not None:
                hash_index._question_index.clear()
                hash_index._import_index.clear()

        overall_status = "paused" if any_chunk_failed else "completed"
        async with session_factory() as final_db:
            await ckpt.update_pipeline_status(
                final_db,
                self.pipeline_id,
                status=overall_status,
                error_message=pipeline_errors[0] if pipeline_errors else None,
                finished=True,
            )
        await ckpt.invalidate_progress_cache(self.pipeline_id)

        # Aggregate stats across chunks
        agg_stats = {
            "total_chunks": len(chunk_ranges),
            "completed_chunks": sum(1 for c in chunk_results if c["status"] == "completed"),
            "failed_chunks": sum(1 for c in chunk_results if c["status"] == "failed"),
            "to_review": sum(c["question_count"] or 0 for c in chunk_results),
            "extracted": total_pages,
            "total": total_pages,
        }

        risk_flag_counts = _merge_risk_flag_counts(chunk_results)

        finished_at = datetime.now().isoformat()
        # Pick a representative batch_id for the overall pipeline (first
        # successful chunk's batch). Each chunk has its own batch_id under
        # the hood; resume logic uses chunk-level records, not this field.
        first_batch_id = next(
            (c["batch_id"] for c in chunk_results if c["batch_id"]),
            "",
        )

        return {
            "pipeline_id": self.pipeline_id,
            "status": overall_status,
            "batch_id": first_batch_id,
            "stats": agg_stats,
            "diagnostics": {
                "chunked": True,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "total_pages": total_pages,
                "risk_flag_counts": risk_flag_counts,
                "chunks": chunk_results,
                "hash_index": (
                    dict(hash_index.stats) if hash_index is not None else None
                ),
            },
            "stages": {},  # per-chunk stage info lives in diagnostics.chunks
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
    created_by: str | None = None,
    source_sha256: str | None = None,
    page_images: dict[int, bytes] | None = None,
    # P3-2: resume checkpoint for single-pass resume
    resume_from_checkpoint: dict | None = None,
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
        page_images: 预渲染的页面图片字典（{1: image_bytes}），传入后管线跳过
                     _render_page_images，直接使用。用于图片导入场景，让多模态
                     OCR 纠错模型（如 Qwen-VL）能看到原始图片。
        resume_from_checkpoint: P3-2 resume checkpoint data. When set, the
                     pipeline re-runs from extract but uses the same pipeline_id
                     for status continuity.

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
    pipeline.created_by = created_by
    pipeline.source_sha256 = source_sha256

    result = await pipeline.run(
        file_content=file_content,
        file_path=file_path,
        source_type=source_type,
        source_file=source_file,
        subject=subject,
        options=opts,
        db=db,
        progress_callback=progress_callback,
        page_images=page_images,
        resume_from_checkpoint=resume_from_checkpoint,
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
    created_by: str | None = None,
    source_sha256: str | None = None,
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
            created_by=created_by,
            source_sha256=source_sha256,
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


async def _load_seen_hashes_for_resume(db, pipeline_id: str) -> set[str]:
    """Rebuild ``seen_hashes`` from already-imported question rows.

    P1-3: 把"以题号为 key"换成"以 ``question_hash`` 为 key"——这一字段在
    ``QuestionImport`` 表已存在（review_service 写入时计算），因此 resume
    路径直接读列就行，不再依赖 ``raw_data["number"]`` 这种易漂移字段。

    P2-3 keeps a function-level set across chunks so the overlap-region dedup
    never re-imports something a sibling chunk already wrote. After a process
    restart that set is gone — without rebuilding it, a resumed chunk could
    drop legitimate questions whose hashes were written earlier. Best-effort:
    rows missing ``question_hash`` are silently skipped.
    """
    from sqlalchemy import select

    from app.models.import_pipeline import ImportPipelineChunk
    from app.models.question_import import QuestionImport

    chunk_subq = (
        select(ImportPipelineChunk.batch_id)
        .where(
            ImportPipelineChunk.pipeline_id == pipeline_id,
            ImportPipelineChunk.status == "completed",
            ImportPipelineChunk.batch_id.isnot(None),
        )
        .scalar_subquery()
    )
    rows = await db.execute(
        select(QuestionImport.question_hash).where(
            QuestionImport.batch_id.in_(chunk_subq),
            QuestionImport.question_hash.isnot(None),
        )
    )
    hashes: set[str] = set()
    for (qhash,) in rows.all():
        if isinstance(qhash, str) and qhash:
            hashes.add(qhash)
    return hashes


async def resume_pipeline_background(
    *,
    pipeline_id: str,
    file_path: str,
    subject: str | None = None,
    options: dict | None = None,
    db,
) -> None:
    """P2-5: replay only the failed/pending chunks of an existing pipeline.

    Caller (api.v1.imports.resume_pipeline) is responsible for persisting the
    re-uploaded PDF to ``file_path`` and unlinking it once this coroutine
    finishes.

    Behaviour:
        - Loads chunk rows from DB; if no failed/pending chunks remain, marks
          the pipeline ``completed`` and returns immediately.
        - Rebuilds the cross-chunk state (watermark patterns, GlobalHashIndex
          containing already-completed chunk batches, seen_hashes set) so the
          replayed chunks behave the same as if they had run alongside their
          successful siblings.
        - Reuses ``_execute_chunk`` so checkpoint writes, error isolation, and
          hash-index updates stay identical to ``_run_chunked``.
        - Final pipeline status is ``completed`` iff every replayed chunk
          succeeds AND no chunk row remains failed; otherwise stays ``paused``
          so the user can resume again.

    P0-3:
        - 每个 chunk 在独立 ``AsyncSession`` 里跑（事务边界 = chunk 边界），
          避免 PG idle_in_transaction_session_timeout 在长导入中触发。
        - 优先复用 ``pipeline_row.watermark_snapshot``——若存在则跳过
          watermark service 的实时加载，避免管理员在 paused 与 resume
          之间调整规则导致 hash 漂移。NULL（历史 paused pipeline）仍
          fallback 到旧路径。
    """
    from app.features import pipeline_checkpoint as ckpt
    from app.features.global_hash_index import GlobalHashIndex
    from app.models.import_pipeline import (
        ImportPipeline as ImportPipelineRow,
        ImportPipelineChunk,
    )
    from sqlalchemy import select

    opts = dict(options) if options else {}

    # P0-3: 推导 sessionmaker，后续每个 chunk 用独立 session。
    session_factory = _derive_session_factory(db)

    pipeline_row = (
        await db.execute(
            select(ImportPipelineRow).where(
                ImportPipelineRow.pipeline_id == pipeline_id
            )
        )
    ).scalar_one_or_none()
    if pipeline_row is None:
        logger.warning("resume_pipeline_background: pipeline %s missing, abort", pipeline_id)
        return

    pending = await ckpt.get_pending_chunks(db, pipeline_id)
    if not pending:
        # nothing to do — caller probably hit a race; mark completed if no
        # chunks are still failing.
        await ckpt.update_pipeline_status(
            db, pipeline_id, status="completed", finished=True,
        )
        await ckpt.invalidate_progress_cache(pipeline_id)
        return

    # All chunks (for total count + completed batch_ids), single query.
    all_chunks = (
        (
            await db.execute(
                select(ImportPipelineChunk)
                .where(ImportPipelineChunk.pipeline_id == pipeline_id)
                .order_by(ImportPipelineChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    if not all_chunks:
        logger.warning("resume_pipeline_background: pipeline %s has no chunk rows", pipeline_id)
        return

    total_pages = pipeline_row.total_pages or all_chunks[-1].page_end
    chunk_overlap = _resolve_chunk_overlap()
    max_chunk_index = all_chunks[-1].chunk_index
    completed_batch_ids = [
        c.batch_id for c in all_chunks if c.status == "completed" and c.batch_id
    ]
    # P0-3: snapshot 字段在 ORM 行里就是 list/dict/None；提早抓住后续不再
    # 依赖 pipeline_row 的 detached 状态。
    snapshot = pipeline_row.watermark_snapshot

    # Resolve import mode + strategy + watermark patterns the same way
    # ImportPipeline.run() does, so resumed chunks see the same shared context.
    mode_str = opts.get("import_mode", "auto")
    try:
        import_mode = ImportMode(mode_str)
    except ValueError:
        import_mode = ImportMode.AUTO
    strategy = get_strategy(import_mode)

    # P0-3: 优先用首次导入时的 watermark snapshot；NULL 才回退到实时加载。
    watermark_patterns: list = []
    if snapshot:
        watermark_patterns = _deserialize_watermark_patterns(snapshot)
        if not watermark_patterns:
            logger.warning(
                "resume: watermark_snapshot present but empty/unparsable for %s; "
                "falling back to live rules",
                pipeline_id,
            )
    if not watermark_patterns:
        if not snapshot:
            logger.warning(
                "resume: legacy pipeline %s without watermark_snapshot, "
                "reloading from current rules",
                pipeline_id,
            )
        try:
            from app.services.watermark_service import load_rules
            watermark_patterns = await load_rules(db)
        except Exception as exc:
            logger.warning("resume: watermark load_rules failed (%s); using defaults", exc)
        if not watermark_patterns:
            from app.services.watermark_service import get_default_patterns
            watermark_patterns = get_default_patterns()

    shared: dict = {
        "import_mode": import_mode,
        "strategy": strategy,
        "watermark_patterns": watermark_patterns,
    }

    # Rebuild GlobalHashIndex: recent_days window + every batch_id this
    # pipeline already wrote, so resumed chunks can dedupe against their
    # successful siblings.
    hash_index: GlobalHashIndex | None = GlobalHashIndex()
    try:
        async with session_factory() as init_db:
            await hash_index.load(init_db, batch_ids=completed_batch_ids or None)
    except Exception:
        logger.exception(
            "resume: GlobalHashIndex.load failed; similarity match will fallback"
        )
        hash_index = None
    if hash_index is not None:
        shared["hash_index"] = hash_index

    async with session_factory() as init_db:
        seen_hashes = await _load_seen_hashes_for_resume(init_db, pipeline_id)

    # Mark the pipeline running again so status queries reflect the in-progress
    # resume and a concurrent second resume can detect the conflict.
    async with session_factory() as init_db:
        await ckpt.update_pipeline_status(init_db, pipeline_id, status="running")
    await ckpt.invalidate_progress_cache(pipeline_id)

    pipeline = ImportPipeline(options=opts)
    pipeline.pipeline_id = pipeline_id
    started_at = datetime.now().isoformat()

    chunk_results: list[dict] = []
    any_chunk_failed = False
    try:
        for chunk in pending:
            # P0-3: 每个 chunk 一个独立 session（事务边界 = chunk 边界）。
            async with session_factory() as chunk_db:
                outcome = await pipeline._execute_chunk(
                    chunk_index=chunk.chunk_index,
                    page_start=chunk.page_start,
                    logical_end=chunk.page_end,
                    total_pages=total_pages,
                    is_last_chunk=(chunk.chunk_index == max_chunk_index),
                    chunk_overlap=chunk_overlap,
                    file_content=None,
                    file_path=file_path,
                    source_type=pipeline_row.source_type or "pdf",
                    source_file=pipeline_row.source_file or "",
                    subject=subject,
                    opts=opts,
                    db=chunk_db,
                    shared=shared,
                    progress_callback=None,
                    started_at=started_at,
                    seen_hashes=seen_hashes,
                    hash_index=hash_index,
                    page_image_refs=None,
                )
            chunk_results.append(outcome)
            if outcome["status"] == "failed":
                any_chunk_failed = True
    finally:
        # P1-1: 清空 hash_index 内部 dict，避免 resume 路径异常时大字典残留。
        if hash_index is not None:
            hash_index._question_index.clear()
            hash_index._import_index.clear()

    # Recompute overall status from current DB state — chunks not in
    # ``pending`` could still be ``failed`` if a prior resume left them so;
    # also covers the case where an earlier chunk silently regressed (we
    # never overwrite completed chunks here).
    async with session_factory() as final_db:
        progress = await ckpt.get_pipeline_progress(final_db, pipeline_id, use_cache=False)
        still_failing = (progress and progress.get("failed_chunks", 0) > 0)
        overall_status = "paused" if (any_chunk_failed or still_failing) else "completed"
        await ckpt.update_pipeline_status(
            final_db,
            pipeline_id,
            status=overall_status,
            finished=(overall_status == "completed"),
        )
    await ckpt.invalidate_progress_cache(pipeline_id)


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
        # P0-1: release Excel bytes after import function consumes them
        del file_content
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


async def get_pipeline_status(pipeline_id: str, db=None) -> dict | None:
    """查询流水线状态（Redis + 内存 fallback）。

    P0-3: 主 store 已瘦身，本函数把 diagnostics 从独立 KV 合并回去，
    对外返回与改造前一致的完整视图。

    P2-6: 当 ``db`` 注入时，从 import_pipelines / import_pipeline_chunks 拉
    chunk 进度并合并到 ``chunk_progress`` 字段。db=None 或无 chunk 记录时省
    略该字段，向后兼容图片 / Excel / 单 pass 等无 chunk 场景。

    P2-resume-store: ``resume_pipeline_background`` 只更新 DB 的
    ``import_pipelines.status``，不回写 ``_pipeline_store`` 主 store——首次
    导入结束时写入的 ``status="paused"`` 在内存里会一直停在这里，导致 resume
    途中（running）和 resume 完成（completed）期间前端轮询拿到的还是 paused。
    chunked 路径下 ``chunk_progress.status`` 来自 DB 权威源，因此当 chunk
    进度可用时用它覆盖顶层 ``status``，不为 chunked 路径之外的场景（image /
    excel / 单 pass）引入新行为。
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

    if db is not None:
        try:
            from app.features import pipeline_checkpoint as ckpt

            progress = await ckpt.get_pipeline_progress(
                db, pipeline_id, use_cache=True
            )
            if progress is not None:
                data["chunk_progress"] = progress
                db_status = progress.get("status")
                if db_status:
                    data["status"] = db_status
        except Exception:
            logger.debug(
                "fetch chunk_progress for %s failed", pipeline_id, exc_info=True
            )
    return data
