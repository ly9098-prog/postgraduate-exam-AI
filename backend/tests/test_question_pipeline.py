"""question_pipeline 单元测试 — 只测 pipeline 输入输出。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.features.question_pipeline import (  # noqa: E402
    normalizer,
    process_question_pipeline,
)

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def ok(name: str) -> None:
    PASSED.append(name)
    print(f"  ✓ {name}")


def fail(name: str, msg: str) -> None:
    FAILED.append((name, msg))
    print(f"  ✗ {name}: {msg}")


def check(name: str, cond: bool, msg: str = "") -> None:
    ok(name) if cond else fail(name, msg)


def test_excel_path() -> None:
    print("\n[1] Excel 输入 → 标准化 + DB 适配")
    raw = {
        "subject": "数学二",
        "question_type": "单选",
        "stem": "下列正确的是？",
        "options": "A. 甲\nB. 乙",
        "answer": "答案是A",
        "explanation": "解析：因为甲正确。",
        "tags": "函数,导数",
        "difficulty": "2",
    }
    result = process_question_pipeline(raw, "excel", {"file": "a.xlsx", "page": 0})
    check("is_valid", result["is_valid"], repr(result))
    norm = result["normalized"]
    check("subject 映射", norm["subject"] == "math2", norm["subject"])
    check("question_type 映射", norm["question_type"] == "single_choice", norm["question_type"])
    check("answer 清洗", norm["answer"] == "A", repr(norm["answer"]))
    fields = result["import_fields"]
    check("parsed_content", fields["parsed_content"] == {"text": "下列正确的是？"}, repr(fields))
    check("parsed_options", fields["parsed_options"] == {"A": "甲", "B": "乙"}, repr(fields))
    check("parsed_analysis", fields["parsed_analysis"] == "因为甲正确。", repr(fields))
    check("question_fields 存在", result["question_fields"] is not None, "")


def test_pdf_path() -> None:
    print("\n[2] PDF 输入 → 兼容旧 question_type=choice + explanation")
    raw = {
        "subject": "math2",
        "stem": "1. 函数 f(x)=x^2 的导数？",
        "options": "A:2x\\nB:x\\nC:1\\nD:0",
        "answer": "A",
        "explanation": "f'(x)=2x。",
        "question_type": "choice",
    }
    result = process_question_pipeline(raw, "pdf", {"file": "p.pdf", "page": 1})
    check("PDF is_valid", result["is_valid"], repr(result))
    check("PDF type 兼容", result["normalized"]["question_type"] == "single_choice", "")
    check("PDF stem 去前缀", "1." not in result["normalized"]["stem"], result["normalized"]["stem"])


def test_ai_multiple_choice() -> None:
    print("\n[3] AI 输入 → 多选答案与列表选项")
    raw = {
        "subject": "exam408",
        "question_type": "multiple",
        "stem": "下列属于操作系统功能的是？",
        "options": [
            {"key": "A", "text": "进程管理"},
            {"key": "B", "text": "内存管理"},
            {"key": "C", "text": "杀毒"},
            {"key": "D", "text": "文件管理"},
        ],
        "answer": ["a", "B", "d"],
        "analysis": "解析：杀毒不是 OS 的核心功能。",
    }
    result = process_question_pipeline(raw, "ai")
    check("AI multiple is_valid", result["is_valid"], repr(result))
    check("AI 答案标准化", result["normalized"]["answer"] == ["A", "B", "D"], repr(result["normalized"]["answer"]))
    check("AI 多选 DB 字符串", result["import_fields"]["parsed_answer"] == "A,B,D", repr(result["import_fields"]))


def test_invalid_input() -> None:
    print("\n[4] 缺失字段 → invalid，不出 question_fields")
    result = process_question_pipeline(
        {"stem": "", "answer": ""}, "manual"
    )
    check("invalid", not result["is_valid"], repr(result))
    check("stem_empty 在错误中", "stem_empty" in result["errors"], repr(result["errors"]))
    check("answer_empty 在错误中", "answer_empty" in result["errors"], repr(result["errors"]))
    check("question_fields 为 None", result["question_fields"] is None, "")


def test_text_cleaning() -> None:
    print("\n[5] 文本清洗 — 页码 / 题号 / 重复行")
    out = normalizer.clean_text(
        "第 1 页\n1. 设函数  f(x)=x^2，\n求导数。\n求导数。"
    )
    check("去页码", "第 1 页" not in out, repr(out))
    check("去题号", not out.startswith("1."), repr(out))
    check("去重复行", out.count("求导数") == 1, repr(out))


def test_dedup_helpers() -> None:
    print("\n[6] 去重辅助")
    left = "设函数 f(x)=x^2，求导数。"
    right = "设函数f(x)=x^2，求导数。"
    check("stem_hash 忽略空白", normalizer.stem_hash(left) == normalizer.stem_hash(right))
    check("相似题检测", normalizer.is_similar_stem(left, right))


def test_source_type_meta() -> None:
    print("\n[7] source_type 元信息保留")
    result = process_question_pipeline(
        {"stem": "1+1=?", "answer": "2", "question_type": "fill"},
        "ocr",
        {"file": "x.pdf", "page": 3},
    )
    check("source_type 字段", result["source_type"] == "ocr", repr(result["source_type"]))
    check("source 元信息", result["normalized"]["source"] == {"file": "x.pdf", "page": 3}, repr(result["normalized"]["source"]))


def main() -> int:
    print("=" * 60)
    print("question_pipeline 单元测试")
    print("=" * 60)
    test_excel_path()
    test_pdf_path()
    test_ai_multiple_choice()
    test_invalid_input()
    test_text_cleaning()
    test_dedup_helpers()
    test_source_type_meta()
    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name, msg in FAILED:
            print(f"  ✗ {name}\n    {msg}")
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
