"""Content Block 回归测试用例。

用例组织：
- positive: 应产生 code segment 的题目
- negative: 不应产生 code segment 的题目
- edge: 边界条件
- mixed: 代码 + 公式混排
- malformed: 异常围栏
"""


def _c(name, description, content_text, expected_segment_types, expected_code_count=0, expected_text="", has_render_mode=True):
    return {
        "name": name,
        "description": description,
        "content": {"text": content_text},
        "expected_segment_types": expected_segment_types,
        "expected_code_count": expected_code_count,
        "expected_text": expected_text,
        "has_render_mode": has_render_mode,
    }


# ============================================================
# 正向用例 — 应产生 code segment
# ============================================================

POSITIVE_CASES = [
    _c(
        "c_single_block",
        "单代码块 C 语言",
        "阅读以下代码：\n```c\nint main() {\n    return 0;\n}\n```\n请回答问题。",
        ["text", "newline", "code", "text"],
        expected_code_count=1,
        expected_text="c",
    ),
    _c(
        "java_class_block",
        "Java 类定义代码块",
        "分析程序：\n```java\npublic class ListNode {\n    int val;\n    ListNode next;\n}\n```",
        ["text", "newline", "code"],
        expected_code_count=1,
        expected_text="java",
    ),
    _c(
        "python_def_block",
        "Python 函数定义代码块",
        "```python\ndef binary_search(arr, target):\n    left = 0\n    right = len(arr) - 1\n    return -1\n```",
        ["code"],
        expected_code_count=1,
        expected_text="python",
    ),
    _c(
        "sql_select_block",
        "SQL 查询代码块",
        "```sql\nSELECT name, score\nFROM students\nWHERE score > 90;\n```",
        ["code"],
        expected_code_count=1,
        expected_text="sql",
    ),
    _c(
        "html_div_block",
        "HTML 代码块",
        "```html\n<div class=\"container\">\n    <p>Hello</p>\n</div>\n```",
        ["code"],
        expected_code_count=1,
        expected_text="html",
    ),
    _c(
        "no_language_fence",
        "无语言标签的围栏",
        "代码：\n```\nint x = 1;\nint y = 2;\n```\n结束",
        ["text", "newline", "code", "text"],
        expected_code_count=1,
        expected_text="text",  # 无语言 → "text"
    ),
    _c(
        "two_code_blocks",
        "两个代码块",
        "第一段：\n```c\nint a = 1;\n```\n第二段：\n```python\ndef foo():\n    pass\n```",
        ["text", "newline", "code", "text", "newline", "code"],
        expected_code_count=2,
    ),
    _c(
        "three_code_blocks",
        "三个代码块",
        "```c\na\n```\n```java\nb\n```\n```python\nc\n```",
        ["code", "code", "code"],
        expected_code_count=3,
    ),
]

# ============================================================
# 负向用例 — 不应产生 code segment
# ============================================================

NEGATIVE_CASES = [
    _c(
        "plain_math_question",
        "纯数学题（无代码）",
        "设函数 $f(x)=x^2+1$，则 $f'(x)=$（ ）。\nA. $2x$\nB. $x^2$",
        [],  # 无 segments（because "```" not in text）
        has_render_mode=False,
    ),
    _c(
        "plain_408_question",
        "纯 408 选择题（无代码）",
        "在 HTTP 协议中，状态码 404 表示（ ）。\nA. 服务器错误\nB. 未找到\nC. 重定向\nD. 成功",
        [],
        has_render_mode=False,
    ),
    _c(
        "inline_backticks_not_fence",
        "内联反引号（非围栏）",
        "使用 `malloc` 函数分配内存。",
        [],
        has_render_mode=False,
    ),
    _c(
        "unclosed_fence",
        "未闭合的围栏",
        "```c\nint x = 1;\n没有闭合标记",
        [],
        has_render_mode=False,
    ),
    _c(
        "empty_fence",
        "空围栏",
        "```\n```",
        ["code"],
        expected_code_count=1,  # 空代码块仍被识别为 code segment
        expected_text="text",
    ),
    _c(
        "fence_in_math_context",
        "数学上下文中的反引号",
        "设 $x = ```3$，求值。",
        [],  # 数学 $ 包裹的 ``` 不是围栏
        has_render_mode=False,
    ),
]

# ============================================================
# 边界用例
# ============================================================

EDGE_CASES = [
    _c(
        "fence_at_very_start",
        "围栏在文本最开头",
        "```c\nint x = 0;\n```\n后续文本。",
        ["code", "text"],
        expected_code_count=1,
    ),
    _c(
        "fence_at_very_end",
        "围栏在文本最末尾",
        "文本开头。\n```c\nreturn 0;\n```",
        ["text", "newline", "code"],
        expected_code_count=1,
    ),
    _c(
        "fence_with_trailing_whitespace",
        "围栏语言标签有尾随空格",
        "```c  \nint x = 1;\n```",
        ["code"],
        expected_code_count=1,
        expected_text="c  ",
    ),
    _c(
        "code_with_empty_lines",
        "代码块内含空行",
        "```python\ndef foo():\n\n    pass\n\n```",
        ["code"],
        expected_code_count=1,
    ),
    _c(
        "very_long_code_block",
        "长代码块（50+ 行）",
        "```c\n" + "\n".join(f"    line_{i}();" for i in range(60)) + "\n```",
        ["code"],
        expected_code_count=1,
    ),
    _c(
        "fence_with_special_chars",
        "围栏内含特殊字符",
        "```c\n// &lt;&gt;&amp;&quot;\nchar *s = \"hello\\nworld\";\n```",
        ["code"],
        expected_code_count=1,
    ),
    _c(
        "backtick_in_code_content",
        "代码内容含反引号",
        "```python\n# 使用 ` 作为特殊字符\nx = '`'\n```",
        ["code"],
        expected_code_count=1,
    ),
    _c(
        "content_before_after_fence_no_newline",
        "围栏前后无换行",
        "阅读```c\nint x;\n```理解",
        ["text", "code", "text"],
        expected_code_count=1,
    ),
    _c(
        "only_empty_text",
        "仅空文本",
        "",
        [],
        has_render_mode=False,
    ),
    _c(
        "none_content",
        "content 为 None",
        None,
        [],
        has_render_mode=False,
    ),
]

# ============================================================
# 混排用例 — 代码 + 公式
# ============================================================

MIXED_CASES = [
    _c(
        "code_then_math",
        "代码块后跟数学公式",
        "```c\nint x = 1;\n```\n已知 $x$ 的值为（ ）。",
        ["code", "text"],
        expected_code_count=1,
    ),
    _c(
        "math_then_code",
        "数学公式后跟代码块",
        "设 $f(x)=x^2$，程序实现：\n```python\ndef f(x):\n    return x * x\n```",
        ["text", "newline", "code"],
        expected_code_count=1,
    ),
    _c(
        "math_between_codes",
        "代码块之间夹数学公式",
        "```c\nint a;\n```\n公式 $E=mc^2$\n```java\nint b;\n```",
        ["code", "text", "code"],
        expected_code_count=2,
    ),
]

# ============================================================
# 异常围栏用例
# ============================================================

MALFORMED_CASES = [
    _c(
        "nested_fence_like",
        "类似嵌套围栏",
        "```c\n```\n嵌套？\n```\n```",
        ["code", "text", "code"],
        expected_code_count=2,
    ),
    _c(
        "fence_without_newline_after",
        "围栏标记后无换行",
        "```c int x = 1; ```",
        [],  # 不是有效围栏（开标签后无 \n）
        has_render_mode=False,
    ),
    _c(
        "four_backticks",
        "四个反引号",
        "````c\nint x = 1;\n````",
        ["code"],
        expected_code_count=1,
        expected_text="`c",  # regex 匹配到第一个 ` 作为语言
    ),
]

# ============================================================
# 聚合
# ============================================================

ALL_CASES = (
    [("positive", c) for c in POSITIVE_CASES]
    + [("negative", c) for c in NEGATIVE_CASES]
    + [("edge", c) for c in EDGE_CASES]
    + [("mixed", c) for c in MIXED_CASES]
    + [("malformed", c) for c in MALFORMED_CASES]
)

CASE_COUNTS = {
    "positive": len(POSITIVE_CASES),
    "negative": len(NEGATIVE_CASES),
    "edge": len(EDGE_CASES),
    "mixed": len(MIXED_CASES),
    "malformed": len(MALFORMED_CASES),
    "total": len(ALL_CASES),
}
