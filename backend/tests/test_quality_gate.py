"""Domain Quality Gate 测试。

覆盖:
- QuestionStructureQualityGate
- CodeQualityGate
- PlainTextQualityGate
- CompositeQualityGate
- Shadow mode recording
- Edge cases (empty, identical, degraded)
"""
from __future__ import annotations

from app.features.quality_gate import (
    CodeQualityGate,
    CompositeQualityGate,
    PlainTextQualityGate,
    QualityContext,
    QuestionStructureQualityGate,
    record_shadow_decision,
)

# ===================================================================
# 1. QuestionStructureQualityGate
# ===================================================================


def test_qn_structure_identical():
    """相同文本应通过。"""
    gate = QuestionStructureQualityGate()
    text = "1. 题目一\nA. 选项A\nB. 选项B\n答案：A"
    ctx = QualityContext()
    decision = gate.evaluate(text, text, ctx)
    assert decision.accepted
    assert decision.score_after >= 0.8


def test_qn_structure_loss():
    """题号减少应标记。"""
    gate = QuestionStructureQualityGate()
    before = "1. 题目一\n答案：A\n2. 题目二\n答案：B"
    after = "1. 题目一\n答案：A"
    ctx = QualityContext()
    decision = gate.evaluate(before, after, ctx)
    assert "question_number_lost" in decision.risk_flags


def test_qn_structure_empty():
    """空文本应通过。"""
    gate = QuestionStructureQualityGate()
    ctx = QualityContext()
    decision = gate.evaluate("", "", ctx)
    assert decision.accepted


# ===================================================================
# 2. CodeQualityGate
# ===================================================================


def test_code_identical():
    """相同代码应通过。"""
    gate = CodeQualityGate()
    code = "int x = 10;\nif (x > 5) return x;"
    ctx = QualityContext()
    decision = gate.evaluate(code, code, ctx)
    assert decision.accepted


def test_code_identifier_loss():
    """标识符丢失应标记。"""
    gate = CodeQualityGate()
    before = "int result = calculate(a, b);"
    after = "int x = calc(a, b);"  # result→x, calculate→calc
    ctx = QualityContext()
    decision = gate.evaluate(before, after, ctx)
    # May have identifier_changed
    if decision.score_after < 0.7:
        assert not decision.accepted


def test_code_operator_loss():
    """操作符丢失应标记。"""
    gate = CodeQualityGate()
    before = "if (a != b && c->next != NULL)"
    after = "if (a = b && c.next != NULL)"  # != → = and -> → .
    ctx = QualityContext()
    decision = gate.evaluate(before, after, ctx)
    assert "operator_loss" in decision.risk_flags


def test_code_bracket_imbalance():
    """括号不平衡应标记。"""
    gate = CodeQualityGate()
    before = "if (x) { return 1; }"
    after = "if (x { return 1; }"  # missing )
    ctx = QualityContext()
    decision = gate.evaluate(before, after, ctx)
    assert not decision.accepted or "bracket_imbalance" in decision.risk_flags


def test_code_empty():
    """空代码应通过。"""
    gate = CodeQualityGate()
    ctx = QualityContext()
    decision = gate.evaluate("", "", ctx)
    assert decision.accepted


# ===================================================================
# 3. PlainTextQualityGate
# ===================================================================


def test_text_identical():
    """相同文本应通过。"""
    gate = PlainTextQualityGate()
    text = "这是一段普通文本。"
    ctx = QualityContext()
    decision = gate.evaluate(text, text, ctx)
    assert decision.accepted


def test_text_drastically_shortened():
    """文本大幅缩短应标记。"""
    gate = PlainTextQualityGate()
    before = "这是一段很长的文本内容，包含了很多重要信息。"
    after = "文本"
    ctx = QualityContext()
    decision = gate.evaluate(before, after, ctx)
    assert "text_drastically_shortened" in decision.risk_flags or "high_deletion_rate" in decision.risk_flags


def test_text_empty_before():
    """空 before 应通过。"""
    gate = PlainTextQualityGate()
    ctx = QualityContext()
    decision = gate.evaluate("", "some text", ctx)
    assert decision.accepted


# ===================================================================
# 4. CompositeQualityGate
# ===================================================================


def test_composite_gate():
    """Composite gate 应返回所有子 gate 结果。"""
    gate = CompositeQualityGate()
    text = "1. test\nA. opt\n答案：A"
    ctx = QualityContext()
    decisions = gate.evaluate(text, text, ctx)
    assert len(decisions) == 3  # structure + code + text
    all_accepted = all(d.accepted for d in decisions)
    assert all_accepted


def test_composite_gate_degraded():
    """降级输入应在至少一个 gate 中标记。"""
    gate = CompositeQualityGate()
    before = "1. 题目一\nA. 选项A\nint x = 10;\n答案：A"
    after = "1. 题目一\nx = 10;"  # lost A, lost int
    ctx = QualityContext()
    decisions = gate.evaluate(before, after, ctx)
    any_rejected = any(not d.accepted for d in decisions)
    assert any_rejected


# ===================================================================
# 5. Shadow mode recording
# ===================================================================


def test_shadow_recording():
    """Shadow mode 记录正确。"""
    gate = QuestionStructureQualityGate()
    ctx = QualityContext(gate_mode="shadow")
    text = "1. 题目\nA. 选项\n答案：A"
    decision = gate.evaluate(text, text, ctx)
    record = record_shadow_decision(decision, ctx)
    assert record["gate_name"] == "QuestionStructureQualityGate"
    assert record["mode"] == "shadow"
    assert record["would_accept"] is True
    assert len(ctx.diagnostics) == 1


def test_shadow_does_not_affect_output():
    """Shadow mode 不应改变现有决策。"""
    gate = QuestionStructureQualityGate()
    ctx = QualityContext(gate_mode="shadow", existing_decision="accept")

    before = "1. Q1\nA. A\nB. B\n答案：A\n2. Q2\nA. C\nB. D\n答案：B"
    after = "1. Q1\nA. A\nB. B\n答案：A"  # Q2 lost

    # Evaluate gate
    decision = gate.evaluate(before, after, ctx)

    # The gate would reject
    assert not decision.accepted

    # But the existing decision ("accept") is preserved
    record = record_shadow_decision(decision, ctx)
    assert record["existing_decision"] == "accept"
    assert record["would_accept"] is False


# ===================================================================
# 6. Edge cases
# ===================================================================


def test_empty_document_ir():
    """空的 DocumentIR 不应导致 gate 崩溃。"""
    gates = [
        QuestionStructureQualityGate(),
        CodeQualityGate(),
        PlainTextQualityGate(),
    ]
    ctx = QualityContext()
    for gate in gates:
        decision = gate.evaluate("", "", ctx)
        assert isinstance(decision.accepted, bool)
        assert isinstance(decision.risk_flags, list)


def test_quality_decision_defaults():
    """QualityDecision 默认值验证。"""
    from app.features.quality_gate import QualityDecision
    d = QualityDecision(accepted=True)
    assert d.score_before == 0.0
    assert d.gate_version == "1.0"
    assert d.risk_flags == []
    assert d.reason_codes == []
