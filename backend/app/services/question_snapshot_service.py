"""题目截图边界服务 — 为 source_snapshot 计算精确 question_bbox。

功能：
1. 从 normalized_blocks 构造页面 OCR 行（含 bbox/zone）
2. 题号锚点识别（page_start + source_question_no + 正则）
3. 跨页/同页多题边界检测
4. 选项完整性校验与 bbox 扩展
5. 图形区域保护（题干-选项间垂直区域完整保留）
6. 坐标空间感知的 padding
7. 页眉排除（与 wangdao_preprocessor.classify_zone 一致）
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Question number patterns matching question_splitter ──
_Q_NUM_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(\d+)\s*[.．、]"),          # "1." "1．" "1、"
    re.compile(r"^(\d+)\s*[)）]"),            # "1)" "1）"
    re.compile(r"^\((\d+)\)"),                # "(1)"
    re.compile(r"^（(\d+)）"),                # "（1）"
    re.compile(r"^【(\d+)】"),                # "【1】"
    re.compile(r"^第\s*(\d+)\s*题"),          # "第1题"
]

# OCR-tolerant question number (l/I → 1)
_OCR_Q_PATTERN = re.compile(r"^([lI])\s*[.、)）]")

# Visual reference keywords (diagrams between stem and options)
_VISUAL_REF_KEYWORDS = [
    "如图", "如下图", "图中", "见图", "如图所示",
    "如下所示", "如下表", "根据图示",
    "上图", "下图", "表", "示意图",
    "从图中", "由图中", "由图可知", "由表可知",
    "根据图", "根据下表", "根据上表",
]

# ── Coordinate space helpers ──

CoordinateSpace = str
CS_IMAGE_PIXELS = "image_pixels"
CS_PDF_POINTS = "pdf_points"
CS_NORMALIZED_1000 = "normalized_1000"
CS_NORMALIZED_1 = "normalized_1"


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def expand_bbox(
    bbox: tuple[float, float, float, float],
    coordinate_space: str,
    padding_pt: float,
    page_image_width: int,
    page_image_height: int,
    page_pdf_width: float | None = None,
    page_pdf_height: float | None = None,
) -> tuple[float, float, float, float]:
    """Apply coordinate-space-aware padding to a bbox.

    Padding is always specified in PDF points (72 DPI).
    The function converts it to the target coordinate space.

    Args:
        bbox: (x0, y0, x1, y1) in the given coordinate space
        coordinate_space: one of "image_pixels", "pdf_points",
                          "normalized_1000", "normalized_1"
        padding_pt: padding in PDF points to apply on all sides
        page_image_width: page image width in pixels
        page_image_height: page image height in pixels
        page_pdf_width: PDF page width in points (required for pdf_points/image_pixels)
        page_pdf_height: PDF page height in points (required for pdf_points/image_pixels)

    Returns:
        (x0, y0, x1, y1) in the same coordinate space with padding applied,
        clamped to page boundaries.
    """
    x0, y0, x1, y1 = bbox

    if coordinate_space == CS_IMAGE_PIXELS:
        # Image pixels: convert from points to pixels using DPI
        if page_pdf_width and page_pdf_width > 0:
            dpi_x = page_image_width / page_pdf_width * 72
            dpi_y = page_image_height / page_pdf_height * 72 if page_pdf_height else dpi_x
        else:
            dpi_x = dpi_y = 150.0  # fallback default
        pad_x = padding_pt * dpi_x / 72.0
        pad_y = padding_pt * dpi_y / 72.0

    elif coordinate_space == CS_PDF_POINTS:
        # PDF points: 1 pt = 1 unit
        pad_x = padding_pt
        pad_y = padding_pt

    elif coordinate_space == CS_NORMALIZED_1000:
        # 0-1000 normalized: convert points relative to page size
        if page_pdf_width and page_pdf_width > 0:
            pad_x = padding_pt / page_pdf_width * 1000.0
        else:
            pad_x = padding_pt / 612 * 1000.0  # A4 fallback
        if page_pdf_height and page_pdf_height > 0:
            pad_y = padding_pt / page_pdf_height * 1000.0
        else:
            pad_y = padding_pt / 792 * 1000.0

    elif coordinate_space == CS_NORMALIZED_1:
        # 0.0-1.0 normalized
        if page_pdf_width and page_pdf_width > 0:
            pad_x = padding_pt / page_pdf_width
        else:
            pad_x = padding_pt / 612.0
        if page_pdf_height and page_pdf_height > 0:
            pad_y = padding_pt / page_pdf_height
        else:
            pad_y = padding_pt / 792.0

    else:
        # Unknown space — treat as image_pixels with fallback DPI
        pad_x = padding_pt * 150.0 / 72.0
        pad_y = pad_x

    # Determine page boundaries in coordinate space
    if coordinate_space == CS_IMAGE_PIXELS:
        max_x, max_y = float(page_image_width), float(page_image_height)
    elif coordinate_space == CS_PDF_POINTS:
        max_x = float(page_pdf_width or page_image_width / 150.0 * 72)
        max_y = float(page_pdf_height or page_image_height / 150.0 * 72)
    elif coordinate_space == CS_NORMALIZED_1000:
        max_x = 1000.0
        max_y = 1000.0
    elif coordinate_space == CS_NORMALIZED_1:
        max_x = 1.0
        max_y = 1.0
    else:
        max_x, max_y = float(page_image_width), float(page_image_height)

    # Apply and clamp
    return (
        _clamp(x0 - pad_x, 0.0, max_x),
        _clamp(y0 - pad_y, 0.0, max_y),
        _clamp(x1 + pad_x, 0.0, max_x),
        _clamp(y1 + pad_y, 0.0, max_y),
    )


# ── OCR line builder ──


def build_ocr_lines(normalized_blocks: list[dict]) -> list[dict]:
    """从 normalized_blocks 构造页面 OCR 行列表。

    每一行包含：
    - page
    - text
    - bbox (x0, y0, x1, y1)
    - confidence
    - zone (body/header/footer/watermark — 来自 classify_zone)
    - line_index (按 block 内行号)
    - page_width
    - page_height

    过滤空行。
    过滤 header/footer/watermark 区（同步过滤对应的 bbox 行）。

    Returns:
        list of dicts, each describing one OCR line with spatial info
    """
    from app.features.wangdao_preprocessor import classify_zone

    ocr_lines: list[dict] = []

    for block in normalized_blocks:
        page = block.get("page", 0) or block.get("page_index", 0)
        text = block.get("normalized_text") or block.get("text") or ""
        boxes = block.get("boxes", [])
        pw = block.get("page_width", 0)
        ph = block.get("page_height", 0)

        lines = text.split("\n")
        box_idx = 0
        for line_idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                # Empty lines don't consume a box index
                continue

            bbox_entry = boxes[box_idx] if box_idx < len(boxes) else None
            box_idx += 1

            if bbox_entry is None:
                continue

            coords = bbox_entry.get("bbox", [0, 0, 0, 0])
            x0, y0, x1, y1 = coords[0], coords[1], coords[2], coords[3]
            confidence = bbox_entry.get("confidence", 0.0) or 0.0

            # Classify zone to skip headers/footers/watermarks
            zone = classify_zone(stripped, x0, y0, x1, y1, pw, ph)
            if zone in ("header", "footer", "watermark"):
                continue

            ocr_lines.append({
                "page": page,
                "text": stripped,
                "bbox": (float(x0), float(y0), float(x1), float(y1)),
                "confidence": float(confidence),
                "zone": zone,
                "line_index": line_idx,
                "page_width": pw,
                "page_height": ph,
            })

    return ocr_lines


# ── Question number matching ──


def _match_question_number(text: str, expected_num: int | str | None) -> bool:
    """Check if text starts with a question number matching expected_num.

    Supports:
    - Exact number match: "15." vs 15
    - OCR-tolerant: "l." vs 1, "I." vs 1
    - With brackets: "【15】", "(15)"
    - Chinese: "第十五题"
    - Label match: source_question_label like "15.【2013】"

    Returns True if text appears to be the start of the expected question.
    """
    if not text:
        return False

    stripped = text.strip()

    if expected_num is not None:
        expected = int(expected_num) if isinstance(expected_num, str) and expected_num.isdigit() else (
            expected_num if isinstance(expected_num, int) else None
        )

        if expected is not None:
            # Direct number match: "15." vs 15
            for pat in _Q_NUM_PATTERNS:
                m = pat.match(stripped)
                if m:
                    return int(m.group(1)) == expected

            # OCR-tolerant fallback: "l." → 1
            m = _OCR_Q_PATTERN.match(stripped)
            if m:
                return expected == 1

    # If no expected number, just check if it looks like a question number
    for pat in _Q_NUM_PATTERNS:
        if pat.match(stripped):
            return True
    if _OCR_Q_PATTERN.match(stripped):
        return True

    return False


# ── Visual reference detection ──


def _has_visual_reference(text: str) -> bool:
    """Check if text contains visual reference keywords."""
    if not text:
        return False
    for kw in _VISUAL_REF_KEYWORDS:
        if kw in text:
            return True
    return False


# ── Option key extraction ──


def _extract_expected_option_keys(raw_question: dict) -> list[str]:
    """从 raw_question 中提取预期应出现的选项键。

    按优先级尝试：
    - parsed_options
    - options
    - option_lines keys
    """
    for field in ("parsed_options", "options", "option_lines"):
        opts = raw_question.get(field) or {}
        if isinstance(opts, dict) and opts:
            return sorted(opts.keys(), key=lambda k: _option_key_sort_key(k))
        if isinstance(opts, list):
            keys = []
            for o in opts:
                if isinstance(o, dict) and o.get("key"):
                    keys.append(o["key"])
            if keys:
                return keys
    return []


def _option_key_sort_key(k: str) -> int:
    """Sort option keys: A=0, B=1, C=2, D=3, ..."""
    if len(k) == 1 and "A" <= k.upper() <= "Z":
        return ord(k.upper()) - ord("A")
    return 999


def _find_option_lines_in_ocr(
    ocr_lines: list[dict],
    opt_keys: list[str],
) -> list[dict]:
    """Find OCR lines that look like option entries matching the given keys."""
    if not opt_keys:
        return []
    found: list[dict] = []
    upper_keys = [k.upper() for k in opt_keys]
    for ol in ocr_lines:
        text = ol.get("text", "").strip()
        for key in upper_keys:
            if re.match(rf"^\s*{re.escape(key)}\s*[.、:：)）]\s*", text):
                found.append(ol)
                break
    return found


# ── Main bbox computation ──


def compute_question_bbox(
    raw_question: dict,
    ocr_lines: list[dict],
    page: int,
    *,
    visual_regions: list[dict] | None = None,
) -> dict:
    """为单道题目计算 question_bbox。

    Args:
        raw_question: raw_question dict with page_start, source_question_no, etc.
        ocr_lines: full OCR lines for the page (from build_ocr_lines)
        page: page number to compute bbox for
        visual_regions: optional visual regions detected on the page

    Returns:
        dict with:
        - question_bbox: [x0, y0, x1, y1]
        - question_bbox_coordinate_space: "image_pixels"
        - question_bbox_page_width: int
        - question_bbox_page_height: int
        - question_bbox_confidence: float (0.0-1.0)
        - question_bbox_strategy: str
        - question_bbox_diagnostics: dict
    """
    # Extract question metadata
    page_start = raw_question.get("page_start", page)
    source_qno = raw_question.get("source_question_no")
    source_label = raw_question.get("source_question_label", "")
    raw_text = raw_question.get("raw_question_text", "")
    option_lines = raw_question.get("option_lines") or {}
    expected_keys = _extract_expected_option_keys(raw_question)
    next_q_start = raw_question.get("_next_question_page_start")

    # Filter OCR lines to the target page
    page_lines = [l for l in ocr_lines if l.get("page") == page]
    if not page_lines:
        return _make_fallback_result(
            page, raw_question, "no_ocr_lines_on_page",
        )

    # Get page dimensions from first OCR line
    pw = page_lines[0].get("page_width", 0)
    ph = page_lines[0].get("page_height", 0)

    # ── Step 1: Find anchor line (question start) ──
    anchor = _find_anchor_line(
        page_lines, raw_text, source_qno, source_label,
    )

    if anchor is None:
        return _make_fallback_result(
            page, raw_question, "anchor_not_found",
            page_width=pw, page_height=ph,
        )

    anchor_idx = anchor["line_index"]
    anchor_text = anchor["text"]
    anchor_bbox = anchor["bbox"]

    # ── Step 2: Determine bottom boundary ──

    # Find all OCR lines belonging to this question (from anchor to next question
    # or end of page)
    question_lines = _collect_question_lines(
        page_lines, anchor_idx, page, raw_question, option_lines,
    )

    if not question_lines:
        # Fall back to just the anchor line
        question_lines = [anchor]

    # ── Step 3: Compute union bbox from all question lines ──
    bbox = _union_bbox(question_lines)

    # ── Step 4: Check if there's a next question on the same page ──
    next_q_line = _find_next_question_line(page_lines, anchor_idx + 1)

    if next_q_line:
        next_bbox = next_q_line["bbox"]
        # Don't let our bbox extend past the next question's start
        # Preserve some gap (the blank line between questions is normal)
        bbox = (bbox[0], bbox[1], bbox[2], min(bbox[3], next_bbox[1]))
        strategy = "ocr_anchor_to_next_question"
    else:
        strategy = "ocr_anchor_to_all_lines"

    # ── Step 5: Extend for option coverage ──
    if expected_keys:
        opt_lines_found = _find_option_lines_in_ocr(question_lines, expected_keys)
        if opt_lines_found:
            opt_union = _union_bbox(opt_lines_found)
            # Expand bbox bottom to cover all options
            if opt_union[3] > bbox[3]:
                bbox = (bbox[0], bbox[1], bbox[2], opt_union[3])
            # Expand left/right to cover options (handles horizontal layout)
            if opt_union[0] < bbox[0]:
                bbox = (opt_union[0], bbox[1], bbox[2], bbox[3])
            if opt_union[2] > bbox[2]:
                bbox = (bbox[0], bbox[1], opt_union[2], bbox[3])
            strategy = strategy.replace("all_lines", "all_lines_with_options")

        # Verify coverage
        matched_keys = _match_option_keys(opt_lines_found, expected_keys)
        coverage = len(matched_keys) / len(expected_keys) if expected_keys else 1.0

        # If coverage is incomplete, try to extend bottom to find missing options
        if coverage < 1.0 and next_q_line is None:
            extended = _extend_for_missing_options(
                page_lines, question_lines, bbox, expected_keys, matched_keys,
            )
            if extended:
                bbox = extended
                # Re-check coverage after extension
                opt_lines_found = _find_option_lines_in_ocr(
                    [l for l in page_lines if l["bbox"][1] >= anchor_bbox[1] and l["bbox"][3] <= bbox[3]],
                    expected_keys,
                )
                matched_keys = _match_option_keys(opt_lines_found, expected_keys)
                coverage = len(matched_keys) / len(expected_keys) if expected_keys else 1.0
    else:
        matched_keys = []
        coverage = 1.0

    # ── Step 6: Protect visual reference area (figure between stem and options) ──
    if _has_visual_reference(raw_text) or _has_visual_reference(anchor_text):
        # Merge visual regions into the bbox
        if visual_regions:
            for vr in visual_regions:
                if vr.get("source_page") == page:
                    vr_bbox = vr.get("bbox")
                    if vr_bbox and len(vr_bbox) == 4:
                        # Only include visual regions that are within or near our question
                        vr_center_y = (vr_bbox[1] + vr_bbox[3]) / 2
                        if anchor_bbox[1] <= vr_center_y <= bbox[3] + 50:
                            bbox = (
                                min(bbox[0], vr_bbox[0]),
                                min(bbox[1], vr_bbox[1]),
                                max(bbox[2], vr_bbox[2]),
                                max(bbox[3], vr_bbox[3]),
                            )

        # Even without visual_regions, ensure the vertical gap between stem
        # and options is preserved (don't collapse the graphics area)
        # This is already handled since we use all OCR lines and options bbox

    # ── Step 7: Ensure header exclusion (defensive) ──
    # Check that the bbox top doesn't start above the first real content
    top_line = question_lines[0]
    if top_line.get("zone") == "body":
        # Make sure we're not including brand banner area
        # Bbox top should be close to the anchor line top
        # (already satisfied since anchor line starts from question number)
        pass

    # ── Step 8: Apply safe padding ──
    padding_pt = 8.0
    padded = expand_bbox(
        bbox,
        CS_IMAGE_PIXELS,
        padding_pt,
        pw, ph,  # page_image_width, page_image_height
        None, None,  # page_pdf_width, page_pdf_height (unknown at this stage)
    )

    # ── Build diagnostics ──
    diagnostics = {
        "anchor_text": anchor_text[:100],
        "anchor_bbox": list(anchor_bbox),
        "anchor_line_index": anchor_idx,
        "num_question_lines": len(question_lines),
        "matched_option_keys": sorted(matched_keys),
        "expected_option_keys": expected_keys,
        "coverage": round(coverage, 4),
        "has_visual_reference": _has_visual_reference(raw_text),
        "strategy": strategy,
    }

    return {
        "question_bbox": [padded[0], padded[1], padded[2], padded[3]],
        "question_bbox_coordinate_space": CS_IMAGE_PIXELS,
        "question_bbox_page_width": pw,
        "question_bbox_page_height": ph,
        "question_bbox_confidence": round(coverage, 4),
        "question_bbox_strategy": strategy,
        "question_bbox_diagnostics": diagnostics,
    }


def _find_anchor_line(
    page_lines: list[dict],
    raw_text: str,
    source_qno: int | str | None,
    source_label: str,
) -> dict | None:
    """Find the OCR line that is the start of the target question.

    Priority:
    1. source_question_no match (number)
    2. source_question_label match
    3. First line of raw_text fuzzy match
    4. Any question-number-like line with matching page position
    """
    candidates: list[dict] = []

    for i, line in enumerate(page_lines):
        text = line.get("text", "").strip()
        is_qnum = _match_question_number(text, source_qno)

        # Priority 1: exact number match
        if is_qnum:
            line["_match_type"] = "exact_number"
            line["_match_score"] = 3
            candidates.append(line)
            continue

        # Priority 2: source_label match (e.g. "15.【2013 统考真题】")
        if source_label and source_label.strip()[:20] in text:
            line["_match_type"] = "label"
            line["_match_score"] = 2
            candidates.append(line)
            continue

        # Priority 3: fuzzy raw_text prefix match
        if raw_text:
            raw_prefix = raw_text.strip()[:40]
            if text[:40] == raw_prefix[:40]:
                line["_match_type"] = "stem_prefix"
                line["_match_score"] = 1
                candidates.append(line)

    if candidates:
        # Sort by score (highest first), then by position (top of page first)
        candidates.sort(key=lambda l: (-l.get("_match_score", 0), l.get("bbox", [0, 0, 0, 0])[1]))
        result = dict(candidates[0])
        result["line_index"] = page_lines.index(candidates[0])
        return result

    # Priority 4: Any line that looks like a question number (last resort)
    for i, line in enumerate(page_lines):
        text = line.get("text", "").strip()
        if _match_question_number(text, None):
            result = dict(line)
            result["line_index"] = i
            result["_match_type"] = "any_qnum"
            result["_match_score"] = 0
            return result

    return None


def _collect_question_lines(
    page_lines: list[dict],
    anchor_idx: int,
    page: int,
    raw_question: dict,
    option_lines: dict,
) -> list[dict]:
    """Collect all OCR lines belonging to this question.

    Includes:
    - Lines from anchor onward
    - Option lines
    - Lines before a next-question marker

    Stops at:
    - Next question number on the same page
    - End of page
    """
    collected: list[dict] = [page_lines[anchor_idx]]

    for i in range(anchor_idx + 1, len(page_lines)):
        line = page_lines[i]
        text = line.get("text", "").strip()

        # Check if this is a new question (by number pattern)
        if _match_question_number(text, None):
            # Check if this is really a new question or a continuation
            # (e.g., "1." could be an option line in some layouts)
            is_option = False
            for key in option_lines or {}:
                if text.startswith(f"{key}.") or text.startswith(f"{key}、"):  # noqa: SIM114
                    is_option = True
                    break
                if re.match(rf"^\s*{re.escape(key)}\s*[.、:：)）]", text):
                    is_option = True
                    break
            if not is_option:
                break  # This is the next question

        collected.append(line)

    return collected


def _find_next_question_line(
    page_lines: list[dict],
    start_idx: int,
) -> dict | None:
    """Find the first line after start_idx that looks like a new question."""
    for i in range(start_idx, len(page_lines)):
        text = page_lines[i].get("text", "").strip()
        if _match_question_number(text, None):
            return page_lines[i]
    return None


def _union_bbox(lines: list[dict]) -> tuple[float, float, float, float]:
    """Compute union bbox from a list of lines with 'bbox' key."""
    if not lines:
        return (0.0, 0.0, 0.0, 0.0)

    x0 = min(l["bbox"][0] for l in lines)
    y0 = min(l["bbox"][1] for l in lines)
    x1 = max(l["bbox"][2] for l in lines)
    y1 = max(l["bbox"][3] for l in lines)
    return (x0, y0, x1, y1)


def _match_option_keys(
    opt_lines: list[dict],
    expected_keys: list[str],
) -> list[str]:
    """Return which expected option keys were found in the opt_lines."""
    matched: list[str] = []
    upper_expected = [k.upper() for k in expected_keys]
    for ol in opt_lines:
        text = ol.get("text", "").strip()
        for key in upper_expected:
            if key not in matched and re.match(rf"^\s*{re.escape(key)}\s*[.、:：)）]\s*", text):
                matched.append(key)
    return sorted(matched, key=_option_key_sort_key)


def _extend_for_missing_options(
    page_lines: list[dict],
    current_question_lines: list[dict],
    current_bbox: tuple[float, float, float, float],
    expected_keys: list[str],
    already_matched: list[str],
) -> tuple[float, float, float, float] | None:
    """Extend bbox bottom to find missing option lines."""
    missing = set(k.upper() for k in expected_keys) - set(k.upper() for k in already_matched)
    if not missing:
        return None

    _, _, _, current_bottom = current_bbox
    last_line = current_question_lines[-1] if current_question_lines else None
    last_bottom = last_line["bbox"][3] if last_line else current_bottom

    extended_bottom = current_bottom
    found_any = False

    for line in page_lines:
        if line["bbox"][1] <= last_bottom:
            continue
        text = line.get("text", "").strip()
        for key in missing:
            if re.match(rf"^\s*{re.escape(key)}\s*[.、:：)）]\s*", text):
                if line["bbox"][3] > extended_bottom:
                    extended_bottom = line["bbox"][3]
                missing.discard(key)
                found_any = True
                break

    if found_any:
        return (current_bbox[0], current_bbox[1], current_bbox[2], extended_bottom)
    return None


def _make_fallback_result(
    page: int,
    raw_question: dict,
    reason: str,
    page_width: int = 0,
    page_height: int = 0,
) -> dict:
    """Generate a fallback result when bbox computation fails.

    Uses the raw_question's existing question_bbox if available,
    otherwise signals failure for full-page fallback.
    """
    existing = raw_question.get("question_bbox")
    if existing and len(existing) == 4:
        return {
            "question_bbox": existing,
            "question_bbox_coordinate_space": raw_question.get(
                "question_bbox_coordinate_space", CS_IMAGE_PIXELS,
            ),
            "question_bbox_page_width": raw_question.get("question_bbox_page_width", page_width),
            "question_bbox_page_height": raw_question.get("question_bbox_page_height", page_height),
            "question_bbox_confidence": 0.3,
            "question_bbox_strategy": f"fallback_existing:{reason}",
            "question_bbox_diagnostics": {
                "fallback_reason": reason,
                "alert": f"could not compute bbox: {reason}",
            },
        }

    return {
        "question_bbox": None,
        "question_bbox_coordinate_space": CS_IMAGE_PIXELS,
        "question_bbox_page_width": page_width,
        "question_bbox_page_height": page_height,
        "question_bbox_confidence": 0.0,
        "question_bbox_strategy": f"fallback_unknown:{reason}",
        "question_bbox_diagnostics": {
            "fallback_reason": reason,
            "alert": f"could not compute bbox: {reason}",
        },
    }


# ── Batch API ──


def compute_question_bboxes(
    raw_questions: list[dict],
    normalized_blocks: list[dict],
    *,
    visual_regions: list[dict] | None = None,
) -> list[dict]:
    """Compute question_bbox for all raw_questions.

    Modifies raw_questions in place, attaching bbox fields.

    Args:
        raw_questions: list of question dicts with page_start, etc.
        normalized_blocks: normalized blocks from pipeline (with boxes)
        visual_regions: optional list of visual region dicts

    Returns:
        The modified raw_questions list (same objects, mutated in place).
    """
    # Build OCR lines once
    ocr_lines = build_ocr_lines(normalized_blocks)

    # Group OCR lines by page for efficient lookup
    ocr_lines_by_page: dict[int, list[dict]] = {}
    for ol in ocr_lines:
        p = ol.get("page", 0)
        ocr_lines_by_page.setdefault(p, []).append(ol)

    for q in raw_questions:
        page = q.get("page_start") or q.get("page", 1)
        page_ocr = ocr_lines_by_page.get(page, [])

        result = compute_question_bbox(
            q, page_ocr, page,
            visual_regions=visual_regions,
        )

        for key, value in result.items():
            q[key] = value

    return raw_questions


# ── Source snapshot rendering ──


def render_source_snapshot(
    file_path: str,
    page: int,
    bbox_image_pixels: list[float] | None,
    page_image_width: int,
    page_image_height: int,
    *,
    dpi: int = 220,
    max_long_side: int = 3200,
) -> bytes | None:
    """Render a high-DPI clip from a PDF page for source_snapshot.

    Uses PyMuPDF to open the PDF and render just the target region
    at a higher DPI. Only renders the clip area, not the full page.

    Args:
        file_path: path to the PDF file
        page: 1-based page number
        bbox_image_pixels: [x0, y0, x1, y1] in image pixel space (from question_bbox)
        page_image_width: width of the original rendered page in pixels
        page_image_height: height of the original rendered page in pixels
        dpi: DPI for the snapshot rendering (default 220, range 180-260)
        max_long_side: maximum long edge in pixels (default 3200)

    Returns:
        PNG bytes of the clipped region, or None on failure.
    """
    try:
        import fitz
    except ImportError:
        logger.error("PyMuPDF not available for source_snapshot rendering")
        return None

    try:
        doc = fitz.open(file_path, filetype="pdf")
    except Exception as e:
        logger.warning("Cannot open PDF %s: %s", file_path, e)
        return None

    try:
        if page < 1 or page > len(doc):
            logger.warning("Page %d out of range (PDF has %d pages)", page, len(doc))
            return None

        pdf_page = doc[page - 1]

        if bbox_image_pixels and len(bbox_image_pixels) == 4 and page_image_width > 0 and page_image_height > 0:
            # Convert image pixel bbox to PDF points
            # PDF page bounds in points
            pdf_rect = pdf_page.rect
            pdf_w = pdf_rect.width
            pdf_h = pdf_rect.height

            # Map image pixel coords back to PDF points
            scale_x = pdf_w / page_image_width
            scale_y = pdf_h / page_image_height
            clip_rect = fitz.Rect(
                bbox_image_pixels[0] * scale_x,
                bbox_image_pixels[1] * scale_y,
                bbox_image_pixels[2] * scale_x,
                bbox_image_pixels[3] * scale_y,
            )
        else:
            # Full page fallback
            clip_rect = pdf_page.rect

        # Render at specified DPI, only the clip area
        pix = pdf_page.get_pixmap(dpi=dpi, clip=clip_rect, alpha=False)

        # Constrain to max_long_side (maintain aspect ratio)
        if max(pix.width, pix.height) > max_long_side:
            scale = max_long_side / max(pix.width, pix.height)
            pix = pdf_page.get_pixmap(
                dpi=int(dpi * scale), clip=clip_rect, alpha=False,
            )

        return pix.tobytes("png")
    except Exception as e:
        logger.warning("Failed to render source_snapshot page=%d: %s", page, e)
        return None
    finally:
        doc.close()
