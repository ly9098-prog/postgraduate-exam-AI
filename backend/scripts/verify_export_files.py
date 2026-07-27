#!/usr/bin/env python3
"""Phase 8: Real PDF/DOCX generation and verification.

Generates real export files with test data, validates them, and saves
the results for visual inspection.
"""

import asyncio
import io
import os
import sys
import zipfile

# Ensure app can be imported
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Must set DATABASE_URL before any app imports
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.services.export.docx_exporter import DocxExporter
from app.services.export.pdf_exporter import PdfExporter
from app.services.export.exporter_base import ExportResult


def _make_question(
    stem: str,
    qtype: str = "single_choice",
    options: dict | None = None,
    answer: str = "A",
    analysis: str = "",
    image_urls: list | None = None,
):
    return {
        "content": {"stem": stem, "text": stem},
        "question_type": qtype,
        "options": options or {"A": "选项 A", "B": "选项 B", "C": "选项 C", "D": "选项 D"},
        "answer": answer,
        "analysis": analysis,
        "subject": {"id": 1, "label": "数学"},
        "image_urls": image_urls or [],
        "_group_title": "",
    }


def _make_formula_question(stem: str, latex: str, answer: str = "A"):
    """Question with mathematical formula content."""
    return {
        "content": {"stem": stem, "text": stem, "formulas": [latex]},
        "question_type": "single_choice",
        "options": {"A": f"${latex}$", "B": "其他", "C": "不确定", "D": "以上都不对"},
        "answer": answer,
        "analysis": f"分析: ${latex}$ 是本题的关键公式。",
        "subject": {"id": 1, "label": "数学"},
        "image_urls": [],
        "_group_title": "",
    }


def _make_config(**overrides) -> dict:
    config = {
        "title": "考研数学错题巩固练习",
        "file_name": "export.pdf",
        "show_date": True,
        "export_date": "2026-07-27",
        "sort_by": "newest",
        "group_by": "subject",
        "answer_position": "end",
        "analysis_position": "end",
        "space_style": "standard",
        "product_name": "MemoGrad",
        "total_count": 1,
        "skip_count": 0,
    }
    config.update(overrides)
    return config


async def generate(format: str, questions: list[dict], config: dict) -> ExportResult:
    """Generate an export in the given format."""
    snapshot = {"questions": questions, "config": config}
    exporter = PdfExporter() if format == "pdf" else DocxExporter()
    return await exporter.export(snapshot, "/tmp")


def verify_pdf(file_bytes: bytes, label: str) -> dict:
    """Verify a PDF file is valid and return stats."""
    result = {"label": label, "format": "PDF", "valid": False, "size_bytes": len(file_bytes), "size_kb": len(file_bytes) / 1024}

    if not file_bytes:
        result["error"] = "Empty file bytes"
        return result

    # Check PDF header
    if file_bytes[:5] != b"%PDF-":
        result["error"] = f"Invalid PDF header: {file_bytes[:20]}"
        return result

    result["valid"] = True
    result["header"] = file_bytes[:8].decode("ascii", errors="replace")

    # Try to extract text via simple approach
    text_parts = []
    in_text = False
    for line in file_bytes.decode("latin-1").split("\n"):
        if line.strip().startswith("(") and line.strip().endswith(")"):
            text_parts.append(line.strip()[1:-1])
        elif "BT" in line:
            in_text = True
        elif "ET" in line:
            in_text = False

    result["extracted_chars"] = len(" ".join(text_parts))

    # Count pages by looking for /Type /Page entries
    page_count = file_bytes.count(b"/Type /Page") - file_bytes.count(b"/Type /Pages")
    result["page_count_approx"] = max(1, page_count)

    return result


def verify_docx(file_bytes: bytes, label: str) -> dict:
    """Verify a DOCX file is valid and return stats."""
    result = {"label": label, "format": "DOCX", "valid": False, "size_bytes": len(file_bytes), "size_kb": len(file_bytes) / 1024}

    if not file_bytes:
        result["error"] = "Empty file bytes"
        return result

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            names = zf.namelist()
            result["zip_entries"] = len(names)

            # Check required OOXML files
            result["has_content_types"] = "[Content_Types].xml" in names
            result["has_document"] = "word/document.xml" in names
            result["has_styles"] = "word/styles.xml" in names

            # Check for OMML math content
            has_omml = any("word/document.xml" in n for n in names)
            if has_omml:
                doc_xml = zf.read("word/document.xml").decode("utf-8")
                result["has_m_omath"] = "m:oMath" in doc_xml or ":oMath" in doc_xml
                result["has_m_omathpara"] = "m:oMathPara" in doc_xml or ":oMathPara" in doc_xml
                result["has_w_tbl"] = "w:tbl" in doc_xml
                result["has_w_tr"] = "w:tr" in doc_xml
                result["doc_size_chars"] = len(doc_xml)

            # Check for page field
            result["has_page_field"] = any("PAGE" in zf.read(n).decode("utf-8", errors="replace") for n in names if n.endswith(".xml"))

            # Check for NUMPAGES field
            result["has_numpages_field"] = any("NUMPAGES" in zf.read(n).decode("utf-8", errors="replace") for n in names if n.endswith(".xml"))

        result["valid"] = True
    except zipfile.BadZipFile as e:
        result["error"] = f"Bad zip file: {e}"
    except Exception as e:
        result["error"] = f"Verification error: {e}"

    return result


def generate_questions(count: int, include_formulas: bool = False) -> list[dict]:
    """Generate a list of test questions."""
    questions = []

    # Single choice
    for i in range(1, min(count + 1, 10)):
        questions.append(_make_question(
            stem=f"{i}. 设函数 $f(x) = x^{2} + 2x + 1$，则 $f'(x)$ 等于？",
            qtype="single_choice",
            options={"A": "$2x+2$", "B": "$2x+1$", "C": "$x+2$", "D": "$2x$"},
            answer="A",
            analysis="根据求导公式，$(x^2)' = 2x$，$(2x)' = 2$，$(1)' = 0$，因此 $f'(x) = 2x+2$。",
        ))

    # Multiple choice
    if count >= 4:
        questions.append(_make_question(
            stem="以下哪些是奇函数？",
            qtype="multiple_choice",
            options={"A": "$\\sin x$", "B": "$x^3$", "C": "$\\cos x$", "D": "$x^2$"},
            answer="AB",
            analysis="奇函数满足 $f(-x) = -f(x)$。$\\sin x$ 和 $x^3$ 是奇函数。",
        ))

    # True/false
    if count >= 5:
        questions.append(_make_question(
            stem="设 $A$ 为 $n$ 阶方阵，若 $|A| = 0$，则 $A$ 不可逆。",
            qtype="true_false",
            options={"A": "正确", "B": "错误"},
            answer="A",
            analysis="行列式为零的矩阵不可逆，这是线性代数的基本定理。",
        ))

    # Subjective
    if count >= 6:
        questions.append(_make_question(
            stem="求极限 $\\lim_{x \\to 0} \\frac{\\sin x}{x}$。",
            qtype="subjective",
            answer="$1$",
            analysis="这是第一个重要极限，$\\lim_{x \\to 0} \\frac{\\sin x}{x} = 1$。",
        ))

    # Chemistry with subscripts/superscripts
    if count >= 7:
        questions.append(_make_question(
            stem="化学式 $H_2O$ 中，氢元素的化合价是？",
            qtype="single_choice",
            options={"A": "$+1$", "B": "$-1$", "C": "$+2$", "D": "$0$"},
            answer="A",
            analysis="在水中，氢的化合价为 $+1$，氧的化合价为 $-2$。",
        ))

    # Formulas
    if include_formulas:
        formulas = [
            r"\int_{0}^{\infty} e^{-x^2} dx = \frac{\sqrt{\pi}}{2}",
            r"\sum_{i=1}^{n} i = \frac{n(n+1)}{2}",
            r"\alpha^2 + \beta^2 = (\alpha + \beta)^2 - 2\alpha\beta",
            r"\begin{bmatrix} 1 & 2 \\ 3 & 4 \end{bmatrix}",
            r"E = mc^2",
            r"\lim_{x \to 0} \frac{\sin x}{x} = 1",
        ]
        for i, formula in enumerate(formulas[:max(0, count - 6)]):
            questions.append(_make_formula_question(
                stem=f"公式题 {i+1}: 请解释以下公式的含义",
                latex=formula,
            ))

    # Fill remaining
    while len(questions) < count:
        idx = len(questions) + 1
        questions.append(_make_question(
            stem=f"{idx}. 以下关于微分中值定理的说法正确的是？",
            qtype="single_choice",
            options={"A": "罗尔定理", "B": "拉格朗日中值定理", "C": "柯西中值定理", "D": "以上都是"},
            answer="D",
            analysis="三个中值定理是微分学的重要内容，它们之间存在递进关系。",
        ))

    # Trim to exact count
    return questions[:count]


async def main():
    output_dir = "/home/lmh/projects/postgraduate-ai/backend/tests/artifacts"
    os.makedirs(output_dir, exist_ok=True)

    results = []

    # 1. Small PDF
    print("=" * 60)
    print("生成小规模 PDF (5 题)...")
    questions = generate_questions(5)
    cfg = _make_config(title="小规模测试", file_name="small_test.pdf", total_count=len(questions))
    result = await generate("pdf", questions, cfg)
    pdf_result = verify_pdf(result.file_bytes, "small_pdf_5q")
    results.append(pdf_result)
    if pdf_result["valid"]:
        path = os.path.join(output_dir, "small_5q.pdf")
        with open(path, "wb") as f:
            f.write(result.file_bytes)
        print(f"  ✅ 生成成功: {path} ({pdf_result['size_kb']:.1f} KB, ~{pdf_result['page_count_approx']}页)")
    else:
        print(f"  ❌ 失败: {pdf_result.get('error')}")

    # 2. Small DOCX
    print("\n生成小规模 DOCX (5 题)...")
    cfg = _make_config(title="小规模测试", file_name="small_test.docx", total_count=len(questions))
    result = await generate("docx", questions, cfg)
    docx_result = verify_docx(result.file_bytes, "small_docx_5q")
    results.append(docx_result)
    if docx_result["valid"]:
        path = os.path.join(output_dir, "small_5q.docx")
        with open(path, "wb") as f:
            f.write(result.file_bytes)
        print(f"  ✅ 生成成功: {path} ({docx_result['size_kb']:.1f} KB)")
        print(f"     内容: {docx_result['has_m_omath']=}, {docx_result['has_w_tbl']=}")
    else:
        print(f"  ❌ 失败: {docx_result.get('error')}")

    # 3. Formula-rich PDF (10 questions with formulas)
    print("\n生成公式 PDF (10 题, 含矩阵/积分/求和)...")
    questions = generate_questions(10, include_formulas=True)
    cfg = _make_config(title="公式测试", file_name="formula_test.pdf", total_count=len(questions))
    result = await generate("pdf", questions, cfg)
    pdf_result = verify_pdf(result.file_bytes, "formula_pdf_10q")
    results.append(pdf_result)
    if pdf_result["valid"]:
        path = os.path.join(output_dir, "formula_10q.pdf")
        with open(path, "wb") as f:
            f.write(result.file_bytes)
        print(f"  ✅ 生成成功: {path} ({pdf_result['size_kb']:.1f} KB, ~{pdf_result['page_count_approx']}页)")
    else:
        print(f"  ❌ 失败: {pdf_result.get('error')}")

    # 4. Formula-rich DOCX
    print("\n生成公式 DOCX (10 题, 含矩阵/积分/求和)...")
    cfg = _make_config(title="公式测试", file_name="formula_test.docx", total_count=len(questions))
    result = await generate("docx", questions, cfg)
    docx_result = verify_docx(result.file_bytes, "formula_docx_10q")
    results.append(docx_result)
    if docx_result["valid"]:
        path = os.path.join(output_dir, "formula_10q.docx")
        with open(path, "wb") as f:
            f.write(result.file_bytes)
        print(f"  ✅ 生成成功: {path} ({docx_result['size_kb']:.1f} KB)")
        print(f"     OMML: {docx_result.get('has_m_omath')}, Table: {docx_result.get('has_w_tbl')}")
    else:
        print(f"  ❌ 失败: {docx_result.get('error')}")

    # 5. 100-question PDF
    print("\n生成 100 题 PDF...")
    questions_100 = generate_questions(100)
    cfg = _make_config(title="百题测试", file_name="hundred_test.pdf", total_count=len(questions_100))
    result = await generate("pdf", questions_100, cfg)
    pdf_result = verify_pdf(result.file_bytes, "hundred_pdf_100q")
    results.append(pdf_result)
    if pdf_result["valid"]:
        path = os.path.join(output_dir, "hundred_100q.pdf")
        with open(path, "wb") as f:
            f.write(result.file_bytes)
        print(f"  ✅ 生成成功: {path} ({pdf_result['size_kb']:.1f} KB, ~{pdf_result['page_count_approx']}页)")
    else:
        print(f"  ❌ 失败: {pdf_result.get('error')}")

    # 6. 100-question DOCX
    print("\n生成 100 题 DOCX...")
    cfg = _make_config(title="百题测试", file_name="hundred_test.docx", total_count=len(questions_100))
    result = await generate("docx", questions_100, cfg)
    docx_result = verify_docx(result.file_bytes, "hundred_docx_100q")
    results.append(docx_result)
    if docx_result["valid"]:
        path = os.path.join(output_dir, "hundred_100q.docx")
        with open(path, "wb") as f:
            f.write(result.file_bytes)
        print(f"  ✅ 生成成功: {path} ({docx_result['size_kb']:.1f} KB)")
        print(f"     Table: {docx_result.get('has_w_tbl')}, Page field: {docx_result.get('has_page_field')}")
    else:
        print(f"  ❌ 失败: {docx_result.get('error')}")

    # Summary
    print("\n" + "=" * 60)
    print("验收结果汇总:")
    print("=" * 60)
    all_valid = True
    for r in results:
        status = "✅" if r["valid"] else "❌"
        print(f"  {status} {r['label']}: {r['format']}, {r['size_kb']:.1f} KB")
        if not r["valid"]:
            print(f"      原因: {r.get('error')}")
            all_valid = False

    print(f"\n全部通过: {'✅ 是' if all_valid else '❌ 否'}")
    return all_valid


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
