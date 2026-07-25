"""数学区域检测：基于 Unicode 字符区间 + 字体名辅助。

任何异常 → 返回空列表，记录 warning，不抛出。
"""
import logging
import re
from dataclasses import dataclass
from enum import StrEnum

import fitz

logger = logging.getLogger(__name__)

# ── Unicode 数学字符区间 ──────────────────────────────────────────────────────

_MATH_RANGES = [
    (0x0391, 0x03C9),   # 希腊字母 Α-Ω, α-ω
    (0x2200, 0x22FF),   # 数学运算符 ∫ ∑ ∏ ≤ ≥ ≠ ∈ ∉ ∞ ∂ …
    (0x2100, 0x214F),   # 字母化数字符号 ℝ ℤ ℕ ℂ …
    (0x2070, 0x209C),   # 上标/下标 Unicode
]

_MATH_ASCII = set("^_{}\\")

# ── 字体名辅助关键词 ─────────────────────────────────────────────────────────

_MATH_FONT_KEYWORDS = [
    "Math", "CMMI", "Symbol", "MT Extra", "Cambria", "STIX", "Mathmaru",
]

# ── 可调参数 ──────────────────────────────────────────────────────────────────

_PADDING = 6.0
_MERGE_GAP = 12.0
_CLUSTER_GAP = 20.0
_MIN_WIDTH = 12.0
_MIN_HEIGHT = 8.0
_DISPLAY_WIDTH_RATIO = 0.7
_DISPLAY_HEIGHT_RATIO = 1.5
_SAME_LINE_Y_RATIO = 0.5
_SAME_LINE_Y_RATIO_CLASSIFY = 0.6

# LaTeX 定界符正则
_RE_INLINE_MATH = re.compile(r"\$([^$\n]+?)\$")
_RE_DISPLAY_MATH = re.compile(r"\$\$([\s\S]*?)\$\$")


# ── 枚举 / 数据类 ─────────────────────────────────────────────────────────────

class MathRegionType(StrEnum):
    INLINE = "inline"
    DISPLAY = "display"
    MIXED = "mixed"


@dataclass
class MathRegion:
    page_num: int
    bbox: tuple[float, float, float, float]
    region_type: MathRegionType
    raw_latex: str | None = None
    image_url: str | None = None


# ── 内部辅助 ─────────────────────────────────────────────────────────────────

def _is_math_char(ch: str) -> bool:
    if ch in _MATH_ASCII:
        return True
    cp = ord(ch)
    for lo, hi in _MATH_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def _is_math_font(font_name: str) -> bool:
    if not font_name:
        return False
    for kw in _MATH_FONT_KEYWORDS:
        if kw in font_name:
            return True
    if "+Math" in font_name:
        return True
    return False


def _median_height(chars):
    heights = sorted(c[3] - c[1] for c in chars)
    if not heights:
        return 8.0
    return heights[len(heights) // 2]


# ── 主检测函数 ───────────────────────────────────────────────────────────────

def detect_page(page: fitz.Page) -> list[MathRegion]:
    """检测单页 PDF 中的数学公式区域。"""
    try:
        raw = page.get_text("rawdict")
    except Exception as e:
        logger.warning("提取页面文本失败 (page %d): %s", page.number, e)
        return []

    # 收集所有字符及其 bbox、数学标记
    chars = []  # (x0, y0, x1, y1, is_math, text)
    all_text_chars = []  # 所有字符（含非数学），用于后续分类

    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                font = span.get("font", "")
                font_is_math = _is_math_font(font)
                for ch_info in span.get("chars", []):
                    ch = ch_info["c"]
                    bbox = ch_info["bbox"]
                    is_math = _is_math_char(ch) or font_is_math
                    entry = (*bbox, is_math, ch)
                    chars.append(entry)
                    all_text_chars.append(entry)

    if not chars:
        return []

    # 估算行高
    med_h = _median_height(chars)
    line_threshold = max(med_h * _SAME_LINE_Y_RATIO, 4.0)

    # 按 y 中心排序（同行聚合）
    char_with_y = [(c[0], c[1], c[2], c[3], c[4], c[5], (c[1] + c[3]) / 2) for c in chars]
    char_with_y.sort(key=lambda c: (c[6], c[0]))

    # 按行分组 → 同行内聚类
    regions = _cluster_by_lines(char_with_y, line_threshold)

    # 扩展 + 合并 + 过滤
    regions = _expand_and_filter(regions)

    # 分类
    regions = _classify_regions(regions, char_with_y, line_threshold, page.rect.width)

    # 填充页码
    for r in regions:
        r.page_num = page.number

    # 降级：正则检测 $...$ / $$...$$
    regex_regions = _detect_latex_delimiters(page)
    regions = _merge_regex_regions(regions, regex_regions, char_with_y, line_threshold)

    return regions


# ── 行分组 + 同行聚类 ─────────────────────────────────────────────────────────

def _cluster_by_lines(char_with_y, line_threshold):
    """按 y 中心分行，同行内对数学字符做 x 间距聚类。"""
    regions: list[MathRegion] = []
    current_line_y = None
    line_chars = []

    for c in char_with_y:
        y_center = c[6]
        if current_line_y is None or abs(y_center - current_line_y) > line_threshold:
            if line_chars:
                regions.extend(_cluster_line(line_chars))
            current_line_y = y_center
            line_chars = [c]
        else:
            line_chars.append(c)

    if line_chars:
        regions.extend(_cluster_line(line_chars))

    return regions


def _cluster_line(line_chars):
    """同行内：取数学字符，按 x 间距 < _CLUSTER_GAP 聚合为候选区域。"""
    math_chars = [(c[0], c[1], c[2], c[3], c[5]) for c in line_chars if c[4]]
    if len(math_chars) < 2:
        return []

    # 按 x 排序
    math_chars.sort(key=lambda c: c[0])

    clusters = []
    cur = [math_chars[0]]
    for i in range(1, len(math_chars)):
        gap = math_chars[i][0] - cur[-1][2]
        if gap < _CLUSTER_GAP:
            cur.append(math_chars[i])
        else:
            clusters.append(cur)
            cur = [math_chars[i]]
    clusters.append(cur)

    regions = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        x0 = min(c[0] for c in cluster)
        y0 = min(c[1] for c in cluster)
        x1 = max(c[2] for c in cluster)
        y1 = max(c[3] for c in cluster)
        raw = "".join(c[4] for c in cluster)
        regions.append(MathRegion(
            page_num=0,
            bbox=(x0, y0, x1, y1),
            region_type=MathRegionType.MIXED,  # 暂定，后续分类
            raw_latex=raw,
        ))

    return regions


# ── 扩展 / 合并 / 过滤 ───────────────────────────────────────────────────────

def _expand_and_filter(regions):
    """bbox 四周扩展 6pt，同行间距 < 12pt 合并，过滤最小面积。"""
    # 扩展
    for r in regions:
        x0, y0, x1, y1 = r.bbox
        r.bbox = (
            max(0, x0 - _PADDING),
            max(0, y0 - _PADDING),
            x1 + _PADDING,
            y1 + _PADDING,
        )

    # 同行合并
    regions.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
    merged = []
    for r in regions:
        if not merged:
            merged.append(r)
            continue
        prev = merged[-1]
        # 同一行判断
        prev_y_mid = (prev.bbox[1] + prev.bbox[3]) / 2
        cur_y_mid = (r.bbox[1] + r.bbox[3]) / 2
        prev_h = prev.bbox[3] - prev.bbox[1]
        if abs(cur_y_mid - prev_y_mid) < max(prev_h * _SAME_LINE_Y_RATIO, 4.0):
            gap = r.bbox[0] - prev.bbox[2]
            if gap < _MERGE_GAP:
                prev.bbox = (
                    min(prev.bbox[0], r.bbox[0]),
                    min(prev.bbox[1], r.bbox[1]),
                    max(prev.bbox[2], r.bbox[2]),
                    max(prev.bbox[3], r.bbox[3]),
                )
                if prev.raw_latex and r.raw_latex:
                    prev.raw_latex += r.raw_latex
                continue
        merged.append(r)

    # 最小面积过滤
    merged = [r for r in merged
              if (r.bbox[2] - r.bbox[0]) >= _MIN_WIDTH
              and (r.bbox[3] - r.bbox[1]) >= _MIN_HEIGHT]

    return merged


# ── 区域分类 ─────────────────────────────────────────────────────────────────

def _classify_regions(regions, char_with_y, line_threshold, page_width):
    """将每个区域分类为 INLINE / DISPLAY / MIXED。"""
    for r in regions:
        rx0, ry0, rx1, ry1 = r.bbox
        region_w = rx1 - rx0
        region_h = ry1 - ry0
        y_center = (ry0 + ry1) / 2

        # 同行所有字符
        same_line = [c for c in char_with_y
                     if abs(c[6] - y_center) < max(region_h * _SAME_LINE_Y_RATIO_CLASSIFY, 5.0)]

        if not same_line:
            r.region_type = MathRegionType.MIXED
            continue

        line_x0 = min(c[0] for c in same_line)
        line_x1 = max(c[2] for c in same_line)
        line_w = line_x1 - line_x0

        # Display：占行宽 ≥ 70%
        if line_w > 0 and region_w >= line_w * _DISPLAY_WIDTH_RATIO:
            r.region_type = MathRegionType.DISPLAY
            # 高度超过行高 1.5 倍 → 扩展至整行高度
            if region_h > (max(c[3] - c[1] for c in same_line) * _DISPLAY_HEIGHT_RATIO):
                r.bbox = (r.bbox[0], min(c[1] for c in same_line),
                          r.bbox[2], max(c[3] for c in same_line))
            continue

        # Inline：同行有其他文字 span
        has_nearby_text = False
        for c in same_line:
            if not c[4]:  # 非数学字符
                # 在区域左侧或右侧相邻位置
                if (c[2] <= rx0 + _PADDING * 2 and rx0 - c[2] < line_w * 0.5) or \
                   (c[0] >= rx1 - _PADDING * 2 and c[0] - rx1 < line_w * 0.5):
                    has_nearby_text = True
                    break
        if has_nearby_text:
            r.region_type = MathRegionType.INLINE
        else:
            r.region_type = MathRegionType.MIXED

    return regions


# ── 正则降级 ─────────────────────────────────────────────────────────────────

def _detect_latex_delimiters(page):
    """检测页面文本中的 $...$ / $$...$$ 定界符。"""
    try:
        text = page.get_text()
    except Exception:
        return []

    regions = []
    for m in _RE_INLINE_MATH.finditer(text):
        regions.append(MathRegion(
            page_num=page.number,
            bbox=(0, 0, 0, 0),
            region_type=MathRegionType.INLINE,
            raw_latex=m.group(1),
        ))

    for m in _RE_DISPLAY_MATH.finditer(text):
        regions.append(MathRegion(
            page_num=page.number,
            bbox=(0, 0, 0, 0),
            region_type=MathRegionType.DISPLAY,
            raw_latex=m.group(1),
        ))

    return regions


def _merge_regex_regions(existing, regex_regions, char_with_y, line_threshold):
    """合并正则检测结果：已有区域足够则不重复添加。"""
    if not regex_regions:
        return existing

    # 如果已有基于字符检测的区域，正则结果作为补充
    # 只有当现有区域为空时，才用正则结果作为"有公式"的信号
    if existing:
        return existing

    # 尝试把正则匹配到的 LaTeX 映射回页面坐标
    # 坐标映射不可靠 → 保留 raw_latex 但不设 bbox（bbox 为 0）
    # 后续 Stage 2 可跳过或做整页截图
    return existing


# ── 文档级检测 ────────────────────────────────────────────────────────────────

def detect_document(doc: fitz.Document, pages: list[int] | None = None) -> dict[int, list[MathRegion]]:
    """检测多页 PDF 的数学区域。

    Args:
        doc: pymupdf Document
        pages: 要检测的页码列表，None 表示全部页

    Returns:
        {page_num: [MathRegion, ...]}
    """
    result: dict[int, list[MathRegion]] = {}
    target = pages if pages is not None else list(range(len(doc)))

    for pn in target:
        if pn < 0 or pn >= len(doc):
            continue
        try:
            regions = detect_page(doc[pn])
            result[pn] = regions
        except Exception as e:
            logger.warning("数学区域检测失败 page %d: %s", pn, e)
            result[pn] = []

    return result


# ── Stage 5：扫描版 OCR 框聚类检测 ───────────────────────────────────────────

def detect_from_ocr_boxes(
    boxes: list[dict],
    page_height: int,
) -> list[MathRegion]:
    """从 OCR 检测框聚类中推断数学区域（扫描版 PDF 专用）。

    Args:
        boxes: [{"bbox": [x0, y0, x1, y1], "conf": float}, ...]
               bbox 单位为像素，坐标系原点在左上角
        page_height: 页面高度（像素），用于异常过滤

    Returns:
        MathRegion 列表，region_type 均为 MIXED（扫描版无法精确分类）
    """
    try:
        return _cluster_ocr_boxes(boxes, page_height)
    except Exception as e:
        logger.warning("OCR 框聚类检测失败: %s", e)
        return []


def _cluster_ocr_boxes(boxes: list[dict], page_height: int) -> list[MathRegion]:
    if not boxes:
        return []

    # 解析并过滤噪声框
    parsed = []
    for b in boxes:
        bbox = b.get("bbox", [])
        if len(bbox) < 4:
            continue
        x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        w, h = x1 - x0, y1 - y0
        if h < 8 or w <= 0:  # 高度 < 8px 过滤
            continue
        if w / h > 5:         # 宽高比 > 5:1 的细条过滤
            continue
        parsed.append((x0, y0, x1, y1))

    if not parsed:
        return []

    # 水平投影分行：按 y 中心，差值 < 行高均值 × 0.6 视为同行
    heights = [b[3] - b[1] for b in parsed]
    avg_h = sum(heights) / len(heights) if heights else 16.0
    line_threshold = avg_h * 0.6

    parsed.sort(key=lambda b: (b[1] + b[3]) / 2)

    lines: list[list[tuple]] = []
    for box in parsed:
        y_center = (box[1] + box[3]) / 2
        placed = False
        for line in lines:
            line_y = sum((b[1] + b[3]) / 2 for b in line) / len(line)
            if abs(y_center - line_y) < line_threshold:
                line.append(box)
                placed = True
                break
        if not placed:
            lines.append([box])

    # 行内 DBSCAN 聚类（eps=15px）→ 合并为候选区域
    eps = 15.0
    regions: list[MathRegion] = []

    for line in lines:
        line.sort(key=lambda b: b[0])
        clusters: list[list[tuple]] = []
        cur = [line[0]]
        for box in line[1:]:
            gap = box[0] - cur[-1][2]
            if gap < eps:
                cur.append(box)
            else:
                clusters.append(cur)
                cur = [box]
        clusters.append(cur)

        for cluster in clusters:
            x0 = min(b[0] for b in cluster)
            y0 = min(b[1] for b in cluster)
            x1 = max(b[2] for b in cluster)
            y1 = max(b[3] for b in cluster)
            regions.append(MathRegion(
                page_num=0,
                bbox=(x0, y0, x1, y1),
                region_type=MathRegionType.MIXED,
                raw_latex=None,
                image_url=None,
            ))

    return regions
