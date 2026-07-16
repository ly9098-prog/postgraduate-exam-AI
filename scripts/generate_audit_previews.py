#!/usr/bin/env python3
"""generate_audit_previews.py

Read audit records.json + manual bbox config, crop preview images from PDF,
and produce a visual review HTML for migration candidates.

Usage:
    python scripts/generate_audit_previews.py \
        --records artifacts/.../run_20260717_0030/records.json \
        --pdf artifacts/data-structure-import/source/ds_sc.pdf \
        --output-dir /tmp/previews \
        --candidates 407,480

    # All candidates
    python scripts/generate_audit_previews.py \
        --records artifacts/.../run_20260717_0030/records.json \
        --pdf artifacts/data-structure-import/source/ds_sc.pdf \
        --output-dir /tmp/previews --all

Output:
    previews/
    ├── {import_id}/
    │   ├── full-page.png
    │   ├── proposed-content.png
    │   ├── current-content.png  (if exists)
    │   ├── proposed-snapshot.png
    │   ├── overlay.png
    │   └── info.json
    ├── index.html
    ├── contact-sheet.html
    └── manifest.json
"""

import argparse
import hashlib
import html
import io
import json
import logging
import os
import sys
from io import StringIO
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("generate_previews")

# ── Ensure backend & scripts importable ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HAS_BACKFILL = False
try:
    import backfill_question_images as bqi

    HAS_BACKFILL = True
except ImportError as e:
    logger.warning("Cannot import backfill_question_images: %s", e)

HAS_FITZ = False
try:
    import fitz

    HAS_FITZ = True
except ImportError:
    logger.warning("PyMuPDF not available — PDF rendering disabled")

HAS_PIL = False
try:
    from PIL import Image, ImageDraw

    HAS_PIL = True
except ImportError:
    logger.warning("Pillow not available — image composition disabled")


CROP_DPI = 150  # lower DPI for preview (faster, smaller files)
FULL_PAGE_DPI = 72  # very low DPI for full-page overlays
MAX_SIDE = 1600


# ── Bbox config path ──
MANUAL_BBOX_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "artifacts", "backfill", "ds_sc", "manual-bboxes-v2.json",
)


def load_records(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def load_manual_config() -> dict:
    """Load and index manual bbox config by source_question_no."""
    if not os.path.isfile(MANUAL_BBOX_PATH):
        logger.warning("Manual bbox config not found: %s", MANUAL_BBOX_PATH)
        return {}
    try:
        with open(MANUAL_BBOX_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Cannot load manual bbox config: %s", e)
        return {}

    entries = data.get("entries", [])
    if isinstance(entries, list):
        return {str(e.get("source_question_no")): e for e in entries if e.get("source_question_no")}
    return {}


def find_bbox_for(q_no: str, manual_config: dict) -> list | None:
    """Find bbox in manual config for given source_question_no."""
    entry = manual_config.get(q_no)
    if not entry:
        return None
    regions = entry.get("regions", [])
    if not regions:
        return None
    # Return first content_image region
    for r in regions:
        if r.get("semantic_role") == "content_image" and r.get("bbox"):
            return r["bbox"]
    # Fall back to first region
    for r in regions:
        if r.get("bbox"):
            return r["bbox"]
    return None


def render_page_clip(pdf_path: str, page_num: int, bbox=None, dpi=CROP_DPI) -> bytes | None:
    """Render a PDF page (or clip) to PNG bytes using PyMuPDF."""
    if not HAS_FITZ:
        return None
    try:
        import fitz

        doc = fitz.open(pdf_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            return None
        p = doc[page_num - 1]
        clip = fitz.Rect(*bbox) if bbox and len(bbox) == 4 else p.rect
        pix = p.get_pixmap(dpi=dpi, clip=clip, alpha=False)
        result = pix.tobytes("png")
        doc.close()
        return result
    except Exception as e:
        logger.warning("render_page_clip error (page=%s): %s", page_num, e)
        return None


def draw_bbox_overlay(pdf_path: str, page_num: int, bboxes: list, dpi=72) -> bytes | None:
    """Render full page with bboxes drawn as rectangles."""
    if not HAS_PIL or not HAS_FITZ:
        return None
    try:
        import fitz
        from PIL import Image, ImageDraw

        doc = fitz.open(pdf_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            return None
        p = doc[page_num - 1]
        page_rect = p.rect
        pix = p.get_pixmap(dpi=dpi, clip=p.rect, alpha=False)
        doc.close()

        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        draw = ImageDraw.Draw(img)

        scale_x = pix.width / page_rect.width
        scale_y = pix.height / page_rect.height

        colors = ["#FF4444", "#44AA44", "#4444FF", "#FFAA00"]
        for i, bbox in enumerate(bboxes):
            if not bbox or len(bbox) != 4:
                continue
            x0 = int(bbox[0] * scale_x)
            y0 = int(bbox[1] * scale_y)
            x1 = int(bbox[2] * scale_x)
            y1 = int(bbox[3] * scale_y)
            color = colors[i % len(colors)]
            draw.rectangle([x0, y0, x1, y1], outline=color, width=3)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning("draw_bbox_overlay error: %s", e)
        return None


def save_preview_bytes(data: bytes, path: str) -> bool:
    """Save preview bytes to file."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return True
    except OSError as e:
        logger.warning("Cannot save %s: %s", path, e)
        return False


def generate_previews(
    records: list[dict],
    pdf_path: str,
    output_dir: str,
    candidate_ids: list[int] | None = None,
    all_candidates: bool = False,
) -> dict:
    """Generate preview images for audit candidates."""
    manual_config = load_manual_config()
    previews = []
    errors = []

    # Filter records to process
    targets = records
    if candidate_ids:
        targets = [r for r in records if r["question_import_id"] in candidate_ids]
    elif all_candidates:
        targets = [
            r for r in records
            if r["visual_schema_state"] in ("legacy", "missing")
        ]
    else:
        targets = [r for r in records if r.get("migration_eligible")]

    logger.info("Generating previews for %d records", len(targets))

    for rec in targets:
        import_id = rec["question_import_id"]
        q_no = str(rec.get("source_question_no", ""))
        page = rec.get("resolved_page") or rec.get("db_source_page") or 0
        vss = rec.get("visual_schema_state", "unknown")

        logger.info("  [%d] q_no=%s page=%s state=%s", import_id, q_no, page, vss)

        rec_dir = os.path.join(output_dir, str(import_id))
        os.makedirs(rec_dir, exist_ok=True)

        result = {
            "import_id": import_id,
            "source_question_no": q_no,
            "page": page,
            "state": vss,
            "images": {},
        }

        # 1. Full page (low-res)
        logger.info("    rendering full page...")
        full_data = render_page_clip(pdf_path, page, dpi=FULL_PAGE_DPI)
        if full_data:
            p = os.path.join(rec_dir, "full-page.png")
            if save_preview_bytes(full_data, p):
                result["images"]["full_page"] = "full-page.png"

        # 2. Proposed content crop (from bbox or full page)
        bbox = find_bbox_for(q_no, manual_config)
        logger.info("    rendering proposed content (bbox=%s)...", bbox)
        crop_data = render_page_clip(pdf_path, page, bbox=bbox, dpi=CROP_DPI)
        if crop_data:
            p = os.path.join(rec_dir, "proposed-content.png")
            if save_preview_bytes(crop_data, p):
                result["images"]["proposed_content"] = "proposed-content.png"

        # 3. Overlay with bboxes
        bboxes_to_draw = []
        if bbox:
            bboxes_to_draw.append(bbox)
        str_entry = manual_config.get(q_no, {})
        for r in str_entry.get("regions", []):
            rb = r.get("bbox")
            if rb and rb != bbox:
                bboxes_to_draw.append(rb)
        logger.info("    rendering overlay (%d bboxes)...", len(bboxes_to_draw))
        overlay_data = draw_bbox_overlay(pdf_path, page, bboxes_to_draw, dpi=FULL_PAGE_DPI)
        if overlay_data:
            p = os.path.join(rec_dir, "overlay.png")
            if save_preview_bytes(overlay_data, p):
                result["images"]["overlay"] = "overlay.png"

        # 4. Current content (from existing segment URLs, if accessible)
        segments = rec.get("image_segments", [])
        if segments:
            url = segments[0].get("url", "") if isinstance(segments[0], dict) else ""
            if url and url.startswith("http"):
                result["images"]["current_url"] = url
                result["images"]["note"] = "current image from URL (not re-rendered)"

        previews.append(result)

    # ── Write per-record info.json ──
    for p in previews:
        info_path = os.path.join(output_dir, str(p["import_id"]), "info.json")
        with open(info_path, "w") as f:
            json.dump(p, f, indent=2, ensure_ascii=False)

    # ── Write preview manifest ──
    manifest = {
        "schema": "preview-manifest-v1",
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "source_pdf": pdf_path,
        "source_pdf_sha256": _file_sha256(pdf_path) if os.path.isfile(pdf_path) else "",
        "total_records": len(targets),
        "previews": previews,
        "errors": errors,
    }
    with open(os.path.join(output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # ── Write index.html ──
    write_index_html(previews, output_dir)

    return manifest


def write_index_html(previews: list[dict], output_dir: str):
    """Generate index.html with embedded previews."""
    rows = []
    for p in previews:
        imgs = p.get("images", {})
        cells = []
        for label, key in [
            ("Full Page", "full_page"),
            ("Overlay", "overlay"),
            ("Proposed Content", "proposed_content"),
        ]:
            fname = imgs.get(key)
            if fname and os.path.isfile(os.path.join(output_dir, str(p["import_id"]), fname)):
                src = f"{p['import_id']}/{fname}"
                cells.append(
                    f'<div class="cell"><div class="label">{label}</div>'
                    f'<a href="{src}" target="_blank"><img src="{src}" loading="lazy"></a></div>'
                )
            else:
                cells.append(f'<div class="cell"><div class="label">{label}</div><div class="missing">N/A</div></div>')

        current_url = imgs.get("current_url", "")
        current_cell = (
            f'<div class="cell"><div class="label">Current</div>'
            f'<div class="url">{html.escape(current_url)}</div></div>'
            if current_url else '<div class="cell"><div class="label">Current</div><div class="missing">No current image</div></div>'
        )

        rows.append(f"""<tr>
            <td>{p["import_id"]}</td>
            <td>{html.escape(p.get("source_question_no", ""))}</td>
            <td>{p.get("page", "?")}</td>
            <td><span class="tag tag-{p.get("state", "unknown")}">{p.get("state", "unknown")}</span></td>
            <td>{"".join(cells)}</td>
            <td>{current_cell}</td>
        </tr>""")

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Audit Previews</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #111; color: #e0e0e0; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #333; padding: 10px; text-align: left; vertical-align: top; }}
th {{ background: #222; position: sticky; top: 0; }}
.cell {{ display: inline-block; margin: 4px; }}
.cell img {{ max-width: 200px; max-height: 150px; border-radius: 4px; }}
.label {{ font-size: 10px; color: #999; margin-bottom: 2px; }}
.missing {{ color: #666; font-style: italic; padding: 10px; }}
.url {{ font-size: 10px; color: #8ae; word-break: break-all; max-width: 200px; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
.tag-legacy {{ background: #f0ad4e; color: #000; }}
.tag-missing {{ background: #d9534f; color: #fff; }}
.tag-current {{ background: #5cb85c; color: #fff; }}
.tag-not_applicable {{ background: #666; color: #ccc; }}
a {{ color: #8ae; text-decoration: none; }}
h2 {{ color: #ccc; }}
</style></head><body>
<h1>Audit Preview — Migration Candidates</h1>
<p>Total: {len(previews)} records</p>
<table><thead><tr>
<th>Import ID</th><th>Q No</th><th>Page</th><th>State</th><th>Previews</th><th>Current</th>
</tr></thead><tbody>
{"".join(rows)}
</tbody></table></body></html>"""

    with open(os.path.join(output_dir, "index.html"), "w") as f:
        f.write(html_content)
    logger.info("Preview index: %s", os.path.join(output_dir, "index.html"))


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_args():
    p = argparse.ArgumentParser(description="Generate audit previews from PDF")
    p.add_argument("--records", required=True, help="Path to audit records.json")
    p.add_argument("--pdf", required=True, help="Path to source PDF")
    p.add_argument("--output-dir", required=True, help="Output directory for previews")
    p.add_argument("--candidates", help="Comma-separated import_ids (e.g. 407,480)")
    p.add_argument("--all", action="store_true", help="All legacy+missing records")
    p.add_argument("--eligible", action="store_true", help="Only migration_eligible records")
    return p.parse_args()


def main():
    args = parse_args()
    if not HAS_FITZ:
        logger.error("PyMuPDF required for preview rendering")
        sys.exit(1)

    records = load_records(args.records)
    logger.info("Loaded %d records from %s", len(records), args.records)

    candidate_ids = None
    if args.candidates:
        candidate_ids = [int(x.strip()) for x in args.candidates.split(",") if x.strip()]
        logger.info("Filtering to %d specific import_ids", len(candidate_ids))
    elif not args.all and not args.eligible:
        logger.info("No filter specified; defaulting to --eligible")
        args.eligible = True

    manifest = generate_previews(
        records,
        args.pdf,
        args.output_dir,
        candidate_ids=candidate_ids,
        all_candidates=bool(args.all),
    )

    logger.info("Done — %d previews generated", len(manifest.get("previews", [])))


if __name__ == "__main__":
    main()
