"""视觉题目边界检测器 — 利用 OCR bbox 坐标检测题目分界。

当正则题号切分失败时（整本教材 OCR 无法识别题号边界），
通过行间距突变和缩进重置信号辅助切分。
"""

import re
import statistics

_QUESTION_NUMBER_PATTERN = re.compile(r"^\d+\s*[.．、)）]")


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
        page_h = block.get("page_height", 0)
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
