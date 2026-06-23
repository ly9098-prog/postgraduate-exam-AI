"""Layout Router — 结构感知 DAG 路由决策（生产固化版）。

在 layout_reconstruction 之后、split_questions 之前执行。
纯规则实现，不依赖 LLM。

职责：
1. 评估版面重建质量（layout_confidence）
2. 返回路由模式：standard / layout_enhanced / vl_rebuild
3. routing 只由本模块决定，下游不重复评估

路由策略（已冻结，禁止修改）:
    layout_confidence ≥ 0.75 → standard（高置信 fallback）
    0.5 ≤ layout_confidence < 0.75 → layout_enhanced（主路径）
    layout_confidence < 0.5 → vl_rebuild（最后兜底）

约束：
- 不修改 OCR 输出文本
- 不修改 layout_result
- 不决定"是否修复"——只决定"走哪条路"
- ❌ 不允许引入 ML routing / graph routing
- ❌ 不允许新增动态 threshold tuning
- ❌ 不允许增加新的 routing stage
"""

from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

SplitMode = Literal["standard", "layout_enhanced", "vl_rebuild"]

# ── 路由阈值（已固化，禁止修改）───────────────────────────
_CONFIDENCE_HIGH = 0.75       # ≥ 此值 = 结构清晰 → standard
_CONFIDENCE_LOW = 0.5         # < 此值 = 结构失败 → vl_rebuild


def evaluate_routing(layout_result: dict) -> SplitMode:
    """评估版面质量并返回路由模式（生产固化版）。

    路由完全基于 layout_confidence，已有阈值已固化，禁止新增条件。

    Args:
        layout_result: reconstruct_layout 的返回值。
            必须包含 layout_confidence。

    Returns:
        "standard"         — 高置信度，走标准 split（带 layout 注入）
        "layout_enhanced"  — 中等置信度，走 layout+OCR 融合 split（主路径）
        "vl_rebuild"       — 低置信度，需要 PaddleOCR-VL 重建（最后兜底）
    """
    confidence = layout_result.get("layout_confidence", 1.0)

    # ── 高置信度 → standard ──
    if confidence >= _CONFIDENCE_HIGH:
        logger.info(
            "Route: standard (confidence=%.2f >= %.2f)",
            confidence, _CONFIDENCE_HIGH,
        )
        return "standard"

    # ── 低置信度 → vl_rebuild（最后兜底）──
    if confidence < _CONFIDENCE_LOW:
        logger.info(
            "Route: vl_rebuild (confidence=%.2f < %.2f)",
            confidence, _CONFIDENCE_LOW,
        )
        return "vl_rebuild"

    # ── 中等置信度 → layout_enhanced（主路径）──
    logger.info(
        "Route: layout_enhanced (confidence=%.2f, threshold=[%.2f, %.2f))",
        confidence, _CONFIDENCE_LOW, _CONFIDENCE_HIGH,
    )
    return "layout_enhanced"
