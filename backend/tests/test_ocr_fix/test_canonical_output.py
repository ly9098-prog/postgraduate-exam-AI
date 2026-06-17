"""Canonical Output Layer 单元测试。

覆盖所有输出类型：
- 纯文本
- Markdown 代码块
- JSON（各类键名结构）
- JSON 代码块
- 混合格式
- 空内容
- 异常边界
"""

from __future__ import annotations

from app.features.ocr_fix.canonical_output import (
    OUTPUT_EMPTY,
    OUTPUT_JSON,
    OUTPUT_JSON_CODEBLOCK,
    OUTPUT_MARKDOWN,
    OUTPUT_PLAIN,
    canonicalize,
)


class TestCanonicalizePlainText:
    """纯文本直通测试。"""

    def test_simple_text(self):
        text = "这是一道数学题。\nA. 选项一\nB. 选项二\n答案：A"
        result, meta = canonicalize(text)
        assert result == text
        assert meta["output_type"] == OUTPUT_PLAIN
        assert meta["strategy"] == "passthrough"
        assert meta["before_length"] == meta["after_length"]

    def test_text_with_latex(self):
        text = "设 $f(x) = x^2 + 1$，求 $f\'(x)$。\nA. $2x$\nB. $x$"
        result, meta = canonicalize(text)
        assert result == text
        assert meta["output_type"] == OUTPUT_PLAIN

    def test_text_with_newlines(self):
        text = "第 1 题\n\n设 $f(x)$ 连续\n\nA. 选项\nB. 选项"
        result, meta = canonicalize(text)
        assert result == text
        assert meta["output_type"] == OUTPUT_PLAIN


class TestCanonicalizeMarkdown:
    """Markdown 代码块剥离测试。"""

    def test_markdown_code_block(self):
        text = "```\n这是一道数学题。\nA. 选项一\nB. 选项二\n答案：A\n```"
        expected = "这是一道数学题。\nA. 选项一\nB. 选项二\n答案：A"
        result, meta = canonicalize(text)
        assert result == expected
        assert meta["output_type"] == OUTPUT_MARKDOWN
        assert meta["strategy"] == "unmark"

    def test_markdown_with_language(self):
        text = "```text\nHello World\n```"
        result, meta = canonicalize(text)
        assert result == "Hello World"
        assert meta["output_type"] == OUTPUT_MARKDOWN


class TestCanonicalizeJson:
    """JSON 转文本测试。"""

    def test_json_corrected_text_key(self):
        text = '{"corrected_text": "这是一道数学题。\\nA. 选项一\\nB. 选项二\\n答案：A"}'
        expected = "这是一道数学题。\nA. 选项一\nB. 选项二\n答案：A"
        result, meta = canonicalize(text)
        assert result == expected
        assert meta["output_type"] == OUTPUT_JSON
        assert meta["strategy"] == "json_to_text"

    def test_json_text_key(self):
        text = '{"text": "设 $f(x)$ 在 $[0,1]$ 连续"}'
        result, meta = canonicalize(text)
        assert result == "设 $f(x)$ 在 $[0,1]$ 连续"
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_content_key(self):
        text = '{"content": "微分中值定理"}'
        result, meta = canonicalize(text)
        assert result == "微分中值定理"
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_option_array(self):
        text = '{"option": [{"text": "A. 可微"}, {"text": "B. 可导"}, {"text": "C. 连续"}]}'
        expected = "A. 可微\nB. 可导\nC. 连续"
        result, meta = canonicalize(text)
        assert result == expected
        assert meta["output_type"] == OUTPUT_JSON
        assert meta["strategy"] == "json_to_text"

    def test_json_options_array(self):
        text = '{"options": [{"text": "A. 收敛"}, {"text": "B. 发散"}]}'
        result, meta = canonicalize(text)
        assert result == "A. 收敛\nB. 发散"
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_choices_array(self):
        text = '{"choices": [{"text": "A. 正确"}, {"text": "B. 错误"}]}'
        result, meta = canonicalize(text)
        assert result == "A. 正确\nB. 错误"
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_option_array_string_items(self):
        text = '{"option": ["A. 选项一", "B. 选项二", "C. 选项三"]}'
        expected = "A. 选项一\nB. 选项二\nC. 选项三"
        result, meta = canonicalize(text)
        assert result == expected
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_list_format(self):
        text = '[{"text": "A. 可微"}, {"text": "B. 可导"}]'
        result, meta = canonicalize(text)
        assert result == "A. 可微\nB. 可导"
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_fallback_unknown_keys(self):
        text = '{"result": "最终答案：D", "explanation": "根据拉格朗日中值定理"}'
        result, meta = canonicalize(text)
        assert "最终答案：D" in result
        assert "根据拉格朗日中值定理" in result
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_short_value_not_extracted(self):
        """短字符串（<=10）不应在兜底匹配中被提取。"""
        text = '{"a": "x", "b": "y"}'
        result, meta = canonicalize(text)
        # 短字符串不满足 len > 10 或 len > 5 的条件
        # 但 _json_to_text_with_fallback 会返回原始 JSON 文本
        assert result == text
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_fixed_text_key(self):
        text = '{"fixed_text": "设 $F(x)=\\\\int_0^x f(t)dt$"}'
        result, meta = canonicalize(text)
        assert "$F(x)=\\int_0^x f(t)dt$" in result
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_corrected_key(self):
        text = '{"corrected": "极限 $\\\\lim_{x \\\\to 0} \\\\frac{\\\\sin x}{x} = 1$"}'
        result, meta = canonicalize(text)
        assert "lim" in result or "\\\\lim" in result or "sin" in result
        assert meta["output_type"] == OUTPUT_JSON

    def test_json_output_key(self):
        text = '{"output": "答案：C\\n解析：根据题意"}'
        result, meta = canonicalize(text)
        assert result == "答案：C\n解析：根据题意"
        assert meta["output_type"] == OUTPUT_JSON


class TestCanonicalizeJsonCodeBlock:
    """JSON 代码块测试。"""

    def test_json_code_block(self):
        text = '```json\n{"corrected_text": "设 $f(x)=x^2$\\nA. 连续\\nB. 可导\\n答案：B"}\n```'
        expected = "设 $f(x)=x^2$\nA. 连续\nB. 可导\n答案：B"
        result, meta = canonicalize(text)
        assert result == expected
        assert meta["output_type"] == OUTPUT_JSON_CODEBLOCK
        assert meta["strategy"] == "json_codeblock_to_text"

    def test_json_code_block_with_option_array(self):
        text = '```json\n{"option": [{"text": "A. 可微"}, {"text": "B. 可导"}]}\n```'
        result, meta = canonicalize(text)
        assert result == "A. 可微\nB. 可导"
        assert meta["output_type"] == OUTPUT_JSON_CODEBLOCK

    def test_json_code_block_unparseable(self):
        """JSON 代码块内内容解析失败时返回原始 JSON 字符串。"""
        text = '```json\n{"broken: unclosed\n```'
        result, meta = canonicalize(text)
        assert result == '{"broken: unclosed'
        assert meta["output_type"] == OUTPUT_JSON_CODEBLOCK


class TestCanonicalizeEmpty:
    """空内容测试。"""

    def test_empty_string(self):
        result, meta = canonicalize("")
        assert result == ""
        assert meta["output_type"] == OUTPUT_EMPTY
        assert meta["strategy"] == "empty"

    def test_whitespace_only(self):
        result, meta = canonicalize("   \n  \t  ")
        assert result == ""
        assert meta["output_type"] == OUTPUT_EMPTY

    def test_only_newlines(self):
        result, meta = canonicalize("\n\n\n")
        assert result == ""
        assert meta["output_type"] == OUTPUT_EMPTY


class TestCanonicalizeModelName:
    """model_name 参数测试。"""

    def test_model_name_in_metadata(self):
        _, meta = canonicalize("hello", model_name="qwen-vl-max")
        assert meta["model_name"] == "qwen-vl-max"

    def test_model_name_none(self):
        _, meta = canonicalize("hello")
        assert meta["model_name"] is None

    def test_model_name_logged(self):
        """验证 model_name 出现在日志中（间接验证）。"""
        result, meta = canonicalize("plain text", model_name="deepseek-chat")
        assert meta["model_name"] == "deepseek-chat"


class TestCanonicalizeLengthTracking:
    """长度追踪测试。"""

    def test_length_passthrough(self):
        _, meta = canonicalize("Hello World")
        assert meta["before_length"] == 11
        assert meta["after_length"] == 11

    def test_length_json_extraction(self):
        text = '{"corrected_text": "Hello World"}'
        _, meta = canonicalize(text)
        assert meta["before_length"] == len(text)
        assert meta["after_length"] == 11  # "Hello World"
        assert meta["before_length"] > meta["after_length"]

    def test_length_markdown_strip(self):
        text = "```\nHello\n```"
        _, meta = canonicalize(text)
        assert meta["before_length"] == len(text)
        assert meta["after_length"] == 5  # "Hello"
