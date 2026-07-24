"""Domain Quality Gate — 领域质量门 Shadow Mode。

本轮只运行 Shadow Mode，不改变现有生产接受/拒绝决策。

接口:
    DomainQualityGate(Protocol)
    QualityDecision
    QualityContext

使用:
    gate = QuestionStructureQualityGate()
    decision = gate.evaluate(before, candidate, context)
    if gate_mode == "shadow":
        record_decision(decision)  # no production impact

Gate 列表:
    - QuestionStructureQualityGate
    - CodeQualityGate
    - PlainTextQualityGate
    - MathQualityGate (接口和最小指标)
    - TableQualityGate (接口和最小指标)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOMAIN_QUALITY_GATE_MODE = "off"  # "off" | "shadow" | "enforce"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class QualityContext:
    """Quality evaluation context."""
    pipeline_fingerprint: str = ""
    gate_mode: str = DOMAIN_QUALITY_GATE_MODE
    existing_decision: str = "accept"  # "accept" | "reject"
    doc_ir_source: str = ""           # "paddleocr" | "paddleocr-vl" | "deepseek"
    diagnostics: list[dict] = field(default_factory=list)


@dataclass
class QualityDecision:
    """Single gate evaluation result."""
    accepted: bool
    score_before: float = 0.0
    score_after: float = 0.0
    delta: float = 0.0
    risk_flags: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    gate_name: str = ""
    gate_version: str = "1.0"


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class DomainQualityGate(Protocol):
    """Domain quality gate protocol.

    All gates implement ``evaluate(before, candidate, context) → QualityDecision``.
    """

    def evaluate(
        self,
        before: Any,
        candidate: Any,
        context: QualityContext,
    ) -> QualityDecision:
        ...


# ---------------------------------------------------------------------------
# Shadow mode recorder
# ---------------------------------------------------------------------------


def record_shadow_decision(
    decision: QualityDecision,
    context: QualityContext,
) -> dict:
    """Record a shadow mode decision for diagnostics.

    In shadow mode, the decision is recorded but does not affect the
    pipeline output. Returns a serializable dict for diagnostics.
    """
    entry = {
        "gate_name": decision.gate_name,
        "gate_version": decision.gate_version,
        "mode": context.gate_mode,
        "existing_decision": context.existing_decision,
        "would_accept": decision.accepted,
        "score_before": round(decision.score_before, 4),
        "score_after": round(decision.score_after, 4),
        "delta": round(decision.delta, 4),
        "risk_flags": decision.risk_flags,
        "reason_codes": decision.reason_codes,
    }
    context.diagnostics.append(entry)
    return entry


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _text_length(text: str) -> int:
    return len(text.strip())


def _char_ratio(text: str) -> dict[str, float]:
    """Compute Chinese, English, digit, symbol ratios."""
    if not text:
        return {"chinese": 0.0, "english": 0.0, "digit": 0.0, "symbol": 0.0, "other": 0.0}
    total = len(text)
    chinese = sum(1 for c in text if '一' <= c <= '鿿')
    english = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    digit = sum(1 for c in text if c.isdigit())
    symbol = sum(1 for c in text if not c.isalnum() and c not in ('\n', ' ', '\t'))
    other = total - chinese - english - digit - symbol
    return {
        "chinese": chinese / max(total, 1),
        "english": english / max(total, 1),
        "digit": digit / max(total, 1),
        "symbol": symbol / max(total, 1),
        "other": other / max(total, 1),
    }


def _tokenize_code(text: str) -> set[str]:
    """Extract code-like tokens from text."""
    return set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', text))


# ---------------------------------------------------------------------------
# QuestionStructureQualityGate
# ---------------------------------------------------------------------------


class QuestionStructureQualityGate:
    """检查题号、选项、答案等结构是否在 OCR 处理后发生变化。"""

    gate_name = "QuestionStructureQualityGate"
    gate_version = "1.0"

    _QN_PATTERN = re.compile(r"(?:^|\n)\s*(\d+)\s*[.、．）)\s]")
    _OPTION_KEY_PATTERN = re.compile(r"(?:^|\n)\s*([A-D])[.、．）)\s]")
    _ANSWER_PATTERN = re.compile(
        r"(?:答案|【答案】|参考答案|正确答案|KEY)\s*[：: ]?\s*([A-D]+|[TF])",
        re.IGNORECASE,
    )

    def evaluate(
        self,
        before: Any,
        candidate: Any,
        context: QualityContext,
    ) -> QualityDecision:
        risk_flags: list[str] = []
        reason_codes: list[str] = []
        metrics: dict[str, float] = {}

        before_text = self._extract_text(before)
        candidate_text = self._extract_text(candidate)

        # Question number count and order
        b_qns = set(self._extract_qnumbers(before_text))
        c_qns = set(self._extract_qnumbers(candidate_text))
        qn_diff = b_qns - c_qns
        if qn_diff:
            risk_flags.append("question_number_lost")
            reason_codes.append("STRUCTURE_QN_LOST")

        extra_qn = c_qns - b_qns
        if extra_qn:
            risk_flags.append("question_number_added")
            reason_codes.append("STRUCTURE_QN_ADDED")

        metrics["qn_count_before"] = float(len(b_qns))
        metrics["qn_count_after"] = float(len(c_qns))
        metrics["qn_jaccard"] = len(b_qns & c_qns) / max(len(b_qns | c_qns), 1)

        # Option key sets
        b_opts = self._extract_option_sets(before_text)
        c_opts = self._extract_option_sets(candidate_text)
        opt_changed = b_opts != c_opts
        if opt_changed:
            risk_flags.append("option_set_changed")
            reason_codes.append("STRUCTURE_OPT_SET_CHANGED")

        # Answer changes
        b_ans = self._extract_answers(before_text)
        c_ans = self._extract_answers(candidate_text)
        ans_changed = b_ans != c_ans
        if ans_changed:
            risk_flags.append("answer_changed")
            reason_codes.append("STRUCTURE_ANSWER_CHANGED")

        # Score
        score_before = 1.0
        score_after = 0.8 if risk_flags else 1.0
        accepted = len(risk_flags) == 0

        return QualityDecision(
            accepted=accepted,
            score_before=score_before,
            score_after=score_after,
            delta=score_after - score_before,
            risk_flags=risk_flags,
            reason_codes=reason_codes,
            metrics=metrics,
            gate_name=self.gate_name,
            gate_version=self.gate_version,
        )

    def _extract_text(self, doc: Any) -> str:
        if hasattr(doc, "text"):
            return doc.text
        if isinstance(doc, str):
            return doc
        return ""

    def _extract_qnumbers(self, text: str) -> list[int]:
        return [int(m.group(1)) for m in self._QN_PATTERN.finditer(text)]

    def _extract_option_sets(self, text: str) -> set[str]:
        return {m.group(1) for m in self._OPTION_KEY_PATTERN.finditer(text)}

    def _extract_answers(self, text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for m in self._ANSWER_PATTERN.finditer(text):
            result[str(len(result) + 1)] = m.group(1).strip()
        return result


# ---------------------------------------------------------------------------
# CodeQualityGate
# ---------------------------------------------------------------------------


class CodeQualityGate:
    """检查代码题中的标识符、操作符、括号平衡等是否被破坏。"""

    gate_name = "CodeQualityGate"
    gate_version = "1.0"

    _OPERATORS = {
        "arrow": re.compile(r"->"),
        "eq": re.compile(r"=="),
        "neq": re.compile(r"!="),
        "leq": re.compile(r"<="),
        "geq": re.compile(r">="),
        "inc": re.compile(r"\+\+"),
        "dec": re.compile(r"--"),
    }
    _BRACKET_PAIRS: list[tuple[str, str]] = [("(", ")"), ("[", "]"), ("{", "}")]

    def evaluate(
        self,
        before: Any,
        candidate: Any,
        context: QualityContext,
    ) -> QualityDecision:
        risk_flags: list[str] = []
        reason_codes: list[str] = []
        metrics: dict[str, float] = {}

        before_text = self._extract_text(before)
        candidate_text = self._extract_text(candidate)

        # Identifier retention
        b_ids = _tokenize_code(before_text)
        c_ids = _tokenize_code(candidate_text)
        id_retention = len(b_ids & c_ids) / max(len(b_ids), 1) if b_ids else 1.0
        metrics["identifier_retention"] = round(id_retention, 4)
        if id_retention < 0.8:
            risk_flags.append("identifier_changed")
            reason_codes.append("CODE_IDENTIFIER_MUTATION")

        # Operator retention
        op_scores: list[float] = []
        for name, pat in self._OPERATORS.items():
            b_count = len(pat.findall(before_text))
            c_count = len(pat.findall(candidate_text))
            if b_count > 0:
                op_scores.append(min(c_count / b_count, 1.0))
        op_retention = sum(op_scores) / max(len(op_scores), 1) if op_scores else 1.0
        metrics["operator_retention"] = round(op_retention, 4)
        if op_retention < 0.8:
            risk_flags.append("operator_loss")
            reason_codes.append("CODE_OPERATOR_LOSS")

        # Bracket balance
        bracket_scores: list[float] = []
        for open_b, close_b in self._BRACKET_PAIRS:
            b_open = before_text.count(open_b)
            b_close = before_text.count(close_b)
            c_open = candidate_text.count(open_b)
            c_close = candidate_text.count(close_b)
            b_balanced = b_open == b_close
            c_balanced = c_open == c_close
            if b_balanced and c_balanced:
                bracket_scores.append(1.0)
            elif (not b_balanced) and (not c_balanced):
                bracket_scores.append(1.0)
            else:
                bracket_scores.append(0.0)
        bracket_rate = sum(bracket_scores) / max(len(bracket_scores), 1)
        metrics["bracket_balance"] = round(bracket_rate, 4)
        if bracket_rate < 0.8:
            risk_flags.append("bracket_imbalance")
            reason_codes.append("CODE_BRACKET_IMBALANCE")

        score_after = min(1.0, id_retention * 0.4 + op_retention * 0.4 + bracket_rate * 0.2)
        accepted = score_after >= 0.7

        return QualityDecision(
            accepted=accepted,
            score_before=1.0,
            score_after=round(score_after, 4),
            delta=round(score_after - 1.0, 4),
            risk_flags=risk_flags,
            reason_codes=reason_codes,
            metrics=metrics,
            gate_name=self.gate_name,
            gate_version=self.gate_version,
        )

    def _extract_text(self, doc: Any) -> str:
        if hasattr(doc, "text"):
            return doc.text
        if isinstance(doc, str):
            return doc
        return ""


# ---------------------------------------------------------------------------
# PlainTextQualityGate
# ---------------------------------------------------------------------------


class PlainTextQualityGate:
    """检查纯文本修改是否异常（文本覆盖率、删除比例、字符比例变化）。"""

    gate_name = "PlainTextQualityGate"
    gate_version = "1.0"

    def evaluate(
        self,
        before: Any,
        candidate: Any,
        context: QualityContext,
    ) -> QualityDecision:
        risk_flags: list[str] = []
        reason_codes: list[str] = []
        metrics: dict[str, float] = {}

        before_text = self._extract_text(before)
        candidate_text = self._extract_text(candidate)

        if not before_text:
            return QualityDecision(
                accepted=True,
                score_before=1.0,
                score_after=1.0,
                gate_name=self.gate_name,
                gate_version=self.gate_version,
            )

        # Text coverage: fraction of before text preserved in candidate
        coverage = len(candidate_text) / max(len(before_text), 1)
        metrics["text_coverage"] = round(coverage, 4)
        if coverage < 0.5:
            risk_flags.append("text_drastically_shortened")
            reason_codes.append("TEXT_COVERAGE_TOO_LOW")

        # Deletion ratio
        deletions = max(0, len(before_text) - len(candidate_text))
        delete_rate = deletions / max(len(before_text), 1)
        metrics["deletion_rate"] = round(delete_rate, 4)
        if delete_rate > 0.5:
            risk_flags.append("high_deletion_rate")
            reason_codes.append("TEXT_HIGH_DELETION")

        # Character ratio change
        b_ratios = _char_ratio(before_text)
        c_ratios = _char_ratio(candidate_text)
        cn_delta = abs(b_ratios["chinese"] - c_ratios["chinese"])
        en_delta = abs(b_ratios["english"] - c_ratios["english"])
        metrics["cn_ratio_change"] = round(cn_delta, 4)
        metrics["en_ratio_change"] = round(en_delta, 4)
        if cn_delta > 0.3:
            risk_flags.append("chinese_ratio_anomaly")
            reason_codes.append("TEXT_CN_RATIO_CHANGE")
        if en_delta > 0.3:
            risk_flags.append("english_ratio_anomaly")
            reason_codes.append("TEXT_EN_RATIO_CHANGE")

        score_after = 0.0
        score_after += min(1.0, coverage) * 0.5
        score_after += (1.0 - delete_rate) * 0.3
        score_after += (1.0 - min(1.0, cn_delta + en_delta)) * 0.2
        accepted = score_after >= 0.6

        return QualityDecision(
            accepted=accepted,
            score_before=1.0,
            score_after=round(score_after, 4),
            delta=round(score_after - 1.0, 4),
            risk_flags=risk_flags,
            reason_codes=reason_codes,
            metrics=metrics,
            gate_name=self.gate_name,
            gate_version=self.gate_version,
        )

    def _extract_text(self, doc: Any) -> str:
        if hasattr(doc, "text"):
            return doc.text
        if isinstance(doc, str):
            return doc
        return ""


# ---------------------------------------------------------------------------
# Composite gate
# ---------------------------------------------------------------------------


class CompositeQualityGate:
    """Composite gate that runs multiple sub-gates and aggregates results."""

    def __init__(self, gates: list[Any] | None = None):
        self.gates = gates or [
            QuestionStructureQualityGate(),
            CodeQualityGate(),
            PlainTextQualityGate(),
        ]

    def evaluate(
        self,
        before: Any,
        candidate: Any,
        context: QualityContext,
    ) -> list[QualityDecision]:
        """Evaluate all sub-gates and return all decisions."""
        return [gate.evaluate(before, candidate, context) for gate in self.gates]
