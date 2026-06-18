"""question_pipeline 单元测试 — 只测 pipeline 输入输出。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.features.question_pipeline import (  # noqa: E402
    normalizer,
    process_question_pipeline,
)
from app.features.question_normalizer import (  # noqa: E402
    normalize_question as path_a_normalize,
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

    code_out = normalizer.clean_text(
        "1. 有两个并发进程 $P_{1}$ 和 $P_{2}$，其程序代码如下:\n"
        "```tex\n"
        "P1() {                     P2() {\n"
        " x = 1;      // A1          x = -3;     // B1\n"
        " y = 2;                     c = x * x;\n"
        " z = x + y;                 print c;    // B2\n"
        " print z;    // A2          }\n"
        "}\n"
        "```"
    )
    check("代码围栏保留", "```tex" in code_out and "```" in code_out, repr(code_out))
    check("代码换行保留", "\nP1() {                     P2() {\n" in code_out, repr(code_out))
    check("代码缩进保留", "\n x = 1;      // A1          x = -3;" in code_out, repr(code_out))


def test_dedup_helpers() -> None:
    print("\n[6] 去重辅助")
    left = "设函数 f(x)=x^2，求导数。"
    right = "设函数f(x)=x^2，求导数。"
    check("stem_hash 忽略空白", normalizer.stem_hash(left) == normalizer.stem_hash(right))
    check("相似题检测", normalizer.is_similar_stem(left, right))


def test_unified_schema_valid() -> None:
    print("\n[7] 统一 Schema — 有效题目包含全部验证字段")
    raw = {
        "subject": "math2",
        "question_type": "single_choice",
        "stem": "1+1=?",
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "answer": "B",
    }
    result = process_question_pipeline(raw, "excel")
    norm = result["normalized"]
    check("有 validation_status (valid)", norm.get("validation_status") == "passed", repr(norm.get("validation_status")))
    check("有 failure_reason (None)", norm.get("failure_reason") is None, repr(norm.get("failure_reason")))
    check("有 retry_recommended (False)", norm.get("retry_recommended") is False, repr(norm.get("retry_recommended")))
    check("有 ocr_quality_flags ([])", norm.get("ocr_quality_flags") == [], repr(norm.get("ocr_quality_flags")))


def test_unified_schema_invalid() -> None:
    print("\n[8] 统一 Schema — 无效题目输出正确验证字段")
    result = process_question_pipeline(
        {"stem": "", "answer": ""}, "excel"
    )
    norm = result["normalized"]
    check("validation_status=failed", norm.get("validation_status") == "failed", repr(norm.get("validation_status")))
    check("failure_reason 非空列表", isinstance(norm.get("failure_reason"), list) and len(norm["failure_reason"]) > 0, repr(norm.get("failure_reason")))
    check("retry_recommended=False (非选项错误)", norm.get("retry_recommended") is False, repr(norm.get("retry_recommended")))


def test_unified_schema_non_ocr() -> None:
    print("\n[9] 统一 Schema — 非 OCR 来源 ocr_quality_flags 为空")
    for src in ("excel", "ai", "manual"):
        result = process_question_pipeline(
            {"subject": "math2", "question_type": "fill", "stem": "1+1=?", "answer": "2"},
            src,
        )
        flags = result["normalized"].get("ocr_quality_flags", None)
        check(f"{src} ocr_quality_flags=[]", flags == [], repr(flags))


def test_unified_schema_all_sources() -> None:
    print("\n[10] 统一 Schema — 所有来源的字段键一致")
    expected_keys = {
        "validation_status", "failure_reason", "retry_recommended", "ocr_quality_flags",
        "is_valid", "errors", "warnings", "subject", "question_type",
        "stem", "options", "answer", "analysis", "source", "stem_hash",
    }
    for src in ("excel", "pdf", "ai", "manual", "ocr"):
        result = process_question_pipeline(
            {"subject": "math2", "question_type": "fill", "stem": "1+1=?", "answer": "2"},
            src,
        )
        norm_keys = set(result["normalized"].keys())
        missing = expected_keys - norm_keys
        check(f"{src} 不缺验证字段", not missing, f"缺少: {missing}")


def test_source_type_meta() -> None:
    print("\n[11] source_type 元信息保留")
    result = process_question_pipeline(
        {"stem": "1+1=?", "answer": "2", "question_type": "fill"},
        "ocr",
        {"file": "x.pdf", "page": 3},
    )
    check("source_type 字段", result["source_type"] == "ocr", repr(result["source_type"]))
    check("source 元信息", result["normalized"]["source"] == {"file": "x.pdf", "page": 3}, repr(result["normalized"]["source"]))


def test_cross_path_consistency() -> None:
    """两条标准化路径对同一输入输出一致（防止功能发散）。"""
    print("\n[12] 跨路径一致性")

    # Path A: question_normalizer.normalize_question (used by pipeline_orchestrator)
    path_a_input = {
        "raw_question_text": "1. 1+1=?\nA. 1\nB. 2\nC. 3\nD. 4\n答案：B",
        "option_lines": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "page_start": 1,
    }
    path_a_result = path_a_normalize(
        path_a_input,
        matched={"answer": "B"},
        source_info={"subject": "math2"},
    )

    # Path B: question_pipeline.QuestionNormalizer.normalize (used by process_question_pipeline)
    path_b_result = normalizer.normalize({
        "subject": "math2",
        "question_type": "single_choice",
        "stem": "1. 1+1=?",
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "answer": "B",
    })

    # 核心字段比对
    check("stem 一致", path_a_result["stem"] == path_b_result["stem"],
          f"A={path_a_result['stem']!r} B={path_b_result['stem']!r}")
    check("question_type 一致", path_a_result["question_type"] == path_b_result["question_type"],
          f"A={path_a_result['question_type']} B={path_b_result['question_type']}")
    check("answer 一致", path_a_result["answer"] == path_b_result["answer"],
          f"A={path_a_result['answer']!r} B={path_b_result['answer']!r}")
    check("is_valid 一致", path_a_result["is_valid"] == path_b_result["is_valid"],
          f"A={path_a_result['is_valid']} B={path_b_result['is_valid']}")

    # 选项语义一致（忽略 text 中因 LaTeX wrap 导致的细小差异）
    a_opts = {(o["key"], o["text"]) for o in path_a_result.get("options", [])}
    b_opts = {(o["key"], o["text"]) for o in path_b_result.get("options", [])}
    check("options 语义一致", a_opts == b_opts,
          f"A={a_opts} B={b_opts}")


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
    test_unified_schema_valid()
    test_unified_schema_invalid()
    test_unified_schema_non_ocr()
    test_unified_schema_all_sources()
    test_source_type_meta()
    test_cross_path_consistency()
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
