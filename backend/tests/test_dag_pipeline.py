"""测试 DAG overlay pipeline。"""

from unittest.mock import patch

import pytest

from app.core.dag_pipeline import DAGPipeline, IOType, StageNode
from app.core.immutable_regions import Region, TextRegions
from app.core.mutation_guard import MutationError
from app.features.ocr_pipeline_dag import build_ocr_dag, run_ocr_dag
from app.features.text_normalizer import normalize_ocr_text

# ================================================================
# DAG 基础设施
# ================================================================

class TestStageNode:
    def test_create(self):
        node = StageNode(name="test", fn=lambda x: x)
        assert node.name == "test"
        assert node.input_type == IOType.STR
        assert node.output_type == IOType.STR
        assert node.guard is False

    def test_with_description(self):
        node = StageNode(
            name="test", fn=lambda x: x,
            description="noise filter before code detection",
        )
        assert node.description == "noise filter before code detection"


class TestDAGPipeline:
    def test_empty_stages_raises(self):
        with pytest.raises(AssertionError):
            DAGPipeline([])

    def test_single_stage(self):
        dag = DAGPipeline([
            StageNode(name="identity", fn=lambda x: x),
        ])
        assert dag.run("hello") == "hello"

    def test_two_stages(self):
        dag = DAGPipeline([
            StageNode(name="upper", fn=lambda x: x.upper()),
            StageNode(name="exclaim", fn=lambda x: x + "!"),
        ])
        assert dag.run("hello") == "HELLO!"

    def test_empty_text(self):
        dag = DAGPipeline([
            StageNode(name="identity", fn=lambda x: x),
        ])
        assert dag.run("") == ""

    def test_stages_property(self):
        dag = DAGPipeline([StageNode(name="a", fn=lambda x: x)])
        stages = dag.stages
        assert len(stages) == 1
        assert stages[0].name == "a"

    def test_str_to_text_regions_conversion(self):
        """IOType.TEXT_REGIONS 自动转换 str → TextRegions。"""
        def echo_lower(regions: TextRegions) -> TextRegions:
            return TextRegions([
                Region.create(r.id, r.type, r.content.lower())
                for r in regions
            ])

        dag = DAGPipeline([
            StageNode(
                name="lowercase",
                fn=echo_lower,
                input_type=IOType.TEXT_REGIONS,
                output_type=IOType.TEXT_REGIONS,
            ),
        ])
        result = dag.run("HELLO\n```text\nCODE\n```\nWORLD")
        assert isinstance(result, str)
        assert "hello" in result
        assert "code" in result

    def test_text_regions_to_str_conversion(self):
        """IOType.STR 自动转换 TextRegions → str。"""
        def make_upper(regions):
            return regions.to_text().upper()

        dag = DAGPipeline([
            StageNode(
                name="upper",
                fn=make_upper,
                input_type=IOType.TEXT_REGIONS,
                output_type=IOType.STR,
            ),
        ])
        result = dag.run("hello\n```text\ncode\n```")
        assert "HELLO" in result
        assert "CODE" in result


# ================================================================
# OCR DAG 等价性测试
# ================================================================

class TestOCRDAGEquivalence:
    """DAG overlay 输出必须与 normalize_ocr_text() 完全一致。"""

    @pytest.mark.parametrize("text", [
        "",
        "hello world",
        "这是一段中文文本。",
        "int a = 1;\nint b = 2;",
        "```text\nint a;\n```",
        "before\n```python\ndef f():\n    pass\n```\nafter",
        "A. 选项一\nB. 选项二\nC. 选项三\nD. 选项四",
    ])
    def test_basic_equivalence(self, text):
        expected = normalize_ocr_text(text, trace_id="test")
        result = run_ocr_dag(text, trace_id="test")
        assert result == expected, (
            f"DAG mismatch for {text[:50]!r}\n"
            f"  expected={expected[:100]!r}\n"
            f"  actual=  {result[:100]!r}"
        )

    @pytest.mark.parametrize("text", [
        "p->next = q->prior",
        "p − >next  # broken arrow",
        "int *p = (int*)malloc(sizeof(int));",
        "void push(SqStack &S, int x) {\n  if (S.top != -1) {\n    S.data[++S.top] = x;\n  }\n}",
    ])
    def test_code_equivalence(self, text):
        expected = normalize_ocr_text(text, trace_id="test")
        result = run_ocr_dag(text, trace_id="test")
        assert result == expected

    def test_strategy_subset(self):
        """部分策略启用时 DAG 与 normalize_ocr_text 一致。"""
        text = "void f() { return; }\nA. 选项一  hello\nB. 选项二  world"
        strategies = {"space_newline", "digit_letter"}
        expected = normalize_ocr_text(
            text, trace_id="test", enabled_strategies=strategies,
        )
        result = run_ocr_dag(text, trace_id="test", enabled_strategies=strategies)
        assert result == expected

    def test_empty_strategies(self):
        """所有策略关闭时仍然一致。"""
        text = "void f() { return; }\nA. 选项一\nB. 选项二"
        expected = normalize_ocr_text(text, trace_id="test", enabled_strategies=set())
        result = run_ocr_dag(text, trace_id="test", enabled_strategies=set())
        assert result == expected


# ================================================================
# mutation_guard in DAG 上下文
# ================================================================

class TestDAGMutationGuard:
    def test_guard_detects_mutation_in_str_input(self):
        """P2 stage 的 guard 必须在 str→str 场景下检测 code 篡改。"""
        def mutate_code(text: str) -> str:
            # 直接修改 fenced code block 内部内容
            return text.replace("int a;", "int b;")

        dag = DAGPipeline(stages=[
            StageNode(name="bad_stage", fn=mutate_code, guard=True),
        ])
        with pytest.raises(MutationError, match="Code region mutation"):
            dag.run("```text\nint a;\n```", trace_id="test")

    def test_guard_passes_clean_stage(self):
        """未篡改 code 的 stage 不应抛 MutationError。"""
        def clean_stage(text: str) -> str:
            # 只修改非 code 内容
            return text.replace("world", "earth")

        dag = DAGPipeline(stages=[
            StageNode(name="clean", fn=clean_stage, guard=True),
        ])
        result = dag.run("hello world\n```text\nint a;\n```", trace_id="test")
        assert "hello earth" in result
        assert "int a;" in result

    def test_multi_stage_guard(self):
        """多个 stage 都启用 guard 时工作正常。"""
        dag = DAGPipeline(stages=[
            StageNode(name="s1", fn=lambda x: x, guard=True),
            StageNode(name="s2", fn=lambda x: x, guard=True),
            StageNode(name="s3", fn=lambda x: x, guard=True),
        ])
        result = dag.run("before\n```python\ndef f():\n    pass\n```\nafter")
        assert result is not None

    def test_guard_with_no_code(self):
        """无 code 区域时 guard 应为空操作。"""
        dag = DAGPipeline(stages=[
            StageNode(name="noop", fn=lambda x: x.upper(), guard=True),
        ])
        result = dag.run("hello world")
        assert result == "HELLO WORLD"


class TestDAGBuildIntegration:
    def test_build_and_run(self):
        dag = build_ocr_dag()
        result = dag.run("hello world", trace_id="test")
        assert isinstance(result, str)

    def test_build_with_strategies(self):
        dag = build_ocr_dag(enabled_strategies={"space_newline"})
        result = dag.run("A. option\nB. option", trace_id="test")
        assert isinstance(result, str)

    def test_multiple_runs_same_dag(self):
        dag = build_ocr_dag()
        r1 = dag.run("hello world", trace_id="test")
        r2 = dag.run("int a = 1;\nint b = 2;", trace_id="test")
        assert isinstance(r1, str)
        assert isinstance(r2, str)


# ================================================================
# 回归测试
# ================================================================

class TestDAGRegression:
    """从现有回归套件中选取的关键 case。"""

    def test_fenced_code_preserved(self):
        text = "before\n```tex\n$\\alpha + \\beta$\n```\nafter"
        expected = normalize_ocr_text(text, trace_id="test")
        result = run_ocr_dag(text, trace_id="test")
        assert result == expected

    def test_isolated_c_before_code(self):
        text = "C\n\nvoid push(SqStack &S, int x) {\n  if (S.top != -1) {\n    S.data[++S.top] = x;\n  }\n}"
        expected = normalize_ocr_text(text, trace_id="test")
        result = run_ocr_dag(text, trace_id="test")
        assert result == expected


# ================================================================
# 負面测试
# ================================================================

class TestDAGNegative:
    """边界和异常场景。"""

    def test_disabled_code_detection(self):
        """CODE_DETECTOR_ENABLED=false 时 DAG 仍正常工作。"""
        with patch("app.core.config.settings.CODE_DETECTOR_ENABLED", False):
            text = "int a = 1;\nint b = 2;"
            result = run_ocr_dag(text, trace_id="test")
            # code 不会被 fence 保护，但管线不崩溃
            assert isinstance(result, str)

    def test_stage_exception_propagates(self):
        """stage 内异常应向外传播。"""
        def broken(_):
            raise ValueError("stage crashed")

        dag = DAGPipeline(stages=[
            StageNode(name="broken", fn=broken),
        ])
        with pytest.raises(ValueError, match="stage crashed"):
            dag.run("hello")

    def test_guarded_stage_exception_propagates(self):
        """guard 包裹的 stage 抛出异常时也正常传播。"""
        def broken(_):
            raise RuntimeError("guarded crash")

        dag = DAGPipeline(stages=[
            StageNode(name="bad", fn=broken, guard=True),
        ])
        with pytest.raises(RuntimeError, match="guarded crash"):
            dag.run("hello\n```text\nint a;\n```")

    def test_empty_input_returns_empty(self):
        assert run_ocr_dag("", trace_id="test") == ""

    def test_dag_re_run_isolation(self):
        """同一个 DAG 实例多次 run() 不应互相影响。"""
        dag = build_ocr_dag()
        r1 = dag.run("int a = 1;", trace_id="test")
        r2 = dag.run("hello world", trace_id="test")
        r3 = dag.run("int a = 1;", trace_id="test")
        # 相同输入得到相同输出
        assert r1 == r3
        # 不同输入得到不同输出
        assert r1 != r2
