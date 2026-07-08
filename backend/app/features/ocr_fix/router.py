"""OCRFixRouter — 可插拔 OCR 纠错模型路由器。

支持策略：
- manual: 手动选择模型
- auto: PaddleOCR-VL → DeepSeek → rule fallback（默认）

每个 adapter 输出必须通过 safety/quality gate 才能被接受。
非空不等于有效 — 选项丢失、代码符号破坏、题干丢失等都会触发拒绝。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.features.ocr_fix.interfaces import (
    OCRFixResult,
    CandidateDecision,
    CandidateEvaluation,
)

logger = logging.getLogger(__name__)

try:
    from app.core.log_context import log_event
except ImportError:  # pragma: no cover
    def log_event(_lg, _ev, **_kw):  # type: ignore[misc]
        pass

# Default fallback chain for "auto" strategy
_AUTO_CHAIN = ["paddleocr-vl", "deepseek", "rule_fallback"]

# Strategy constants
STRATEGY_MANUAL = "manual"
STRATEGY_AUTO = "auto"


@dataclass
class _AdapterAttempt:
    """Audit trail for a single adapter attempt in the chain."""
    adapter_name: str
    candidate_non_empty: bool = False
    validator_decision: str = ""
    reject_reason: str = ""
    risk_flags: tuple[str, ...] = ()
    latency_ms: float = 0.0
    error: str = ""


def _evaluate_adapter_output(
    result: OCRFixResult,
    original_text: str,
    context: dict[str, Any] | None,
) -> CandidateEvaluation:
    """Evaluate adapter output through the safety/quality gate.

    Uses ``ai_safety.safe_accept_ai_result`` as the primary gate.
    Additional checks are applied for options, code structure, etc.
    """
    from app.features.ai_safety import safe_accept_ai_result

    ctx = context or {}

    # Build quality_report from adapter confidence and existing risk_flags
    quality_report: dict[str, Any] = {}
    if result.confidence is not None and result.confidence < 0.3:
        quality_report["low_confidence"] = True
    if result.risk_flags:
        quality_report["risk_flags"] = list(result.risk_flags)

    # Run the safety gate
    safety = safe_accept_ai_result(
        original_text,
        result.fixed_text,
        context=ctx,
        quality_report=quality_report if quality_report else None,
    )

    risk_flags = tuple(safety.get("risk_flags", []))
    is_accepted = safety.get("accepted", False)
    reason = safety.get("rollback_reason", "")

    if is_accepted:
        if risk_flags:
            return CandidateEvaluation(
                decision=CandidateDecision.ACCEPT,
                reason="accepted_with_risk_flags",
                risk_flags=risk_flags,
            )
        return CandidateEvaluation(
            decision=CandidateDecision.ACCEPT,
            reason="accepted",
            risk_flags=risk_flags,
        )

    # P0: VL low-confidence + options_dropped → mark vl_low_confidence_rejected
    # so downstream stages know to preserve raw OCR structure.
    if (
        "options_dropped" in reason
        and result.confidence is not None
        and result.confidence <= 0.2
    ):
        risk_flags = list(risk_flags) + ["vl_low_confidence_rejected"]

    # ── Determine REJECT_CONTINUE vs REJECT_STOP ──
    # Most safety rejections are REJECT_CONTINUE (try next adapter).
    # REJECT_STOP is reserved for catastrophic failures.
    if reason in (
        "code_symbol_lost:->",
        "code_symbol_lost:{}",
        "code_symbol_lost:int",
    ) and not ctx.get("has_options"):
        # Catastrophic code damage with no options to salvage → stop
        return CandidateEvaluation(
            decision=CandidateDecision.REJECT_STOP,
            reason=reason,
            risk_flags=risk_flags,
        )

    return CandidateEvaluation(
        decision=CandidateDecision.REJECT_CONTINUE,
        reason=reason,
        risk_flags=risk_flags,
    )


class OCRFixRouter:
    """OCR 纠错模型路由器。

    根据 admin 配置选择模型，支持策略模式和失败自动降级。
    每个 adapter 输出必须经过 safety/quality evaluation 才能被接受。
    """

    def __init__(self, adapters: dict[str, Any] | None = None):
        """初始化路由器。

        Args:
            adapters: {model_name: fixer_instance} 映射。
              如果不提供，将在首次调用时按需惰性创建。
        """
        self._adapters: dict[str, Any] = {}
        if adapters:
            self._adapters = dict(adapters)
        self._config: dict[str, Any] = {}

    def configure(self, config: dict[str, Any]) -> None:
        """更新路由配置。"""
        self._config = dict(config)

    def register(self, name: str, fixer: Any) -> None:
        """注册适配器。"""
        self._adapters[name] = fixer

    def _get_adapter(self, name: str) -> Any | None:
        """获取适配器，必要时惰性创建。"""
        if name in self._adapters:
            return self._adapters[name]

        # 惰性创建
        if name == "rule_fallback":
            from app.features.ocr_fix.rule_adapter import RuleFixer
            self._adapters[name] = RuleFixer(config=self._config)
            return self._adapters[name]

        if name == "deepseek":
            from app.features.ocr_fix.deepseek_adapter import DeepSeekFixer
            api_key = self._config.get("deepseek_api_key")
            base_url = self._config.get("deepseek_base_url")
            self._adapters[name] = DeepSeekFixer(
                api_key=api_key, base_url=base_url, config=self._config,
            )
            return self._adapters[name]

        if name == "paddleocr-vl":
            from app.features.ocr_vl.paddleocr_vl_adapter import PaddleOCRVLAdapter
            api_token = self._config.get("paddleocr_vl_api_token")
            base_url = self._config.get("paddleocr_vl_base_url")
            model = self._config.get("paddleocr_vl_model", "PaddleOCR-VL-1.6")
            self._adapters[name] = PaddleOCRVLAdapter(
                api_token=api_token, base_url=base_url, model=model, config=self._config,
            )
            return self._adapters[name]

        logger.warning("Unknown OCR fix adapter: %s", name)
        return None

    def _resolve_chain(self) -> list[str]:
        """根据策略解析模型调用链。"""
        strategy = self._config.get("ocr_fix_strategy", STRATEGY_AUTO)

        if strategy == STRATEGY_MANUAL:
            selected = self._config.get("ocr_fix_model", "")
            if selected:
                return [selected]
            return _AUTO_CHAIN[:1]  # 选了一个但为空时走 rule

        # STRATEGY_AUTO
        return list(_AUTO_CHAIN)

    async def fix(
        self,
        image: bytes | None = None,
        ocr_text: str = "",
        context: dict[str, Any] | None = None,
    ) -> OCRFixResult:
        """执行 OCR 纠错，支持安全门评估和自动降级。

        按策略链顺序尝试每个模型：
        1. 非空输出 → safety evaluation
           - ACCEPT → 立即返回
           - REJECT_CONTINUE → 记录原因，尝试下一适配器
           - REJECT_STOP → 安全失败，返回原始文本
        2. 空/异常 → 记录错误，尝试下一适配器
        3. 全部失败 → 返回原始文本（degraded 标记）
        """
        chain = self._resolve_chain()
        attempts: list[_AdapterAttempt] = []
        last_error: str | None = None

        for model_name in chain:
            adapter = self._get_adapter(model_name)
            if adapter is None:
                continue

            # 跳过不可用的适配器
            if hasattr(adapter, "is_available") and not adapter.is_available:
                logger.debug("OCR fix adapter '%s' unavailable, skipping", model_name)
                continue

            attempt = _AdapterAttempt(adapter_name=model_name)
            start = time.monotonic()

            try:
                result = await adapter.fix(
                    image=image, ocr_text=ocr_text, context=context,
                )
                attempt.latency_ms = (time.monotonic() - start) * 1000

                # Check for error responses
                is_error = (
                    result.raw_response
                    and isinstance(result.raw_response, str)
                    and result.raw_response.startswith("error:")
                )

                if result.fixed_text and not is_error:
                    attempt.candidate_non_empty = True

                    # ── Safety evaluation ──
                    evaluation = _evaluate_adapter_output(
                        result, ocr_text, context,
                    )
                    attempt.validator_decision = evaluation.decision.value
                    attempt.reject_reason = evaluation.reason
                    attempt.risk_flags = evaluation.risk_flags

                    if evaluation.decision == CandidateDecision.ACCEPT:
                        logger.info(
                            "OCR fix accepted from '%s' (conf=%.2f, flags=%s): %s",
                            model_name, result.confidence or 0,
                            list(evaluation.risk_flags),
                            evaluation.reason,
                        )
                        log_event(
                            logger, "ocr.fix.router.accept", "info",
                            adapter=model_name,
                            confidence=result.confidence or 0,
                            risk_flags=list(evaluation.risk_flags),
                            latency_ms=attempt.latency_ms,
                        )
                        # Attach evaluation metadata to result
                        result.risk_flags = list(evaluation.risk_flags)
                        result.safety = {
                            "accepted": True,
                            "risk_flags": list(evaluation.risk_flags),
                        }
                        attempts.append(attempt)
                        self._log_audit_trail(attempts, final_decision="accepted")
                        return result

                    if evaluation.decision == CandidateDecision.REJECT_STOP:
                        logger.warning(
                            "OCR fix REJECT_STOP from '%s': %s (flags=%s) — "
                            "returning original text",
                            model_name, evaluation.reason, list(evaluation.risk_flags),
                        )
                        log_event(
                            logger, "ocr.fix.router.reject", "warning",
                            adapter=model_name,
                            decision="reject_stop",
                            reason=evaluation.reason[:200],
                            risk_flags=list(evaluation.risk_flags),
                        )
                        attempts.append(attempt)
                        self._log_audit_trail(attempts, final_decision="reject_stop")
                        return OCRFixResult(
                            fixed_text=ocr_text,
                            confidence=0.0,
                            model_used=f"degraded_{model_name}_rejected",
                            raw_response=f"rejected:{evaluation.reason}",
                            risk_flags=list(evaluation.risk_flags),
                            safety={
                                "accepted": False,
                                "rejected": True,
                                "reason": evaluation.reason,
                                "risk_flags": list(evaluation.risk_flags),
                            },
                        )

                    # REJECT_CONTINUE
                    logger.info(
                        "OCR fix REJECT_CONTINUE from '%s': %s — trying next adapter",
                        model_name, evaluation.reason,
                    )
                    attempts.append(attempt)
                    last_error = evaluation.reason
                    continue

                # Empty result or error
                error_msg = result.raw_response or "empty result"
                logger.warning(
                    "OCR fix '%s' returned no usable result, degrading: %s",
                    model_name, error_msg,
                )
                last_error = error_msg
                attempt.error = error_msg
            except Exception as exc:
                attempt.latency_ms = (time.monotonic() - start) * 1000
                logger.warning("OCR fix '%s' raised, degrading: %s", model_name, exc)
                last_error = str(exc)
                attempt.error = str(exc)

            attempts.append(attempt)

        # ── All adapters failed ──
        self._log_audit_trail(attempts, final_decision="all_failed")
        logger.warning(
            "All OCR fix models failed (%s), returning original text",
            " -> ".join(chain),
        )
        log_event(
            logger, "ocr.fix.router.all_failed", "warning",
            chain=" -> ".join(chain),
            attempt_count=len(attempts),
            last_error=last_error[:200] if last_error else None,
        )
        return OCRFixResult(
            fixed_text=ocr_text,
            confidence=0.0,
            model_used=f"degraded_{last_error}" if last_error else "degraded_all",
            safety={
                "accepted": False,
                "all_failed": True,
                "last_error": last_error,
                "attempts": [
                    {
                        "adapter": a.adapter_name,
                        "decision": a.validator_decision,
                        "reason": a.reject_reason or a.error,
                    }
                    for a in attempts
                ],
            },
        )

    def _log_audit_trail(
        self,
        attempts: list[_AdapterAttempt],
        *,
        final_decision: str,
    ) -> None:
        """Log the full audit trail of adapter attempts."""
        if not attempts:
            return
        audit: list[dict] = []
        for a in attempts:
            entry: dict = {
                "adapter": a.adapter_name,
                "candidate_non_empty": a.candidate_non_empty,
                "latency_ms": round(a.latency_ms, 1),
            }
            if a.validator_decision:
                entry["decision"] = a.validator_decision
            if a.reject_reason:
                entry["reason"] = a.reject_reason
            if a.risk_flags:
                entry["risk_flags"] = list(a.risk_flags)
            if a.error:
                entry["error"] = a.error
            audit.append(entry)
        logger.info(
            "OCRFixRouter audit: final=%s attempts=%s",
            final_decision, audit,
        )
