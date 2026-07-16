#!/usr/bin/env python3
"""Backfill question images for data-structure PDF import.

Crops pages from ds_sc.pdf, uploads to question-assets storage, and writes
image segments into question_imports.parsed_content.

Usage:
    # Dry-run preview
    python scripts/backfill_question_images.py \
        --db sqlite+aiosqlite:///path/to/postgraduate.db \
        --pdf /path/to/ds_sc.pdf \
        --dry-run

    # Backfill specific IDs
    python scripts/backfill_question_images.py \
        --db sqlite+aiosqlite:///path/to/postgraduate.db \
        --pdf /path/to/ds_sc.pdf \
        --ids 229,369,371

    # Full backfill (all pending with visual reference)
    python scripts/backfill_question_images.py \
        --db sqlite+aiosqlite:///path/to/postgraduate.db \
        --pdf /path/to/ds_sc.pdf \
        --mode full-page \
        --output-report backfill_report.json

Re-runnable: skips existing image segments with identical asset_kind+page+checksum.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import logging
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# ── Imports that may fail before path fix ──

import fitz
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.models.question_import import QuestionImport
from app.services.admin_import_service import resolve_source_page, resolve_source_page_end
from app.services.storage_backend import get_question_assets_storage, compress_image
from app.services.visual_region_types import make_image_segment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_question_images")

# ── Default skip list (questions that mention "图G" as math concept, not actual figures) ──
SKIP_IDS_DEFAULT = frozenset({337, 343, 346, 347, 365, 379, 408})

# ── Known page mapping for the 19 image-dependent questions ──
KNOWN_PAGE_MAP: dict[int, int] = {
    229: 108, 369: 286, 371: 288, 380: 297, 388: 307,
    395: 314, 397: 316, 400: 319, 402: 321, 405: 324,
    407: 326, 411: 330, 412: 331, 451: 370, 457: 376,
    460: 379, 461: 380, 472: 391, 480: 399,
}

OPTIONAL_IDS = frozenset({345})  # 345->262, matrix layout, marked optional_visual


@dataclass
class BackfillResult:
    import_id: int
    page: int | None = None
    status: str = "pending"  # pending | success | skipped | failed
    crop_mode: str | None = None
    crop_confidence: float = 0.0
    bbox: list[float] | None = None
    image_url: str | None = None
    checksum: str | None = None
    skip_reason: str | None = None
    failure_reason: str | None = None
    # Replacement tracking
    old_image_url: str | None = None
    old_checksum: str | None = None
    action: str | None = None  # inserted | replaced | skipped
    # Page backfill
    page_backfill_action: str | None = None


def _compute_checksum(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()[:12]


def _existing_segment_key(seg: dict) -> tuple:
    """Generate dedup key for an existing segment: (asset_kind, source_page, checksum)."""
    if not isinstance(seg, dict):
        return ()
    asset_kind = seg.get("asset_kind") or seg.get("region_type", "")
    source_page = seg.get("source_page", 0)
    checksum = seg.get("checksum", "")
    return (asset_kind, source_page, checksum)


def _has_image_segment(segments: list | None, checksum: str, source_page: int) -> bool:
    """Check if an image segment with matching (source_page, checksum) already exists."""
    if not segments:
        return False
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        if seg.get("type") != "image":
            continue
        if seg.get("source_page") == source_page and seg.get("checksum") == checksum:
            return True
    return False


def _get_text_segment(text: str | None) -> dict | None:
    """Get existing text segment from parsed_content, or None."""
    if not text:
        return None
    existing = {"type": "text", "text": text}
    return existing


async def validate_pdf(pdf_path: str, expected_pages: int = 513) -> int:
    """Validate PDF exists and has expected page count. Returns page count."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    doc = fitz.open(pdf_path)
    total = len(doc)
    doc.close()
    if total < expected_pages:
        logger.warning(
            "PDF has %d pages, expected %d. Some pages may be missing.",
            total, expected_pages,
        )
    logger.info("PDF validated: %s (%d pages)", pdf_path, total)
    return total


def render_page(pdf_path: str, page_num: int, dpi: int = 200) -> bytes:
    """Render a single PDF page to PNG bytes at given DPI."""
    doc = fitz.open(pdf_path)
    try:
        if page_num < 1 or page_num > len(doc):
            raise ValueError(f"Page {page_num} out of range (PDF has {len(doc)} pages)")
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


# ── PDF figure region detection ──────────────────────────────────────────


def _merge_bboxes(
    bboxes: list[tuple[float, float, float, float]],
    gap_threshold: float = 20.0,
) -> list[tuple[float, float, float, float]]:
    """Merge nearby bboxes that are within gap_threshold PDF points."""
    if not bboxes:
        return []
    sorted_boxes = sorted(bboxes, key=lambda b: (b[1], b[0]))  # sort by y then x
    merged: list[tuple[float, float, float, float]] = [sorted_boxes[0]]
    for box in sorted_boxes[1:]:
        prev = merged[-1]
        # Check vertical/horizontal proximity
        if box[1] <= prev[3] + gap_threshold:  # overlapping or within gap
            merged[-1] = (
                min(prev[0], box[0]),
                min(prev[1], box[1]),
                max(prev[2], box[2]),
                max(prev[3], box[3]),
            )
        else:
            merged.append(box)
    return merged


def detect_figure_region(
    pdf_path: str,
    page_num: int,
    dpi: int = 200,
) -> tuple[bytes | None, list[float] | None, float]:
    """Detect figure region on a PDF page using layout analysis.

    Strategy:
    1. Extract text blocks, image blocks, and vector drawings from the PDF page.
    2. Identify non-text content (embedded images, drawings with lines/shapes).
    3. Merge nearby figure bboxes with a gap threshold.
    4. Select the most significant figure region (largest non-text cluster).
    5. Crop the rendered page at that bbox with padding.

    Returns:
        (cropped_png_bytes or None, bbox_in_pixels or None, confidence 0.0–1.0)
        Returns (None, None, 0.0) for full-page fallback when no figure detected.
    """
    import fitz as _fitz

    doc = _fitz.open(pdf_path)
    try:
        if page_num < 1 or page_num > len(doc):
            return None, None, 0.0
        page = doc[page_num - 1]

        # 1. Collect text block bboxes
        text_blocks: list[tuple[float, float, float, float]] = []
        blocks_dict = page.get_text("dict", flags=_fitz.TEXT_PRESERVE_WHITESPACE)
        for block in blocks_dict.get("blocks", []):
            if block.get("type") == 0:  # text
                b = block["bbox"]
                text_blocks.append((b[0], b[1], b[2], b[3]))

        # 2. Collect embedded image bboxes
        image_bboxes: list[tuple[float, float, float, float]] = []
        for img_info in page.get_images(full=True):
            # Each image info: (xref, smask, width, height, bpc, colorspace, ...)
            # Try to get the image's placement on the page
            try:
                pix = _fitz.Pixmap(doc, img_info[0])
                # Get image transform/placement on page
                for img_block in blocks_dict.get("blocks", []):
                    if img_block.get("type") == 1:  # image block
                        b = img_block["bbox"]
                        image_bboxes.append((b[0], b[1], b[2], b[3]))
            except Exception:
                pass
        # Dedup image bboxes
        if image_bboxes:
            image_bboxes = list(set(image_bboxes))

        # 3. Collect vector drawing bboxes
        drawing_bboxes: list[tuple[float, float, float, float]] = []
        for draw in page.get_drawings():
            rect = draw["rect"]
            w = rect.x1 - rect.x0
            h = rect.y1 - rect.y0
            # Filter out very thin lines (likely borders or underlines)
            if w < 5 and h < 5:
                continue
            # Filter out full-page boundary boxes
            page_rect = page.rect
            if w > page_rect.width * 0.95 and h > page_rect.height * 0.95:
                continue
            drawing_bboxes.append((rect.x0, rect.y0, rect.x1, rect.y1))

        # 4. Build candidate figure regions from non-text content
        figure_candidates = image_bboxes + drawing_bboxes

        if not figure_candidates:
            return None, None, 0.0

        # Merge nearby bboxes
        merged = _merge_bboxes(figure_candidates, gap_threshold=15.0)

        # 5. Pick the most significant figure region:
        #    - Largest area wins
        #    - Must be at least 40x40 PDF points
        significant = [
            b for b in merged
            if (b[2] - b[0]) >= 40 and (b[3] - b[1]) >= 40
        ]
        if not significant:
            return None, None, 0.0

        # Pick largest area
        best = max(significant, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))

        # 6. Add padding (12 PDF points ~= 2mm at 72 DPI)
        pad = 12
        x0 = max(0, best[0] - pad)
        y0 = max(0, best[1] - pad)
        x1 = best[2] + pad
        y1 = best[3] + pad

        # 7. Render and crop
        scale = dpi / 72
        pix = page.get_pixmap(dpi=dpi)
        img_data = pix.tobytes("png")

        from PIL import Image, ImageChops
        import io

        img = Image.open(io.BytesIO(img_data))
        px_bbox = (int(x0 * scale), int(y0 * scale), int(x1 * scale), int(y1 * scale))

        # Clamp to image boundaries
        px_bbox = (
            max(0, px_bbox[0]),
            max(0, px_bbox[1]),
            min(img.width, px_bbox[2]),
            min(img.height, px_bbox[3]),
        )

        if px_bbox[2] <= px_bbox[0] or px_bbox[3] <= px_bbox[1]:
            return None, None, 0.0

        cropped = img.crop(px_bbox)

        # Auto-trim white borders
        if cropped.mode != "RGB":
            cropped = cropped.convert("RGB")
        bg = Image.new("RGB", cropped.size, (255, 255, 255))
        diff = ImageChops.difference(cropped, bg)
        trim_bbox = diff.getbbox()
        if trim_bbox:
            tpad = 3
            tx0 = max(0, trim_bbox[0] - tpad)
            ty0 = max(0, trim_bbox[1] - tpad)
            tx1 = min(cropped.width, trim_bbox[2] + tpad)
            ty1 = min(cropped.height, trim_bbox[3] + tpad)
            if tx1 > tx0 and ty1 > ty0:
                cropped = cropped.crop((tx0, ty0, tx1, ty1))

        buf = io.BytesIO()
        cropped.save(buf, format="PNG")

        # Estimate confidence: image-based figures are high confidence,
        # drawing-only regions are medium
        has_images = len(image_bboxes) > 0
        confidence = 0.85 if has_images else 0.65

        return buf.getvalue(), [x0, y0, x1, y1], confidence

    finally:
        doc.close()


def try_auto_crop(page_bytes: bytes, dpi: int = 200) -> tuple[bytes | None, list[float] | None]:
    """Legacy wrapper (kept for compatibility, delegates to detect_figure_region via the caller).

    Deprecated: Use detect_figure_region directly.
    """
    return None, None


def full_page_crop(page_png: bytes) -> bytes:
    """Return full page as the crop result (with auto-trim of blank margins)."""
    from PIL import Image, ImageChops
    import io

    img = Image.open(io.BytesIO(page_png))
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Auto-trim: remove solid white/off-white borders
    bg = Image.new("RGB", img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg)
    bbox = diff.getbbox()
    if bbox:
        # Add small padding
        pad = 4
        x0, y0, x1, y1 = bbox
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(img.width, x1 + pad)
        y1 = min(img.height, y1 + pad)
        if x1 > x0 and y1 > y0:
            img = img.crop((x0, y0, x1, y1))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def process_single_question(
    db: AsyncSession,
    qi: QuestionImport,
    pdf_path: str,
    dpi: int,
    force: bool,
    dry_run: bool,
    manual_bbox: list[float] | None = None,
    replace_existing: bool = False,
) -> BackfillResult:
    """Process a single QuestionImport record for image backfill.

    Args:
        manual_bbox: Optional manually defined bbox [x0, y0, x1, y1] in PDF points
                     (from region manifest), taking priority over auto-detection.
        replace_existing: If True and an existing image segment for the same
                         (asset_kind, source_page) is found, replace it instead
                         of appending a duplicate segment.

    Returns BackfillResult with status and details.
    """
    result = BackfillResult(import_id=qi.id)

    # 1. Resolve page number
    page = (
        qi.source_page_start
        or resolve_source_page(qi.raw_data)
        or KNOWN_PAGE_MAP.get(qi.id)
    )
    if page is None:
        result.status = "skipped"
        result.skip_reason = "无法解析页码"
        return result

    result.page = page

    # 2. Get existing segments for dedup
    parsed_content = dict(qi.parsed_content or {})
    segments = list(parsed_content.get("segments") or []) if isinstance(parsed_content.get("segments"), list) else []

    # Insert text segment if missing
    text = parsed_content.get("text") or ""
    has_text_segment = any(s.get("type") == "text" for s in segments if isinstance(s, dict))
    if text and not has_text_segment:
        segments.insert(0, {"type": "text", "text": text})

    # 3. Determine crop strategy (priority: manual_bbox > auto_region > full_page)
    final_png: bytes | None = None
    crop_confidence: float = 0.0
    pdf_bbox: list[float] | None = None
    crop_mode: str = "full_page_fallback"

    if manual_bbox is not None:
        # Priority 1: manual manifest bbox
        crop_mode = "manual_bbox"
        crop_confidence = 1.0
        pdf_bbox = manual_bbox
    else:
        # Priority 2: auto-detect figure region from PDF layout
        try:
            auto_png, auto_bbox, auto_confidence = detect_figure_region(
                pdf_path, page, dpi=dpi,
            )
            if auto_png is not None and auto_bbox is not None:
                crop_mode = "auto_region"
                crop_confidence = auto_confidence
                pdf_bbox = auto_bbox
                final_png = auto_png
            else:
                # Will fall back to full_page below
                pass
        except Exception as e:
            logger.warning(
                "Auto-crop failed for page %d (import_id=%s): %s, falling back to full page",
                page, qi.id, e,
            )

    # 4. Render + crop (or full page fallback)
    if crop_mode == "manual_bbox" or (crop_mode == "auto_region" and final_png is None):
        # Render page and crop at bbox
        try:
            page_png = render_page(pdf_path, page, dpi=dpi)
        except Exception as e:
            result.status = "failed"
            result.failure_reason = f"渲染第{page}页失败: {e}"
            return result

        if pdf_bbox:
            from PIL import Image, ImageChops
            import io as _io
            scale = dpi / 72
            img = Image.open(_io.BytesIO(page_png))
            if img.mode != "RGB":
                img = img.convert("RGB")
            px_bbox = (
                int(max(0, pdf_bbox[0] * scale)),
                int(max(0, pdf_bbox[1] * scale)),
                int(min(img.width, pdf_bbox[2] * scale)),
                int(min(img.height, pdf_bbox[3] * scale)),
            )
            if px_bbox[2] > px_bbox[0] and px_bbox[3] > px_bbox[1]:
                cropped = img.crop(px_bbox)
                buf = _io.BytesIO()
                cropped.save(buf, format="PNG")
                final_png = buf.getvalue()
            else:
                final_png = page_png

    if final_png is None:
        # Full-page fallback
        try:
            page_png = render_page(pdf_path, page, dpi=dpi)
        except Exception as e:
            result.status = "failed"
            result.failure_reason = f"渲染第{page}页失败: {e}"
            return result
        crop_mode = "full_page_fallback"
        crop_confidence = 0.0
        pdf_bbox = None
        final_png = full_page_crop(page_png)

    # 5. Set result metadata from crop strategy
    result.crop_mode = crop_mode
    result.bbox = pdf_bbox or [0, 0, 100, 100]
    result.crop_confidence = crop_confidence

    checksum = _compute_checksum(final_png)
    result.checksum = checksum

    # 6. Find existing image segment for this page (for dedup and replacement)
    existing_seg: dict | None = None
    existing_seg_idx: int | None = None
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
        if seg.get("type") != "image":
            continue
        if seg.get("asset_kind") == "question_figure" and seg.get("source_page") == page:
            existing_seg = seg
            existing_seg_idx = idx
            break

    # Dedup: check if same image already exists (same checksum)
    if existing_seg and existing_seg.get("checksum") == checksum:
        result.image_url = existing_seg.get("url")
        result.status = "skipped"
        result.skip_reason = "已存在相同图片（幂等跳过）"
        result.action = "skipped"
        return result

    # Record old image info for replacement
    old_image_url: str | None = None
    old_checksum: str | None = None
    if existing_seg:
        old_image_url = existing_seg.get("url")
        old_checksum = existing_seg.get("checksum")
        result.old_image_url = old_image_url
        result.old_checksum = old_checksum

    # Check crop_mode uses manual_bbox if we're acting on a manifest entry
    # (already set at the start of this function)

    # 7. Upload
    uploaded_asset: str | None = None
    if not dry_run:
        try:
            storage = get_question_assets_storage()
            month = datetime.now().strftime("%Y%m")
            filename = f"{month}/ds_sc/q_{qi.id}_p{page}_{checksum}.png"
            url = await storage.upload(filename, final_png)
            result.image_url = url
            uploaded_asset = url
        except Exception as e:
            result.status = "failed"
            result.failure_reason = f"上传图片失败: {e}"
            return result
    else:
        month = datetime.now().strftime("%Y%m")
        result.image_url = f"/static/question-assets/{month}/ds_sc/q_{qi.id}_p{page}_{checksum}.png"

    # 8. Build image segment
    image_seg = make_image_segment(
        url=result.image_url or "",
        alt="题目原图",
        region_type="illustration",
        source_page=page,
        bbox=result.bbox,
        coordinate_space="pdf_points",
        confidence=crop_confidence,
        requires_review=(crop_mode == "full_page_fallback"),
        display=True,
    )
    image_seg["asset_kind"] = "question_figure"
    image_seg["checksum"] = checksum
    image_seg["crop_mode"] = crop_mode

    # 9. Replace or append image segment
    if replace_existing and existing_seg_idx is not None:
        # Replace existing segment
        segments[existing_seg_idx] = image_seg
        result.action = "replaced"
    else:
        # Append new segment
        segments.append(image_seg)
        result.action = "inserted"

    # 10. Write to DB and clean up old image
    if not dry_run:
        try:
            qi.parsed_content = {
                **parsed_content,
                "render_mode": "segments",
                "segments": segments,
            }
            await db.flush()
        except Exception as e:
            result.status = "failed"
            result.failure_reason = f"DB 写入失败: {e}"
            # Orphan cleanup: remove new uploaded file
            if uploaded_asset:
                try:
                    storage = get_question_assets_storage()
                    if await storage.delete(uploaded_asset):
                        logger.info("Cleaned up orphan file: %s", uploaded_asset)
                    else:
                        logger.warning("Failed to clean up orphan file: %s", uploaded_asset)
                except Exception as cleanup_e:
                    logger.warning("Orphan cleanup error for %s: %s", uploaded_asset, cleanup_e)
            return result

        # DB write succeeded — now clean up old image file if this was a replacement
        if old_image_url and uploaded_asset and old_image_url != uploaded_asset:
            try:
                storage = get_question_assets_storage()
                if await storage.delete(old_image_url):
                    logger.info("Cleaned up replaced file: %s", old_image_url)
                else:
                    logger.warning(
                        "Could not delete old file (may have been already removed): %s",
                        old_image_url,
                    )
            except Exception as cleanup_e:
                logger.warning(
                    "Old file cleanup error for %s: %s", old_image_url, cleanup_e,
                )

    result.status = "success"
    return result


async def _backfill_page_numbers(
    db: AsyncSession,
    import_ids: list[int] | None = None,
    all_records: bool = False,
    dry_run: bool = True,
) -> list[dict]:
    """Backfill source_page_start and source_page_end for question_imports.

    Resolves page numbers from the same fallback chain as process_single_question,
    and writes them back to the database field (not just raw_data).

    Returns list of result dicts with import_id, page, action.
    """
    conditions = [QuestionImport.status == "pending", QuestionImport.question_id.is_(None)]
    if not all_records and import_ids:
        conditions.append(QuestionImport.id.in_(import_ids))

    from sqlalchemy import select as _select
    stmt = _select(QuestionImport).where(*conditions).order_by(QuestionImport.id.asc())
    rows = (await db.execute(stmt)).scalars().all()

    page_results: list[dict] = []
    for qi in rows:
        page = (
            qi.source_page_start
            or resolve_source_page(qi.raw_data)
            or KNOWN_PAGE_MAP.get(qi.id)
        )
        action = "would_update" if dry_run else "updated"
        if page is not None and qi.source_page_start is None:
            if not dry_run:
                qi.source_page_start = page
                qi.source_page_end = page
            page_results.append({
                "import_id": qi.id,
                "page": page,
                "action": action,
                "field_was_empty": qi.source_page_start is None,
            })
        elif page is not None and qi.source_page_start is not None:
            page_results.append({
                "import_id": qi.id,
                "page": qi.source_page_start,
                "action": "already_set",
            })

    return page_results


async def backfill_question_images(
    db_url: str,
    pdf_path: str,
    import_ids: list[int] | None = None,
    mode: str = "full-page",
    dpi: int = 200,
    dry_run: bool = True,
    force: bool = False,
    region_manifest: dict[int, dict] | None = None,
    replace_existing: bool = False,
    allow_unverified: bool = False,
    backfill_pages: bool = True,
    backfill_all_pages: bool = False,
) -> list[BackfillResult]:
    """Main backfill logic."""
    # Validate PDF
    total_pages = await validate_pdf(pdf_path)

    engine = create_async_engine(db_url, echo=False)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    results: list[BackfillResult] = []

    async with SessionFactory() as db:
        # Build query conditions
        conditions = [QuestionImport.status == "pending", QuestionImport.question_id.is_(None)]
        if import_ids:
            conditions.append(QuestionImport.id.in_(import_ids))

        # Fetch records
        stmt = select(QuestionImport).where(*conditions).order_by(QuestionImport.id.asc())
        rows = (await db.execute(stmt)).scalars().all()

        if not rows:
            logger.warning("No matching question_imports found")
            return results

        logger.info("Found %d question_imports to process", len(rows))

        for qi in rows:
            # Check skip list
            if qi.id in SKIP_IDS_DEFAULT and not force:
                res = BackfillResult(
                    import_id=qi.id,
                    status="skipped",
                    skip_reason=f"ID {qi.id} 在默认跳过列表中（\"图G\"为数学对象名，非实际图片）",
                )
                if qi.id in KNOWN_PAGE_MAP:
                    res.page = KNOWN_PAGE_MAP[qi.id]
                results.append(res)
                continue

            # Look up manual bbox from manifest
            manual_bbox = None
            if region_manifest and qi.id in region_manifest:
                entry = region_manifest[qi.id]
                if not entry.get("verified") and not allow_unverified:
                    # Skip unverified manifest entries (unless explicitly allowed)
                    res = BackfillResult(
                        import_id=qi.id,
                        status="skipped",
                        skip_reason=f"ID {qi.id} 在 manifest 中但未确认(verified=false)，使用 --allow-unverified-regions 强制使用",
                    )
                    if qi.id in KNOWN_PAGE_MAP:
                        res.page = KNOWN_PAGE_MAP[qi.id]
                    results.append(res)
                    continue
                if "bbox" in entry:
                    manual_bbox = entry["bbox"]

            try:
                res = await process_single_question(
                    db, qi, pdf_path, dpi, force, dry_run,
                    manual_bbox=manual_bbox,
                    replace_existing=replace_existing,
                )
                results.append(res)

                if res.status == "success" and not dry_run:
                    await db.commit()
                    logger.info(
                        "  ✓ import_id=%s page=%s → %s",
                        res.import_id, res.page, res.image_url,
                    )
                elif res.status == "success" and dry_run:
                    logger.info(
                        "  [DRY-RUN] import_id=%s page=%s → %s",
                        res.import_id, res.page, res.image_url,
                    )
                elif res.status == "skipped":
                    logger.info("  - import_id=%s skipped: %s", res.import_id, res.skip_reason)
                else:
                    logger.warning(
                        "  ✗ import_id=%s failed: %s",
                        res.import_id, res.failure_reason,
                    )
            except Exception as e:
                logger.exception("Unexpected error processing import_id=%s", qi.id)
                results.append(BackfillResult(
                    import_id=qi.id,
                    status="failed",
                    failure_reason=f"未预期错误: {e}",
                ))

        # Page number backfill
        if backfill_pages and (backfill_all_pages or import_ids):
            page_ids = None if backfill_all_pages else import_ids
            page_results = await _backfill_page_numbers(
                db, import_ids=page_ids, all_records=backfill_all_pages, dry_run=dry_run,
            )
            if not dry_run and page_results:
                await db.commit()
            # Log page backfill results
            updated = [r for r in page_results if r["action"] == "updated"]
            would_update = [r for r in page_results if r["action"] == "would_update"]
            if updated:
                logger.info("页码回填: %d 条已更新", len(updated))
                for r in updated:
                    logger.info("  import_id=%s → source_page_start=%s", r["import_id"], r["page"])
            elif would_update:
                logger.info("页码回填(dry-run): %d 条将更新", len(would_update))
                for r in would_update[:5]:
                    logger.info("  import_id=%s → source_page_start=%s (dry-run)", r["import_id"], r["page"])
                if len(would_update) > 5:
                    logger.info("  … 以及 %d 条", len(would_update) - 5)

    await engine.dispose()
    return results


def generate_report(results: list[BackfillResult], output_path: str | None = None) -> dict:
    """Generate summary report and optionally write to file."""
    stats = {"total": 0, "success": 0, "skipped": 0, "failed": 0}
    items = []

    for r in results:
        stats["total"] += 1
        stats[r.status] = stats.get(r.status, 0) + 1
        items.append({
            "import_id": r.import_id,
            "page": r.page,
            "status": r.status,
            "crop_mode": r.crop_mode,
            "crop_confidence": r.crop_confidence,
            "bbox": r.bbox,
            "image_url": r.image_url,
            "checksum": r.checksum,
            "skip_reason": r.skip_reason,
            "failure_reason": r.failure_reason,
            "action": r.action,
            "old_image_url": r.old_image_url,
            "old_checksum": r.old_checksum,
        })

    report = {
        "summary": stats,
        "generated_at": datetime.now().isoformat(),
        "items": items,
    }

    if output_path:
        ext = os.path.splitext(output_path)[1].lower()
        if ext == ".csv":
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=items[0].keys() if items else [])
                writer.writeheader()
                writer.writerows(items)
            logger.info("CSV report written to %s", output_path)
        else:
            with open(output_path, "w") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            logger.info("JSON report written to %s", output_path)

    return report


def parse_ids(value: str | None) -> list[int] | None:
    """Parse comma-separated IDs."""
    if not value:
        return None
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def _backup_sqlite(db_path: str, backup_dir: str) -> tuple[str, str]:
    """备份 SQLite 数据库文件。返回 (备份路径, 文件MD5[:12])。"""
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"postgraduate_backup_{ts}.db")
    import shutil
    shutil.copy2(db_path, backup_path)
    with open(db_path, "rb") as f:
        original_hash = _compute_checksum(f.read())
    with open(backup_path, "rb") as f:
        backup_hash = _compute_checksum(f.read())
    logger.info("Database backup: %s (original md5[:12]=%s)", backup_path, original_hash)
    assert original_hash == backup_hash, "Backup checksum mismatch!"
    return backup_path, original_hash


def _db_file_path(db_url: str) -> str | None:
    """Extract SQLite file path from URL, or return None for non-SQLite."""
    if db_url.startswith("sqlite"):
        # sqlite+aiosqlite:///path or sqlite:///path
        path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
        return path
    return None


async def _db_snapshot(db: AsyncSession) -> dict:
    """Take a pre/post execution snapshot of key metrics."""
    from sqlalchemy import select, func
    from app.models.question_import import QuestionImport
    from app.models.question import Question

    qi_total = await db.scalar(select(func.count()).select_from(QuestionImport))
    qi_pending = await db.scalar(
        select(func.count()).select_from(QuestionImport).where(QuestionImport.status == "pending")
    )
    qi_linked = await db.scalar(
        select(func.count()).select_from(QuestionImport).where(QuestionImport.question_id.isnot(None))
    )
    q_total = await db.scalar(select(func.count()).select_from(Question))
    return {
        "question_imports_total": qi_total or 0,
        "pending_count": qi_pending or 0,
        "linked_question_count": qi_linked or 0,
        "questions_total": q_total or 0,
    }


async def _verify_invariants(pre: dict, post: dict) -> list[str]:
    """Verify execution invariants. Returns list of violations (empty = all pass)."""
    violations = []
    if pre["questions_total"] != post["questions_total"]:
        violations.append(
            f"questions 数量变化: {pre['questions_total']} → {post['questions_total']}"
        )
    if pre["question_imports_total"] != post["question_imports_total"]:
        violations.append(
            f"question_imports 总数变化: {pre['question_imports_total']} → {post['question_imports_total']}"
        )
    return violations


def main():
    parser = argparse.ArgumentParser(
        description="Backfill question images for data-structure PDF import",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run preview
  python scripts/backfill_question_images.py \\
      --db sqlite+aiosqlite:///./postgraduate.db \\
      --pdf artifacts/ds_sc.pdf \\
      --dry-run

  # Backfill specific IDs with manifest
  python scripts/backfill_question_images.py \\
      --db sqlite+aiosqlite:///./postgraduate.db \\
      --pdf artifacts/ds_sc.pdf \\
      --ids 229,369,371 \\
      --region-manifest artifacts/data-structure-import/question-image-regions.json

  # Full backfill with report and backup
  python scripts/backfill_question_images.py \\
      --db sqlite+aiosqlite:///./postgraduate.db \\
      --pdf artifacts/ds_sc.pdf \\
      --no-dry-run \\
      --output-report backfill_report.json \\
      --backup-dir artifacts/data-structure-import/backups
        """,
    )
    parser.add_argument("--db", required=True, help="Database URL (e.g. sqlite+aiosqlite:///./postgraduate.db)")
    parser.add_argument("--pdf", required=True, help="Path to source PDF file (ds_sc.pdf)")
    parser.add_argument("--ids", help="Comma-separated import IDs to process (default: all pending with page info)")
    parser.add_argument("--mode", choices=["auto", "full-page"], default="full-page", help="Crop mode (default: full-page)")
    parser.add_argument("--dpi", type=int, default=200, help="Page render DPI (default: 200)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview changes without applying (default: true)")
    parser.add_argument("--no-dry-run", action="store_false", dest="dry_run", help="Actually apply changes")
    parser.add_argument("--force", action="store_true", help="Process IDs in the default skip list")
    parser.add_argument("--output-report", help="Path to output report JSON/CSV file")
    parser.add_argument("--region-manifest", help="Path to JSON file with manual bbox definitions (import_id → {page, bbox, note})")
    parser.add_argument("--backup-dir", default="artifacts/data-structure-import/backups", help="Directory for DB backups (default: artifacts/data-structure-import/backups)")
    parser.add_argument("--skip-backup", action="store_true", help="Skip database backup even in --no-dry-run mode")
    parser.add_argument("--include-optional", action="store_true", help="Include optional IDs (e.g. 345) in processing")
    parser.add_argument("--replace-existing-images", action="store_true", help="Replace existing image segments for the same page (instead of appending)")
    parser.add_argument("--allow-unverified-regions", action="store_true", help="Allow unverified entries in region manifest")
    parser.add_argument("--backfill-pages", action="store_true", default=True, help="Backfill source_page_start/source_page_end (default: true)")
    parser.add_argument("--no-backfill-pages", action="store_false", dest="backfill_pages", help="Skip page number backfill")
    parser.add_argument("--backfill-all-pages", action="store_true", help="Backfill page numbers for ALL pending records, not just the processed subset")

    args = parser.parse_args()

    # Load region manifest
    region_manifest: dict[int, dict] = {}
    if args.region_manifest:
        if not os.path.exists(args.region_manifest):
            logger.error("Region manifest not found: %s", args.region_manifest)
            sys.exit(1)
        with open(args.region_manifest) as f:
            raw = json.load(f)
            for k, v in raw.items():
                try:
                    region_manifest[int(k)] = v
                except (ValueError, TypeError):
                    pass
        logger.info("Loaded %d entries from region manifest", len(region_manifest))

    # Actual execution requires --no-dry-run; default is dry-run
    backup_path: str | None = None
    if args.dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE — no changes will be made to the database or files")
        logger.info("=" * 60)
    else:
        # Database backup
        db_path = _db_file_path(args.db)
        if db_path:
            if not args.skip_backup:
                backup_path, original_hash = _backup_sqlite(db_path, args.backup_dir)
                logger.info("Database backed up: %s (md5[:12]=%s)", backup_path, original_hash)
            else:
                logger.info("Database backup skipped (--skip-backup)")
        else:
            logger.warning(
                "Non-SQLite database detected. Automatic backup not supported. "
                "Please ensure you have a manual backup before proceeding."
            )
            logger.warning("Set --skip-backup to suppress this warning and continue.")

    import_ids = parse_ids(args.ids)

    # Take pre-execution snapshot
    engine = create_async_engine(args.db, echo=False)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        pre_snapshot = {}
        async with SessionFactory() as db:
            pre_snapshot = await _db_snapshot(db)

        results = await backfill_question_images(
            db_url=args.db,
            pdf_path=args.pdf,
            import_ids=import_ids,
            mode=args.mode,
            dpi=args.dpi,
            dry_run=args.dry_run,
            force=args.force,
            region_manifest=region_manifest if region_manifest else None,
            replace_existing=args.replace_existing_images,
            allow_unverified=args.allow_unverified_regions,
            backfill_pages=args.backfill_pages,
            backfill_all_pages=args.backfill_all_pages,
        )

        post_snapshot = {}
        async with SessionFactory() as db:
            post_snapshot = await _db_snapshot(db)
            if not args.dry_run:
                violations = await _verify_invariants(pre_snapshot, post_snapshot)
                if violations:
                    for v in violations:
                        logger.error("INVARIANT VIOLATION: %s", v)
                    sys.exit(2)

        # Generate report
        report = generate_report(results, args.output_report)
        if args.output_report:
            # Also embed pre/post snapshots and backup path
            report["pre_snapshot"] = pre_snapshot
            report["post_snapshot"] = post_snapshot
            if backup_path:
                report["backup_path"] = backup_path
            with open(args.output_report, "w") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        s = report["summary"]

        print()
        print("=" * 60)
        print("Backfill Report")
        print("=" * 60)
        print(f"  Total:    {s['total']}")
        print(f"  Success:  {s.get('success', 0)}")
        print(f"  Skipped:  {s.get('skipped', 0)}")
        print(f"  Failed:   {s.get('failed', 0)}")
        if not args.dry_run:
            print()
            print("  Pre/Post:")
            for k, v in pre_snapshot.items():
                delta = post_snapshot.get(k, v)
                changed = " ⬆" if delta > v else " ⬇" if delta < v else ""
                print(f"    {k}: {v} → {delta}{changed}")
        if args.dry_run:
            print(f"\n  ⚠  DRY RUN — no changes persisted. Re-run with --no-dry-run to apply.")
        print()

        # Print success/failure details
        for item in report["items"]:
            if item["status"] == "success":
                cm = item.get("crop_mode", "?")
                cc = item.get("crop_confidence", 0)
                print(f"  ✓ #{item['import_id']} (p{item['page']} [{cm}] conf={cc}) → {item['image_url']}")
            elif item["status"] == "skipped":
                print(f"  - #{item['import_id']}: {item['skip_reason']}")
            elif item["status"] == "failed":
                print(f"  ✗ #{item['import_id']}: {item['failure_reason']}")

    asyncio.run(_run())
    # Dispose engine after async run completes
    import gc
    gc.collect()


if __name__ == "__main__":
    main()
