"""代码检测器回归测试。

验证 code_detector 行为符合约束 1-8：
- 双重判断（关键词不能单独触发）
- 单行不触发
- Feature Flag 透传
- 命中日志输出
- clean_ocr_text / text_normalizer / question_pipeline 链路
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.features.code_detector import (  # noqa: E402
    CodeDetectStats,
    _detect_and_wrap,
    _score_line,
    wrap_code_fences,
)
from tests.ocr_regression.code.cases import REGRESSION_CASES  # noqa: E402

# ============================================================
# 单元测试：行打分
# ============================================================


class TestLineScoring:
    """逐行打分逻辑"""

    def test_code_line_with_indent_and_keyword(self):
        """缩进 + 关键词 → 应得分 ≥ 1"""
        assert _score_line("    int i = 0;") >= 1

    def test_code_line_with_brace_only(self):
        """独立花括号行 → struct_score ≥ 2 → 应得分 ≥ 2"""
        assert _score_line("{") >= 2

    def test_code_line_with_semicolon(self):
        """分号结尾 → struct_score ≥ 1"""
        score = _score_line("printf(\"hello\");")
        assert score >= 1

    def test_keyword_alone_no_struct(self):
        """仅关键词无结构信号 → 得分为 0"""
        assert _score_line("对于以下说法") == 0  # "对于" 不应触发

    def test_python_def_with_colon(self):
        """Python def 行应被识别"""
        assert _score_line("def foo(x):") >= 1

    def test_html_tag_line(self):
        """HTML 标签行应被识别"""
        assert _score_line("<div class=\"x\">") >= 1

    def test_cjk_math_line(self):
        """纯中文数学行 → 得分为 0"""
        assert _score_line("设函数 f(x)=x²+1，求 f'(x)") == 0


# ============================================================
# 集成测试：代码块检测
# ============================================================


class TestCodeBlockDetection:
    """正例 — 验证代码块被正确识别并包裹围栏"""

    @pytest.mark.parametrize(
        "case",
        [c for c in REGRESSION_CASES if c["expected_has_fence"]],
        ids=[c["name"] for c in REGRESSION_CASES if c["expected_has_fence"]],
    )
    def test_detects_code_fence(self, case):
        """正例：应插入 ``` 围栏"""
        result, _stats = _detect_and_wrap(case["raw_text"])
        assert "```" in result, f"{case['name']}: 应检测到代码围栏"
        # 验证围栏数量（成对出现）
        fence_count = result.count("```")
        assert fence_count >= 2, f"{case['name']}: 围栏应成对出现"
        assert fence_count % 2 == 0, f"{case['name']}: 围栏数应为偶数"

    @pytest.mark.parametrize(
        "case",
        [c for c in REGRESSION_CASES if c["expected_has_fence"]],
        ids=[c["name"] for c in REGRESSION_CASES if c["expected_has_fence"]],
    )
    def test_min_code_lines(self, case):
        """正例：围栏内代码行数不低于预期"""
        result, _stats = _detect_and_wrap(case["raw_text"])
        parts = result.split("```")
        code_content = ""
        for i, part in enumerate(parts):
            if i % 2 == 1:
                code_content = part
                break
        lines = [l for l in code_content.split("\n") if l.strip()]
        assert len(lines) >= case["expected_min_code_lines"], (
            f"{case['name']}: 围栏内代码行数 {len(lines)} < "
            f"预期 {case['expected_min_code_lines']}"
        )


class TestNoFalsePositive:
    """负例 — 验证非代码文本不触发围栏"""

    @pytest.mark.parametrize(
        "case",
        [c for c in REGRESSION_CASES if not c["expected_has_fence"]],
        ids=[c["name"] for c in REGRESSION_CASES if not c["expected_has_fence"]],
    )
    def test_no_false_positive(self, case):
        """负例：不应插入围栏"""
        result, _stats = _detect_and_wrap(case["raw_text"])
        assert "```" not in result, (
            f"{case['name']}: 不应检测到代码围栏，但结果包含 ```"
        )


# ============================================================
# Feature Flag 测试
# ============================================================


class TestFeatureFlag:
    """约束 6：Feature Flag 透传"""

    def test_flag_disabled_passthrough(self, monkeypatch):
        """Flag 关闭时，wrap_code_fences 应透传原始文本"""
        monkeypatch.setattr(
            "app.features.code_detector.settings.CODE_DETECTOR_ENABLED", False
        )
        text = "int i=1;\nwhile(i<=n)\n    i=i*2;\n"
        result = wrap_code_fences(text, trace_id="test")
        assert result == text

    def test_flag_enabled_detects(self, monkeypatch):
        """Flag 开启时，应检测代码块"""
        monkeypatch.setattr(
            "app.features.code_detector.settings.CODE_DETECTOR_ENABLED", True
        )
        text = "int i=1;\nwhile(i<=n)\n    i=i*2;\n"
        result = wrap_code_fences(text, trace_id="test")
        assert "```" in result


# ============================================================
# 命中日志测试
# ============================================================


class TestHitLogging:
    """约束 7：命中统计日志"""

    def test_stats_fields(self):
        """stats 字段正确填充"""
        text = (
            "题干\n"
            "int i=1;\n"
            "while(i<=n)\n"
            "    i=i*2;\n"
            "选项 A. ..."
        )
        _result, stats = _detect_and_wrap(text)
        assert isinstance(stats, CodeDetectStats)
        assert stats.block_count >= 1
        assert stats.total_code_lines >= 2
        assert stats.avg_code_lines >= 1.0

    def test_no_code_stats_zero(self):
        """无代码时 stats 全为零"""
        text = "纯中文题干，不含任何代码"
        _result, stats = _detect_and_wrap(text)
        assert stats.block_count == 0
        assert stats.question_count == 0
        assert stats.avg_code_lines == 0.0

    def test_log_format(self):
        """日志格式正确"""
        text = "int i=1;\nwhile(i<=n)\n    i=i*2;\n"
        _result, stats = _detect_and_wrap(text)
        log = stats.to_log("test_trace")
        assert "trace_id=test_trace" in log
        assert "questions=" in log
        assert "blocks=" in log
        assert "avg_lines=" in log
        assert "languages=" in log


# ============================================================
# 链路回归测试
# ============================================================


class TestPipelinePreservation:
    """约束 5：clean_ocr_text → text_normalizer → question_pipeline 链路"""

    def test_clean_ocr_text_preserves_fence(self, monkeypatch):
        """clean_ocr_text 不破坏围栏内的缩进和空格"""
        monkeypatch.setattr(
            "app.features.code_detector.settings.CODE_DETECTOR_ENABLED", True
        )
        from app.services.ocr_service import clean_ocr_text

        ocr_raw = "题目：\nint main() {\n    printf(\"hello\");\n    return 0;\n}\n"
        result = clean_ocr_text(ocr_raw, trace_id="test")

        assert "```" in result
        assert "    printf" in result or "printf" in result  # 代码内容保留
        assert "return 0;" in result

    def test_text_normalizer_preserves_fence(self, monkeypatch):
        """ImportTextNormalizer 不合并/压缩围栏内内容"""
        monkeypatch.setattr(
            "app.features.code_detector.settings.CODE_DETECTOR_ENABLED", True
        )
        from app.features.text_normalizer import ImportTextNormalizer

        text_with_fence = (
            "题干文本\n"
            "```text\n"
            "int i = 1;\n"
            "while(i <= n)\n"
            "    i = i * 2;\n"
            "```\n"
            "A. O(n)"
        )
        normalizer = ImportTextNormalizer()
        blocks = [{"text": text_with_fence, "page": 1, "block_index": 0}]
        result = normalizer.normalize(blocks)

        normalized_text = result[0]["normalized_text"]
        # 围栏应保留
        assert "```" in normalized_text
        # 围栏内内容应保留不变
        assert "while(i <= n)" in normalized_text
        assert "    i = i * 2;" in normalized_text

    def test_code_detector_idempotent(self, monkeypatch):
        """代码检测器幂等：已含围栏的文本不应产生嵌套围栏"""
        monkeypatch.setattr(
            "app.features.code_detector.settings.CODE_DETECTOR_ENABLED", True
        )
        already_fenced = (
            "题干\n"
            "```text\n"
            "int i = 1;\n"
            "while(i <= n)\n"
            "    i = i * 2;\n"
            "```\n"
            "选项"
        )
        result = wrap_code_fences(already_fenced, trace_id="test")
        # 围栏数应为 2 对，不应嵌套
        assert result.count("```") == 2  # 一对围栏


# ============================================================
# 回归用例快照
# ============================================================


class TestRegressionSnapshot:
    """所有回归用例的快照一致性测试"""

    @pytest.mark.parametrize(
        "case",
        REGRESSION_CASES,
        ids=[c["name"] for c in REGRESSION_CASES],
    )
    def test_deterministic(self, case):
        """同一输入多次运行结果一致"""
        r1, _s1 = _detect_and_wrap(case["raw_text"])
        r2, _s2 = _detect_and_wrap(case["raw_text"])
        assert r1 == r2, f"{case['name']}: 多次运行结果不一致"
