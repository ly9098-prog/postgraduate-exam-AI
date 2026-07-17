"""CandidateEvaluator — 统一 AI 纠错候选评估器。

替代分散在 OCRFixRouter、pipeline_orchestrator 和兼容层中的多套安全检查。
所有 AI 纠错候选（PaddleOCR-VL、DeepSeek、rule fallback）经过此单一入口评估。

输出:
    accepted_text, decision, reason_codes, diff,
    quality_before, quality_after, provenance, evaluator_version

后续模块只消费决策，不重复实现 acceptance policy。
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------


class CandidateDecision(Enum):
    ACCEPT = "accept"
    REJECT_CONTINUE = "reject_continue"  # rejected, try next adapter
    REJECT_STOP = "reject_stop"          # catastrophic failure, return original


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


def _build_diff(before: str, after: str) -> str:
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
# Evaluator output
# ---------------------------------------------------------------------------


@dataclass
class CandidateEvaluation:
    """单一候选的完整评估结果。"""
    decision: CandidateDecision = CandidateDecision.REJECT_CONTINUE
    reason_code: str = ""
    accepted_text: str = ""
    diff: str = ""
    quality_before: dict[str, Any] = field(default_factory=dict)
    quality_after: dict[str, Any] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
    evaluator_version: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------


def _quality_profile(text: str) -> dict[str, Any]:
    """Compute a quality profile for the given text."""
    return {
        "length": len(text),
        "nonempty_lines": len([l for l in text.splitlines() if l.strip()]),
        "chinese_chars": _count_chinese_chars(text),
        "code_symbols": _count_code_symbols(text),
        "options_count": _count_options(text),
        "has_watermark": _has_watermark(text),
    }


# ---------------------------------------------------------------------------
# CandidateEvaluator
# ---------------------------------------------------------------------------


_EVALUATOR_VERSION = "v1"


class CandidateEvaluator:
    """Unified, versioned evaluator for AI correction candidates.

    All OCR fix outputs (PaddleOCR-VL, DeepSeek, rule fallback, etc.) should
    be evaluated through this single entry point before acceptance.

    Usage::

        evaluator = CandidateEvaluator()
        evaluation = evaluator.evaluate(
            original_text="...",
            candidate_text="...",
            context={"has_options": True},
            quality_report={"low_confidence": False},
        )
        if evaluation.decision == CandidateDecision.ACCEPT:
            # use evaluation.accepted_text
            pass
    """

    def __init__(self) -> None:
        self._version = _EVALUATOR_VERSION

    @property
    def version(self) -> str:
        return self._version

    def evaluate(
        self,
        original_text: str,
        candidate_text: str,
        *,
        context: dict[str, Any] | None = None,
        quality_report: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> CandidateEvaluation:
        """Evaluate a single AI correction candidate.

        Args:
            original_text: Pre-correction text (before AI).
            candidate_text: Post-correction text (after AI).
            context: {has_options, stem_context, expected_answer, after_answer,
                      is_code_context}.
            quality_report: {low_confidence, garbled_detected}.
            provenance: {engine, model_version, adapter}.

        Returns:
            CandidateEvaluation with decision and metadata.
        """
        ctx = context or {}
        risk_flags: list[str] = []

        q_before = _quality_profile(original_text)
        q_after = _quality_profile(candidate_text)

        # ── Checks (ordered by severity) ──

        # 1. Empty candidate
        if not candidate_text or not candidate_text.strip():
            return CandidateEvaluation(
                decision=CandidateDecision.REJECT_CONTINUE,
                reason_code="after_empty",
                diff="(empty output)",
                quality_before=q_before,
                quality_after=q_after,
                evaluator_version=self._version,
                provenance=provenance or {},
            )

        # 2. Length anomaly
        len_before = len(original_text.strip())
        len_after = len(candidate_text.strip())
        if len_before > 10:
            ratio = len_after / max(len_before, 1)
            if ratio < 0.5:
                return self._reject(
                    f"length_collapse({len_before}->{len_after})",
                    original_text, candidate_text,
                    q_before, q_after, provenance,
                )
            if ratio > 2.0:
                return self._reject(
                    f"length_explosion({len_before}->{len_after})",
                    original_text, candidate_text,
                    q_before, q_after, provenance,
                )

        # 3. Code symbol drift
        is_code = ctx.get("is_code_context", False) or bool(
            re.search(r"[{};]|int\s|void\s|#include|printf|malloc|struct\s",
                      original_text)
        )
        if is_code:
            before_syms = q_before.get("code_symbols", {})
            after_syms = q_after.get("code_symbols", {})
            for name in before_syms:
                delta = abs(after_syms.get(name, 0) - before_syms[name])
                if before_syms[name] > 0 and delta >= before_syms[name]:
                    return self._reject(
                        f"code_symbol_lost:{name}",
                        original_text, candidate_text,
                        q_before, q_after, provenance,
                        risk_flags=(
                            risk_flags + [f"code_symbol_drift:{name}"]
                        ),
                    )
                elif before_syms[name] > 0 and delta > before_syms[name] * 0.5:
                    risk_flags.append(f"code_symbol_drift:{name}")

        # 4. Stem loss
        stem_ctx = ctx.get("stem_context", "")
        if stem_ctx:
            stem_chinese = _count_chinese_chars(stem_ctx)
            after_chinese = q_after["chinese_chars"]
            if stem_chinese > 5 and after_chinese < stem_chinese * 0.3:
                return self._reject(
                    f"stem_lost({stem_chinese}->{after_chinese})",
                    original_text, candidate_text,
                    q_before, q_after, provenance,
                )

        # 5. Option drop
        if ctx.get("has_options"):
            before_opts = q_before["options_count"]
            after_opts = q_after["options_count"]
            if before_opts >= 3 and after_opts < before_opts:
                return self._reject(
                    f"options_dropped({before_opts}->{after_opts})",
                    original_text, candidate_text,
                    q_before, q_after, provenance,
                )

        # 6. Answer modified
        expected = ctx.get("expected_answer", "")
        if expected:
            after_answer = ctx.get("after_answer", "")
            if after_answer and after_answer != expected:
                return self._reject(
                    f"answer_modified({expected}->{after_answer})",
                    original_text, candidate_text,
                    q_before, q_after, provenance,
                    risk_flags=["answer_modified"],
                )

        # 7. Watermark retained by AI
        if _has_watermark(candidate_text) and not _has_watermark(original_text):
            risk_flags.append("watermark_retained_by_ai")

        # 8. Quality report flags
        if quality_report:
            if quality_report.get("low_confidence"):
                risk_flags.append("low_confidence_source")
            if quality_report.get("garbled_detected"):
                risk_flags.append("garbled_source")

        # ── Accept ──
        diff = _build_diff(original_text, candidate_text)
        return CandidateEvaluation(
            decision=CandidateDecision.ACCEPT,
            reason_code="accepted" if not risk_flags else "accepted_with_risk_flags",
            accepted_text=candidate_text,
            diff=diff,
            quality_before=q_before,
            quality_after=q_after,
            risk_flags=risk_flags,
            evaluator_version=self._version,
            provenance=provenance or {},
        )

    def _reject(
        self,
        reason: str,
        original_text: str,
        candidate_text: str,
        q_before: dict,
        q_after: dict,
        provenance: dict | None,
        *,
        risk_flags: list[str] | None = None,
        stop: bool = False,
    ) -> CandidateEvaluation:
        return CandidateEvaluation(
            decision=CandidateDecision.REJECT_STOP if stop else CandidateDecision.REJECT_CONTINUE,
            reason_code=reason,
            accepted_text="",
            diff=_build_diff(original_text, candidate_text),
            quality_before=q_before,
            quality_after=q_after,
            risk_flags=risk_flags or [],
            evaluator_version=self._version,
            provenance=provenance or {},
        )


# ---------------------------------------------------------------------------
# Convenience: evaluate-and-decide wrapper
# ---------------------------------------------------------------------------

_evaluator_instance: CandidateEvaluator | None = None


def get_evaluator() -> CandidateEvaluator:
    """Return the process-wide CandidateEvaluator singleton."""
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = CandidateEvaluator()
    return _evaluator_instance


def evaluate_candidate(
    original_text: str,
    candidate_text: str,
    *,
    context: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> CandidateEvaluation:
    """Evaluate a single AI correction candidate using the singleton evaluator."""
    return get_evaluator().evaluate(
        original_text, candidate_text,
        context=context,
        quality_report=quality_report,
        provenance=provenance,
    )
