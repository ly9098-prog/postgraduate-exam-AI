"""AI edit trace & safety gate — 统一 AI 修改追踪与自动回滚保护。

每个 AI 介入点记录 unified trace，safe_accept_ai_result 提供多维度
自动审核，高风险修改自动拒绝或标记人工审核。
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unified AI edit trace
# ---------------------------------------------------------------------------


@dataclass
class AIEditTrace:
    """统一的 AI 修改记录。"""
    stage: str                           # "ocr_fix" / "ai_repair" / "ai_complete" / "ai_enrich"
    model: str                           # "qwen-vl" / "deepseek" / "rule_fallback" ...
    before: str                          # 修改前文本（截断到 2000 字符）
    after: str                           # 修改后文本（截断到 2000 字符）
    diff: str = ""                       # unified diff 摘要
    risk_flags: list[str] = field(default_factory=list)
    accepted: bool = True
    rollback_reason: str | None = None
    tokens_used: int = 0
    duration_ms: int = 0
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "model": self.model,
            "before": self.before[:500],
            "after": self.after[:500],
            "diff": self.diff[:300],
            "risk_flags": self.risk_flags,
            "accepted": self.accepted,
            "rollback_reason": self.rollback_reason,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
        }


# ---------------------------------------------------------------------------
# Code symbol patterns for protection
# ---------------------------------------------------------------------------

_CODE_SYMBOLS = [
    ("->", r"->"),
    ("==", r"=="),
    ("!=", r"!="),
    ("<=", r"<="),
    (">=", r">="),
    ("*", r"\*"),
    ("&", r"&"),
    ("++", r"\+\+"),
    ("--", r"--"),
]

_WATERMARK_PATTERNS = re.compile(
    r"扫描|扫一扫|二维码|公众号|微信.*扫|扫码.*关注|关注.*微信|"
    r"版权所有|未经许可.*不得|独家.*提供|翻印必究|盗版.*追究",
)


def _count_code_symbols(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, pat in _CODE_SYMBOLS:
        counts[name] = len(re.findall(pat, text))
    return counts


def _count_chinese_chars(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def _count_options(text: str) -> int:
    return len(re.findall(r"(?:^|\n)\s*[A-D][.、．）)\s]", text))


def _has_watermark(text: str) -> bool:
    return bool(_WATERMARK_PATTERNS.search(text))


# ---------------------------------------------------------------------------
# diff 生成
# ---------------------------------------------------------------------------


def _build_diff(before: str, after: str) -> str:
    """生成简短 unified diff 摘要（最多 20 行）。"""
    differ = list(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        lineterm="",
        n=1,
    ))
    if not differ:
        return "(no change)"
    return "\n".join(differ[:20])


# ---------------------------------------------------------------------------
# safe_accept_ai_result
# ---------------------------------------------------------------------------


def safe_accept_ai_result(
    before: str,
    after: str,
    *,
    context: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
) -> dict:
    """多维度自动审核 AI 修改结果。

    Returns:
        {
            "accepted": bool,         # True = 接受修改
            "risk_flags": [str],      # 风险标记列表
            "rollback_reason": str|None,  # 拒绝原因
            "diff": str,              # diff 摘要
        }
    """
    ctx = context or {}
    risk_flags: list[str] = []
    rollback_reason: str | None = None

    # ---- 1. after 为空 ----
    if not after or not after.strip():
        return _reject("after_empty", diff="(empty output)")

    # ---- 2. 长度异常保护 ----
    len_before = len(before.strip())
    len_after = len(after.strip())
    if len_before > 10:  # 原文本太短时不触发
        ratio = len_after / max(len_before, 1)
        if ratio < 0.5:
            return _reject(
                f"length_collapse({len_before}→{len_after}, ratio={ratio:.2f})",
                diff=_build_diff(before, after),
            )
        if ratio > 2.0:
            return _reject(
                f"length_explosion({len_before}→{len_after}, ratio={ratio:.2f})",
                diff=_build_diff(before, after),
            )

    # ---- 3. 代码符号数量异常变化 ----
    is_code_context = ctx.get("is_code_context", False) or bool(
        re.search(r"[{};]|int\s|void\s|#include|printf|malloc|struct\s", before)
    )
    if is_code_context:
        before_syms = _count_code_symbols(before)
        after_syms = _count_code_symbols(after)
        for name in before_syms:
            delta = abs(after_syms.get(name, 0) - before_syms[name])
            if before_syms[name] > 0 and delta > before_syms[name] * 0.5:
                risk_flags.append(f"code_symbol_drift:{name}")
                if delta >= before_syms[name]:  # 丢失了所有该符号
                    return _reject(
                        f"code_symbol_lost:{name}",
                        risk_flags=risk_flags,
                        diff=_build_diff(before, after),
                    )

    # ---- 4. 题干丢失检测 ----
    stem_context = ctx.get("stem_context", "")
    if stem_context:
        stem_chinese = _count_chinese_chars(stem_context)
        after_chinese = _count_chinese_chars(after)
        if stem_chinese > 5 and after_chinese < stem_chinese * 0.3:
            return _reject(
                f"stem_lost({stem_chinese}→{after_chinese} chinese chars)",
                diff=_build_diff(before, after),
            )

    # ---- 5. 选项数量减少 ----
    if ctx.get("has_options"):
        before_opts = _count_options(before)
        after_opts = _count_options(after)
        if before_opts >= 3 and after_opts < before_opts:
            return _reject(
                f"options_dropped({before_opts}→{after_opts})",
                diff=_build_diff(before, after),
            )

    # ---- 6. 答案被无依据修改 ----
    expected_answer = ctx.get("expected_answer", "")
    if expected_answer and expected_answer not in after:
        risk_flags.append("answer_modified")

    # ---- 7. 水印文字被 AI 保留 ----
    if _has_watermark(after) and not _has_watermark(before):
        risk_flags.append("watermark_retained_by_ai")

    # ---- 8. 质量报告标记 ----
    if quality_report:
        if quality_report.get("low_confidence"):
            risk_flags.append("low_confidence_source")
        if quality_report.get("garbled_detected"):
            risk_flags.append("garbled_source")

    diff = _build_diff(before, after)
    return {
        "accepted": True,
        "risk_flags": risk_flags,
        "rollback_reason": rollback_reason,
        "diff": diff,
    }


def _reject(reason: str, *, risk_flags: list[str] | None = None, diff: str = "") -> dict:
    return {
        "accepted": False,
        "risk_flags": risk_flags or [],
        "rollback_reason": reason,
        "diff": diff,
    }


# ---------------------------------------------------------------------------
# 便捷函数：构建 trace + 按需回滚
# ---------------------------------------------------------------------------


def evaluate_and_trace(
    stage: str,
    model: str,
    before: str,
    after: str,
    *,
    context: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
    tokens_used: int = 0,
    duration_ms: int = 0,
) -> tuple[AIEditTrace, str]:
    """评估 AI 修改并返回 trace + 最终文本（可能回滚）。

    Returns:
        (trace, final_text) — 如果 rejected，final_text == before（回滚原文）
    """
    safety = safe_accept_ai_result(
        before, after,
        context=context,
        quality_report=quality_report,
    )

    trace = AIEditTrace(
        stage=stage,
        model=model,
        before=before[:2000],
        after=after[:2000],
        diff=safety["diff"],
        risk_flags=safety["risk_flags"],
        accepted=safety["accepted"],
        rollback_reason=safety["rollback_reason"],
        tokens_used=tokens_used,
        duration_ms=duration_ms,
        context=context or {},
    )

    if not safety["accepted"]:
        logger.warning(
            "AI safety REJECTED [%s/%s]: %s",
            stage, model, safety["rollback_reason"],
        )
        return trace, before  # 回滚

    if safety["risk_flags"]:
        logger.info(
            "AI safety ACCEPTED with flags [%s/%s]: %s",
            stage, model, ", ".join(safety["risk_flags"]),
        )

    return trace, after
