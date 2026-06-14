#!/usr/bin/env python3
"""Apply remaining fixes to text_normalizer.py"""
import sys

with open('app/features/text_normalizer.py', 'r') as f:
    content = f.read()

# Find the old LaTeX section
old_1_start = content.find('# OCR 常将编程/CS 上下文中的单字母变量误识为 LaTeX 希腊符号')
old_1_end = content.find(
    '    # ---------------------------------------------------------------\n    # 标点符号规范化',
    old_1_start
)

if old_1_start == -1 or old_1_end == -1:
    print("ERROR: Could not find old LaTeX section boundaries")
    print(f"old_1_start={old_1_start}, old_1_end={old_1_end}")
    sys.exit(1)

new_1 = '''    # OCR 视觉误识逆向映射表
    # 这不是希腊字母到拉丁字母的语义映射，而是 OCR 视觉错误的修复：
    # OCR 看到拉丁字母，输出 LaTeX 希腊符号。此表将这些误识产物还原。
    # 例如 gamma→r 是因为 OCR 视觉上 γ 像 r，不代表希腊语义（γ=g）
    _OCR_LATEX_REVERSION_MAP = {
        "alpha": "a",   # OCR 视觉: a/q → \\alpha
        "beta": "B",    # OCR 视觉: B → \\beta
        "gamma": "r",   # OCR 视觉: r → \\gamma（视觉误识，非希腊语义映射）
        "delta": "d",   # OCR 视觉: d → \\delta
        "theta": "0",   # OCR 视觉: 0 → \\theta
        "lambda": "l",  # OCR 视觉: l → \\lambda
    }

    _PROG_CONTEXT_SIGNALS = (
        "->", "next", "prior", "链表", "结点", "节点", "指针",
        "数组", "栈", "队列", "NULL", "malloc", "struct",
        "单链表", "双链表", "循环链表", "头插法", "前驱", "后继",
    )

    _RE_LATEX_GREEK_SINGLE = re.compile(
        r"\\$?\\\\" r"(alpha|beta|gamma|delta|theta|lambda)" r"\\$?"
    )

    def _fix_latex_substitutions(self, text: str) -> str:
        """行级作用域：仅在含编程信号的「行」内还原 OCR 误识的 LaTeX 符号。

        OCR 常把 ``q``/``a`` 误识为 ``\\\\alpha``，``B`` 误识为 ``\\\\beta`` 等。
        改为逐行判断上下文，避免跨区域污染：
        - ``链表 p->next = \\\\alpha`` → 该行含编程信号，允许替换
        - ``设\\\\alpha+\\\\beta=1`` → 无编程信号，保留 LaTeX 不动
        """
        if not text:
            return text

        def _replace(m: re.Match) -> str:
            cmd = m.group(1)
            return self._OCR_LATEX_REVERSION_MAP.get(cmd, m.group(0))

        lines = text.split("\\n")
        result: list[str] = []
        for line in lines:
            if any(sig in line for sig in self._PROG_CONTEXT_SIGNALS):
                result.append(self._RE_LATEX_GREEK_SINGLE.sub(_replace, line))
            else:
                result.append(line)
        return "\\n".join(result)
'''

old_block = content[old_1_start:old_1_end]
content = content.replace(old_block, new_1)

with open('app/features/text_normalizer.py', 'w') as f:
    f.write(content)

print("text_normalizer.py patched successfully!")
