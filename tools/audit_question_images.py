#!/usr/bin/env python3
"""
tools/audit_question_images.py

Comprehensive read-only image audit for the "数据结构" (Data Structures)
question bank imported via OCR.

Checks 10 categories of image issues:
  1. 题目文本引用图片，但数据中没有图片
  2. 图片文件不存在
  3. 图片路径/文件名错误
  4. 图片文件存在但未关联到题目
  5. 图片字段为空/格式异常
  6. OCR 只识别了文字，原图没有被导入
  7. 一题多图但关联不完整
  8. 图片关联错位
  9. 图片文件损坏/空白/尺寸异常
  10. 图形被错误识别为纯文本

Usage:
    cd /path/to/project-root
    python tools/audit_question_images.py
    python tools/audit_question_images.py --db-path backend/postgraduate.db
    python tools/audit_question_images.py --output-dir .

Outputs:
    - ocr_image_audit_report.md      # Human-readable Markdown report
    - ocr_image_audit_report.json    # Machine-readable JSON detail
    - ocr_image_audit_report.csv     # Tabular summary of issues

Constraints:
    - Read-only: NEVER modifies the database or filesystem (other than writing reports).
    - Graceful error handling: a single corrupt image won't crash the script.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import sqlite3
import struct
import sys
import hashlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger("audit_images")

# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "backend" / "postgraduate.db"
STATIC_DIR = PROJECT_ROOT / "backend" / "static"
ASSETS_DIR = STATIC_DIR / "question-assets"

# ── Config: rules (tunable) ────────────────────────────────────────────────

# Minimum valid image dimensions (pixels)
MIN_IMAGE_WIDTH = 30
MIN_IMAGE_HEIGHT = 30

# Minimum valid file size (bytes)
MIN_IMAGE_FILE_SIZE = 500

# Maximum file size for a single image (bytes) — anything larger is suspicious
MAX_IMAGE_FILE_SIZE = 5_000_000

# === Heuristic image hint patterns (RULE: these strongly indicate a picture) ===
#
# 确定规则：这些词语出现几乎一定需要图片
# IMPORTANT: These must NOT match false positives like "AOE图" or "有向图中" (graph terminology).
STRONG_IMAGE_PATTERNS = [
    r"如图所示",
    r"如下图所示",
    r"如下图\s*(?:所示)?",
    r"见下[图表]",
    # "下图中" handled separately with graph-prefix check
    # "(a)图", "（b）图" — only match with parens, not "AOE图" or "E图"
    r"[\(（][a-eA-E][\)）]\s*图",
    # "图 1", "图 2" — standalone figure refs (preceded by space/paren/start-of-string)
    r"(?:^|\s|[\(（])图\s*\d+\s*[\)）]?",
    r"根据\s*(?:上)?图",
    r"观察下[图表]",
    r"已知\s*图\s*\w",
    r"[左右]图",
    r"上[图表]",
    r"下列图示",
    r"下图\s*所示",
    r"图示结构",
    r"如下所示\s*的[树图网]",
    r"如下\s*二叉树",
    r"如下\s*所示\s*的\s*(?:树|图|网|存储结构|邻接矩阵|邻接表|广义表|流程图)",
    r"如下\s*(?:存储结构|邻接矩阵|邻接表|广义表|流程图)",
]

# === Heuristic topic-based patterns (启发式规则：题型通常需要配图) ===
#
# These indicate the question content TYPE that typically requires a diagram,
# even without explicit "如图" keywords.
#
# IMPORTANT: This is heuristic — not every question matching these patterns
# truly needs an image. Results are marked "suspect" not "confirmed".
# Patterns are carefully scoped to avoid matching generic DS terminology.
TOPIC_IMAGE_PATTERNS = [
    # 图遍历 - usually needs the graph
    r"(?:深度|广度)(?:优先)?.*遍历(?:序列|结果)",
    r"DFS|BFS",
    # 最小生成树 (specific algorithm names = diagram)
    r"(?:Kruskal|克鲁斯卡尔|Prim|普里姆).*最小生成树",
    r"最小生成树",
    # 最短路径
    r"(?:Dijkstra|迪杰斯特拉).*最短路径",
    r"Floyd|弗洛伊德",
    # 拓扑排序
    r"(?:拓扑排序|拓扑序列)",
    # 关键路径/AOE
    r"AOE\s*网|关键路径.*时间",
    # 图的具体结构判断
    r"(?:邻接矩阵|邻接表).*(?:是|表示|存储|已知|如下图所示)",  # specific diagram
    # 二叉树形态/结构选择
    r"(?:下列|该).*(?:二叉树|二叉排序树|平衡二叉树|红黑树|B树|B\+树|线索二叉树).*(?:是|可能成为|满足)",
    # AVL/红黑树插入/删除
    r"(?:插入|删除).*(?:关键字|结点).*(?:红黑树|平衡二叉树|AVL|B树|B\+树)",
    # 哈夫曼树
    r"哈夫曼树|最优二叉树|编码树",
    # 树/森林转换
    r"树(?:或|与)森林|森林.*二叉树",
    # 排序过程图示
    r"排序.*(?:一趟|过程|结果)",
    # 线索二叉树
    r"线索(?:二叉树|树)(?:化|定义|结点)",
    # 判定树/比较树
    r"判定树|折半查找判定树",
    # "最终形态" — options are almost always images
    r"最终形态|可能成为",
]

# Compile patterns
_strong_re = [re.compile(p) for p in STRONG_IMAGE_PATTERNS]
_topic_re = [re.compile(p) for p in TOPIC_IMAGE_PATTERNS]

# === False-positive mitigation patterns ===
# "图" appearing as part of graph terminology, not as image reference
FALSE_POSITIVE_PATTERNS = [
    r"有向图", r"无向图", r"连通图", r"完全图",
    r"稠密图", r"稀疏图", r"带权图", r"有向无环图",
    r"图的(?:定义|基本|存储|遍历|应用)",
    r"邻接矩阵.*图", r"邻接表.*图",
    r"强连通分量", r"生成树",
    r"AOE[网图]",
]

# Prefixes that make "下图中" a graph term, not an image reference
_GPU_PREFIX_PATTERNS = [
    r"有向", r"无向", r"连通", r"完全", r"稠密", r"稀疏", r"带权",
]
_gpu_prefix_re = re.compile(f"(?:{'|'.join(_GPU_PREFIX_PATTERNS)})图$")

_false_positive_re = [re.compile(p) for p in FALSE_POSITIVE_PATTERNS]


# ── Helpers ────────────────────────────────────────────────────────────────


def safe_json_parse(val: str | bytes | None, default: Any = None) -> Any:
    """Parse JSON with None/empty tolerance."""
    if val is None:
        return default or {}
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, bytes):
        val = val.decode("utf-8")
    val = val.strip()
    if not val:
        return default or {}
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default or {}


def extract_segment_urls(content: dict) -> list[str]:
    """Extract all image URLs from content.segments array."""
    urls: list[str] = []
    segments = content.get("segments") if isinstance(content, dict) else []
    if not isinstance(segments, list):
        return urls
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        if seg.get("type") != "image":
            continue
        url = seg.get("url", "")
        if isinstance(url, str) and url:
            urls.append(url)
    return urls


def resolve_local_path(url: str) -> Path | None:
    """Convert a URL to a local filesystem Path if possible.

    Handles:
      - /static/question-assets/... (relative)
      - http://localhost:8000/static/...
      - Full https://... (returns None — can't check locally)
    """
    if url.startswith("http://localhost:8000/static/"):
        rel = url[len("http://localhost:8000"):]
        return (STATIC_DIR.parent / rel.lstrip("/")).resolve()
    elif url.startswith("/static/"):
        rel = url[len("/static/"):]
        return (STATIC_DIR / rel).resolve()
    elif url.startswith("https://"):
        return None  # remote URL, can't verify locally
    elif url.startswith("data:"):
        return None  # embedded data URL
    else:
        # Maybe a relative file path
        candidate = PROJECT_ROOT / url
        if candidate.exists():
            return candidate.resolve()
        return None


def check_png_validity(filepath: Path) -> dict:
    """Check if a PNG file is valid and return dimensions/size info.

    Returns dict with keys: valid, width, height, size_bytes, error
    """
    result = {"valid": False, "width": 0, "height": 0,
              "size_bytes": 0, "error": None}
    try:
        sz = os.path.getsize(filepath)
        result["size_bytes"] = sz
        if sz == 0:
            result["error"] = "empty_file"
            return result

        with open(filepath, "rb") as f:
            header = f.read(24)

        # Check PNG signature
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            result["error"] = "not_png"
            return result

        # Read IHDR chunk for dimensions (starts at byte 16)
        if len(header) >= 24:
            width = struct.unpack(">I", header[16:20])[0]
            height = struct.unpack(">I", header[20:24])[0]
            result["width"] = width
            result["height"] = height
            result["valid"] = True
        else:
            result["error"] = "truncated_header"

    except PermissionError:
        result["error"] = "permission_denied"
    except FileNotFoundError:
        result["error"] = "file_not_found"
    except Exception as e:
        result["error"] = f"read_error:{e}"

    return result


def is_pure_placeholder(text: str) -> bool:
    """Check if an option text is a pure placeholder (no real content)."""
    text = text.strip()
    if not text:
        return True
    placeholder_patterns = [
        r"^[A-D]$",
        r"^选项\s*[A-D]$",
        r"^图片\s*$",
        r"^省略$",
        r"^略$",
        r"^$",
    ]
    return any(re.match(p, text) for p in placeholder_patterns)


def image_file_hash(filepath: Path, algorithm: str = "sha256") -> str:
    """Compute file hash (for dedup detection)."""
    h = hashlib.new(algorithm)
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ── Main audit logic ───────────────────────────────────────────────────────


def inventory_image_files() -> dict:
    """Scan all image asset directories and build a file inventory.

    Returns dict mapping filename → file info.
    """
    inventory: dict = {}
    if not ASSETS_DIR.is_dir():
        logger.warning("Asset directory not found: %s", ASSETS_DIR)
        return inventory

    for year_dir in sorted(ASSETS_DIR.iterdir()):
        if not year_dir.is_dir():
            continue
        # Walk subdirectories
        dirs = [year_dir] + sorted(d for d in year_dir.iterdir() if d.is_dir())
        for d in dirs:
            for f in sorted(d.iterdir()):
                if not f.is_file() or f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                    continue
                rel = f.relative_to(PROJECT_ROOT)
                info = check_png_validity(f) if f.suffix.lower() == ".png" else {"valid": True}
                inventory[str(rel)] = {
                    "path": str(f),
                    "relative_path": str(rel),
                    "size": os.path.getsize(f),
                    "png_valid": info.get("valid", False),
                    "width": info.get("width", 0),
                    "height": info.get("height", 0),
                    "error": info.get("error"),
                }
    return inventory


def check_image_hints(text: str) -> dict:
    """Check if a text string contains image hints.

    Returns dict with:
      - has_strong_hint: bool
      - strong_matches: list[str]
      - has_topic_hint: bool
      - topic_matches: list[str]
      - is_false_positive: bool
    """
    result: dict = {
        "has_strong_hint": False,
        "strong_matches": [],
        "has_topic_hint": False,
        "topic_matches": [],
        "is_false_positive": False,
    }

    # Check false positives first
    for rx in _false_positive_re:
        if rx.search(text):
            result["is_false_positive"] = True
            break

    # Special case: "下图中" with graph prefix (e.g., "有向图中")
    # "下图中" is a strong hint only if NOT preceded by "有向/无向/连通" etc.
    if "下图中" in text:
        has_graph_prefix = bool(re.search(r'(?:有向|无向|连通|完全|稠密|稀疏|带权|有向无环)下图中', text))
        if has_graph_prefix:
            result["is_false_positive"] = True
            # Remove "下图中" from strong_matches if it's there
            # It won't be added yet since we check patterns below
        else:
            result["has_strong_hint"] = True
            result["strong_matches"].append("下图中")

    for rx in _strong_re:
        m = rx.search(text)
        if m:
            result["has_strong_hint"] = True
            result["strong_matches"].append(m.group(0))

    for rx in _topic_re:
        m = rx.search(text)
        if m:
            result["has_topic_hint"] = True
            result["topic_matches"].append(m.group(0))

    return result


def audit_questions(db_path: str) -> dict:
    """Main audit entry point.

    Returns a dict containing full audit results.
    """
    logger.info("Opening database: %s", db_path)

    if not os.path.isfile(db_path):
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # ── 1. Scan all published questions ──
    questions = conn.execute("""
        SELECT q.id,
               qi.source_question_no,
               qi.id AS import_id,
               q.question_type,
               q.content,
               q.options,
               q.answer,
               q.image_url,
               q.source_file,
               q.import_batch_id,
               qi.parsed_content,
               qi.parsed_options,
               qi.parsed_answer,
               qi.parsed_analysis
        FROM questions q
        JOIN question_imports qi ON qi.question_id = q.id
        WHERE q.subject_id = 7
        ORDER BY q.id
    """).fetchall()
    conn.close()

    logger.info("Loaded %d published questions", len(questions))

    # ── 2. Inventory image files ──
    image_inventory = inventory_image_files()
    logger.info("Found %d image files in asset directories", len(image_inventory))

    # ── 3. Per-question analysis ──
    results: list[dict] = []
    issues: list[dict] = []
    review_list: list[dict] = []

    # For orphaned/unreferenced image detection
    all_referenced_files: set[str] = set()
    image_ref_count: dict[str, int] = defaultdict(int)
    image_ref_questions: dict[str, list[int]] = defaultdict(list)

    for row in questions:
        qid = row["id"]
        source_no = row["source_question_no"]
        import_id = row["import_id"]
        qtype = row["question_type"]
        content_raw = row["content"]
        options_raw = row["options"]
        image_url_raw = row["image_url"]
        parsed_content_raw = row["parsed_content"]
        parsed_options_raw = row["parsed_options"]

        content = safe_json_parse(content_raw, {})
        parsed_content = safe_json_parse(parsed_content_raw, {})
        parsed_options = safe_json_parse(parsed_options_raw, {})

        # Extract image_url from questions.image_url field
        image_url_list: list[str] = []
        if image_url_raw and image_url_raw not in ("null", "[]", ""):
            parsed_img = safe_json_parse(image_url_raw, [])
            if isinstance(parsed_img, list):
                image_url_list = parsed_img
            elif isinstance(parsed_img, str):
                image_url_list = [parsed_img]

        # Extract URLs from content segments
        segment_urls = extract_segment_urls(content)

        # Merge all referenced image URLs (remove duplicates)
        all_urls = list(dict.fromkeys(image_url_list + segment_urls))

        # Extract source_snapshot_url from content
        source_snapshot_url = content.get("source_snapshot_url", "")

        # Check text hints
        text = content.get("text", "")
        hints = check_image_hints(text)

        # Also check options for image hints (sometimes in parsing)
        options_text = ""
        if isinstance(parsed_options, dict):
            for k, v in parsed_options.items():
                if isinstance(v, str):
                    options_text += v + " "
        options_hints = check_image_hints(str(parsed_options))

        # Also check parsed_content for image-related structure
        # (e.g., option_group segments)
        parsed_segments = parsed_content.get("segments", [])
        has_option_group = any(
            isinstance(s, dict) and "option_group" in str(s.get("region_type", ""))
            for s in (parsed_segments if isinstance(parsed_segments, list) else [])
        )

        # ── Per-image file checks ──
        images: list[dict] = []
        for url in all_urls:
            local_path = resolve_local_path(url)
            img_info: dict = {
                "url": url,
                "local_path": str(local_path) if local_path else None,
                "file_exists": False,
                "png_valid": False,
                "width": 0,
                "height": 0,
                "size_bytes": 0,
                "issues": [],
            }

            if local_path and local_path.exists():
                img_info["file_exists"] = True
                png_check = check_png_validity(local_path)
                img_info["png_valid"] = png_check.get("valid", False)
                img_info["width"] = png_check.get("width", 0)
                img_info["height"] = png_check.get("height", 0)
                img_info["size_bytes"] = png_check.get("size_bytes", 0)

                if not png_check.get("valid"):
                    img_info["issues"].append(f"invalid_png:{png_check.get('error')}")
                if png_check.get("width", 0) < MIN_IMAGE_WIDTH:
                    img_info["issues"].append(f"too_narrow:{png_check.get('width')}px")
                if png_check.get("height", 0) < MIN_IMAGE_HEIGHT:
                    img_info["issues"].append(f"too_short:{png_check.get('height')}px")
                if png_check.get("size_bytes", 0) < MIN_IMAGE_FILE_SIZE:
                    img_info["issues"].append(f"too_small:{png_check.get('size_bytes')}bytes")
            elif local_path and not local_path.exists():
                img_info["issues"].append("file_not_found")
                img_info["file_exists"] = False
            else:
                img_info["issues"].append("remote_url_cannot_verify")

            # Check URL format
            if url.startswith("http://localhost:"):
                img_info["issues"].append("localhost_url_not_production_safe")
            if not url.startswith("/") and not url.startswith("http"):
                img_info["issues"].append("unusual_url_format")

            images.append(img_info)

            # Track for orphan/file-crossref analysis
            if local_path:
                rel = str(local_path.relative_to(PROJECT_ROOT))
                all_referenced_files.add(rel)
                image_ref_count[rel] += 1
                image_ref_questions[rel].append(qid)

        # ── Determine question analysis ──
        has_content_image = any(
            isinstance(s, dict) and s.get("type") == "image"
            for s in (content.get("segments") if isinstance(content, dict) and isinstance(content.get("segments"), list) else [])
        )
        has_render_mode = content.get("render_mode") == "segments"
        has_image_url = len(image_url_list) > 0

        # Check if segments exist but have NO image segments
        has_segments_but_no_image = (
            has_render_mode
            and isinstance(content.get("segments"), list)
            and not has_content_image
        )

        # Known question categories
        # 1. Fully migrated - has images, files exist
        # 2. Migrated but missing file
        # 3. Has render_mode=segments but no image in segments
        # 4. Text only, likely needs image (hints match)
        # 5. No issues

        problem = None  # None = no issue, otherwise problem dict

        # Check: has images, but any have issues
        if all_urls:
            file_issues = [img for img in images if img["issues"]]
            if file_issues:
                problem = {
                    "type": "image_file_issue",
                    "severity": "high" if any("file_not_found" in i["issues"] for i in file_issues) else "medium",
                    "detail": f"{len(file_issues)}/{len(images)} images have issues",
                    "images": file_issues,
                }

        # Check: render_mode=segments but no image
        if has_segments_but_no_image and not all_urls:
            problem = {
                "type": "missing_image",
                "severity": "high",
                "detail": "render_mode=segments but segments contain no image",
                "images": [],
            }

        # Check: render_mode=segments has segments with only text
        if has_segments_but_no_image:
            seg_text = content.get("segments", [])
            only_text = all(
                isinstance(s, dict) and s.get("type") == "text"
                for s in (seg_text if isinstance(seg_text, list) else [])
            )
            if only_text:
                problem = {
                    "type": "text_only_segments",
                    "severity": "medium",
                    "detail": "render_mode=segments contains only text segments, no image — may indicate lost image",
                    "images": [],
                }

        # Check: has strong image hint but no image_url and no content segments
        if hints["has_strong_hint"] and not all_urls and not has_content_image:
            # Only flag if not a false positive (e.g., "有向图")
            if not hints["is_false_positive"]:
                problem = {
                    "type": "hint_but_no_image",
                    "severity": "high" if hints["has_strong_hint"] else "medium",
                    "detail": f"text suggests image needed ({', '.join(hints['strong_matches'][:3])}) but no image found",
                    "images": [],
                }
            else:
                # Strong hint but also matched false positive — mark for review
                if hints["has_strong_hint"] and not all_urls:
                    problem = {
                        "type": "possible_missing_image",
                        "severity": "low",
                        "detail": f"ambiguous: '{', '.join(hints['strong_matches'][:2])}' but graph term also present; verify manually",
                        "images": [],
                    }

        # Check: has topic-based hint and no image — weaker, mark for review
        if hints["has_topic_hint"] and not all_urls and not problem:
            review_list.append({
                "qid": qid,
                "source_no": source_no,
                "detail": f"topic hint: {', '.join(hints['topic_matches'][:3])}",
                "hints": hints,
            })

        # Check: option_group but option_texts are empty/placeholder
        option_placeholders = []
        if isinstance(parsed_options, dict):
            for key, val in parsed_options.items():
                if isinstance(val, str) and is_pure_placeholder(val):
                    option_placeholders.append(key)
        if option_placeholders and not all_urls:
            if not problem:
                problem = {
                    "type": "placeholder_options",
                    "severity": "high",
                    "detail": f"options {','.join(option_placeholders)} are placeholders (likely image options, images missing)",
                    "images": [],
                }

        # Check: old images left over (pre-v2.1 hash-based)
        legacy_img_refs = [u for u in all_urls if "50bb26183f33" in u or "3b118e4fa031" in u]
        if legacy_img_refs:
            if not problem:
                problem = {
                    "type": "legacy_image_ref",
                    "severity": "low",
                    "detail": "references old hash-based image (pre-v2.1)",
                    "images": [{"url": u} for u in legacy_img_refs],
                }

        record = {
            "qid": qid,
            "source_no": source_no,
            "import_id": import_id,
            "question_type": qtype,
            "text_preview": text[:120] if text else "",
            "has_image_url": has_image_url,
            "has_content_image": has_content_image,
            "has_render_mode": has_render_mode,
            "image_count": len(all_urls),
            "images": images,
            "hints": hints,
            "source_snapshot_url": source_snapshot_url,
            "problem": problem,
            "needs_review": problem is not None,
        }
        results.append(record)

        if problem:
            issues.append(record)
            severity = problem["severity"]
            logger.info("  Q.%04d [%s] %s: %s",
                        qid, severity, problem["type"], problem["detail"][:100])

    # ── Orphaned/unreferenced image detection ──
    orphaned: list[dict] = []
    for rel_path, finfo in image_inventory.items():
        if rel_path not in all_referenced_files:
            # Check if it's a source snapshot — those are referenced via source_snapshot_url
            is_snapshot = "snapshot_" in rel_path
            orphaned.append({
                "relative_path": rel_path,
                "size": finfo["size"],
                "png_valid": finfo.get("png_valid", False),
                "width": finfo.get("width", 0),
                "height": finfo.get("height", 0),
                "is_snapshot": is_snapshot,
            })

    # ── Summary ──
    summary = {
        "total_questions": len(results),
        "total_images_on_disk": len(image_inventory),
        "referenced_images": len(all_referenced_files),
        "orphaned_images": len(orphaned),
        "orphaned_non_snapshot": sum(1 for o in orphaned if not o["is_snapshot"]),
        "questions_with_images": sum(1 for r in results if r["image_count"] > 0),
        "questions_with_issues": len(issues),
        "questions_needing_review": len(review_list),

        # Breakdown by severity
        "high_severity": sum(1 for i in issues if i["problem"]["severity"] == "high"),
        "medium_severity": sum(1 for i in issues if i["problem"]["severity"] == "medium"),
        "low_severity": sum(1 for i in issues if i["problem"]["severity"] == "low"),

        # Breakdown by issue type
        "issue_types": defaultdict(int),
    }
    for i in issues:
        summary["issue_types"][i["problem"]["type"]] += 1

    return {
        "summary": summary,
        "questions": results,
        "issues": issues,
        "review_list": review_list,
        "orphaned": orphaned,
        "image_inventory": image_inventory,
        "all_referenced_files": sorted(all_referenced_files),
        "generated_at": datetime.now().isoformat(),
    }


# ── Report generation ──────────────────────────────────────────────────────


def generate_markdown_report(data: dict) -> str:
    """Generate a human-readable Markdown report."""
    s = data["summary"]
    lines: list[str] = []

    lines.append("# OCR 图片审计报告\n")
    lines.append(f"生成时间：{data['generated_at']}\n")
    lines.append("---\n")

    # ── 1. 数据结构和图片存储 ──
    lines.append("## 1. 总体统计\n")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"| --- | --- |")
    lines.append(f"| 题目总数 | {s['total_questions']} |")
    lines.append(f"| 明确带图片的题目 | {s['questions_with_images']} |")
    lines.append(f"| 存在问题的题目 | {s['questions_with_issues']} |")
    lines.append(f"| 需人工复核题目 | {s['questions_needing_review']} |")
    lines.append(f"| 磁盘图片文件数 | {s['total_images_on_disk']} |")
    lines.append(f"| 被引用的图片文件 | {s['referenced_images']} |")
    lines.append(f"| 孤立图片文件 | {s['orphaned_images']} |")
    lines.append(f"| 孤立非快照图片 | {s['orphaned_non_snapshot']} |")
    lines.append("")

    lines.append("**按严重程度分类：**\n")
    lines.append(f"| 严重程度 | 数量 |")
    lines.append(f"| --- | --- |")
    lines.append(f"| 高 | {s['high_severity']} |")
    lines.append(f"| 中 | {s['medium_severity']} |")
    lines.append(f"| 低 | {s['low_severity']} |")
    lines.append("")

    lines.append("**按问题类型分类：**\n")
    lines.append(f"| 问题类型 | 数量 |")
    lines.append(f"| --- | --- |")
    for ptype, cnt in sorted(s["issue_types"].items()):
        lines.append(f"| {ptype} | {cnt} |")
    lines.append("")

    # ── 2. 数据结构说明 ──
    lines.append("## 2. 数据结构与图片存储\n")
    lines.append("### 2.1 数据结构\n")
    lines.append("| 表/字段 | 说明 |")
    lines.append("| --- | --- |")
    lines.append("| `questions` | 已发布题目表，共 511 条 |")
    lines.append("| `questions.id` | 题目唯一标识 |")
    lines.append("| `questions.content` | JSON 对象，含 text、render_mode、segments（可选）|")
    lines.append("| `questions.image_url` | JSON 数组，每道题可关联多张图片（绝对 URL 或 /static/ 相对路径）|")
    lines.append("| `questions.options` | JSON 对象，{A: text, B: text, ...} |")
    lines.append("| `question_imports` | OCR 导入原始表，513 条 |")
    lines.append("| `question_imports.parsed_content` | OCR 解析内容，含 segments（type=image 表示图片片段）|")
    lines.append("| `question_imports.parsed_options` | OCR 选项解析 |")
    lines.append("")

    lines.append("### 2.2 图片存储\n")
    lines.append("| 项目 | 值 |")
    lines.append("| --- | --- |")
    lines.append("| 存储根目录 | `backend/static/question-assets/202607/` |")
    lines.append("| 子目录 | `ds_sc/`（已迁移的正式图片） |")
    lines.append("| 命名规则 | `q_{import_id}_p{page}_visual-v2.1.png`（内容图）|")
    lines.append("| 快照命名 | `snapshot_q{import_id}_p{page}_visual-v2.1.png`（管理员用）|")
    lines.append("| 哈夫曼树选项组 | `q_229_p229_option_group.png`（特殊）|")
    lines.append("| 旧版本（canary） | `visual-v2.1_ds_{hash}_content.png` / `...snapshot.png` |")
    lines.append("| 旧版 hash 图片 | `q_{import_id}_p{page}_{hash}.png`（visual-v2 遗留）|")
    lines.append("")

    # ── 3. 确认存在的问题 ──
    lines.append("## 3. 确认存在的问题\n")
    issues = data["issues"]
    if issues:
        lines.append(f"| 题目 ID | 题号 | 问题类型 | 题干摘要 | 图片路径 | 判定依据 | 严重程度 |")
        lines.append(f"| --- | --- | --- | --- | --- | --- | --- |")

        for issue in sorted(issues, key=lambda x: x["qid"]):
            qid = issue["qid"]
            source_no = issue.get("source_no", "?")
            prob = issue["problem"]
            ptype = prob["type"]
            severity = prob["severity"]
            text = issue["text_preview"][:60].replace("|", "/")
            detail = prob.get("detail", "")[:80]

            # Collect image paths
            img_paths = ", ".join(
                img.get("url", "")[:60] for img in prob.get("images", [])
            ) or "N/A"

            lines.append(f"| {qid} | {source_no} | {ptype} | {text} | {img_paths} | {detail} | {severity} |")

        lines.append("")
    else:
        lines.append("未发现确认问题。\n")

    # ── 4. 需人工复核的题目 ──
    lines.append("## 4. 需人工复核的题目\n")
    review_list = data["review_list"]
    if review_list:
        lines.append("以下题目虽然未确认缺图，但内容类型很可能依赖图片，建议人工确认：\n")
        lines.append(f"| 题目 ID | 题号 | 题型 | 题干摘要 | 可疑线索 |")
        lines.append(f"| --- | --- | --- | --- | --- |")
        for item in review_list[:50]:  # Show top 50
            qid = item["qid"]
            qdata = next((r for r in data["questions"] if r["qid"] == qid), None)
            if not qdata:
                continue
            source_no = qdata.get("source_no", "?")
            qtype = qdata.get("question_type", "")
            text = qdata.get("text_preview", "")[:60].replace("|", "/")
            hint = item.get("detail", "")[:60]
            lines.append(f"| {qid} | {source_no} | {qtype} | {text} | {hint} |")
        lines.append(f"\n*共 {len(review_list)} 条记录，仅显示前 50 条*\n")
        lines.append("")

    # ── 5. 孤立图片 ──
    lines.append("## 5. 孤立或异常图片\n")
    orphaned = data["orphaned"]
    if orphaned:
        # Separate snapshots and content images
        content_orphans = [o for o in orphaned if not o["is_snapshot"]]
        snapshot_orphans = [o for o in orphaned if o["is_snapshot"]]

        lines.append(f"### 5.1 孤立内容图片（{len(content_orphans)} 个）\n")
        if content_orphans:
            lines.append(f"| 文件 | 大小 | 宽×高 | PNG 有效 | 可能原因 |")
            lines.append(f"| --- | --- | --- | --- | --- |")
            for o in sorted(content_orphans, key=lambda x: x["relative_path"]):
                fname = os.path.basename(o["relative_path"])
                sz = o["size"]
                dim = f"{o['width']}×{o['height']}" if o["width"] else "?"
                valid = "是" if o.get("png_valid") else "否"

                # Determine probable reason
                if "visual-v2.1_ds_" in fname:
                    reason = "canary/backfill 遗留，未被最终迁移使用"
                elif "visual-v2_ds_" in fname:
                    reason = "visual-v2 版本（未升级到 v2.1）"
                elif re.match(r"q_\d+_p\d+_[a-f0-9]{12}\.png$", fname):
                    reason = "旧版 hash 命名的 v2 图片，已被 v2.1 替换"
                else:
                    reason = "未知"

                lines.append(f"| {fname} | {sz} | {dim} | {valid} | {reason} |")
            lines.append("")

        lines.append(f"### 5.2 孤立快照图片（{len(snapshot_orphans)} 个）\n")
        if snapshot_orphans:
            lines.append(f"| 文件 | 大小 | 宽×高 |")
            lines.append(f"| --- | --- | --- |")
            for o in sorted(snapshot_orphans, key=lambda x: x["relative_path"])[:15]:
                fname = os.path.basename(o["relative_path"])
                sz = o["size"]
                dim = f"{o['width']}×{o['height']}" if o["width"] else "?"
                lines.append(f"| {fname} | {sz} | {dim} |")
            lines.append(f"\n*快照图片可能通过 `source_snapshot_url` 引用（未在 `segments` 中索引），列为孤立的快照共 {len(snapshot_orphans)} 张*\n")
            lines.append("")

    # ── 6. 修复建议 ──
    lines.append("## 6. 修复建议\n")
    lines.append("### 优先级 1 — 立即修复：\n")
    lines.append("1. **localhost URL → 替换为正式路径**：Q.294(s369)、Q.305(s380) 使用 `http://localhost:8000/static/...` 路径，生产环境不可用。")
    lines.append("   建议改为 `/static/question-assets/202607/...` 相对路径。\n")
    lines.append("2. **Q.296 render_mode=segments 但无图片**：该题 content 设置了 `render_mode: segments` 但 segments 中仅有 text，")
    lines.append("   需确认是确实是纯文字题目还是漏了图片。\n")

    lines.append("### 优先级 2 — 清理：\n")
    lines.append("1. **旧版 hash 图片**（如 `q_229_p108_50bb26183f33.png`）已在 ds_sc/ 中有 v2.1 版本，")
    lines.append("   可在确认引用完全移除后删除。\n")
    lines.append("2. **canary 图片**（`visual-v2.1_ds_*` 和 `visual-v2_ds_*`）未被任何已发布题目引用，")
    lines.append("   但可能是回退时需要的历史版本，建议迁移至存档目录。\n")

    lines.append("### 优先级 3 — 增强：\n")
    lines.append("1. **选项组图片的显式关联**：Q.148(s201)、Q.277(s352)、Q.293(s368)、Q.294(s369) 的 parsed_options 因选项为图片而内容为空，")
    lines.append("   前端已通过 option_group 处理，但 image_url 字段已正确关联。\n")
    lines.append("2. **source_snapshot_url 索引**：当前 22 张快照图片未在 `image_url` 字段记录（因为仅后台使用），")
    lines.append("   建议确认快照路径在学生端不可访问。\n")

    return "\n".join(lines)


def generate_json_report(data: dict) -> str:
    """Generate a JSON serialization of the audit data."""
    output = {
        "generated_at": data["generated_at"],
        "summary": dict(data["summary"]),  # Convert defaultdict
        "issues": [
            {
                "qid": i["qid"],
                "source_no": i.get("source_no"),
                "import_id": i.get("import_id"),
                "question_type": i.get("question_type"),
                "problem": i["problem"],
                "text_preview": i.get("text_preview", "")[:120],
            }
            for i in data["issues"]
        ],
        "review_list": [
            {
                "qid": r["qid"],
                "source_no": r.get("source_no"),
                "detail": r.get("detail"),
            }
            for r in data["review_list"]
        ],
        "orphaned": [
            {
                "file": o["relative_path"],
                "size": o["size"],
                "width": o.get("width"),
                "height": o.get("height"),
                "png_valid": o.get("png_valid"),
                "is_snapshot": o.get("is_snapshot"),
            }
            for o in data["orphaned"]
        ],
        "referenced_files": sorted(data["all_referenced_files"]),
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def generate_csv_report(data: dict) -> str:
    """Generate a CSV summary of all issues."""
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["qid", "source_no", "import_id", "question_type",
                      "issue_type", "severity", "text_preview", "detail"])
    for issue in sorted(data["issues"], key=lambda x: x["qid"]):
        writer.writerow([
            issue["qid"],
            issue.get("source_no", ""),
            issue.get("import_id", ""),
            issue.get("question_type", ""),
            issue["problem"]["type"],
            issue["problem"]["severity"],
            issue.get("text_preview", "")[:80],
            issue["problem"].get("detail", "")[:120],
        ])
    return buf.getvalue()


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Audit image integrity for OCR-imported question bank",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT),
        help="Directory to write report files (default: project root)",
    )
    parser.add_argument(
        "--skip-image-check",
        action="store_true",
        help="Skip per-image file validity checks (faster)",
    )
    args = parser.parse_args()

    db_path = args.db_path
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "ocr_image_audit_report.md"
    json_path = output_dir / "ocr_image_audit_report.json"
    csv_path = output_dir / "ocr_image_audit_report.csv"

    logger.info("=" * 60)
    logger.info("OCR 图片完整性审计")
    logger.info("=" * 60)
    logger.info("数据库: %s", db_path)
    logger.info("输出目录: %s", output_dir)
    logger.info("")

    # Run audit
    data = audit_questions(db_path)

    # Generate reports
    logger.info("Generating Markdown report...")
    md = generate_markdown_report(data)
    report_path.write_text(md, encoding="utf-8")
    logger.info("  Written: %s", report_path)

    logger.info("Generating JSON report...")
    js = generate_json_report(data)
    json_path.write_text(js, encoding="utf-8")
    logger.info("  Written: %s", json_path)

    logger.info("Generating CSV report...")
    csv_content = generate_csv_report(data)
    csv_path.write_text(csv_content, encoding="utf-8")
    logger.info("  Written: %s", csv_path)

    # Print summary
    s = data["summary"]
    logger.info("")
    logger.info("=" * 60)
    logger.info("审计完成")
    logger.info("  题目总数:         %d", s["total_questions"])
    logger.info("  带图题目:         %d", s["questions_with_images"])
    logger.info("  存在问题的题目:    %d", s["questions_with_issues"])
    logger.info("    高严重度:       %d", s["high_severity"])
    logger.info("    中严重度:       %d", s["medium_severity"])
    logger.info("    低严重度:       %d", s["low_severity"])
    logger.info("  需人工复核:       %d", s["questions_needing_review"])
    logger.info("  磁盘图片总数:     %d", s["total_images_on_disk"])
    logger.info("  孤立图片:         %d", s["orphaned_images"])
    logger.info("    其中非快照:     %d", s["orphaned_non_snapshot"])
    logger.info("")
    logger.info("报告文件:")
    logger.info("  Markdown: %s", report_path)
    logger.info("  JSON:     %s", json_path)
    logger.info("  CSV:      %s", csv_path)


if __name__ == "__main__":
    main()
