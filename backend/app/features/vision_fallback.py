"""PaddleOCR-VL 视觉回退 — 当代码完整性检测到损坏时触发。

位置：在 ``normalize_question()`` 的代码完整性检测之后、结果组装之前调用。
调用方负责提供 ``page_image``（页面图片字节），来源为 pipeline 的 page_images 或 page_image_refs。

不依赖外部 DB 配置（由调用方解析后传入）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.features.code_integrity import detect_code_block_integrity

logger = logging.getLogger(__name__)

# 触发视觉回退的 code integrity flag 集合
CODE_TRIGGER_FLAGS: frozenset[str] = frozenset({
    "code_block_incomplete",
    "code_block_truncated",
    "code_garbled_text",
    "code_brace_unbalanced",
    "code_line_break_suspicious",
    "code_structure_regression",
})

_DEFAULT_VL_BASE_URL = "https://paddleocr.aistudio-app.com"
_DEFAULT_VL_MODEL = "PaddleOCR-VL-1.6"


def needs_vision_fallback(risk_flags: list[str]) -> bool:
    """检查 risk_flags 是否包含触发视觉回退的代码完整性标记。

    Args:
        risk_flags: normalized result 中的 risk_flags 列表。

    Returns:
        如果包含任一触发 flag 则返回 True。
    """
    return bool(CODE_TRIGGER_FLAGS & set(risk_flags))


def _build_vl_config(config: dict | None) -> dict:
    """从配置字典构建 VL 配置，缺失 api_token 时发出警告。"""
    cfg = config or {}
    api_token = cfg.get("paddleocr_vl_api_token") or cfg.get("api_token") or ""
    if not api_token:
        logger.warning("PaddleOCR-VL api_token 未配置，视觉回退不可用")
    return {
        "api_token": api_token,
        "base_url": cfg.get("paddleocr_vl_base_url") or cfg.get("base_url") or _DEFAULT_VL_BASE_URL,
        "model": cfg.get("paddleocr_vl_model") or cfg.get("model") or _DEFAULT_VL_MODEL,
    }


def _call_vl_sync(image_bytes: bytes, vl_config: dict) -> str:
    """同步调用 PaddleOCR-VL（通过 OCRFixRouter 唯一入口）。

    在已有事件循环的环境中（如 pipeline），通过新建事件循环避免冲突。

    Args:
        image_bytes: 页面图片 PNG 字节。
        vl_config: 包含 api_token/base_url/model 的配置字典。

    Returns:
        识别文本，失败或不可用时返回空字符串。
    """
    api_token = vl_config.get("api_token", "")
    if not api_token:
        return ""

    base_url = vl_config.get("base_url", _DEFAULT_VL_BASE_URL)
    model = vl_config.get("model", _DEFAULT_VL_MODEL)

    from app.features.ocr_fix.router import STRATEGY_MANUAL, OCRFixRouter

    router = OCRFixRouter()
    router.configure({
        "ocr_fix_strategy": STRATEGY_MANUAL,
        "ocr_fix_model": "paddleocr-vl",
        "paddleocr_vl_api_token": api_token,
        "paddleocr_vl_base_url": base_url,
        "paddleocr_vl_model": model,
    })

    async def _run() -> str:
        result = await router.fix(
            image=image_bytes, ocr_text="",
            context={"entry_point": "vision_fallback"},
        )
        return result.fixed_text or ""

    try:
        try:
            text = asyncio.run(_run())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                text = loop.run_until_complete(_run())
            finally:
                loop.close()
        if text:
            logger.info(
                "PaddleOCR-VL vision fallback succeeded (text_len=%d)", len(text)
            )
        else:
            logger.warning("PaddleOCR-VL vision fallback returned empty text")
        return text
    except Exception as exc:
        logger.warning("PaddleOCR-VL vision fallback failed: %s", exc)
        return ""


def _compare_code_results(
    original_code: dict,
    fallback_code: dict,
) -> str:
    """比较原结果与 VL 回退结果的代码完整性，判断回退是否值得采用。

    支持两种输入格式：
    - ``detect_code_block_integrity`` 结果：含 ``score`` / ``flags``
    - ``normalize_question`` 结果：含 ``confidence_score`` / ``risk_flags``

    比较维度（按优先级）：
    1. 代码完整性分数（score 越低越好）或置信度（confidence_score 越高越好）
    2. flag 数量（越少越好）
    3. 是否存在严重 flag（code_block_truncated / code_block_incomplete）

    Returns:
        "better":   回退结果更优，应替换原结果
        "worse":    回退结果更差，应保留原结果
        "similar":  回退结果无明显改善，保留原结果
    """
    # 兼容两种格式
    orig_score = original_code.get("score", original_code.get("confidence_score", 0))
    fallback_score = fallback_code.get("score", fallback_code.get("confidence_score", 0))
    orig_flags = set(original_code.get("flags", original_code.get("risk_flags", [])))
    fallback_flags = set(fallback_code.get("flags", fallback_code.get("risk_flags", [])))

    # 对 normalize_question 结果：confidence_score 越高越好，需要反转
    # detect_code_block_integrity 的结果用 score（越低越好）
    using_confidence = "risk_flags" in original_code
    if using_confidence:
        # confidence_score 越高越好，score_rev = 1.0 - confidence
        orig_score = 1.0 - orig_score if orig_score < 1.0 else 0.0
        fallback_score = 1.0 - fallback_score if fallback_score < 1.0 else 0.0

    # 回退结果具有严重 flag 而原结果没有 → 更差
    severe = {"code_block_truncated", "code_block_incomplete"}
    if (fallback_flags & severe) and not (orig_flags & severe):
        return "worse"

    # 回退结果完全没有 flag → 明显更好
    if not fallback_flags and orig_flags:
        return "better"

    # 原结果完全没有 flag → 无需回退（不应发生，但防御）
    if not orig_flags:
        return "similar"

    # 分数比较
    score_diff = fallback_score - orig_score
    if score_diff <= -0.2:
        return "better"
    elif score_diff >= 0.1:
        return "worse"
    else:
        # 分数接近：比较 flag 数量
        if len(fallback_flags) < len(orig_flags):
            return "better"
        elif len(fallback_flags) > len(orig_flags):
            return "worse"
        else:
            return "similar"


def apply_vision_fallback(
    raw_question: dict,
    normalized: dict,
    page_image: bytes | None = None,
    vl_config: dict | None = None,
) -> dict:
    """对已标准化题目执行 PaddleOCR-VL 视觉回退。

    在 ``normalize_question()`` 中代码完整性检测到触发 flag 后调用。
    流程：
    1. 检查是否有 page_image（没有则标记 unavailable 并返回）
    2. 调用 PaddleOCR-VL 重新识别
    3. 将 VL 结果作为 raw_question_text 传入 ``normalize_question()`` 重新标准化
    4. 比较两轮代码完整性结果
    5. 回退结果更好时替换原结果

    Args:
        raw_question: 原始题目 dict（含 raw_question_text 等字段）。
        normalized: 已标准化的题目结果（含 risk_flags / stem / confidence_score 等）。
        page_image: 页面图片字节（可选，没有则无法回退）。
        vl_config: PaddleOCR-VL 配置字典（可选，由调用方从 DB 解析后传入）。

    Returns:
        更新后的 standardized result（含 vision_fallback_* 状态字段）。
    """
    risk_flags = normalized.get("risk_flags") or []
    stem = normalized.get("stem") or ""

    # 初始化 fallback 状态
    result = dict(normalized)
    result["vision_fallback_attempted"] = True

    if not needs_vision_fallback(risk_flags):
        # 没有触发 flag → 不需要回退（防御性检查）
        result["vision_fallback_attempted"] = False
        result["vision_fallback_status"] = "not_needed"
        return result

    if not page_image:
        logger.info(
            "Vision fallback unavailable: no page_image for question (%.60s...)",
            stem[:60],
        )
        result["vision_fallback_status"] = "unavailable"
        result["vision_fallback_reason"] = list(risk_flags)
        return result

    # 调用 PaddleOCR-VL
    vl_text = _call_vl_sync(page_image, _build_vl_config(vl_config))
    if not vl_text:
        result["vision_fallback_status"] = "failed"
        result["vision_fallback_reason"] = list(risk_flags)
        return result

    # 对 VL 结果执行代码完整性检测
    stem_has_code = normalized.get("_stem_has_code", False)
    vl_code: dict[str, Any] = {"score": 0, "flags": []}
    if stem_has_code:
        # VL 结果作为 stem 的替代：使用 detect_code_block_integrity 比较
        vl_code = detect_code_block_integrity(vl_text)
    orig_code = detect_code_block_integrity(stem) if stem_has_code else {"score": 0, "flags": []}

    # 比较
    verdict = _compare_code_results(orig_code, vl_code)

    result["vision_fallback_engine"] = "paddleocr_vl"
    result["vision_fallback_reason"] = list(risk_flags)
    result["pre_fallback_code_flags"] = list(orig_code.get("flags", []))
    result["post_fallback_code_flags"] = list(vl_code.get("flags", []))

    if verdict == "better":
        # VL 结果更好 → 原样保留 vl_text 作为新的 raw_text 和 stem
        # （注：完整的重新标准化由调用方处理，此处仅更新状态）
        result["vision_fallback_status"] = "success"
        result["vision_fallback_used"] = True
        logger.info(
            "Vision fallback improved code integrity: score %.2f→%.2f, "
            "flags %s→%s",
            orig_code.get("score", 0), vl_code.get("score", 0),
            orig_code.get("flags", []), vl_code.get("flags", []),
        )
    elif verdict == "worse":
        result["vision_fallback_status"] = "not_better"
        result["vision_fallback_used"] = False
        logger.info(
            "Vision fallback result is worse: score %.2f→%.2f — keeping original",
            orig_code.get("score", 0), vl_code.get("score", 0),
        )
    else:
        # similar
        result["vision_fallback_status"] = "not_better"
        result["vision_fallback_used"] = False

    return result
