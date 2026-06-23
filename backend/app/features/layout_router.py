"""Layout Router — 结构感知 DAG 路由决策。

在 layout_reconstruction 之后、split_questions 之前执行。
纯规则实现，不依赖 LLM。

职责：
1. 评估版面重建质量（layout_confidence + option_detection_score）
2. 返回路由模式：standard / layout_enhanced / vl_rebuild
3. routing 只由本模块决定，下游不重复评估

约束：
- 不修改 OCR 输出文本
- 不修改 layout_result
- 不决定"是否修复"——只决定"走哪条路"
"""

from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

SplitMode = Literal["standard", "layout_enhanced", "vl_rebuild"]

# ── 路由阈值 ──────────────────────────────────────────────
_CONFIDENCE_HIGH = 0.75       # ≥ 此值 = 结构清晰
_CONFIDENCE_LOW = 0.5         # < 此值 = 结构失败
_OPTION_SCORE_HIGH = 0.8      # 选项检测高分阈值


def evaluate_routing(layout_result: dict) -> SplitMode:
    """评估版面质量并返回路由模式。

    Args:
        layout_result: reconstruct_layout 的返回值。
            必须包含 layout_confidence 和 option_detection_failed。
            推荐包含 option_detection_score（0.0~1.0）。

    Returns:
        "standard"       — 结构清晰，走标准 split（带 layout 注入）
        "layout_enhanced" — 结构不稳定，走 layout+OCR 融合 split
        "vl_rebuild"     — 结构失败，需要 PaddleOCR-VL 重建
    """
    confidence = layout_result.get("layout_confidence", 1.0)
    opt_failed = layout_result.get("option_detection_failed", False)
    opt_score = layout_result.get("option_detection_score", 1.0)

    # ── 情况 3：结构失败 → VL 重建 ──
    if confidence < _CONFIDENCE_LOW or opt_failed:
        logger.info(
            "Route: vl_rebuild (confidence=%.2f < %.2f, opt_failed=%s)",
            confidence, _CONFIDENCE_LOW, opt_failed,
        )
        return "vl_rebuild"

    # ── 情况 1：标准结构路径 ──
    if confidence >= _CONFIDENCE_HIGH and opt_score >= _OPTION_SCORE_HIGH:
        logger.info(
            "Route: standard (confidence=%.2f >= %.2f, opt_score=%.2f >= %.2f)",
            confidence, _CONFIDENCE_HIGH, opt_score, _OPTION_SCORE_HIGH,
        )
        return "standard"

    # ── 情况 2：结构不稳定 → layout 增强 ──
    logger.info(
        "Route: layout_enhanced (confidence=%.2f, opt_score=%.2f)",
        confidence, opt_score,
    )
    return "layout_enhanced"
