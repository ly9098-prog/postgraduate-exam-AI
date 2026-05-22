"""PDF 题目解析单元测试 — 重点覆盖"解析文本中含答案关键词"的污染问题"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.import_service import _parse_pdf  # noqa: E402


def _make_pdf(text: str) -> bytes:
    """用 PyMuPDF 构造一份纯文本 PDF（单页）"""
    import fitz
    import io
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 80), text, fontsize=11, fontname="china-s")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ── 测试辅助 ──────────────────────────────────────────────────────────────────

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def ok(name: str) -> None:
    PASSED.append(name)
    print(f"  ✓ {name}")


def fail(name: str, msg: str) -> None:
    FAILED.append((name, msg))
    print(f"  ✗ {name}: {msg}")


def check(name: str, cond: bool, msg: str = "") -> None:
    if cond:
        ok(name)
    else:
        fail(name, msg)


# ── 测试用例 ──────────────────────────────────────────────────────────────────

def test_answer_not_polluted_by_analysis_text() -> None:
    """解析区含"标准答案""选A""因此选A"时，answer 字段不被污染"""
    print("\n[1] 解析文本含答案关键词 — 不污染 answer 字段")
    text = (
        "1. 下面哪个寄存器存放程序计数器？\n"
        "A. PC\n"
        "B. IR\n"
        "C. MAR\n"
        "D. MBR\n"
        "答案：A\n"
        "解析：本题考查寄存器功能。标准答案为A（PC，程序计数器）。\n"
        "近似题的标准答案通常也选A。因此按照定义选A是正确的。\n"
        "偏移量为0x1000，意味着目标地址=0x2000 1004H+0x1000*4？不行。\n"
        "更合理：题设答案应该是A，因为PC负责保存下一条指令地址。\n"
    )
    results = _parse_pdf(_make_pdf(text), "test.pdf")
    assert results, "未解析出题目"
    r = results[0]

    check("answer==A", r["answer"] == "A", f"answer={r['answer']!r}")
    check("analysis 包含完整解析",
          "偏移量" in r["explanation"],
          f"analysis={r['explanation'][:80]!r}")
    check("answer 不含'偏移量'",
          "偏移量" not in r["answer"],
          f"answer={r['answer']!r}")
    check("answer 不含'更合理'",
          "更合理" not in r["answer"],
          f"answer={r['answer']!r}")


def test_analysis_only_no_formal_answer_line() -> None:
    """没有正式答案行时，answer 为空，解析完整保留"""
    print("\n[2] 无正式答案行 — answer 为空，解析不截断")
    text = (
        "1. 操作系统的主要功能包括哪些？\n"
        "解析：操作系统主要提供进程管理、内存管理、文件系统、I/O管理。\n"
        "答案一般选B或D，具体看题目表述。正确答案通常为B。\n"
    )
    results = _parse_pdf(_make_pdf(text), "test.pdf")
    assert results, "未解析出题目"
    r = results[0]

    check("无正式答案行 answer 为空", r["answer"] == "", f"answer={r['answer']!r}")
    check("解析文本含'进程管理'",
          "进程管理" in r["explanation"],
          f"analysis={r['explanation'][:80]!r}")


def test_answer_before_analysis_correct_split() -> None:
    """标准结构：选项 → 答案行 → 解析行，正确切分"""
    print("\n[3] 标准结构：答案行在解析行之前，正确分割")
    text = (
        "1. TCP 与 UDP 的区别是什么？\n"
        "A. TCP 无连接\n"
        "B. TCP 有连接\n"
        "C. UDP 有连接\n"
        "D. 以上均错\n"
        "参考答案：B\n"
        "解析：TCP是面向连接的协议，三次握手建立连接。UDP无连接，速度快。\n"
        "因此答案是B，TCP提供可靠传输。\n"
    )
    results = _parse_pdf(_make_pdf(text), "test.pdf")
    assert results, "未解析出题目"
    r = results[0]

    check("answer==B", r["answer"] == "B", f"answer={r['answer']!r}")
    check("analysis 含'三次握手'",
          "三次握手" in r["explanation"],
          f"analysis={r['explanation'][:80]!r}")
    check("answer 不含'三次握手'",
          "三次握手" not in r["answer"],
          f"answer={r['answer']!r}")


def test_analysis_first_no_separate_answer_line() -> None:
    """解析行先出现（无单独答案行），解析中含"选A"也不影响"""
    print("\n[4] 解析行先出现，解析内含'选A'")
    text = (
        "1. 下列哪项是冯诺依曼结构的特征？\n"
        "A. 存储程序\n"
        "B. 哈佛结构\n"
        "C. 堆栈机\n"
        "D. 数据流\n"
        "解析：冯诺依曼体系存储程序，因此选A。标准答案也是A。\n"
        "答案应该是A，因为存储程序是冯诺依曼的核心思想。\n"
    )
    results = _parse_pdf(_make_pdf(text), "test.pdf")
    assert results, "未解析出题目"
    r = results[0]

    # 无正式答案行（"解析"先出现，之后的"答案"行在解析区内，不应提取）
    check("answer 为空或正确",
          r["answer"] in ("", "A"),
          f"answer={r['answer']!r}")
    check("analysis 含'冯诺依曼'",
          "冯诺依曼" in r["explanation"],
          f"analysis={r['explanation'][:80]!r}")


def test_multiple_questions_isolation() -> None:
    """多题时，第一题的解析不污染第二题的答案"""
    print("\n[5] 多题隔离 — 第一题解析不污染第二题答案")
    text = (
        "1. 第一题：下列正确的是？\n"
        "A. 选项一\n"
        "B. 选项二\n"
        "答案：A\n"
        "解析：第一题答案是A，不要选B，因此正确答案是A。\n"
        "2. 第二题：下列错误的是？\n"
        "A. 错误选项\n"
        "B. 正确选项\n"
        "答案：B\n"
        "解析：第二题选B，标准答案为B。\n"
    )
    results = _parse_pdf(_make_pdf(text), "test.pdf")
    assert len(results) >= 2, f"期望至少2题，实际={len(results)}"
    r1, r2 = results[0], results[1]

    check("第一题 answer==A", r1["answer"] == "A", f"r1.answer={r1['answer']!r}")
    check("第二题 answer==B", r2["answer"] == "B", f"r2.answer={r2['answer']!r}")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 60)
    print("PDF 题目解析单元测试")
    print("=" * 60)

    test_answer_not_polluted_by_analysis_text()
    test_analysis_only_no_formal_answer_line()
    test_answer_before_analysis_correct_split()
    test_analysis_first_no_separate_answer_line()
    test_multiple_questions_isolation()

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("\n失败明细：")
        for name, msg in FAILED:
            print(f"  ✗ {name}\n    {msg}")
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
