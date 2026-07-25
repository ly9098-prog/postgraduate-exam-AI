#!/usr/bin/env python3
"""调试脚本：对指定的 PDF 页码和题号生成 question_bbox 截图。

Usage:
    python scripts/debug_question_snapshot.py \
        --pdf "24王道数据结构选择做题本.pdf" \
        --page 295 \
        --question 15 \
        --out /tmp/question_15_snapshot.png

Requires:
    - PyMuPDF (fitz)
    - PIL (Pillow)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("debug_question_snapshot")


def main():
    parser = argparse.ArgumentParser(description="Debug question_bbox snapshot generation")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--page", type=int, required=True, help="Page number (1-based)")
    parser.add_argument("--question", type=int, default=None, help="Question number (optional)")
    parser.add_argument("--out", default="/tmp/question_snapshot.png", help="Output PNG path")
    args = parser.parse_args()

    pdf_path = args.pdf
    page = args.page
    question_num = args.question
    out_path = args.out

    if not os.path.isfile(pdf_path):
        logger.error("PDF not found: %s", pdf_path)
        sys.exit(1)

    # ── Step 1: Open PDF and render page to get OCR boxes ──
    logger.info("Opening PDF: %s", pdf_path)
    logger.info("Page: %d, Question: %s", page, question_num or "auto")

    try:
        import fitz
    except ImportError:
        logger.error("PyMuPDF (fitz) not installed. Run: pip install PyMuPDF")
        sys.exit(1)

    doc = fitz.open(pdf_path, filetype="pdf")
    if page < 1 or page > len(doc):
        logger.error("Page %d out of range (PDF has %d pages)", page, len(doc))
        doc.close()
        sys.exit(1)

    # ── Step 2: Render page at standard OCR DPI (150) for OCR processing ──
    pdf_page = doc[page - 1]
    page_rect = pdf_page.rect
    pdf_w = page_rect.width
    pdf_h = page_rect.height

    pix = pdf_page.get_pixmap(dpi=150)
    img_w = pix.width
    img_h = pix.height
    logger.info("PDF page size: %.1f x %.1f pts", pdf_w, pdf_h)
    logger.info("Rendered image size: %d x %d px", img_w, img_h)

    # Save the rendered page for reference
    render_temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    render_path = render_temp.name
    pix.save(render_path)
    logger.info("Rendered page saved to: %s", render_path)

    # ── Step 3: Simulate OCR blocks (we need boxes for the snapshot service) ──
    # For a debug script, extract text blocks with position info from the PDF
    # In a real pipeline, this would be actual OCR output
    try:
        from PIL import Image
    except ImportError:
        logger.error("Pillow not installed. Run: pip install Pillow")
        doc.close()
        sys.exit(1)

    # Extract text with positions
    blocks = pdf_page.get_text("dict")["blocks"]

    # Build simulated OCR blocks
    text_lines = []
    boxes = []
    for block in blocks:
        if block.get("type") != 0:  # Skip image blocks
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                bbox = span.get("bbox", [0, 0, 0, 0])
                # Convert PDF points to image pixels (150 DPI)
                scale_x = img_w / pdf_w
                scale_y = img_h / pdf_h
                text_lines.append(text)
                boxes.append({
                    "bbox": [
                        bbox[0] * scale_x,
                        bbox[1] * scale_y,
                        bbox[2] * scale_x,
                        bbox[3] * scale_y,
                    ],
                    "confidence": 0.95,
                })

    logger.info("Extracted %d text lines from PDF", len(text_lines))

    # Combine into a single "block" for the snapshot service
    normalized_blocks = [
        {
            "page": page,
            "text": "\n".join(text_lines),
            "normalized_text": "\n".join(text_lines),
            "boxes": boxes,
            "page_width": img_w,
            "page_height": img_h,
        },
    ]

    # ── Step 4: Build OCR lines and compute question bbox ──
    from app.services.question_snapshot_service import build_ocr_lines, compute_question_bbox

    ocr_lines = build_ocr_lines(normalized_blocks)
    logger.info("OCR lines after header filtering: %d", len(ocr_lines))

    # Print first few lines for debugging
    for i, line in enumerate(ocr_lines[:20]):
        logger.info("  line[%d]: text=%.60s bbox=%s zone=%s",
                     i, line["text"], line["bbox"], line["zone"])

    # Build raw_question
    raw_q = {
        "page_start": page,
        "source_question_no": question_num,
        "raw_question_text": "",
        "option_lines": {},
    }

    result = compute_question_bbox(raw_q, ocr_lines, page)
    bbox = result.get("question_bbox")
    strategy = result.get("question_bbox_strategy", "unknown")
    confidence = result.get("question_bbox_confidence", 0.0)
    diagnostics = result.get("question_bbox_diagnostics", {})

    logger.info("=" * 60)
    logger.info("question_bbox result:")
    logger.info("  bbox: %s", bbox)
    logger.info("  strategy: %s", strategy)
    logger.info("  confidence: %.4f", confidence)
    logger.info("  coordinate_space: %s", result.get("question_bbox_coordinate_space"))
    logger.info("  page_width: %d", result.get("question_bbox_page_width", 0))
    logger.info("  page_height: %d", result.get("question_bbox_page_height", 0))
    logger.info("  diagnostics: %s", diagnostics)

    # ── Step 5: Generate snapshot ──
    from app.services.question_snapshot_service import render_source_snapshot

    if bbox and len(bbox) == 4:
        png_bytes = render_source_snapshot(
            pdf_path, page, bbox, img_w, img_h,
            dpi=220, max_long_side=3200,
        )
    else:
        logger.warning("No valid bbox, rendering full page at 150 DPI")
        png_bytes = pix.tobytes("png")

    if png_bytes:
        with open(out_path, "wb") as f:
            f.write(png_bytes)
        logger.info("=" * 60)
        logger.info("Snapshot saved to: %s", out_path)

        # Report dimensions
        snapshot_img = Image.open(out_path)
        logger.info("  output_width: %d", snapshot_img.width)
        logger.info("  output_height: %d", snapshot_img.height)
        logger.info("  output_format: %s", snapshot_img.format)
    else:
        logger.error("Failed to generate snapshot")

    doc.close()

    # Cleanup
    try:
        os.unlink(render_path)
    except OSError:
        pass


if __name__ == "__main__":
    main()
