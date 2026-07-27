"""视觉题目边界检测器 — 利用 OCR bbox 坐标检测题目分界。

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.document_ir import DocumentIR


当正则题号切分失败时（整本教材 OCR 无法识别题号边界），
通过行间距突变和缩进重置信号辅助切分。
"""

import re
import statistics

_QUESTION_NUMBER_PATTERN = re.compile(r"^\d+\s*[.．、)）]")
_CIRCLED_OPTION_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_OPTION_PATTERN = re.compile(r"^(?:[" + _CIRCLED_OPTION_CHARS + r"]\s*)?[A-D]\s*[.．、:：)）]")
_EXERCISE_MARKER_PATTERN = re.compile(r"习题精选|练习题|巩固练习|单项选择题|多项选择题|选择题")
_QUESTION_SIGNAL_PATTERN = re.compile(r"下列|以下|正确|错误|的是|哪|选择|计算|判断|已知|设|若|求|问|？|\?")
_PROSE_MARKER_PATTERN = re.compile(r"定义|定理|知识点|证明|证毕|解法|例题|性质|推论|本节|本章")


def _percentile(data: list[float], p: float) -> float:
    """简易百分位数计算（不依赖 numpy）。"""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (len(sorted_data) - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(sorted_data) - 1)
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


def filter_book_layout_blocks(normalized_blocks: list[dict]) -> tuple[list[dict], dict]:
    diagnostics = {
        "enabled": False,
        "pages_considered": 0,
        "filtered_line_count": 0,
        "kept_line_count": 0,
        "region_signals": [],
    }
    filtered_blocks: list[dict] = []

    for block in normalized_blocks:
        boxes = block.get("boxes")
        page_w = block.get("page_width", 0)
        page_h = block.get("page_height", 0)
        text = block.get("normalized_text") or block.get("text", "")
        lines = text.split("\n")
        line_count = min(len(lines), len(boxes or []))
        if not boxes or line_count < 4 or not page_w or not page_h:
            filtered_blocks.append(block)
            continue

        diagnostics["enabled"] = True
        diagnostics["pages_considered"] += 1
        keep_start: int | None = None
        signal = ""

        for i in range(line_count):
            line = lines[i].strip()
            if not line:
                continue
            if _EXERCISE_MARKER_PATTERN.search(line):
                for j in range(i + 1, line_count):
                    candidate = lines[j].strip()
                    if _QUESTION_NUMBER_PATTERN.match(candidate) and _QUESTION_SIGNAL_PATTERN.search(candidate):
                        keep_start = j
                        signal = "exercise_marker+question"
                        break
                if keep_start is not None:
                    break

        if keep_start is None:
            page_mid = page_w / 2
            left_prose = 0
            right_prose = 0
            left_question = 0
            right_question = 0
            first_question_by_side: dict[str, int] = {}
            for i in range(line_count):
                line = lines[i].strip()
                bbox = boxes[i].get("bbox", [0, 0, 0, 0])
                side = "right" if bbox[0] >= page_mid else "left"
                if _PROSE_MARKER_PATTERN.search(line):
                    if side == "right":
                        right_prose += 1
                    else:
                        left_prose += 1
                is_question = (
                    _QUESTION_NUMBER_PATTERN.match(line)
                    and (_QUESTION_SIGNAL_PATTERN.search(line) or i + 3 < line_count)
                ) or _OPTION_PATTERN.match(line)
                if is_question:
                    if side == "right":
                        right_question += 1
                    else:
                        left_question += 1
                    first_question_by_side.setdefault(side, i)
            if right_question >= 3 and left_prose >= 2 and left_question == 0:
                keep_start = first_question_by_side.get("right")
                signal = "two_column_right_question"
            elif left_question >= 3 and right_prose >= 2 and right_question == 0:
                keep_start = first_question_by_side.get("left")
                signal = "two_column_left_question"

        if keep_start is None:
            filtered_blocks.append(block)
            diagnostics["kept_line_count"] += line_count
            continue

        kept_lines = lines[keep_start:]
        kept_boxes = list(boxes[keep_start:line_count])
        diagnostics["filtered_line_count"] += keep_start
        diagnostics["kept_line_count"] += len(kept_lines)
        diagnostics["region_signals"].append({
            "page": block.get("page", 1),
            "block_index": block.get("block_index", 0),
            "line_index": keep_start,
            "signal": signal,
            "preview": "".join(kept_lines[:2])[:80],
        })
        new_block = dict(block)
        new_text = "\n".join(kept_lines).strip()
        new_block["normalized_text"] = new_text
        if "raw_text" in new_block:
            new_block["raw_text"] = new_text
        if "text" in new_block:
            new_block["text"] = new_text
        new_block["boxes"] = kept_boxes
        filtered_blocks.append(new_block)

    return filtered_blocks, diagnostics


def detect_visual_boundaries(normalized_blocks: list[dict]) -> list[dict]:
    """利用 OCR bbox 坐标检测题目边界。

    对每个有 boxes 数据的 block（对应一页 OCR 结果），通过以下信号判断新题目起始：
    - 行间距突变（> 1.5× 中位数间距）+ 题号模式
    - 缩进重置（当前行回到左边距，上一行偏右）+ 题号模式
    - 超大间距（> 2.5× 中位数），即使无题号

    Args:
        normalized_blocks: 经过 normalize 的 blocks，需含 boxes/page_width/page_height

    Returns:
        按 (block_index, line_index) 排序的边界列表：
        [{"block_index": int, "line_index": int, "page": int, "signal": str}]
    """
    boundaries: list[dict] = []

    for block in normalized_blocks:
        boxes = block.get("boxes")
        page_w = block.get("page_width", 0)
        block.get("page_height", 0)
        text = block.get("normalized_text") or block.get("text", "")

        if not boxes or len(boxes) < 4 or not page_w:
            continue

        text_lines = text.split("\n")
        line_count = min(len(boxes), len(text_lines))

        if line_count < 4:
            continue

        # Step 1: 计算行间距（gap = 下一行 y0 - 当前行 y3）
        gaps: list[float] = []
        for i in range(line_count - 1):
            bbox_curr = boxes[i].get("bbox", [0, 0, 0, 0])
            bbox_next = boxes[i + 1].get("bbox", [0, 0, 0, 0])
            gap = bbox_next[1] - bbox_curr[3]
            gaps.append(gap)

        if not gaps:
            continue

        median_gap = statistics.median(gaps)
        if median_gap <= 0:
            continue

        # Step 2: 计算典型左边距（15th percentile）
        left_margins = [boxes[i].get("bbox", [0])[0] for i in range(line_count)]
        typical_left = _percentile(left_margins, 15)
        margin_tolerance = page_w * 0.02
        indent_threshold = page_w * 0.05

        # Step 3: 逐行扫描边界信号
        block_idx = block.get("block_index", 0)
        page = block.get("page", 1)

        for i in range(1, line_count):
            line_text = text_lines[i].strip() if i < len(text_lines) else ""
            if not line_text:
                continue

            gap = gaps[i - 1] if i - 1 < len(gaps) else 0
            curr_left = boxes[i].get("bbox", [0])[0]
            prev_left = boxes[i - 1].get("bbox", [0])[0]

            is_large_gap = gap > median_gap * 1.5
            is_very_large_gap = gap > median_gap * 2.5
            is_indent_reset = (
                curr_left <= typical_left + margin_tolerance
                and prev_left > typical_left + indent_threshold
            )
            has_number = bool(_QUESTION_NUMBER_PATTERN.match(line_text))

            if has_number and (is_large_gap or is_indent_reset):
                boundaries.append({
                    "block_index": block_idx,
                    "line_index": i,
                    "page": page,
                    "signal": "gap+number" if is_large_gap else "indent+number",
                })
            elif is_very_large_gap and not has_number:
                boundaries.append({
                    "block_index": block_idx,
                    "line_index": i,
                    "page": page,
                    "signal": "large_gap",
                })

    boundaries.sort(key=lambda b: (b["block_index"], b["line_index"]))
    return boundaries


def filter_book_layout_blocks_from_ir(doc: "DocumentIR") -> tuple[list[dict], dict]:  # noqa: F821
    """DocumentIR-native entry point for filter_book_layout_blocks.

    Converts DocumentIR to blocks at the boundary and delegates to the
    legacy implementation. Returns blocks-format result for upstream stages.
    """
    from app.core.document_ir import document_ir_to_blocks
    blocks = document_ir_to_blocks(doc)
    return filter_book_layout_blocks(blocks)


def detect_visual_boundaries_from_ir(doc: "DocumentIR") -> list[dict]:  # noqa: F821
    """DocumentIR-native entry point for detect_visual_boundaries.

    Converts DocumentIR to blocks at the boundary and delegates to the
    legacy implementation.
    """
    from app.core.document_ir import document_ir_to_blocks
    blocks = document_ir_to_blocks(doc)
    return detect_visual_boundaries(blocks)
