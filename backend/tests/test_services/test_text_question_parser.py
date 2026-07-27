"""测试文本题目解析器 — text_question_parser.py"""

from __future__ import annotations

import pytest

from app.features.text_question_parser import (
    _normalize_text,
    _split_batch,
    parse_text_questions,
)


class TestNormalizeText:
    """文本预处理测试。"""

    def test_chinese_number_title_replaced_with_separator(self):
        """第X题 独立标题行应被替换为分隔标记，而非直接删除。"""
        text = "第一题\n\n题干内容\n\nA. 选项1\nB. 选项2\n\n答案: A"
        result = _normalize_text(text)
        assert "===" in result, "第X题应被替换为 === 分隔符"
        assert "第一题" not in result, "第X题原文应被替换"

    def test_multi_chinese_number_titles_preserved_as_separators(self):
        """多题文本中第X题标题均应保留为分隔符，不丢失边界。"""
        text = "第一题\n\nQ1? A\n\n第二题\n\nQ2? B"
        result = _normalize_text(text)
        # 应保留两个 === 分隔符
        assert result.count("===") == 2


class TestSplitBatch:
    """批量拆分测试。"""

    def test_split_by_chinese_number_title(self):
        """第X题 经 normalize 转换为 === 后应能作为批量拆分依据。"""
        text = "第一题\n\nQ1 stem?\n\nA. opt1\nB. opt2\n\n答案: A\n\n第二题\n\nQ2 stem?\n\nA. opt1\nB. opt2\n\n答案: B"
        normalized = _normalize_text(text)
        result = _split_batch(normalized)
        assert len(result) == 2, f"应拆分为 2 块，实际 {len(result)}"
        assert "Q1 stem" in result[0]
        assert "Q2 stem" in result[1]

    def test_single_chinese_number_title_no_split(self):
        """仅含一个第X题的不应拆分。"""
        text = "第一题\n\nQ1 stem?\n\nA. opt1\nB. opt2\n\n答案: A"
        result = _split_batch(text)
        assert len(result) == 1

    def test_no_chinese_number_title_fallback_to_existing(self):
        """不含第X题标题的，保持原有拆分逻辑不变。"""
        text = "Q1?\n\nA. a\nB. b\n\n答案: A\n\n---\n\nQ2?\n\nA. c\nB. d\n\n答案: B"
        result = _split_batch(text)
        assert len(result) == 2


class TestParseTextQuestions:
    """集成解析测试 — 模拟 BUGS.md 真实场景。"""

    def test_two_chinese_numbered_questions(self):
        """两道『第X题』格式题目应正确解析为两道独立题目。"""
        text = """第一题

某计算机采用32位定长指令字，支持字节寻址。一条相对转移指令的地址为0x0000 2000H，执行后跳转到0x0000 1FF8H，指令长度为4字节，偏移量用补码表示。则该指令偏移量字段的值为多少？

A. -8
B. -4
C. 4
D. 8

-8

目标地址 = 当前指令地址 + 指令长度 + 偏移量。
0x1FF8 = 0x2000 + 4 + 偏移量
偏移量 = 0x1FF8 - 0x2004 = -12，不在选项中。
按常见简化（不加指令长度）：偏移量 = 目标 - 当前 = 0x1FF8 - 0x2000 = -8。
故答案为A。

第二题

某计算机主存地址空间大小为128MB，按字节编址，采用直接映射Cache，块大小为32字节，Cache数据区容量为4KB。则主存地址中用于标记（Tag）的位数是多少？

A. 12
B. 14
C. 16
D. 18

C

主存128MB = 2^27字节 → 地址总长度27位。
块大小32B = 2^5 → 块内偏移5位。
Cache数据区4KB，块大小32B → Cache块数 = 4KB / 32B = 128 = 2^7。
直接映射：地址 = Tag + 索引(7位) + 偏移(5位)。
Tag位数 = 27 - 7 - 5 = 15位，但选项无15。
常见变体：若按字寻址（4B/字），主存容量变为128MB/4=32M字=2^25字，块内偏移=32B/4B=8字=2^3，索引仍为7位，Tag=25-3-7=15，仍无。
若Cache数据区容量理解为包含标记，或主存为256MB，则Tag=16。
本题按常见题库答案为16，对应主存256MB（2^28B）时：28-7-5=16。
故选C。"""

        result = parse_text_questions(text, subject="408")
        assert result["raw_count"] == 2, f"应识别 2 道题，实际 {result['raw_count']}"
        questions = result["questions"]
        assert len(questions) == 2, f"应返回 2 道题，实际 {len(questions)}"

        q1 = questions[0]
        assert q1["is_valid"], "第一题应有效"
        assert "32位定长指令字" in q1["stem"], "第一题题干应包含题目标识"
        assert len(q1["options"]) == 4, "第一题应有 4 个选项"
        assert q1["analysis"], "第一题应有解析"

        q2 = questions[1]
        assert q2["is_valid"], "第二题应有效"
        assert "主存地址空间" in q2["stem"], "第二题题干应包含题目标识"
        assert len(q2["options"]) == 4, "第二题应有 4 个选项"
        assert q2["analysis"], "第二题应有解析"

        # 验证第二题未被误吸入第一题解析
        assert "主存地址空间" not in q1["analysis"], "第二题内容不应在第一题解析中"

    def test_single_question_with_title(self):
        """含『第一题』标题的单题应正常解析。"""
        text = """第一题

某计算机采用32位定长指令字，支持字节寻址。则该指令偏移量字段的值为多少？

A. -8
B. -4
C. 4
D. 8

C"""
        result = parse_text_questions(text, subject="408")
        assert result["raw_count"] == 1
        assert len(result["questions"]) == 1
        assert result["questions"][0]["is_valid"]

    def test_text_without_chinese_titles(self):
        """无第X题标题的文本不应受影响。"""
        text = "Q?\n\nA. a\nB. b\n\n答案: A\n\n解析：略"
        result = parse_text_questions(text, subject="math")
        assert result["raw_count"] == 1

    def test_fenced_code_block_is_preserved(self):
        text = r"""有两个并发进程 \(P_{1}\) 和 \(P_{2}\)，其程序代码如下:
```tex
P1() {                     P2() {
 x = 1;      // A1          x = -3;     // B1
 y = 2;                     c = x * x;
 z = x + y;                 print c;    // B2
 print z;    // A2          }
}
```
可能打印出的 z 值有( )，可能打印出的 c 值有( )。

A. 1,1
B. 2,2
答案：A"""
        result = parse_text_questions(text, subject="408")
        question = result["questions"][0]
        assert "```tex" in question["stem"]
        assert "P1() {                     P2() {" in question["stem"]
        assert " x = 1;      // A1          x = -3;     // B1" in question["stem"]
        assert "$P_1$" in question["stem"]


class TestMathFormulaImport:
    """数学公式文本导入兼容测试。"""

    def test_latex_option_delimiters_are_removed_and_compacted(self):
        text = "A. \\( T_1(n) = n \\log_2 n + 5000n \\)"
        result = parse_text_questions("题干？\n" + text + "\nB. x\n答案：A", subject="exam408")
        assert result["questions"][0]["options"][0]["text"] == r"T_1(n)=n\log_2n+5000n"

    def test_unicode_math_is_standardized(self):
        text = "题干？\nA. T₁(n)=nlog₂n+5000n\nB. x\n答案：A"
        result = parse_text_questions(text, subject="exam408")
        assert result["questions"][0]["options"][0]["text"] == r"T_1(n)=n\log_2n+5000n"

    def test_escaped_latex_command_is_collapsed(self):
        text = "题干？\nA. T_1(n)=n\\log_2n+5000n\nB. x\n答案：A"
        result = parse_text_questions(text, subject="exam408")
        assert result["questions"][0]["options"][0]["text"] == r"T_1(n)=n\log_2n+5000n"

    def test_display_math_delimiters_are_removed(self):
        text = "题干？\nA. $$T_1(n)=n\\log_2n+5000n$$\nB. x\n答案：A"
        result = parse_text_questions(text, subject="exam408")
        assert result["questions"][0]["options"][0]["text"] == r"T_1(n)=n\log_2n+5000n"

    def test_full_time_complexity_question(self):
        text = r"""
05. 下列关于时间复杂度的函数中，时间复杂度最小的是（ ）。

A. \( T_1(n) = n \log_2 n + 5000n \)

B. \( T_2(n) = n^2 - 8000n \)

C. \( T_3(n) = n \log_2 n - 6000n \)

D. \( T_4(n) = 20000 \log_2 n \)

答案：D
"""
        result = parse_text_questions(text, subject="exam408")
        assert result["raw_count"] == 1
        question = result["questions"][0]
        assert question["question_type"] == "single_choice"
        assert question["stem"] == "下列关于时间复杂度的函数中，时间复杂度最小的是( )。"
        assert {item["key"]: item["text"] for item in question["options"]} == {
            "A": r"T_1(n)=n\log_2n+5000n",
            "B": "T_2(n)=n^2-8000n",
            "C": r"T_3(n)=n\log_2n-6000n",
            "D": r"T_4(n)=20000\log_2n",
        }
        assert question["answer"] == "D"
        assert question["is_valid"]

    @pytest.mark.parametrize("answer_line", ["答案：D", "答案:D", "参考答案：D", "正确答案：D", "【答案】D"])
    def test_answer_label_variants(self, answer_line):
        text = f"题干？\nA. a\nB. b\nC. c\nD. d\n{answer_line}"
        result = parse_text_questions(text, subject="exam408")
        assert result["questions"][0]["answer"] == "D"


class TestCodeBlockInStem:
    """题干内嵌 C 代码块：缩进 + 控制流括号结尾，多行不可被合并。"""

    def test_p3_while_loop_keeps_increment_on_separate_line(self):
        """BUGS.md P3: while(...) 后的 i++ 必须独立一行，不与条件合并。"""
        text = (
            "7. 下列算法的时间复杂度为（ ）。\n"
            "\n"
            "void fun(int n) {\n"
            "    int i=0;\n"
            "    while(i*i*i<=n)\n"
            "    i++;\n"
            "}\n"
            "\n"
            "A. \\( O(n) \\)\n"
            "B. \\( O(n \\log_2 n) \\)\n"
            "C. \\( O(\\sqrt[3]{n}) \\)\n"
            "D. \\( O(\\sqrt{n}) \\)\n"
            "答案：C\n"
        )
        result = parse_text_questions(text, subject="exam408-ds")
        assert result["raw_count"] == 1
        q = result["questions"][0]
        stem = q["stem"]
        # 控制流括号结尾的行不能被合并
        assert "while(i*i*i<=n)\n    i++;" in stem
        # 缩进保留
        assert "    int i=0;" in stem
        assert "    while(i*i*i<=n)" in stem
        # 大括号独立成行
        assert "void fun(int n) {" in stem
        assert stem.rstrip().endswith("}")
        # 选项内嵌 LaTeX 应被识别为 4 个并保留公式
        opts = {item["key"]: item["text"] for item in q["options"]}
        assert set(opts) == {"A", "B", "C", "D"}
        assert opts["A"] == "O(n)"
        assert opts["C"] == r"O(\sqrt[3]{n})"
        assert opts["D"] == r"O(\sqrt{n})"
        assert q["answer"] == "C"
        assert q["is_valid"]

    def test_p4_nested_for_loops_each_on_separate_line(self):
        """BUGS.md P4: 嵌套 for(...) 与 printf 必须各自独占一行。"""
        text = (
            "8. 下列程序段的时间复杂度为( )。\n"
            "\n"
            "if (n>=0) {\n"
            "    for (int i = 0; i<n; i++)\n"
            "    for (int j = 0; j<n; j++)\n"
            '    printf("输入数据大于或等于零\\n");\n'
            "}\n"
            "else {\n"
            "    for (int j = 0; j<n; j++)\n"
            '    printf("输入数据小于零\\n");\n'
            "}\n"
            "\n"
            "A. O(n)\n"
            "B. O(n^2)\n"
            "C. O(n^3)\n"
            "D. O(1)\n"
            "答案：B\n"
        )
        result = parse_text_questions(text, subject="exam408-ds")
        q = result["questions"][0]
        stem = q["stem"]
        # 两个 for 必须各自一行，不能粘成一行
        assert "for (int i = 0; i<n; i++)\n    for (int j = 0; j<n; j++)" in stem
        # printf 必须独立一行
        assert 'for (int j = 0; j<n; j++)\n    printf("输入数据大于或等于零\\n");' in stem
        # else 分支同样保持
        assert 'for (int j = 0; j<n; j++)\n    printf("输入数据小于零\\n");' in stem
        # 没有把多行合并成一行的痕迹
        assert "i++)    for" not in stem
        assert "j++)    printf" not in stem
        assert q["answer"] == "B"
        assert q["is_valid"]
