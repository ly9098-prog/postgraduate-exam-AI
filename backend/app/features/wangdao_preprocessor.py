"""王道PDF预处理器 — 基于坐标的水印/页眉页脚过滤。

在 extract 阶段之后、normalize_text 之前执行。
利用 OCR bbox 坐标信息过滤水印、页眉、页脚，标注区域类型。
"""

import re


_WATERMARK_KEYWORDS = re.compile(
    r"(王道|计算?机教育|机教育|算机教育|道计算|几教育|千道|全丰道|"
    r"kaoya[no]?|Kaoyan|com|ska|ai\.)"
)

_HEADER_KEYWORDS = re.compile(
    r"(考研复习指导|第\s*\d+\s*章.{0,10}$)"
)


def preprocess_wangdao_blocks(raw_blocks: list[dict]) -> list[dict]:
    """过滤水印/页眉/页脚，为每个block标注zone。

    输入: raw_blocks — 带有 boxes, page_width, page_height 字段
    输出: 过滤后的 blocks，每个block增加 zone 字段
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

        filtered_lines = _filter_lines(text, boxes, page_w, page_h)

        if not filtered_lines:
            continue

        new_text = "\n".join(filtered_lines)
        new_block = {**block, "text": new_text, "zone": "body"}
        result.append(new_block)

    return result


def _filter_lines(
    text: str, boxes: list[dict], page_w: int, page_h: int
) -> list[str]:
    """逐行过滤，返回保留的行列表。"""
    lines = text.split("\n")
    kept: list[str] = []

    box_idx = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue

        bbox = boxes[box_idx] if box_idx < len(boxes) else None
        box_idx += 1

        if bbox is None:
            kept.append(line)
            continue

        coords = bbox.get("bbox", [0, 0, 0, 0])
        x0, y0, x1, y1 = coords[0], coords[1], coords[2], coords[3]

        zone = _classify_zone(stripped, x0, y0, x1, y1, page_w, page_h)

        if zone in ("watermark", "header", "footer"):
            continue

        kept.append(line)

    return kept


def _classify_zone(
    text: str, x0: float, y0: float, x1: float, y1: float,
    page_w: int, page_h: int,
) -> str:
    """基于坐标和内容判断文本行的区域类型。"""
    text_len = len(text.strip())
    rel_y0 = y0 / page_h if page_h else 0
    rel_y1 = y1 / page_h if page_h else 0
    rel_x0 = x0 / page_w if page_w else 0
    rel_x1 = x1 / page_w if page_w else 0

    # 页眉区域：页面顶部6%，短文本
    if rel_y0 < 0.06 and text_len < 30:
        if _HEADER_KEYWORDS.search(text) or text_len < 15:
            return "header"

    # 页脚区域：页面底部6%，短文本
    if rel_y1 > 0.94 and text_len < 20:
        return "footer"

    # 水印检测：关键词匹配 + 位置辅助
    if _WATERMARK_KEYWORDS.search(text):
        # 短水印文本（<15字），任何位置都过滤
        if text_len < 15:
            return "watermark"
        # 较长文本只在边缘区域过滤（避免误删正文中提到"计算机"的内容）
        if rel_x1 > 0.75 or rel_y1 > 0.85:
            return "watermark"

    # 位置+长度的兜底水印检测：右下角的极短文本
    if text_len <= 6 and (rel_x0 > 0.70 or rel_y0 > 0.85):
        cjk_alpha = sum(1 for c in text if ("一" <= c <= "鿿") or c.isalpha())
        if cjk_alpha / max(text_len, 1) < 0.5:
            return "watermark"

    return "body"
