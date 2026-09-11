"""王道PDF预处理器 — 基于坐标的水印/页眉页脚过滤。

在 extract 阶段之后、normalize_text 之前执行。
利用 OCR bbox 坐标信息过滤水印、页眉、页脚，标注区域类型。

必须保证文本行与 bbox 保持严格一一对应。
"""

import re

# 品牌页眉关键词（王道教材顶部品牌栏）
_BRAND_HEADER_KEYWORDS = re.compile(
    r"(风中易小生|考研计算机|WD数据结构|王道|考研|做题本|"
    r"复习指导|天勤|高分笔记)"
)

_WATERMARK_KEYWORDS = re.compile(
    r"(王道|计算?机教育|机教育|算机教育|道计算|几教育|千道|全丰道|"
    r"kaoya[no]?|Kaoyan|com|ska|ai\.)"
)

_HEADER_KEYWORDS = re.compile(r"(考研复习指导|第\s*\d+\s*章.{0,10}$)")


def preprocess_wangdao_blocks(raw_blocks: list[dict]) -> list[dict]:
    """过滤水印/页眉/页脚，为每个block标注zone。

    输入: raw_blocks — 带有 boxes, page_width, page_height 字段
    输出: 过滤后的 blocks，每个block增加 zone 字段

    保证输出 block 中 text.splitlines() 与 boxes 一一对应。
    """
    result: list[dict] = []

    for block in raw_blocks:
        boxes = block.get("boxes", [])
        page_w = block.get("page_width", 0)
        page_h = block.get("page_height", 0)
        text = block.get("text", "")

        if not boxes or not page_w or not page_h:
            block["zone"] = "body"
            result.append(block)
            continue

        kept_lines, kept_boxes = _filter_lines_and_boxes(text, boxes, page_w, page_h)

        if not kept_lines:
            continue

        new_text = "\n".join(kept_lines)
        new_block = {**block, "text": new_text, "boxes": kept_boxes, "zone": "body"}
        result.append(new_block)

    return result


def preprocess_wangdao_blocks_detailed(
    raw_blocks: list[dict],
) -> tuple[list[dict], dict]:
    """Like preprocess_wangdao_blocks but also returns diagnostics.
    Returns (filtered_blocks, diagnostics).
    """
    result: list[dict] = []
    diagnostics = {"removed_lines": 0, "removed_by_category": {}}

    for block in raw_blocks:
        boxes = block.get("boxes", [])
        page_w = block.get("page_width", 0)
        page_h = block.get("page_height", 0)
        text = block.get("text", "")

        if not boxes or not page_w or not page_h:
            block["zone"] = "body"
            result.append(block)
            continue

        kept_lines, kept_boxes, removal_info = _filter_lines_and_boxes_detailed(
            text,
            boxes,
            page_w,
            page_h,
        )

        for cat, count in removal_info.items():
            diagnostics["removed_by_category"][cat] = (
                diagnostics["removed_by_category"].get(cat, 0) + count
            )
        diagnostics["removed_lines"] += sum(removal_info.values())

        if not kept_lines:
            continue

        new_text = "\n".join(kept_lines)
        new_block = {**block, "text": new_text, "boxes": kept_boxes, "zone": "body"}
        result.append(new_block)

    return result, diagnostics


def _filter_lines(text: str, boxes: list[dict], page_w: int, page_h: int) -> list[str]:
    kept_lines, _ = _filter_lines_and_boxes(text, boxes, page_w, page_h)
    return kept_lines


def _filter_lines_and_boxes(
    text: str,
    boxes: list[dict],
    page_w: int,
    page_h: int,
) -> tuple[list[str], list[dict]]:
    """Filter lines and corresponding boxes simultaneously.
    Returns (kept_lines, kept_boxes) with identical length for non-empty lines.
    """
    lines = text.split("\n")
    kept_lines: list[str] = []
    kept_boxes: list[dict] = []

    box_idx = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue

        bbox = boxes[box_idx] if box_idx < len(boxes) else None
        box_idx += 1

        if bbox is None:
            # Can't determine zone without bbox — skip the line to keep
            # kept_lines / kept_boxes aligned 1:1 for non-empty lines
            continue

        coords = bbox.get("bbox", [0, 0, 0, 0])
        x0, y0, x1, y1 = coords[0], coords[1], coords[2], coords[3]

        zone = classify_zone(stripped, x0, y0, x1, y1, page_w, page_h)

        if zone in ("watermark", "header", "footer"):
            continue

        kept_lines.append(line)
        kept_boxes.append(bbox)

    return kept_lines, kept_boxes


def _filter_lines_and_boxes_detailed(
    text: str,
    boxes: list[dict],
    page_w: int,
    page_h: int,
) -> tuple[list[str], list[dict], dict[str, int]]:
    lines = text.split("\n")
    kept_lines: list[str] = []
    kept_boxes: list[dict] = []
    removed_by_category: dict[str, int] = {}

    box_idx = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue

        bbox_entry = boxes[box_idx] if box_idx < len(boxes) else None
        box_idx += 1

        if bbox_entry is None:
            # Can't determine zone without bbox — skip to keep
            # kept_lines / kept_boxes aligned 1:1
            continue

        coords = bbox_entry.get("bbox", [0, 0, 0, 0])
        x0, y0, x1, y1 = coords[0], coords[1], coords[2], coords[3]

        zone = classify_zone(stripped, x0, y0, x1, y1, page_w, page_h)

        if zone in ("watermark", "header", "footer"):
            removed_by_category[zone] = removed_by_category.get(zone, 0) + 1
            continue

        kept_lines.append(line)
        kept_boxes.append(bbox_entry)

    return kept_lines, kept_boxes, removed_by_category


def _classify_zone(
    text: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    page_w: int,
    page_h: int,
) -> str:
    return classify_zone(text, x0, y0, x1, y1, page_w, page_h)


def classify_zone(
    text: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    page_w: int,
    page_h: int,
) -> str:
    """基于坐标和内容判断文本行的区域类型。
    公开函数，供 question_snapshot_service 等外部模块复用。
    """
    text_len = len(text.strip())
    rel_y0 = y0 / page_h if page_h else 0
    rel_y1 = y1 / page_h if page_h else 0
    rel_x0 = x0 / page_w if page_w else 0
    rel_x1 = x1 / page_w if page_w else 0

    # 品牌页眉：页面顶部10%，横向覆盖 >60% 页面宽度，含品牌关键词
    if rel_y0 < 0.10 and (rel_x1 - rel_x0) > 0.60:
        if _BRAND_HEADER_KEYWORDS.search(text):
            return "header"

    # 页眉区域：页面顶部6%，短文本
    if rel_y0 < 0.06 and text_len < 30:
        if _HEADER_KEYWORDS.search(text) or text_len < 15:
            return "header"

    # 页脚区域：页面底部6%，短文本
    if rel_y1 > 0.94 and text_len < 20:
        return "footer"

    # 水印检测：关键词匹配 + 位置辅助
    if _WATERMARK_KEYWORDS.search(text):
        if text_len < 15:
            return "watermark"
        if rel_x1 > 0.75 or rel_y1 > 0.85:
            return "watermark"

    # 位置+长度的兜底水印检测：右下角的极短文本
    if text_len <= 6 and (rel_x0 > 0.70 or rel_y0 > 0.85):
        cjk_alpha = sum(1 for c in text if ("一" <= c <= "鿿") or c.isalpha())
        if cjk_alpha / max(text_len, 1) < 0.5:
            return "watermark"

    return "body"
