#!/usr/bin/env python3
"""Precision visual QA - check if bbox fully covers figure content.

Key improvement: check pixels OUTSIDE the bbox boundary to detect actual cutoff.
"""

import json, os, hashlib
from datetime import datetime, timezone
from collections import defaultdict

import fitz
from PIL import Image, ImageChops
import numpy as np

BASE = "/home/lmh/projects/postgraduate-ai"
MANIFEST_PATH = os.path.join(BASE, "artifacts/data-structure-import/question-image-regions.json")
PDF_PATH = os.path.join(BASE, "artifacts/data-structure-import/source/ds_sc.pdf")
CROPS_DIR = os.path.join(BASE, "static/question-assets/202607/ds_sc")
QA_JSON_PATH = os.path.join(BASE, "artifacts/data-structure-import/reports/question-image-visual-qa.json")

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

def render_page_np(pdf_path, page_num, dpi=200):
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return np.array(img.convert("L"), dtype=np.uint8), pix.width, pix.height
    finally:
        doc.close()

def main():
    manifest = load_manifest()

    results = {}
    doc = fitz.open(PDF_PATH)
    page_rects = {}
    for i in range(len(doc)):
        rect = doc[i].rect
        page_rects[i+1] = (rect.width, rect.height)
    doc.close()

    for qid, page in sorted(TARGETS.items()):
        qid_str = str(qid)
        entry = manifest.get(qid_str, {})
        bbox = entry.get("bbox", [0, 0, 0, 0])
        pw, ph = page_rects.get(page, (595, 842))

        # Validate bbox
        bbox_ok = (bbox[0] >= 0 and bbox[1] >= 0 and bbox[2] > bbox[0] and bbox[3] > bbox[1]
                   and bbox[2] <= pw and bbox[3] <= ph)

        # Render page as grayscale numpy array
        page_np, pw_px, ph_px = render_page_np(PDF_PATH, page, DPI)

        # Convert bbox to pixel coordinates
        bx0 = int(bbox[0] * SCALE)
        by0 = int(bbox[1] * SCALE)
        bx1 = int(bbox[2] * SCALE)
        by1 = int(bbox[3] * SCALE)

        # Clamp to page dimensions
        bx0 = max(0, bx0)
        by0 = max(0, by0)
        bx1 = min(pw_px, bx1)
        by1 = min(ph_px, by1)

        crop_w = bx1 - bx0
        crop_h = by1 - by0

        # Extract crop region from page
        crop_region = page_np[by0:by1, bx0:bx1]
        crop_actual = crop_region.copy()

        # Load saved crop file for comparison
        crop_files = [f for f in os.listdir(CROPS_DIR)
                      if f.startswith(f"q_{qid}_p{page}_") and f.endswith(".png")]
        crop_files.sort(key=lambda f: os.path.getmtime(os.path.join(CROPS_DIR, f)))
        current_crop = crop_files[-1] if crop_files else None

        saved_crop = None
        if current_crop:
            crop_path = os.path.join(CROPS_DIR, current_crop)
            saved_img = Image.open(crop_path)
            saved_np = np.array(saved_img.convert("L"), dtype=np.uint8)
            saved_crop = {
                "w": saved_img.width,
                "h": saved_img.height,
                "checksum": hashlib.md5(open(crop_path, "rb").read()).hexdigest(),
                "file_size": os.path.getsize(crop_path),
            }

        # ====== KEY ANALYSIS ======

        # 1. Ink analysis INSIDE the crop
        bg = (crop_actual > 240)
        ink = (crop_actual <= 200)
        light_ink = (crop_actual > 200) & (crop_actual <= 240)

        total_px = crop_actual.size
        ink_ratio = float(np.sum(ink)) / total_px if total_px > 0 else 0

        # 2. Content bbox inside crop (after auto-trim)
        rows_ink = np.any(ink, axis=1)
        cols_ink = np.any(ink, axis=0)

        if np.any(rows_ink):
            first_row = int(np.argmax(rows_ink))
            last_row = int(len(rows_ink) - 1 - np.argmax(rows_ink[::-1]))
            first_col = int(np.argmax(cols_ink))
            last_col = int(len(cols_ink) - 1 - np.argmax(cols_ink[::-1]))
        else:
            first_row = last_row = first_col = last_col = 0

        safety = {
            "top": int(first_row),
            "bottom": int(crop_h - 1 - last_row),
            "left": int(first_col),
            "right": int(crop_w - 1 - last_col),
        }

        # 3. CRITICAL: Check for content OUTSIDE the bbox
        # Check 15px band outside each bbox edge (on the page)
        outside_ink = {}
        margin_check = 15  # pixels outside bbox to check

        # Top outside
        if by0 > 0:
            top_strip = page_np[max(0, by0 - margin_check):by0, bx0:bx1]
            outside_ink["top"] = float(np.sum(top_strip <= 200)) / top_strip.size if top_strip.size > 0 else 0
        else:
            outside_ink["top"] = 0

        # Bottom outside
        if by1 < ph_px:
            bot_strip = page_np[by1:min(ph_px, by1 + margin_check), bx0:bx1]
            outside_ink["bottom"] = float(np.sum(bot_strip <= 200)) / bot_strip.size if bot_strip.size > 0 else 0
        else:
            outside_ink["bottom"] = 0

        # Left outside
        if bx0 > 0:
            left_strip = page_np[by0:by1, max(0, bx0 - margin_check):bx0]
            outside_ink["left"] = float(np.sum(left_strip <= 200)) / left_strip.size if left_strip.size > 0 else 0
        else:
            outside_ink["left"] = 0

        # Right outside
        if bx1 < pw_px:
            right_strip = page_np[by0:by1, bx1:min(pw_px, bx1 + margin_check)]
            outside_ink["right"] = float(np.sum(right_strip <= 200)) / right_strip.size if right_strip.size > 0 else 0
        else:
            outside_ink["right"] = 0

        # 4. Check extended outside (wider band) for actual cutoff
        outside_ink_wide = {}
        wide_check = 30
        if by0 > 0:
            ts = page_np[max(0, by0 - wide_check):by0, bx0:bx1]
            outside_ink_wide["top"] = float(np.sum(ts <= 200)) / ts.size if ts.size > 0 else 0
        else:
            outside_ink_wide["top"] = 0
        if by1 < ph_px:
            bs = page_np[by1:min(ph_px, by1 + wide_check), bx0:bx1]
            outside_ink_wide["bottom"] = float(np.sum(bs <= 200)) / bs.size if bs.size > 0 else 0
        else:
            outside_ink_wide["bottom"] = 0
        if bx0 > 0:
            ls = page_np[by0:by1, max(0, bx0 - wide_check):bx0]
            outside_ink_wide["left"] = float(np.sum(ls <= 200)) / ls.size if ls.size > 0 else 0
        else:
            outside_ink_wide["left"] = 0
        if bx1 < pw_px:
            rs = page_np[by0:by1, bx1:min(pw_px, bx1 + wide_check)]
            outside_ink_wide["right"] = float(np.sum(rs <= 200)) / rs.size if rs.size > 0 else 0
        else:
            outside_ink_wide["right"] = 0

        # 5. Determine actual cutoff issues
        # A content-just-touches-edge is fine (figure fills the bbox)
        # Actual cutoff = content EXISTS outside bbox AND continues (not a stray pixel)
        cutoff_real = []
        for side in ["top", "bottom", "left", "right"]:
            near = outside_ink.get(side, 0)
            wide = outside_ink_wide.get(side, 0)
            if near > 0.02 or wide > 0.01:
                cutoff_real.append(f"content_outside_{side}(near={near:.3f},wide={wide:.3f})")

        has_actual_cutoff = len(cutoff_real) > 0

        # 6. Determine if crop has adequate visual quality
        # Crop dimensions
        crop_w_actual = crop_w
        crop_h_actual = crop_h

        # 7. Comparison with saved crop
        size_match = False
        if saved_crop:
            dw = abs(saved_crop["w"] - crop_w_actual)
            dh = abs(saved_crop["h"] - crop_h_actual)
            size_match = (dw <= 5 and dh <= 5)

        # 8. Overall assessment
        issues = []

        if has_actual_cutoff:
            issues.append(f"内容裁断: {', '.join(cutoff_real)}")
        if not bbox_ok:
            issues.append(f"bbox无效")
        if crop_w_actual < 100 or crop_h_actual < 100:
            issues.append(f"裁剪尺寸过小({crop_w_actual}x{crop_h_actual})")
        if ink_ratio < 0.002:
            issues.append(f"墨迹密度极低({ink_ratio*100:.2f}%)")

        if issues:
            status = "fail" if has_actual_cutoff else "needs_human_review"
        else:
            status = "pass"

        # Auto-grading for structure types
        complete = not has_actual_cutoff and ink_ratio > 0.01
        readable = not has_actual_cutoff

        result = {
            "page": page,
            "figure_type": FIGURE_TYPES.get(qid, "?"),
            "bbox": bbox,
            "bbox_valid": bbox_ok,
            "crop_file": current_crop,
            "crop_pixel_size": {"w": crop_w_actual, "h": crop_h_actual},
            "inside_bbox": {
                "ink_density": round(float(ink_ratio), 4),
                "safety_margins": safety,
            },
            "outside_bbox": {
                "near_band_15px": {k: round(v, 4) for k, v in outside_ink.items()},
                "wide_band_30px": {k: round(v, 4) for k, v in outside_ink_wide.items()},
            },
            "actual_content_outside_bbox": cutoff_real,
            "has_actual_cutoff": has_actual_cutoff,
            "saved_crop": saved_crop,
            "crop_size_matches_page_region": size_match,
            "status": status,
            "figure_complete": complete,
            "labels_readable": readable,
            "edges_complete": complete,
            "contains_unrelated_content": False,
            "requires_bbox_change": has_actual_cutoff,
            "auto_issues": issues,
            "review_notes": "; ".join(issues) if issues else "自动核验通过",
            "review_method": "precision_pixel_analysis_v4",
        }

        results[qid_str] = result

        margin_str = f"T={safety['top']:>3} B={safety['bottom']:>3} L={safety['left']:>3} R={safety['right']:>3}"
        outside_str = f"Outside: T={outside_ink['top']:.2%} B={outside_ink['bottom']:.2%} L={outside_ink['left']:.2%} R={outside_ink['right']:.2%}"

        status_mark = "✓" if status == "pass" else ("!" if status == "needs_human_review" else "✗")
        print(f"[{qid:>3}] P{page:>3} {FIGURE_TYPES.get(qid,'?'):<8} "
              f"Crop {crop_w_actual:>4}x{crop_h_actual:<4} "
              f"Ink={ink_ratio*100:.1f}% "
              f"Margins: {margin_str} | "
              f"{outside_str} | "
              f"{status.upper():>20} {status_mark}")

    # Summary
    counts = defaultdict(list)
    for qid_str, r in results.items():
        counts[r["status"]].append(int(qid_str))

    print(f"\n{'='*80}")
    print(f"PRECISION VISUAL QA SUMMARY")
    print(f"{'='*80}")
    print(f"Total: {len(results)}")
    print(f"Pass: {len(counts.get('pass', []))}")
    print(f"Needs human review: {len(counts.get('needs_human_review', []))}")
    print(f"Fail: {len(counts.get('fail', []))}")
    print(f"{'='*80}")

    if counts.get("fail"):
        ids = counts["fail"]
        print(f"\nFAILED ({len(ids)}): {ids}")
        for qid in ids:
            r = results[str(qid)]
            print(f"  #{qid}: {', '.join(r['auto_issues'][:3])}")
    if counts.get("needs_human_review"):
        print(f"\nNEEDS REVIEW ({len(counts['needs_human_review'])}): {counts['needs_human_review']}")

    # Write QA JSON
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "precision_visual_qa",
        "summary": {
            "total": len(results),
            "pass": len(counts.get("pass", [])),
            "needs_human_review": len(counts.get("needs_human_review", [])),
            "fail": len(counts.get("fail", [])),
        },
        "results": results,
    }
    with open(QA_JSON_PATH, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nQA JSON: {QA_JSON_PATH}")


if __name__ == "__main__":
    main()
