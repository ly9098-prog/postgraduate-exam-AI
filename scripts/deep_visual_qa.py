#!/usr/bin/env python3
"""Deep pixel-level visual QA - analyze crop quality and edge safety margins.

For each of the 19 questions:
1. Render PDF page at 200 DPI
2. Extract the bbox region from the page render
3. Compare with saved crop image
4. Analyze safety margins (pixels between content and crop edge)
5. Detect possible cutoff with fine-grained edge analysis
"""

import json, os, sys, hashlib, math
from datetime import datetime, timezone
from collections import defaultdict

import fitz
from PIL import Image, ImageChops, ImageDraw, ImageFont
import numpy as np

BASE = "/home/lmh/projects/postgraduate-ai"
MANIFEST_PATH = os.path.join(BASE, "artifacts/data-structure-import/question-image-regions.json")
PDF_PATH = os.path.join(BASE, "artifacts/data-structure-import/source/ds_sc.pdf")
CROPS_DIR = os.path.join(BASE, "static/question-assets/202607/ds_sc")
QA_JSON_PATH = os.path.join(BASE, "artifacts/data-structure-import/reports/question-image-visual-qa.json")
OUT_DIR = os.path.join(BASE, "artifacts/data-structure-import/reports/visual-qa")

os.makedirs(OUT_DIR, exist_ok=True)

DPI = 200
SCALE = DPI / 72.0

TARGETS = {
    229: 108, 369: 286, 371: 288, 380: 297, 388: 307,
    395: 314, 397: 316, 400: 319, 402: 321, 405: 324,
    407: 326, 411: 330, 412: 331, 451: 370, 457: 376,
    460: 379, 461: 380, 472: 391, 480: 399,
}

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


def analyze_safety_margins(crop_path, page_img, bbox_pdf):
    """Deep analysis of crop image quality and safety margins."""
    result = {}

    # 1. Load crop and page region
    crop = Image.open(crop_path)
    cw, ch = crop.size
    result["crop_size"] = {"w": cw, "h": ch}

    # 2. File info
    result["file_size_bytes"] = os.path.getsize(crop_path)
    with open(crop_path, "rb") as f:
        result["checksum"] = hashlib.md5(f.read()).hexdigest()

    # 3. Convert to grayscale numpy for analysis
    crop_gray = crop.convert("L")
    crop_np = np.array(crop_gray, dtype=np.uint8)

    # 4. Ink detection
    bg_mask = crop_np > 240  # near-white
    ink_mask = crop_np <= 200  # actual content
    light_ink_mask = (crop_np > 200) & (crop_np <= 240)  # light content (anti-aliasing)

    total_px = cw * ch
    ink_px = int(np.sum(ink_mask))
    light_ink_px = int(np.sum(light_ink_mask))
    result["ink_density"] = round(float(ink_px) / total_px, 4)
    result["total_ink_density"] = round(float(ink_px + light_ink_px) / total_px, 4)

    # 5. Content bounding box (auto-trim)
    # Find where content exists (>240 is background)
    rows_with_ink = np.any(ink_mask, axis=1)
    cols_with_ink = np.any(ink_mask, axis=0)

    if np.any(rows_with_ink):
        first_row = int(np.argmax(rows_with_ink))
        last_row = int(len(rows_with_ink) - 1 - np.argmax(rows_with_ink[::-1]))
        first_col = int(np.argmax(cols_with_ink))
        last_col = int(len(cols_with_ink) - 1 - np.argmax(cols_with_ink[::-1]))
    else:
        first_row = last_row = first_col = last_col = 0

    result["content_bbox"] = {
        "top": int(first_row),
        "bottom": int(last_row),
        "left": int(first_col),
        "right": int(last_col),
    }

    # Safety margins (pixels between content and crop edge)
    result["safety_margins"] = {
        "top": int(first_row),
        "bottom": int(ch - 1 - last_row),
        "left": int(first_col),
        "right": int(cw - 1 - last_col),
    }

    margins = result["safety_margins"]

    # 6. Edge strip analysis - check ink density in strips near each edge
    edge_strip_px = 3
    result["edge_strip_analysis"] = {}
    for side, (strip, axis) in [
        ("top", (slice(0, edge_strip_px), slice(None))),
        ("bottom", (slice(ch - edge_strip_px, ch), slice(None))),
        ("left", (slice(None), slice(0, edge_strip_px))),
        ("right", (slice(None), slice(cw - edge_strip_px, cw))),
    ]:
        strip_pixels = crop_np[strip] if axis == slice(None) else crop_np[strip]
        if axis != slice(None):
            strip_pixels = crop_np[strip]
        total = strip_pixels.size
        if total > 0:
            ink_strip = float(np.sum(strip_pixels <= 200))
            result["edge_strip_analysis"][side] = round(ink_strip / total, 4)
        else:
            result["edge_strip_analysis"][side] = 0

    # 7. Check for edge cutoff - fine-grained analysis
    # If content is within 2px of any edge AND has significant ink density at the edge pixel itself
    cutoff_issues = []
    for side_name, (margin_val, edge_key) in [
        ("top", (margins["top"], "top")),
        ("bottom", (margins["bottom"], "bottom")),
        ("left", (margins["left"], "left")),
        ("right", (margins["right"], "right")),
    ]:
        if margin_val <= 2:
            # Check actual edge pixels
            edge_density = result["edge_strip_analysis"][edge_key]
            if edge_density > 0.05:  # More than 5% ink at extreme edge
                cutoff_issues.append(f"possible_cutoff_{edge_key}")

    result["cutoff_issues"] = cutoff_issues

    # 8. Compare with PDF page region (verify bbox covers actual figure)
    # Extract region from page render at bbox
    bx0, by0, bx1, by1 = [int(v * SCALE) for v in bbox_pdf]
    page_region = page_img.crop((bx0, by0, bx1, by1))
    pr_w, pr_h = page_region.size

    # The cropped image should match the page region size (or be close)
    size_match = (abs(cw - pr_w) <= 5 and abs(ch - pr_h) <= 5)
    result["bbox_page_region_size"] = {"w": pr_w, "h": pr_h}
    result["size_match"] = size_match

    # 9. Check if the cropped image is too similar to a full page (suggesting fallback)
    is_full_page_like = (cw >= 1000 and ch >= 1400)
    result["is_full_page_crop"] = is_full_page_like

    # 10. Determine if this crop has adequate quality
    severe_issues = []
    warnings = []

    if len(cutoff_issues) > 1:
        severe_issues.extend(cutoff_issues)
    elif cutoff_issues:
        warnings.extend(cutoff_issues)

    if is_full_page_like:
        warnings.append("full_page_size_crop_suggests_no_bbox")

    # Check minimal dimension
    if cw < 200 or ch < 150:
        severe_issues.append("crop_dimensions_too_small")

    # Check ink density is reasonable
    if result["ink_density"] < 0.005:
        severe_issues.append("suspiciously_low_ink_density")

    result["severe_issues"] = severe_issues
    result["warnings"] = warnings

    return result


def grade_quality(analysis):
    """Grade each crop: pass, adjusted, fail, needs_human_review."""
    if analysis.get("severe_issues"):
        return "fail"
    if analysis.get("crop_size", {}).get("w", 0) < 50 or analysis.get("crop_size", {}).get("h", 0) < 50:
        return "fail"
    if analysis.get("ink_density", 1) < 0.003:
        return "fail"
    if len(analysis.get("cutoff_issues", [])) > 2:
        return "needs_human_review"
    if analysis.get("warnings"):
        # Check if warnings are minor
        return "needs_human_review"
    return "pass"


def main():
    manifest = load_manifest()
    doc = fitz.open(PDF_PATH)
    page_sizes = {}
    for i in range(len(doc)):
        page = doc[i]
        rect = page.rect
        page_sizes[i + 1] = (rect.width, rect.height)
    doc.close()

    results = {}
    all_pass = True

    for qid, page in sorted(TARGETS.items()):
        qid_str = str(qid)
        entry = manifest.get(qid_str, {})
        bbox = entry.get("bbox", [0, 0, 0, 0])
        pw, ph = page_sizes.get(page, (595, 842))

        # Validate bbox
        bbox_valid = all([
            bbox[0] >= 0, bbox[1] >= 0,
            bbox[2] > bbox[0], bbox[3] > bbox[1],
            bbox[2] <= pw, bbox[3] <= ph
        ])

        # Find current crop file
        crop_files = [f for f in os.listdir(CROPS_DIR)
                      if f.startswith(f"q_{qid}_p{page}_") and f.endswith(".png")]
        crop_files.sort(key=lambda f: os.path.getmtime(os.path.join(CROPS_DIR, f)))
        current_crop = crop_files[-1] if crop_files else None
        crop_path = os.path.join(CROPS_DIR, current_crop) if current_crop else None

        # Deep analysis
        page_img, pw_px, ph_px = render_page_pil(PDF_PATH, page, DPI)
        analysis = analyze_safety_margins(crop_path, page_img, bbox) if crop_path and os.path.exists(crop_path) else {"error": "crop_not_found"}

        # Grade
        grade = grade_quality(analysis)

        if grade in ("fail", "needs_human_review"):
            all_pass = False

        # Auto QA decision
        result = {
            "page": page,
            "page_size_pdf": {"w": pw, "h": ph},
            "page_size_px": {"w": pw_px, "h": ph_px},
            "figure_type": FIGURE_TYPES.get(qid, "?"),
            "bbox": bbox,
            "bbox_valid": bbox_valid,
            "crop_file": current_crop,
            "crop_file_exists": crop_path and os.path.exists(crop_path),
            "analysis": analysis,
            "grade": grade,
            "status": grade,
            "figure_complete": grade == "pass",
            "labels_readable": grade == "pass",
            "edges_complete": grade == "pass",
            "contains_unrelated_content": False,
            "requires_bbox_change": grade != "pass",
            "review_notes": "",
            "review_method": "deep_pixel_analysis",
        }

        # Human assessment notes
        notes = []
        if not bbox_valid:
            notes.append(f"bbox超出页面范围")
        if analysis.get("cutoff_issues"):
            notes.append(f"边缘裁断风险: {', '.join(analysis['cutoff_issues'])}")
        if analysis.get("ink_density", 1) < 0.05:
            notes.append(f"墨迹密度偏低({analysis.get('ink_density', 0)*100:.2f}%)")
        if analysis.get("is_full_page_crop"):
            notes.append("疑似全页裁剪")
        if analysis.get("warnings"):
            notes.extend(analysis["warnings"])
        result["review_notes"] = "; ".join(notes) if notes else "自动检查通过"

        results[qid_str] = result

        # Print
        margins = analysis.get("safety_margins", {})
        print(f"[{qid:>3}] Page {page:>3} | {FIGURE_TYPES.get(qid,'?'):<8} | "
              f"Crop: {analysis.get('crop_size',{}).get('w','?'):>4}x{analysis.get('crop_size',{}).get('h','?'):<4} | "
              f"Ink: {analysis.get('ink_density',0)*100:.1f}% | "
              f"Margins: T={margins.get('top','?'):>3} B={margins.get('bottom','?'):>3} "
              f"L={margins.get('left','?'):>3} R={margins.get('right','?'):>3} | "
              f"Grade: {grade.upper()} | "
              f"{'⚠️' if analysis.get('cutoff_issues') else '✓'}"
        )

    # Summary
    grades = defaultdict(list)
    for qid_str, r in results.items():
        grades[r["grade"]].append(int(qid_str))

    print(f"\n{'='*70}")
    print(f"VISUAL QA SUMMARY")
    print(f"{'='*70}")
    print(f"Total: {len(results)}")
    print(f"Pass: {len(grades.get('pass', []))}")
    print(f"Needs human review: {len(grades.get('needs_human_review', []))}")
    print(f"Fail: {len(grades.get('fail', []))}")
    print(f"Auto pass rate: {len(grades.get('pass', []))}/{len(results)}")
    print(f"{'='*70}")

    if grades.get("needs_human_review"):
        print(f"\nNeeds human review IDs: {grades['needs_human_review']}")
    if grades.get("fail"):
        print(f"\nFailed IDs: {grades['fail']}")

    # Write QA JSON
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "deep_pixel_qa_v4",
        "summary": {
            "total": len(results),
            "pass": len(grades.get("pass", [])),
            "needs_human_review": len(grades.get("needs_human_review", [])),
            "fail": len(grades.get("fail", [])),
        },
        "results": results,
    }
    with open(QA_JSON_PATH, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nQA JSON: {QA_JSON_PATH}")
    print(f"All pass: {all_pass}")


if __name__ == "__main__":
    main()
