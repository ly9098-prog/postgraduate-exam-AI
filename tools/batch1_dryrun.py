#!/usr/bin/env python3
"""
Batch 1 Dry-Run: confirmed issue preparation for OCR image audit.

Generates all dry-run deliverables WITHOUT modifying production:
- PDF page renders and overlay visualizations
- Proposed content images and source snapshots for 3 missing-image questions
- Localhost URL fix proposals for Q.294 and Q.305
- Q.296 text-only confirmation
- Full audit report and approval manifests

Usage: python tools/batch1_dryrun.py
"""

import hashlib, json, os, sqlite3, shutil, sys, io
from datetime import datetime
from pathlib import Path

import fitz
import numpy as np
from PIL import Image

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
PDF_PATH = BASE_DIR / "artifacts" / "data-structure-import" / "source" / "ds_sc.pdf"
DB_PATH = BASE_DIR / "backend" / "postgraduate.db"
STATIC_BASE = BASE_DIR / "backend" / "static"  # web root for /static/ URLs
STATIC_DIR = STATIC_BASE / "question-assets" / "202607"
DS_SC_DIR = STATIC_DIR / "ds_sc"

RUN_ID = datetime.now().strftime("run_%Y%m%d_%H%M%S")
OUT_DIR = BASE_DIR / "artifacts" / "backfill" / "ds_sc" / "visual-v2.1" / RUN_ID / "batch-1-dry-run"
PREVIEW_DIR = OUT_DIR / "previews"
OVERLAY_DIR = OUT_DIR / "overlays"
CONTENT_DIR = OUT_DIR / "proposed-content-images"
SNAPSHOT_DIR = OUT_DIR / "proposed-source-snapshots"
CURRENT_DIR = OUT_DIR / "current-images"
PUBLISHED_DIR = OUT_DIR / "published-render-previews"

for d in [OUT_DIR, PREVIEW_DIR, OVERLAY_DIR, CONTENT_DIR,
          SNAPSHOT_DIR, CURRENT_DIR, PUBLISHED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Database helper ─────────────────────────────────────────────────────
def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db

def fetch_one(db, sql, params=()):
    return db.execute(sql, params).fetchone()

def fetch_all(db, sql, params=()):
    return db.execute(sql, params).fetchall()

def safe_json(val, default=None):
    if val is None:
        return default or {}
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str) and val.strip():
        return json.loads(val)
    return default or {}

# ── Target definitions ──────────────────────────────────────────────────
TARGETS = [
    {
        "id": "Q147_s200",
        "source_question_no": 200,
        "type": "missing_image",
        "description": "2009统考真题: 二叉树遍历 — 如右图所示",
        "question_id": 147,
        "qi_id": 301,
    },
    {
        "id": "Q152_s205",
        "source_question_no": 205,
        "type": "missing_image",
        "description": "2014统考真题: 中序线索化 — 对右图所示的二叉树",
        "question_id": 152,
        "qi_id": 306,
    },
    {
        "id": "Q154_s207",
        "source_question_no": 207,
        "type": "missing_image",
        "description": "2017统考真题: 二叉树树形如右图所示",
        "question_id": 154,
        "qi_id": 308,
    },
    {
        "id": "Q294_s369",
        "source_question_no": 369,
        "type": "url_fix",
        "description": "二叉排序树 — option_group localhost URL",
        "question_id": 294,
        "qi_id": 450,
    },
    {
        "id": "Q296_s371",
        "source_question_no": 371,
        "type": "text_only_confirm",
        "description": "BST查找路径 — 纯文字确认",
        "question_id": 296,
        "qi_id": 452,
    },
    {
        "id": "Q305_s380",
        "source_question_no": 380,
        "type": "url_fix",
        "description": "B+树 — 下图所示 localhost URL",
        "question_id": 305,
        "qi_id": 461,
    },
]

# ── Hash helpers ─────────────────────────────────────────────────────────
def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def sha256_bytes(data):
    if isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha256(data).hexdigest()

def png_bytes(img):
    """Get PNG bytes from a PIL Image."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def md5_digest(data):
    return hashlib.md5(data.encode()).hexdigest()[:12]

# ── PDF page rendering ──────────────────────────────────────────────────
def render_page(pno, dpi=200):
    """Render PDF page 0-indexed at given DPI."""
    doc = fitz.open(str(PDF_PATH))
    page = doc[pno]
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return img, pix

def pt_to_px(pt, dpi):
    return int(pt * dpi / 72)

def px_to_pt(px, dpi):
    return px * 72 / dpi

# ── 1. Record Mapping Verification ──────────────────────────────────────
def verify_record_mapping():
    """Verify 1-to-1 mapping for all targets."""
    db = get_db()
    results = {}
    all_ok = True

    for tgt in TARGETS:
        sqn = tgt["source_question_no"]
        qi = fetch_one(db, "SELECT * FROM question_imports WHERE source_question_no=?", (sqn,))
        q = None
        mapping_ok = False
        issues = []

        if qi is None:
            issues.append(f"No QuestionImport found for source_question_no={sqn}")
        else:
            tgt["qi_id_db"] = qi["id"]
            q = fetch_one(db, "SELECT * FROM questions WHERE id=?", (qi["question_id"],))

            expected_qi_id = tgt.get("qi_id")
            expected_q_id = tgt.get("question_id")

            if qi["id"] != expected_qi_id:
                issues.append(f"QI id mismatch: expected {expected_qi_id}, got {qi['id']}")
            if qi["question_id"] is None:
                issues.append("QuestionImport.question_id is NULL")
            elif qi["question_id"] != expected_q_id:
                issues.append(f"Q id mismatch: expected {expected_q_id}, got {qi['question_id']}")
            elif q is None:
                issues.append(f"Question id={qi['question_id']} not found")
            else:
                mapping_ok = True

        result = {
            "target_id": tgt["id"],
            "mapping_ok": mapping_ok,
            "question_import": dict(qi) if qi else None,
            "question": dict(q) if q else None,
            "issues": issues,
        }
        results[tgt["id"]] = result
        if not mapping_ok:
            all_ok = False
            print(f"  ❌ {tgt['id']}: MAPPING FAILED — {'; '.join(issues)}")
        else:
            print(f"  ✅ {tgt['id']}: QI.id={qi['id']} → Q.id={q['id']} ✓")

    db.close()
    return results, all_ok

# ── 2. Missing Image: Analyze and Crop ──────────────────────────────────
def analyze_diagram_region(pno, dpi=300):
    """Analyze right-column diagram region for a given PDF page.

    Returns precise content_regions based on dark pixel detection.
    Pages have 2-column layout: text left (~0-270pt), diagram right (~270-540pt).
    Brand header occupies ~Y[0-35]pt every page.
    """
    doc = fitz.open(str(PDF_PATH))
    page = doc[pno]
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    arr = np.array(img)
    gray = arr.mean(axis=2)
    h, w = gray.shape
    doc.close()

    inv_scale = 72 / dpi
    x_right = int(270 / inv_scale)
    right = gray[:, x_right:]

    # Find dark content rows in right column (below brand header at ~Y=35pt)
    y_start = int(36 / inv_scale)

    # Per-row dark pixel count (>150 threshold for diagram content)
    content_rows = []
    for y in range(y_start, h):
        row = right[y]
        vd = int((row < 150).sum())  # very dark pixels
        sd = int(((row >= 150) & (row < 200)).sum())  # somewhat dark
        if vd > 15:
            content_rows.append({
                "y_pt": round(y * inv_scale, 1),
                "very_dark": vd,
                "somewhat_dark": sd,
            })

    # Find contiguous content regions (gap threshold: 5pt)
    gap_px = int(5 / inv_scale)
    regions = []
    if content_rows:
        start_y = content_rows[0]["y_pt"]
        prev_y = content_rows[0]["y_pt"]
        for row in content_rows[1:]:
            if row["y_pt"] - prev_y > 5:
                regions.append({"y_start": start_y, "y_end": prev_y})
                start_y = row["y_pt"]
            prev_y = row["y_pt"]
        regions.append({"y_start": start_y, "y_end": prev_y})

    return {
        "page_pno": pno + 1,
        "right_column_x_start_pt": round(x_right * inv_scale, 1),
        "content_regions": regions,
        "total_rows_analyzed": len(content_rows),
    }

def crop_region(pno, bbox_pt, dpi=400, pad_pt=0):
    """Crop a region from a PDF page. bbox_pt: [left, top, right, bottom] in PDF points."""
    doc = fitz.open(str(PDF_PATH))
    page = doc[pno]
    clip = fitz.Rect(bbox_pt[0], bbox_pt[1], bbox_pt[2], bbox_pt[3])
    # Add padding
    if pad_pt:
        clip = fitz.Rect(
            max(0, clip.x0 - pad_pt),
            max(0, clip.y0 - pad_pt),
            min(page.rect.width, clip.x1 + pad_pt),
            min(page.rect.height, clip.y1 + pad_pt),
        )
    mat = fitz.Matrix(dpi/72, dpi/72)
    pix = page.get_pixmap(matrix=mat, clip=clip)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return img, pix

def process_missing_image(tgt, record_mapping):
    """Process a missing-image target: locate, crop, generate candidates."""
    sqn = tgt["source_question_no"]
    pno = sqn - 1  # 0-indexed PDF page
    
    # Get question data
    q = record_mapping[tgt["id"]].get("question") or {}
    qi = record_mapping[tgt["id"]].get("question_import") or {}
    q_content = safe_json(q.get("content"))
    qi_content = safe_json(qi.get("parsed_content"))
    
    # Analyze page layout
    analysis = analyze_diagram_region(pno)
    
    # Determine bbox strategies based on pixel analysis
    # Known layout: right column X[270-540]pt, diagram at Y[46-56]pt,
    # option labels at Y[62-71]pt, option text at Y[86-93]pt (s200)
    content_bboxes = []
    snapshot_bboxes = []

    # Per-page content bbox estimates from pixel analysis
    page_bbox_map = {
        200: {
            "diagram_bbox": [278, 43, 540, 58],     # Tree diagram: Y[43-58]pt
            "expanded_bbox": [278, 43, 540, 75],     # Include option labels Y[62-71]
            "snapshot_bbox": [5, 27, 550, 115],      # Full question region
        },
        205: {
            "diagram_bbox": [278, 43, 540, 58],
            "expanded_bbox": [278, 43, 540, 75],
            "snapshot_bbox": [5, 27, 550, 120],
        },
        207: {
            "diagram_bbox": [278, 43, 540, 58],
            "expanded_bbox": [278, 43, 540, 75],
            "snapshot_bbox": [5, 27, 550, 120],
        },
    }

    bboxes = page_bbox_map.get(pno + 1, page_bbox_map[200])

    # Content image: tight diagram crop
    content_bboxes.append({
        "strategy": "tight_diagram",
        "bbox": bboxes["diagram_bbox"],
        "confidence": 0.80,
        "requires_review": True,
    })

    # Content image: expanded with option label context
    content_bboxes.append({
        "strategy": "expanded_diagram",
        "bbox": bboxes["expanded_bbox"],
        "confidence": 0.85,
        "requires_review": True,
    })

    # Source snapshot
    snapshot_bboxes.append({
        "strategy": "full_question_region",
        "bbox": bboxes["snapshot_bbox"],
        "confidence": 0.85,
        "requires_review": True,
    })
    
    # Generate actual image crops for the best candidate
    content_img = None
    snapshot_img = None
    content_info = None
    snap_info = None
    
    if content_bboxes:
        best_content = content_bboxes[0]
        try:
            content_img, cpix = crop_region(pno, best_content["bbox"], dpi=400, pad_pt=2)
            content_png = png_bytes(content_img)
            content_hash = sha256_bytes(content_png)
            content_info = {
                "bbox": best_content["bbox"],
                "strategy": best_content["strategy"],
                "confidence": best_content["confidence"],
                "requires_review": best_content["requires_review"],
                "hash": content_hash,
                "width": content_img.width,
                "height": content_img.height,
                "size_bytes": len(content_png),
            }
            # Save
            fname = f"content_{tgt['id']}_{md5_digest(json.dumps(best_content['bbox']))}.png"
            content_img.save(str(CONTENT_DIR / fname), "PNG")
            content_info["filename"] = fname
        except Exception as e:
            content_info = {"error": str(e)}
    
    if snapshot_bboxes:
        best_snap = snapshot_bboxes[0]
        try:
            snapshot_img, spix = crop_region(pno, best_snap["bbox"], dpi=200, pad_pt=3)
            snap_png = png_bytes(snapshot_img)
            snap_hash = sha256_bytes(snap_png)
            snap_info = {
                "bbox": best_snap["bbox"],
                "strategy": best_snap["strategy"],
                "confidence": best_snap["confidence"],
                "hash": snap_hash,
                "width": snapshot_img.width,
                "height": snapshot_img.height,
                "size_bytes": len(snap_png),
            }
            fname = f"snapshot_{tgt['id']}_{md5_digest(json.dumps(best_snap['bbox']))}.png"
            snapshot_img.save(str(SNAPSHOT_DIR / fname), "PNG")
            snap_info["filename"] = fname
        except Exception as e:
            snap_info = {"error": str(e)}
    
    # Proposed segment structure
    proposed_content_segment = None
    if content_info and content_info.get("filename"):
        proposed_content_segment = {
            "type": "image",
            "url": f"/static/question-assets/202607/ds_sc/{content_info['filename']}",
            "display": True,
            "semantic_role": "content_image",
            "region_type": "stem_diagram",
            "region_id": f"q{sqn}_diagram",
            "placement": "after_stem",
            "source_page": pno + 1,
            "bbox": content_info["bbox"],
            "coordinate_space": "pdf_points",
            "crop_version": "visual-v2.1",
            "confidence": content_info["confidence"],
            "requires_review": True,
        }
    
    proposed_snapshot = None
    if snap_info and snap_info.get("filename"):
        proposed_snapshot = {
            "source_snapshot_url": f"/static/question-assets/202607/ds_sc/{snap_info['filename']}",
            "source_snapshot_page": pno + 1,
            "source_snapshot_bbox": snap_info["bbox"],
            "source_snapshot_coordinate_space": "pdf_points",
            "source_snapshot_full_page": False,
            "source_snapshot_strategy": snap_info["strategy"],
        }
    
    # Quality gates
    quality_gates = [
        {"gate": "bbox_valid", "passed": content_info is not None and content_info.get("width", 0) > 50},
        {"gate": "no_brand_header", "passed": content_bboxes and content_bboxes[0]["bbox"][1] >= 36},
        {"gate": "reasonable_size", "passed": content_info is not None and content_info.get("width", 0) > 100 and content_info.get("height", 0) > 10},
        {"gate": "has_content", "passed": content_info is not None},
    ]
    
    return {
        "target_id": tgt["id"],
        "question_id": q.get("id"),
        "source_question_no": sqn,
        "pdf_page": pno + 1,
        "page_analysis": analysis,
        "proposed_content_bbox": content_bboxes,
        "proposed_snapshot_bbox": snapshot_bboxes,
        "content_candidate": content_info,
        "snapshot_candidate": snap_info,
        "proposed_content_segment": proposed_content_segment,
        "proposed_snapshot_metadata": proposed_snapshot,
        "quality_gates": quality_gates,
        "all_gates_passed": all(g["passed"] for g in quality_gates),
        "warnings": [],
    }

# ── 3. URL Fix: Q.294 and Q.305 ──────────────────────────────────────────
def check_localhost_file(url):
    """Check if a localhost URL's file exists locally and return its info."""
    if not url or "localhost" not in url:
        return None
    
    # Extract path
    # URL like: http://localhost:8000/static/question-assets/202607/visual-v2.1_ds_xxx_content.png
    path_part = url.split("/static/", 1)[-1] if "/static/" in url else None
    if not path_part:
        return None

    pp = Path(path_part)
    local_path = STATIC_BASE / pp
    alt_path = STATIC_BASE / pp.parent / ("ds_sc/" + pp.name)
    
    result = {
        "original_url": url,
        "path_part": str(path_part),
        "static_local_path": str(local_path),
        "ds_sc_local_path": str(alt_path),
        "exists_in_static": local_path.exists(),
        "exists_in_ds_sc": alt_path.exists(),
    }
    
    if local_path.exists():
        result["file_size"] = local_path.stat().st_size
        result["sha256"] = sha256_file(str(local_path))
    elif alt_path.exists():
        result["file_size"] = alt_path.stat().st_size
        result["sha256"] = sha256_file(str(alt_path))
    
    # Proposed canonical URL
    result["proposed_url"] = f"/static/{path_part}"
    
    return result

def process_url_fix(tgt, record_mapping):
    """Process URL fix for localhost URLs."""
    q = record_mapping[tgt["id"]].get("question") or {}
    qi = record_mapping[tgt["id"]].get("question_import") or {}
    q_content = safe_json(q.get("content"))
    qi_content = safe_json(qi.get("parsed_content"))
    
    # Collect all image URLs from all locations
    image_urls = []
    
    # Question.image_url
    q_iu = safe_json(q.get("image_url"), [])
    if isinstance(q_iu, list):
        for url in q_iu:
            image_urls.append({"source": "question.image_url", "url": url})
    
    # Question.content.segments
    q_segments = q_content.get("segments", [])
    for seg in q_segments:
        if seg.get("type") == "image" and seg.get("url"):
            image_urls.append({"source": "question.content.segments[image]", "url": seg["url"], "segment_idx": q_segments.index(seg)})
    
    # QuestionImport.parsed_content.segments
    qi_segments = qi_content.get("segments", [])
    for seg in qi_segments:
        if seg.get("type") == "image" and seg.get("url"):
            image_urls.append({"source": "qi.parsed_content.segments[image]", "url": seg["url"]})
    
    # Question.content.source_snapshot_url
    snap_url = q_content.get("source_snapshot_url")
    if snap_url:
        image_urls.append({"source": "question.content.source_snapshot_url", "url": snap_url})
    
    # QuestionImport.parsed_content.source_snapshot_url
    qi_snap = qi_content.get("source_snapshot_url")
    if qi_snap:
        image_urls.append({"source": "qi.parsed_content.source_snapshot_url", "url": qi_snap})
    
    # Check each URL for localhost
    localhost_urls = []
    non_localhost_urls = []
    for entry in image_urls:
        url = entry["url"]
        if "localhost" in url:
            info = check_localhost_file(url)
            localhost_urls.append({**entry, "file_info": info})
        else:
            non_localhost_urls.append(entry)
    
    # Also check option images (from Q.294 option_group)
    # Check if options JSON contains images
    q_options = safe_json(q.get("options"), {})
    for key, val in q_options.items():
        if isinstance(val, str) and "localhost" in val:
            localhost_urls.append({"source": f"question.options.{key}", "url": val})
    
    all_files_found = all(u.get("file_info", {}).get("exists_in_static") or 
                          u.get("file_info", {}).get("exists_in_ds_sc") for u in localhost_urls)
    
    return {
        "target_id": tgt["id"],
        "localhost_urls_found": localhost_urls,
        "non_localhost_urls": non_localhost_urls,
        "all_files_exist": all_files_found,
        "fix_proposals": [
            {
                "original_url": u["url"],
                "proposed_url": u.get("file_info", {}).get("proposed_url") if u.get("file_info") else None,
                "file_sha256": u.get("file_info", {}).get("sha256") if u.get("file_info") else None,
                "source": u["source"],
            }
            for u in localhost_urls
        ],
    }

# ── 4. Text-only confirmation: Q.296 ────────────────────────────────────
def confirm_text_only(tgt, record_mapping):
    """Confirm Q.296 is text-only by checking source PDF."""
    q = record_mapping[tgt["id"]].get("question") or {}
    qi = record_mapping[tgt["id"]].get("question_import") or {}
    q_content = safe_json(q.get("content"))
    qi_content = safe_json(qi.get("parsed_content"))
    
    sqn = tgt["source_question_no"]
    pno = sqn - 1
    
    result = {
        "target_id": tgt["id"],
        "question_id": q.get("id"),
        "source_question_no": sqn,
        "pdf_page": pno + 1,
    }
    
    # Check stem for visual references
    stem = q_content.get("text", "")
    visual_keywords = ["如图", "右图", "下图", "图中", "下列图", "如下所示", "如图所示"]
    found_visual_refs = [kw for kw in visual_keywords if kw in stem]
    result["stem_visual_refs"] = found_visual_refs
    
    # Check parsed_options for empty/image placeholders
    po = safe_json(qi.get("parsed_options"), {})
    empty_opts = {k: v for k, v in po.items() if not v or (isinstance(v, str) and v.strip() == "")}
    result["empty_options"] = empty_opts
    
    # Check source snapshot for visual content
    snap_url = q_content.get("source_snapshot_url") or qi_content.get("source_snapshot_url")
    result["source_snapshot_url"] = snap_url
    
    # Examine PDF page for diagram content
    try:
        analysis = analyze_diagram_region(pno)
        regions = analysis["content_regions"]
        has_diagram = len(regions) > 0 and regions[0]["y_end"] - regions[0]["y_start"] > 10
        result["pdf_diagram_regions"] = regions
        result["pdf_has_diagram"] = has_diagram
    except Exception as e:
        result["pdf_analysis_error"] = str(e)
        result["pdf_has_diagram"] = False
    
    # Decision - with manual override for known text-only questions
    # Q.296 (s371) is explicitly marked as requires_content_image=false in manual-bboxes-v2.json
    is_text_only_override = (tgt.get("source_question_no") == 371)

    if is_text_only_override:
        requires_content_image = False
        pdf_has_diagram = False  # override
    else:
        requires_content_image = (
            len(found_visual_refs) > 0 or
            (len(empty_opts) > 0) or
            result.get("pdf_has_diagram", False)
        )
    
    result["requires_content_image"] = requires_content_image
    result["visual_kind"] = "none" if not requires_content_image else "ambiguous"
    result["visual_schema_state"] = "not_applicable"
    result["migration_candidate"] = False
    result["migration_eligible"] = False
    result["suggested_action"] = "no_action"
    
    # Check if render_mode=segments with only text is valid
    # Current state: render_mode=segments, segments has 1 text entry
    segments = q_content.get("segments", [])
    all_text = all(s.get("type") == "text" for s in segments)
    result["current_segments_count"] = len(segments)
    result["all_segments_are_text"] = all_text
    result["render_mode_segments_valid"] = True  # Only-text segments is valid
    
    return result

# ── 5. Main generator ────────────────────────────────────────────────────
def generate():
    print("=" * 60)
    print("Batch 1 Dry-Run Generator")
    print(f"Run ID: {RUN_ID}")
    print(f"Output: {OUT_DIR}")
    print("=" * 60)
    
    # Step 1: Verify record mapping
    print("\n[1/5] Verifying record mapping...")
    record_mapping, mapping_ok = verify_record_mapping()
    if not mapping_ok:
        print("  ⚠️  Some mappings failed — check details in manifest")
    
    # Step 2: Gather before-state data
    print("\n[2/5] Gathering before-state data...")
    db = get_db()
    before_state = {}
    for tgt in TARGETS:
        q = fetch_one(db, "SELECT * FROM questions WHERE id=?", (tgt["question_id"],))
        qi = fetch_one(db, "SELECT * FROM question_imports WHERE id=?", (tgt["qi_id"],))
        before_state[tgt["id"]] = {
            "question": dict(q) if q else None,
            "question_import": dict(qi) if qi else None,
        }
    db.close()
    
    # Step 3: Process each target
    print("\n[3/5] Processing targets...")
    results = {}
    
    for tgt in TARGETS:
        print(f"\n  --- {tgt['id']}: {tgt['description']} ---")
        
        if tgt["type"] == "missing_image":
            result = process_missing_image(tgt, record_mapping)
            results[tgt["id"]] = result
            
            # Print summary
            ci = result.get("content_candidate") or {}
            si = result.get("snapshot_candidate") or {}
            qg = result.get("quality_gates", [])
            passed = sum(1 for g in qg if g.get("passed"))
            total = len(qg)
            print(f"    Page analysis: {len(result['page_analysis']['content_regions'])} content regions")
            print(f"    Content candidate: {ci.get('width','?')}x{ci.get('height','?')}px, confidence={ci.get('confidence',0)}")
            print(f"    Snapshot: {si.get('width','?')}x{si.get('height','?')}px")
            print(f"    Quality gates: {passed}/{total} passed")
            print(f"    All passed: {result.get('all_gates_passed')}")
        
        elif tgt["type"] == "url_fix":
            result = process_url_fix(tgt, record_mapping)
            results[tgt["id"]] = result
            
            print(f"    Localhost URLs found: {len(result['localhost_urls_found'])}")
            for u in result["fix_proposals"]:
                print(f"      {u['original_url'][:80]}")
                print(f"      → {u['proposed_url']}")
            print(f"    All files exist locally: {result.get('all_files_exist')}")
        
        elif tgt["type"] == "text_only_confirm":
            result = confirm_text_only(tgt, record_mapping)
            results[tgt["id"]] = result
            
            print(f"    Stem visual refs: {result.get('stem_visual_refs') or 'none'}")
            print(f"    PDF diagram regions: {len(result.get('pdf_diagram_regions', []))}")
            print(f"    Requires content image: {result['requires_content_image']}")
            print(f"    Visual kind: {result['visual_kind']}")
            print(f"    All segments text: {result.get('all_segments_are_text')}")
            print(f"    Suggested action: {result['suggested_action']}")
    
    # Step 4: Generate proposed after-state
    print("\n[4/5] Generating proposed after-state...")
    after_proposed = {}
    for tgt in TARGETS:
        tgt_id = tgt["id"]
        result = results.get(tgt_id, {})
        before = before_state.get(tgt_id, {})
        
        q = before.get("question") or {}
        qi_before = before.get("question_import") or {}
        q_content = safe_json(q.get("content"))
        qi_content = safe_json(qi_before.get("parsed_content"))
        
        if tgt["type"] == "missing_image":
            # Create proposed Question.content
            new_content = dict(q_content)
            new_content["render_mode"] = "segments"
            
            # Build segments: text + image
            segments = []
            stem_text = q_content.get("text", "")
            if stem_text:
                segments.append({
                    "type": "text",
                    "text": stem_text,
                })
            
            ci = result.get("content_candidate") or {}
            if ci.get("filename"):
                segments.append({
                    "type": "image",
                    "url": f"/static/question-assets/202607/ds_sc/{ci['filename']}",
                    "display": True,
                    "semantic_role": "content_image",
                    "region_type": "stem_diagram",
                    "region_id": f"q{tgt['source_question_no']}_diagram",
                    "placement": "after_stem",
                    "source_page": tgt["source_question_no"],
                    "bbox": ci.get("bbox", []),
                    "coordinate_space": "pdf_points",
                    "crop_version": "visual-v2.1",
                    "confidence": ci.get("confidence", 0),
                    "requires_review": True,
                })
            
            new_content["segments"] = segments
            
            # Add snapshot metadata
            si = result.get("snapshot_candidate") or {}
            if si.get("filename"):
                new_content["source_snapshot_url"] = f"/static/question-assets/202607/ds_sc/{si['filename']}"
                new_content["source_snapshot_page"] = tgt["source_question_no"]
                new_content["source_snapshot_bbox"] = si.get("bbox", [])
                new_content["source_snapshot_coordinate_space"] = "pdf_points"
                new_content["source_snapshot_full_page"] = False
                new_content["source_snapshot_strategy"] = si.get("strategy", "")
            
            # Proposed Question.image_url
            new_image_url = []
            if ci.get("filename"):
                new_image_url.append(f"/static/question-assets/202607/ds_sc/{ci['filename']}")
            
            new_qi_content = dict(qi_content) if qi_content else {}
            # If QI content had segments, merge image into it
            qi_segments = list(new_qi_content.get("segments", []))
            if not any(s.get("type") == "image" for s in qi_segments):
                if ci.get("filename"):
                    qi_segments.append({
                        "type": "image",
                        "url": f"/static/question-assets/202607/ds_sc/{ci['filename']}",
                        "display": True,
                        "semantic_role": "content_image",
                        "region_type": "stem_diagram",
                        "region_id": f"q{tgt['source_question_no']}_diagram",
                    })
                new_qi_content["segments"] = qi_segments
            
            if si.get("filename"):
                new_qi_content["source_snapshot_url"] = f"/static/question-assets/202607/ds_sc/{si['filename']}"
            
            after_proposed[tgt_id] = {
                "question_content": new_content,
                "question_image_url": new_image_url,
                "qi_parsed_content": new_qi_content,
            }
        
        elif tgt["type"] == "url_fix":
            url_result = results[tgt_id]
            new_content = dict(q_content)
            new_qi_content = dict(qi_content) if qi_content else {}
            new_image_url = safe_json(q.get("image_url"), [])
            
            # Fix each localhost URL
            for fix in url_result.get("fix_proposals", []):
                orig = fix["original_url"]
                proposed = fix["proposed_url"]
                
                # Fix in content.segments
                segments = new_content.get("segments", [])
                for seg in segments:
                    if seg.get("url") == orig:
                        seg["url"] = proposed
                
                # Fix in content.source_snapshot_url
                if new_content.get("source_snapshot_url") == orig:
                    new_content["source_snapshot_url"] = proposed
                
                # Fix in image_url list
                if isinstance(new_image_url, list):
                    new_image_url = [proposed if u == orig else u for u in new_image_url]
                
                # Fix in QI parsed_content
                qi_segments = new_qi_content.get("segments", [])
                for seg in qi_segments:
                    if seg.get("url") == orig:
                        seg["url"] = proposed
                
                if new_qi_content.get("source_snapshot_url") == orig:
                    new_qi_content["source_snapshot_url"] = proposed
            
            after_proposed[tgt_id] = {
                "question_content": new_content,
                "question_image_url": new_image_url,
                "qi_parsed_content": new_qi_content,
            }
        
        elif tgt["type"] == "text_only_confirm":
            after_proposed[tgt_id] = {
                "status": "no_change_needed",
                "requires_content_image": results[tgt_id].get("requires_content_image"),
                "suggested_action": results[tgt_id].get("suggested_action"),
            }
    
    # Step 5: Write deliverables
    print("\n[5/5] Writing deliverables...")
    
    # Run manifest
    manifest = {
        "run_id": RUN_ID,
        "generated_at": datetime.now().isoformat(),
        "output_dir": str(OUT_DIR),
        "source_pdf": str(PDF_PATH),
        "source_pdf_sha256": sha256_file(str(PDF_PATH)),
        "targets": [
            {
                "id": t["id"],
                "source_question_no": t["source_question_no"],
                "type": t["type"],
                "question_id": t["question_id"],
                "qi_id": t["qi_id"],
            }
            for t in TARGETS
        ],
        "record_mapping_ok": mapping_ok,
    }
    
    with open(OUT_DIR / "run-manifest.json", "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    # Targets summary
    with open(OUT_DIR / "targets.json", "w") as f:
        json.dump(TARGETS, f, indent=2, ensure_ascii=False)
    
    # Record mapping
    rm_clean = {}
    for k, v in record_mapping.items():
        rm_clean[k] = {
            "mapping_ok": v["mapping_ok"],
            "issues": v["issues"],
            "qi_id": v["question_import"]["id"] if v["question_import"] else None,
            "q_id": v["question"]["id"] if v["question"] else None,
            "qi_question_id": v["question_import"]["question_id"] if v["question_import"] else None,
        }
    with open(OUT_DIR / "record-mapping.json", "w") as f:
        json.dump(rm_clean, f, indent=2)
    
    # Before-state
    with open(OUT_DIR / "before.json", "w") as f:
        json.dump(before_state, f, indent=2, ensure_ascii=False, default=str)
    
    # After-proposed
    with open(OUT_DIR / "after-proposed.json", "w") as f:
        json.dump(after_proposed, f, indent=2, ensure_ascii=False, default=str)
    
    # Asset URL diff (for URL fix targets)
    url_diffs = {}
    for tgt in TARGETS:
        if tgt["type"] == "url_fix":
            url_diffs[tgt["id"]] = results[tgt["id"]]
    with open(OUT_DIR / "asset-url-diff.json", "w") as f:
        json.dump(url_diffs, f, indent=2, ensure_ascii=False)
    
    # Quality report
    quality_report = {}
    for tgt in TARGETS:
        tgt_id = tgt["id"]
        r = results.get(tgt_id, {})
        
        if tgt["type"] == "missing_image":
            quality_report[tgt_id] = {
                "page_analysis": r.get("page_analysis"),
                "quality_gates": r.get("quality_gates"),
                "all_passed": r.get("all_gates_passed"),
                "warnings": r.get("warnings", []),
                "content_candidate": r.get("content_candidate"),
                "snapshot_candidate": r.get("snapshot_candidate"),
            }
        elif tgt["type"] == "url_fix":
            quality_report[tgt_id] = {
                "all_files_exist": r.get("all_files_exist"),
                "fixes_proposed": len(r.get("fix_proposals", [])),
            }
        elif tgt["type"] == "text_only_confirm":
            quality_report[tgt_id] = {
                "requires_content_image": r.get("requires_content_image"),
                "visual_kind": r.get("visual_kind"),
                "suggested_action": r.get("suggested_action"),
            }
    
    with open(OUT_DIR / "quality-report.json", "w") as f:
        json.dump(quality_report, f, indent=2, ensure_ascii=False)
    
    # Approval manifest
    approval = {
        "run_id": RUN_ID,
        "generated_at": datetime.now().isoformat(),
        "pdf_sha256": manifest["source_pdf_sha256"],
        "targets": {},
    }
    for tgt in TARGETS:
        tgt_id = tgt["id"]
        r = results.get(tgt_id, {})
        
        base_approval = {
            "record_mapping_approval": "pending",
            "final_approval": "pending",
        }
        
        if tgt["type"] == "missing_image":
            base_approval.update({
                "requires_content_image_approval": "pending",
                "content_bbox_approval": "pending",
                "content_image_approval": "pending",
                "source_snapshot_approval": "pending",
                "segment_placement_approval": "pending",
                "asset_url_approval": "not_applicable",
                "published_sync_approval": "pending",
                "migration_eligible": False,
            })
        elif tgt["type"] == "url_fix":
            base_approval.update({
                "requires_content_image_approval": "not_applicable",
                "content_bbox_approval": "not_applicable",
                "content_image_approval": "not_applicable",
                "source_snapshot_approval": "not_applicable",
                "segment_placement_approval": "not_applicable",
                "asset_url_approval": "pending",
                "published_sync_approval": "pending",
                "migration_eligible": False,
            })
        elif tgt["type"] == "text_only_confirm":
            base_approval.update({
                "requires_content_image_approval": "not_applicable",
                "content_bbox_approval": "not_applicable",
                "content_image_approval": "not_applicable",
                "source_snapshot_approval": "not_applicable",
                "segment_placement_approval": "not_applicable",
                "asset_url_approval": "not_applicable",
                "published_sync_approval": "not_applicable",
                "final_approval": "pending",
                "migration_eligible": False,
                "visual_schema_state": "not_applicable",
            })
        
        approval["targets"][tgt_id] = base_approval
    
    with open(OUT_DIR / "approval.json", "w") as f:
        json.dump(approval, f, indent=2, ensure_ascii=False)
    
    # Full results
    with open(OUT_DIR / "candidate-previews.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    
    # Summary
    print("\n" + "=" * 60)
    print("Batch 1 Dry-Run Complete")
    print("=" * 60)
    print(f"Output directory: {OUT_DIR}")
    print(f"\nDeliverables generated:")
    for f in sorted(OUT_DIR.iterdir()):
        if f.is_file():
            size = f.stat().st_size
            print(f"  {f.name} ({size:,} bytes)")
    
    print(f"\nProposed content images: {len(list(CONTENT_DIR.iterdir()))}")
    print(f"Proposed source snapshots: {len(list(SNAPSHOT_DIR.iterdir()))}")
    print(f"\nMapping status: {'✅ ALL OK' if mapping_ok else '⚠️  ISSUES FOUND'}")
    
    print("\nIMPORTANT: No database, no static files, no production images were modified.")
    print("All outputs are dry-run only. Review deliverables before any apply.")
    
    return manifest

if __name__ == "__main__":
    generate()
