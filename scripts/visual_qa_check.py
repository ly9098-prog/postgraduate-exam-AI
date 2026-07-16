#!/usr/bin/env python3
"""Comprehensive visual QA for 19 cropped question images.

Generates:
- reports/visual-qa/q_ID_pPAGE_review.png (comparison images)
- reports/question-image-visual-qa.json (QA results)
- reports/question-image-visual-qa-final.html (visual review HTML)

Analyzes:
- Cropped image dimensions, aspect ratio, ink density
- Content touching edges (possible cutoff)
- Bbox coverage of figure region
"""

import json
import os
import sys
import hashlib
from datetime import datetime, timezone

import fitz
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

# ── Paths ──
BASE = "/home/lmh/projects/postgraduate-ai"
MANIFEST_PATH = os.path.join(BASE, "artifacts/data-structure-import/question-image-regions.json")
PDF_PATH = os.path.join(BASE, "artifacts/data-structure-import/source/ds_sc.pdf")
CROPS_DIR = os.path.join(BASE, "static/question-assets/202607/ds_sc")
OUT_DIR = os.path.join(BASE, "artifacts/data-structure-import/reports/visual-qa")
QA_JSON_PATH = os.path.join(BASE, "artifacts/data-structure-import/reports/question-image-visual-qa.json")
QA_HTML_PATH = os.path.join(BASE, "artifacts/data-structure-import/reports/question-image-visual-qa-final.html")

os.makedirs(OUT_DIR, exist_ok=True)

DPI = 200
SCALE = DPI / 72.0

TARGETS = {
    229: 108, 369: 286, 371: 288, 380: 297, 388: 307,
    395: 314, 397: 316, 400: 319, 402: 321, 405: 324,
    407: 326, 411: 330, 412: 331, 451: 370, 457: 376,
    460: 379, 461: 380, 472: 391, 480: 399,
}

# Name mapping for human-readable type info
FIGURE_TYPES = {
    229: "火车轨道", 369: "图论-有向图", 371: "邻接表", 380: "图论-有向图",
    388: "图论-无向图", 395: "图论-二叉树", 397: "图论-有向图",
    400: "图论-有向图", 402: "图论-二叉树", 405: "图论-二叉树",
    407: "图论-有向图", 411: "图论-有向图", 412: "图论-有向图",
    451: "树-B树", 457: "树-B树", 460: "树-二叉树", 461: "树-排序树",
    472: "树-哈夫曼树", 480: "树-二叉树",
}


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def render_page_pil(pdf_path, page_num, dpi=200):
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img, pix.width, pix.height
    finally:
        doc.close()


def pdf_to_pixels(bbox_pdf, scale):
    """Convert PDF points to pixel coordinates."""
    return [int(v * scale) for v in bbox_pdf]


def analyze_crop(image_path):
    """Analyze a cropped image for quality indicators."""
    if not os.path.exists(image_path):
        return {"exists": False, "error": "File not found"}

    img = Image.open(image_path)
    w, h = img.size

    # Gray version for ink analysis
    gray = img.convert("L")
    pixels = list(gray.getdata())
    total_pixels = len(pixels)

    # Count "ink" pixels (darker than threshold)
    ink_pixels = sum(1 for p in pixels if p < 200)
    ink_ratio = ink_pixels / total_pixels if total_pixels > 0 else 0

    # Very dark pixels (solid ink, no anti-aliasing)
    dark_pixels = sum(1 for p in pixels if p < 50)
    dark_ratio = dark_pixels / total_pixels if total_pixels > 0 else 0

    # Edge analysis: check if content touches edges
    # Sample edges (5px border)
    edge_ink = 0
    edge_total = 0
    for x in range(w):
        for y in range(5):  # top 5 rows
            if gray.getpixel((x, y)) < 200:
                edge_ink += 1
            edge_total += 1
        for y in range(max(0, h-5), h):  # bottom 5 rows
            if gray.getpixel((x, y)) < 200:
                edge_ink += 1
            edge_total += 1
    for y in range(h):
        for x in range(5):  # left 5 cols
            if gray.getpixel((x, y)) < 200:
                edge_ink += 1
            edge_total += 1
        for x in range(max(0, w-5), w):  # right 5 cols
            if gray.getpixel((x, y)) < 200:
                edge_ink += 1
            edge_total += 1

    edge_ratio = edge_ink / edge_total if edge_total > 0 else 0

    # Check if crop is too small (suspicious)
    too_small = (w < 100 or h < 100)

    # Check if very wide but very short (might miss content)
    aspect = w / max(h, 1)

    # Content bounding box (auto-trim white)
    bg = Image.new("RGB", img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg)
    content_bbox = diff.getbbox()

    content_margin_top = content_bbox[1] if content_bbox else 0
    content_margin_bottom = h - content_bbox[3] if content_bbox else 0
    content_margin_left = content_bbox[0] if content_bbox else 0
    content_margin_right = w - content_bbox[2] if content_bbox else 0

    content_width = content_bbox[2] - content_bbox[0] if content_bbox else 0
    content_height = content_bbox[3] - content_bbox[1] if content_bbox else 0

    # Check if content is too close to edge (possible cutoff)
    has_cutoff_risk = (content_margin_top < 3 or content_margin_bottom < 3 or
                       content_margin_left < 3 or content_margin_right < 3)

    # Check if the crop has significant whitespace on one side
    whitespace_ratio = 1.0 - ((content_width * content_height) / max(w * h, 1))

    # File size per pixel (indicator of quality/compression)
    file_size = os.path.getsize(image_path)
    bytes_per_pixel = file_size / max(w * h, 1)

    # Checksum
    with open(image_path, "rb") as f:
        checksum = hashlib.md5(f.read()).hexdigest()

    return {
        "exists": True,
        "width": w,
        "height": h,
        "aspect_ratio": round(aspect, 2),
        "ink_ratio": round(ink_ratio, 4),
        "dark_ratio": round(dark_ratio, 4),
        "edge_ink_ratio": round(edge_ratio, 4),
        "too_small": too_small,
        "content_bbox": list(content_bbox) if content_bbox else None,
        "content_margin": {
            "top": content_margin_top,
            "bottom": content_margin_bottom,
            "left": content_margin_left,
            "right": content_margin_right,
        },
        "has_cutoff_risk": has_cutoff_risk,
        "whitespace_ratio": round(whitespace_ratio, 3),
        "bytes_per_pixel": round(bytes_per_pixel, 4),
        "file_size_bytes": file_size,
        "checksum_md5": checksum,
    }


def draw_bbox_on_page(page_img, bbox_pdf, scale, color="#FF0000", width=4):
    """Draw bbox rectangle on a rendered page image."""
    draw = ImageDraw.Draw(page_img)
    x0, y0, x1, y1 = [int(v * scale) for v in bbox_pdf]
    draw.rectangle([x0, y0, x1, y1], outline=color, width=width)
    return page_img


def generate_comparison_image(qid, page_num, manifest, crop_path, out_dir):
    """Generate a multi-panel comparison image."""
    page_img, pw, ph = render_page_pil(PDF_PATH, page_num, DPI)
    bbox = manifest.get("bbox", [0, 0, pw/SCALE, ph/SCALE])

    # Marked page
    marked = page_img.copy()
    draw = ImageDraw.Draw(marked)
    bx0, by0, bx1, by1 = [int(v * SCALE) for v in bbox]
    draw.rectangle([bx0, by0, bx1, by1], outline=(255, 0, 0), width=5)

    # Cropped image
    crop_img = Image.open(crop_path) if os.path.exists(crop_path) else None

    # Determine layout based on page/crop sizes
    page_w_display = 600
    page_ratio = ph / pw
    page_h_display = int(page_w_display * page_ratio)

    marked_resized = marked.resize((page_w_display, page_h_display), Image.LANCZOS)

    # Cropped display (scale to max 400 wide)
    if crop_img:
        cw, ch = crop_img.size
        if cw > ch:
            crop_display_w = 400
            crop_display_h = int(400 * ch / cw)
        else:
            crop_display_h = 400
            crop_display_w = int(400 * cw / ch)
        crop_resized = crop_img.resize((crop_display_w, crop_display_h), Image.LANCZOS)
    else:
        crop_resized = Image.new("RGB", (200, 100), (200, 200, 200))
        crop_display_w, crop_display_h = 200, 100

    # Zoomed crop region (2x from original crop)
    if crop_img:
        zoom_factor = 3
        zoom_w = min(crop_img.width * zoom_factor, 800)
        zoom_h = int(zoom_w * crop_img.height / crop_img.width)
        zoomed = crop_img.resize((zoom_w, zoom_h), Image.NEAREST)
    else:
        zoomed = Image.new("RGB", (400, 200), (200, 200, 200))
        zoom_w, zoom_h = 400, 200

    # Full canvas
    margin = 20
    title_h = 180
    panel_gap = 15

    row1_h = max(page_h_display, crop_display_h)
    row2_h = zoom_h
    total_w = page_w_display + panel_gap + max(crop_display_w, 400) + panel_gap + 400
    total_h = title_h + row1_h + panel_gap + row2_h + margin

    canvas = Image.new("RGB", (total_w, total_h), (245, 245, 245))
    draw = ImageDraw.Draw(canvas)

    # Title
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        label_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except (IOError, OSError):
        title_font = ImageFont.load_default()
        label_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # Title
    ftype = FIGURE_TYPES.get(qid, "未知")
    title = f"Q{qid} | Page {page_num} | {ftype}"
    draw.text((margin, 10), title, fill=(0, 0, 0), font=title_font)

    info_y = 40
    info_lines = [
        f"Bbox (PDF pts): [{bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]}]",
        f"Crop: {crop_img.size if crop_img else 'N/A'} px",
    ]
    for i, line in enumerate(info_lines):
        draw.text((margin, info_y + 20 * i), line, fill=(50, 50, 50), font=label_font)

    # Panel 1: Full page with bbox
    px = margin
    py = title_h
    canvas.paste(marked_resized, (px, py))
    draw.text((px, py - 5), "Full Page + Bbox", fill=(200, 0, 0), font=small_font)

    # Panel 2: Cropped result
    cx = px + page_w_display + panel_gap
    cy = py
    canvas.paste(crop_resized, (cx, cy))
    draw.text((cx, cy - 5), "Cropped Result", fill=(0, 120, 0), font=small_font)

    # Panel 3: Zoomed view
    zx = cx + max(crop_display_w, 400) + panel_gap
    zy = py
    canvas.paste(zoomed, (zx, zy))
    draw.text((zx, zy - 5), f"3x Zoom", fill=(0, 0, 150), font=small_font)

    # Details below
    dy = title_h + row1_h + panel_gap + 5
    detail_y = dy
    details = [
        f"Import ID: {qid}  |  PDF Page: {page_num}",
        f"Bbox (PDF pts): [{bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f}]",
        f"Crop size: {crop_img.size[0]}x{crop_img.size[1]} px" if crop_img else "Crop: N/A",
        f"Ink ratio: {analyze_crop(crop_path).get('ink_ratio', 'N/A')*100:.1f}% | Edge ink: {analyze_crop(crop_path).get('edge_ink_ratio', 'N/A')*100:.1f}%",
    ]
    for i, line in enumerate(details):
        draw.text((margin, detail_y + 20 * i), line, fill=(50, 50, 50), font=small_font)

    # Save
    out_path = os.path.join(out_dir, f"q_{qid}_p{page_num}_review.png")
    canvas.save(out_path, "PNG", optimize=True)
    return out_path


def auto_detect_issues(crop_analysis):
    """Automatically detect potential quality issues from crop analysis."""
    issues = []

    if not crop_analysis.get("exists"):
        issues.append("crop_file_missing")
        return issues

    if crop_analysis.get("too_small"):
        issues.append("dimensions_too_small")

    if crop_analysis.get("has_cutoff_risk"):
        margins = crop_analysis["content_margin"]
        if margins.get("top", 99) < 3:
            issues.append("content_touches_top_edge")
        if margins.get("bottom", 99) < 3:
            issues.append("content_touches_bottom_edge")
        if margins.get("left", 99) < 3:
            issues.append("content_touches_left_edge")
        if margins.get("right", 99) < 3:
            issues.append("content_touches_right_edge")

    if crop_analysis.get("whitespace_ratio", 0) > 0.8:
        issues.append("excessive_whitespace")

    if crop_analysis.get("ink_ratio", 1) < 0.01:
        issues.append("very_low_ink_density_suspicious")

    if crop_analysis.get("bytes_per_pixel", 0.5) < 0.02:
        issues.append("very_low_bytes_per_pixel_over_compressed")

    return issues


def main():
    manifest = load_manifest()
    results = {}

    for qid, page in sorted(TARGETS.items()):
        qid_str = str(qid)
        entry = manifest.get(qid_str, {})
        bbox = entry.get("bbox", [0, 0, 0, 0])

        # Find the current crop file (latest mtime = 01:04 bbox crop)
        crop_files = [f for f in os.listdir(CROPS_DIR) if f.startswith(f"q_{qid}_p{page}_") and f.endswith(".png")]
        # The newer file is the current bbox crop
        crop_files.sort(key=lambda f: os.path.getmtime(os.path.join(CROPS_DIR, f)))
        current_crop = crop_files[-1] if crop_files else None

        crop_path = os.path.join(CROPS_DIR, current_crop) if current_crop else None

        # Analyze
        analysis = analyze_crop(crop_path) if crop_path else {"exists": False}
        auto_issues = auto_detect_issues(analysis)

        # Generate comparison image
        comp_path = None
        if crop_path and os.path.exists(crop_path):
            try:
                comp_path = generate_comparison_image(qid, page, entry, crop_path, OUT_DIR)
            except Exception as e:
                print(f"  ERROR generating comparison for q{qid}: {e}")
                comp_path = None

        # Default status - starts as needs_human_review
        # After this script we will manually review and update
        status = "needs_human_review"

        results[qid_str] = {
            "page": page,
            "figure_type": FIGURE_TYPES.get(qid, "unknown"),
            "bbox": bbox,
            "status": status,
            "crop_analysis": analysis,
            "auto_issues": auto_issues,
            "comparison_image": os.path.basename(comp_path) if comp_path else None,
            "review_notes": "自动分析完成，待人工确认",
            "review_method": "automated_analysis",
            "verified_by_auto": len(auto_issues) == 0 and analysis.get("exists"),
        }

        print(f"[{qid}] Page {page} | {FIGURE_TYPES.get(qid, '?')} | "
              f"crop={analysis.get('width','?')}x{analysis.get('height','?')} | "
              f"ink={analysis.get('ink_ratio',0)*100:.1f}% | "
              f"edge_ink={analysis.get('edge_ink_ratio',0)*100:.1f}% | "
              f"issues={auto_issues if auto_issues else 'NONE'}")

    # Summary
    total = len(results)
    auto_pass = sum(1 for r in results.values() if r["auto_issues"] == [] and r["crop_analysis"].get("exists"))
    need_review = sum(1 for r in results.values() if r["auto_issues"] or not r["crop_analysis"].get("exists"))

    print(f"\n{'='*60}")
    print(f"Total: {total} | Auto-pass: {auto_pass} | Needs review: {need_review}")
    print(f"{'='*60}")

    # Write QA JSON
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "visual_qa_script_v4",
        "total": total,
        "auto_pass": auto_pass,
        "needs_review": need_review,
        "results": results,
    }
    with open(QA_JSON_PATH, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nQA JSON written: {QA_JSON_PATH}")

    # Generate comparison images summary
    comps = [r["comparison_image"] for r in results.values() if r["comparison_image"]]
    print(f"Comparison images: {len(comps)} generated")
    for c in comps:
        print(f"  {c}")


if __name__ == "__main__":
    main()
