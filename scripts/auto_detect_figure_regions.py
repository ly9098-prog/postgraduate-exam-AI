#!/usr/bin/env python3
"""CV-based figure detection and bbox refinement for scanned PDF pages.

Two-pass approach:
1. CV detects candidate figure region
2. Expands bbox generously, crops, auto-trims to content, adds padding
3. Saves refined bbox to manifest

Usage:
    python scripts/auto_detect_figure_regions.py \\
        --pdf artifacts/data-structure-import/source/ds_sc.pdf \\
        --output artifacts/data-structure-import/question-image-regions.json
"""

import argparse
import json
import logging
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("auto_figure_detect")

TARGETS = {
    229: 108, 369: 286, 371: 288, 380: 297, 388: 307,
    395: 314, 397: 316, 400: 319, 402: 321, 405: 324,
    407: 326, 411: 330, 412: 331, 451: 370, 457: 376,
    460: 379, 461: 380, 472: 391, 480: 399,
}

RENDER_DPI = 200


def load_existing_manifest(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def render_page_pil(pdf_path: str, page_num: int, dpi: int = 200):
    """Render PDF page to PIL Image."""
    import fitz
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img, pix.width, pix.height
    finally:
        doc.close()


def detect_candidate(pil_img: Image.Image) -> tuple[list[int], float]:
    """CV detection on scanned page to find figure region.

    Returns (bbox_pixels, confidence) where bbox_pixels = [x0, y0, x1, y1].
    """
    w, h = pil_img.size
    gray = pil_img.convert("L")
    img_np = np.array(gray)

    # Adaptive threshold
    binary = cv2.adaptiveThreshold(img_np, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 31, 10)

    # Dilate to connect nearby components
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    dilated = cv2.dilate(binary, kernel, iterations=2)

    # Find contours
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        cy_ratio = (y + ch / 2) / h

        if cw < 30 or ch < 20:
            continue
        if cw > w * 0.95 and ch > h * 0.95:
            continue
        if cy_ratio < 0.15 or cy_ratio > 0.85:
            continue
        aspect = cw / max(ch, 1)
        if aspect > 6:
            continue

        pos_score = 1.0 - abs(cy_ratio - 0.5) * 2.5
        size_score = min(area / 50000, 1.0)
        compact_score = 1.0 if aspect < 3 else max(0, 1.0 - (aspect - 3) * 0.2)
        score = 0.3 * pos_score + 0.4 * size_score + 0.3 * compact_score
        candidates.append({"x": x, "y": y, "w": cw, "h": ch, "score": score, "cy_ratio": cy_ratio})

    if not candidates:
        return None, 0.0

    best = max(candidates, key=lambda c: c["score"])

    # Expand generously (doubled height, wider width)
    expand_top = best["h"] * 0.8
    expand_bottom = best["h"] * 0.8
    expand_sides = best["w"] * 0.3

    x0 = max(0, int(best["x"] - expand_sides))
    y0 = max(0, int(best["y"] - expand_top))
    x1 = min(w, int(best["x"] + best["w"] + expand_sides))
    y1 = min(h, int(best["y"] + best["h"] + expand_bottom))

    return [x0, y0, x1, y1], best["score"]


def refine_with_autotrim(pil_img: Image.Image, bbox_pixels: list[int]) -> list[int]:
    """Crop at bbox, then auto-trim white margins, then add padding."""
    x0, y0, x1, y1 = bbox_pixels
    cropped = pil_img.crop((x0, y0, x1, y1))
    cw, ch = cropped.size

    if cw < 10 or ch < 10:
        return bbox_pixels

    # Auto-trim white margins
    bg = Image.new("RGB", cropped.size, (255, 255, 255))
    diff = ImageChops.difference(cropped, bg)
    trim = diff.getbbox()
    if trim:
        pad = 12  # 12 pixels padding (about 4.3 PDF points at 200 DPI)
        tx0 = max(0, trim[0] - pad)
        ty0 = max(0, trim[1] - pad)
        tx1 = min(cw, trim[2] + pad)
        ty1 = min(ch, trim[3] + pad)
        if tx1 > tx0 and ty1 > ty0:
            # Convert trimmed bbox back to page coordinates
            return [
                x0 + tx0,
                y0 + ty0,
                x0 + tx1,
                y0 + ty1,
            ]

    return bbox_pixels


def pixels_to_pdf(bbox_pixels: list[int], dpi: int) -> list[float]:
    scale = 72.0 / dpi
    return [round(v * scale, 1) for v in bbox_pixels]


def main():
    parser = argparse.ArgumentParser(description="Auto-detect figure regions on scanned PDF pages")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--output", default="artifacts/data-structure-import/question-image-regions.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ids", help="Comma-separated subset")
    args = parser.parse_args()

    target_ids = [int(x.strip()) for x in args.ids.split(",")] if args.ids else sorted(TARGETS.keys())
    existing = load_existing_manifest(args.output)

    results = {}
    for qid in target_ids:
        page = TARGETS.get(qid)
        if not page:
            continue

        logger.info(f"  [DETECT] qid={qid} page={page} ...")
        try:
            pil_img, w, h = render_page_pil(args.pdf, page, dpi=RENDER_DPI)

            # Pass 1: CV detection
            bbox_px, conf = detect_candidate(pil_img)
            if not bbox_px:
                logger.info("  NO CANDIDATE from CV")
                continue

            # Pass 2: Refine with expansion + auto-trim
            refined_px = refine_with_autotrim(pil_img, bbox_px)
            bbox_pdf = pixels_to_pdf(refined_px, RENDER_DPI)

            logger.info(f"  bbox_pdf={bbox_pdf} conf={conf:.2f} "
                        f"crop_size={refined_px[2]-refined_px[0]}x{refined_px[3]-refined_px[1]}px")

            entry = existing.get(str(qid), {})
            entry["page"] = page
            entry["bbox"] = bbox_pdf
            entry["coordinate_space"] = "pdf_points"
            entry["render_dpi"] = RENDER_DPI
            entry["crop_confidence"] = round(conf, 2)
            entry["method"] = "cv_auto_trim"
            entry["note"] = entry.get("note", "")
            if "verified" not in entry:
                entry["verified"] = False
            existing[str(qid)] = entry
            results[str(qid)] = entry

        except Exception as e:
            logger.error(f"  ERROR: {e}")

    if not args.dry_run:
        with open(args.output, "w") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        logger.info(f"\nWritten {len(results)} entries to {args.output}")
    else:
        print("\n=== DRY RUN ===")
        print(json.dumps(results, ensure_ascii=False, indent=2))

    print(f"\nSummary: {len(results)}/{len(target_ids)} targets")


if __name__ == "__main__":
    main()
