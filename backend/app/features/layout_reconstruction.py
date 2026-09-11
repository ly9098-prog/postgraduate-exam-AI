"""Layout Reconstruction — 基于 bbox 空间位置的版面重建。

在 OCR 文本标准化后、题目结构分析前执行。
纯规则实现，不依赖 LLM。

职责：
1. 按页聚类文本行，检测列结构（单栏/双栏）
2. 聚类选项块（A./B./C./D. 模式），即使 OCR 打乱了行顺序
3. 按空间位置重建阅读顺序
4. 输出版面置信度，供下游 fallback 决策

约束：
- 不修改 OCR 输出文本
- 仅输出富化的结构元数据
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── 选项行模式 ──────────────────────────────────────────────
_OPTION_PATTERN = re.compile(r"^\s*([A-Da-d])\s*[.．、:：)）]\s*(.*)")
_QUESTION_NUM_PATTERN = re.compile(r"^\s*(\d+)\s*[.．、)）]")
_PAREN_QUESTION_PATTERN = re.compile(r"^\s*[（(](\d+)[）)]")
# 列检测阈值：x坐标间隙超过页面宽度 × 此比例视为双栏
_COLUMN_GAP_RATIO = 0.08


@dataclass
class LayoutLine:
    """带 bbox 的单行文本."""

    text: str
    page: int
    block_index: int
    line_index: int
    bbox: list[float]  # [x0, y0, x1, y1]
    conf: float = 0.0
    page_width: float = 800
    page_height: float = 1200

    # ---- 几何属性 ----
    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    def is_option(self) -> tuple[str, str] | None:
        """返回 (key, text) 如果该行是选项行，否则 None。"""
        m = _OPTION_PATTERN.match(self.text)
        if m:
            return m.group(1).upper(), m.group(2).strip()
        return None

    def is_question_start(self) -> int | None:
        """返回题号如果该行是题号开始行，否则 None。"""
        m = _QUESTION_NUM_PATTERN.match(self.text)
        if m:
            return int(m.group(1))
        m = _PAREN_QUESTION_PATTERN.match(self.text)
        if m:
            return int(m.group(1))
        return None

    def is_empty(self) -> bool:
        return not self.text.strip()

    @property
    def has_bbox(self) -> bool:
        return self.conf > 0 and any(v > 0 for v in self.bbox)


@dataclass
class ColumnLayout:
    """单列版面。"""

    lines: list[LayoutLine] = field(default_factory=list)
    option_groups: dict[str, str] = field(default_factory=dict)
    option_confidence: float = 0.0
    question_starts: list[int] = field(default_factory=list)


@dataclass
class PageLayout:
    """单页版面分析结果。"""

    page: int
    columns: list[ColumnLayout] = field(default_factory=list)
    is_multicolumn: bool = False
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)


# ================================================================
# 核心算法
# ================================================================


def _collect_lines_from_blocks(
    normalized_blocks: list[dict],
) -> dict[int, list[LayoutLine]]:
    """从 normalized_blocks 中按 page 收集带 bbox 的行。"""
    pages: dict[int, list[LayoutLine]] = {}
    block_line_offset: dict[int, int] = {}

    for block in normalized_blocks:
        page = block.get("page", 0) or block.get("page_index", 0)
        text = block.get("normalized_text") or block.get("text", "")
        boxes = block.get("boxes") or []
        lines = text.split("\n")
        block_idx = block.get("block_index", 0)
        pw = block.get("page_width", 800)
        ph = block.get("page_height", 1200)

        page_lines = pages.setdefault(page, [])
        base = block_line_offset.get(page, 0)

        for i, line_text in enumerate(lines):
            raw_bbox = None
            conf = 0.0
            if i < len(boxes):
                raw_bbox = boxes[i].get("bbox") if isinstance(boxes[i], dict) else None
                conf = boxes[i].get("conf", 0.0) if isinstance(boxes[i], dict) else 0.0

            if raw_bbox and isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
                bbox = [float(v) for v in raw_bbox]
            else:
                bbox = [0, base + i * 20, pw, base + i * 20 + 15]
                conf = 0.0

            page_lines.append(
                LayoutLine(
                    text=line_text,
                    page=page,
                    block_index=block_idx,
                    line_index=len(page_lines),
                    bbox=bbox,
                    conf=conf,
                    page_width=pw,
                    page_height=ph,
                )
            )

        block_line_offset[page] = base + len(lines)

    return pages


def _cluster_by_x_position(
    lines: list[LayoutLine],
) -> list[list[LayoutLine]]:
    """根据 x 坐标的分布将行聚簇为列。"""
    if len(lines) < 4:
        return [sorted(lines, key=lambda l: (l.y0, l.y1))]

    page_w = max(l.page_width for l in lines) if lines else 800

    # 按 cx 排序
    sorted_lines = sorted(lines, key=lambda l: l.cx)

    # 检测 gap：cx 排序序列中最大的间隙
    gaps = []
    for i in range(1, len(sorted_lines)):
        gap = sorted_lines[i].cx - sorted_lines[i - 1].cx
        gaps.append((gap, i))

    if not gaps:
        return [sorted(lines, key=lambda l: (l.y0, l.y1))]

    max_gap, max_gap_idx = max(gaps, key=lambda x: x[0])
    threshold = page_w * _COLUMN_GAP_RATIO

    if max_gap > threshold and 0 < max_gap_idx < len(sorted_lines):
        left = sorted_lines[:max_gap_idx]
        right = sorted_lines[max_gap_idx:]
        left.sort(key=lambda l: (l.y0, l.y1))
        right.sort(key=lambda l: (l.y0, l.y1))
        return [left, right]

    # 单栏
    sorted_lines.sort(key=lambda l: (l.y0, l.y1))
    return [sorted_lines]


def _compute_confidence(
    lines: list[LayoutLine],
    columns: list[list[LayoutLine]],
    option_groups: dict[str, str],
) -> float:
    """计算页面版面置信度 0~1。"""
    if not lines:
        return 1.0

    # 基础：有 bbox 的比例
    has_box_count = sum(1 for l in lines if l.has_bbox)
    bbox_ratio = has_box_count / len(lines)

    # 选项完整度
    found_keys = set(option_groups.keys())
    expected = {"A", "B", "C", "D"}
    has_all_four = expected.issubset(found_keys)
    has_three = {"A", "B", "C"}.issubset(found_keys) or {"B", "C", "D"}.issubset(
        found_keys
    )

    option_score = 0.0
    if has_all_four:
        option_score = 1.0
    elif has_three:
        option_score = 0.7
    elif len(found_keys) >= 2:
        option_score = 0.5
    elif found_keys:
        option_score = 0.3

    # 选项行密度
    option_line_count = sum(1 for l in lines if l.is_option() is not None)
    option_density = min(1.0, option_line_count / max(len(lines), 1) * 4)

    # 多列加分（结构清晰）
    multi_col_bonus = 0.1 if len(columns) > 1 else 0.0

    confidence = (
        bbox_ratio * 0.25
        + option_score * 0.40
        + option_density * 0.25
        + multi_col_bonus * 0.10
    )

    return min(1.0, max(0.0, confidence))


def _analyze_page(
    page: int,
    lines: list[LayoutLine],
) -> PageLayout:
    """分析单页版面。"""
    columns_data = _cluster_by_x_position(lines)
    is_multi = len(columns_data) > 1
    col_layouts: list[ColumnLayout] = []

    all_option_groups: dict[str, str] = {}
    warnings: list[str] = []

    for col_lines in columns_data:
        col_options: dict[str, str] = {}
        q_starts: list[int] = []

        for line in col_lines:
            opt = line.is_option()
            if opt:
                col_options[opt[0]] = opt[1]
            qn = line.is_question_start()
            if qn:
                q_starts.append(qn)

        found = set(col_options.keys())
        if found:
            all_option_groups.update(col_options)

        opt_conf = 0.0
        if {"A", "B", "C", "D"}.issubset(found):
            opt_conf = 1.0
        elif {"A", "B", "C"}.issubset(found) or {"B", "C", "D"}.issubset(found):
            opt_conf = 0.7
        elif len(found) >= 2:
            opt_conf = 0.5
        elif found:
            opt_conf = 0.3

        col_layouts.append(
            ColumnLayout(
                lines=col_lines,
                option_groups=col_options,
                option_confidence=opt_conf,
                question_starts=q_starts,
            )
        )

    if is_multi:
        warnings.append(f"page {page}: {len(columns_data)} columns detected")

    confidence = _compute_confidence(lines, columns_data, all_option_groups)

    return PageLayout(
        page=page,
        columns=col_layouts,
        is_multicolumn=is_multi,
        confidence=confidence,
        warnings=warnings,
    )


def _build_reading_order(
    pages_layout: dict[int, PageLayout],
) -> list[dict]:
    """构建全局阅读顺序。"""
    order: list[dict] = []
    for page in sorted(pages_layout.keys()):
        pl = pages_layout[page]
        for col_idx, col in enumerate(pl.columns):
            sorted_in_col = sorted(col.lines, key=lambda l: (l.y0, l.y1))
            for line in sorted_in_col:
                order.append(
                    {
                        "page": page,
                        "block_index": line.block_index,
                        "line_index": line.line_index,
                        "column": col_idx,
                        "text": line.text[:80],
                    }
                )
    return order


def _build_option_groups_index(
    pages_layout: dict[int, PageLayout],
) -> dict[str, dict[str, str]]:
    """构建 {page: {key: text}} 选项索引。"""
    index: dict[str, dict[str, str]] = {}
    for page, pl in sorted(pages_layout.items()):
        page_options: dict[str, str] = {}
        for col in pl.columns:
            page_options.update(col.option_groups)
        if page_options:
            index[str(page)] = page_options
    return index


def _detect_option_failed(
    option_groups: dict[str, dict[str, str]],
    total_pages: int,
) -> bool:
    """判断选项检测是否失败。

    宽松策略：至少 1 页有 ≥2 个不同选项字母即视为检测成功。
    对比之前的"必须全部 A/B/C/D 同时出现"，避免判断题/三选项题误触发 fallback。
    """
    if total_pages <= 0:
        return False
    for page_options in option_groups.values():
        if len(page_options) >= 2:
            return False
    return True


# ================================================================
# 公开接口
# ================================================================


def reconstruct_layout(
    normalized_blocks: list[dict],
) -> dict[str, Any]:
    """版面重建主入口。

    对 OCR 标准化后的块列表进行空间版面分析，
    输出富化的结构元数据供下游（split/match）使用。

    Args:
        normalized_blocks: 标准化块列表。
            每个块应含: page, block_index, text/normalized_text,
            boxes (list of {bbox, conf}), page_width, page_height。

    Returns:
        layout_result dict (与现有 DAG 兼容):
            layout_blocks: 带 layout_info 的增强块列表。
            option_groups: {page: {key: text}} 选项索引。
            layout_confidence: float 0~1。
            option_detection_score: float 0~1（最高页选项覆盖率）。
            reading_order: [{page, block_index, line_index, column}]。
            option_detection_failed: bool。
            page_layouts: {page: PageLayout} 内部版面数据（供 orchestrator 日志用）。
            warnings: str[]。
    """
    if not normalized_blocks:
        return {
            "layout_blocks": [],
            "option_groups": {},
            "layout_confidence": 1.0,
            "option_detection_score": 0.0,
            "reading_order": [],
            "option_detection_failed": False,
            "page_layouts": {},
            "warnings": ["no blocks to reconstruct"],
        }

    # 1. 按页收集行
    pages_lines = _collect_lines_from_blocks(normalized_blocks)

    # 2. 逐页分析
    pages_layout: dict[int, PageLayout] = {}
    all_warnings: list[str] = []

    for page in sorted(pages_lines.keys()):
        lines = pages_lines[page]
        if not lines:
            continue
        pl = _analyze_page(page, lines)
        pages_layout[page] = pl
        all_warnings.extend(pl.warnings)

    # 3. 构建选项索引
    option_groups = _build_option_groups_index(pages_layout)

    # 4. 计算整体置信度
    if pages_layout:
        layout_confidence = sum(pl.confidence for pl in pages_layout.values()) / len(
            pages_layout
        )
    else:
        layout_confidence = 1.0

    # 5. 构建阅读顺序
    reading_order = _build_reading_order(pages_layout)

    # 6. 选项检测失败标记（宽松策略）
    option_detection_failed = _detect_option_failed(option_groups, len(pages_lines))

    # 6b. 选项检测得分（0.0~1.0，比 bool 更精细）
    # 最高页的选项覆盖率，用于 router 精细决策
    if not option_groups:
        option_detection_score = 0.0
    else:
        max_page_coverage = max(len(keys) for keys in option_groups.values())
        option_detection_score = min(1.0, max_page_coverage / 4.0)

    # 7. 构造 enriched blocks
    _enrich_blocks_with_layout(normalized_blocks, pages_layout)

    return {
        "layout_blocks": normalized_blocks,
        "option_groups": option_groups,
        "layout_confidence": layout_confidence,
        "option_detection_score": option_detection_score,
        "reading_order": reading_order,
        "option_detection_failed": option_detection_failed,
        "page_layouts": pages_layout,
        "warnings": all_warnings,
    }


def _enrich_blocks_with_layout(
    normalized_blocks: list[dict],
    pages_layout: dict[int, PageLayout],
) -> None:
    """就地 enrich normalized_blocks，添加 layout_info 字段。"""
    for block in normalized_blocks:
        page = block.get("page", 0) or block.get("page_index", 0)
        pl = pages_layout.get(page)
        if not pl:
            block["layout_info"] = {"page_type": "unknown"}
            continue

        # 查找此 block 的行落在哪些列中
        block_idx = block.get("block_index", 0)
        col_indices: set[int] = set()
        for col_idx, col in enumerate(pl.columns):
            for line in col.lines:
                if line.block_index == block_idx:
                    col_indices.add(col_idx)

        block["layout_info"] = {
            "page_type": "multicolumn" if pl.is_multicolumn else "single_column",
            "column_count": len(pl.columns),
            "in_columns": sorted(col_indices) if col_indices else [0],
            "page_confidence": pl.confidence,
        }


def needs_fallback(layout_result: dict[str, Any]) -> bool:
    """判断是否触发 PaddleOCR-VL 布局模式回退。

    条件（任一满足即回退）：
    - layout_confidence < 0.6
    - option_detection_failed 为 True

    不要求全部 4 个选项同时出现（宽松策略兼容判断题/三选项题）。

    Args:
        layout_result: reconstruct_layout 的返回值。

    Returns:
        需要回退则 True。
    """
    confidence = layout_result.get("layout_confidence", 1.0)
    opt_failed = layout_result.get("option_detection_failed", False)

    if confidence < 0.6:
        logger.info(
            "Layout fallback triggered: confidence=%.2f < 0.6",
            confidence,
        )
        return True

    if opt_failed:
        logger.info("Layout fallback triggered: option_detection_failed=True")
        return True

    return False
