"""Generate acceptance sample DOCX/PDF files for verification.

Outputs to ``docs/samples/``. These files contain no real user data.
"""

import asyncio
import os
import tempfile

from app.services.export.docx_exporter import DocxExporter
from app.services.export.pdf_exporter import PdfExporter

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "samples")


def _make_question(
    stem: str,
    qtype: str = "single_choice",
    options: dict | None = None,
    answer: str = "A",
    analysis: str = "",
    group_title: str = "",
    image_urls: list | None = None,
    segments: list | None = None,
) -> dict:
    q = {
        "content": {"stem": stem, "text": stem},
        "question_type": qtype,
        "options": options or {"A": "选项 A", "B": "选项 B", "C": "选项 C", "D": "选项 D"},
        "answer": answer,
        "analysis": analysis,
        "subject": {"id": 1, "label": "数学"},
        "_group_title": group_title,
        "image_urls": image_urls or [],
    }
    if segments:
        q["content"]["segments"] = segments
    return q


def _make_config(**overrides) -> dict:
    config = {
        "title": "测试试卷",
        "file_name": "test.docx",
        "show_date": True,
        "export_date": "2026-07-25",
        "sort_by": "newest",
        "group_by": "none",
        "answer_position": "none",
        "analysis_position": "none",
        "space_style": "standard",
        "product_name": "MemoGrad",
        "total_count": 10,
        "skip_count": 0,
    }
    config.update(overrides)
    return config


async def generate_sample(
    name: str,
    questions: list[dict],
    config: dict,
    format: str = "docx",
):
    """Generate a sample file."""
    snapshot = {"questions": questions, "config": config}
    with tempfile.TemporaryDirectory() as tmpdir:
        if format == "docx":
            exp = DocxExporter()
        else:
            exp = PdfExporter()
        result = await exp.export(snapshot, tmpdir)
        if result.success and result.file_bytes:
            path = os.path.join(SAMPLES_DIR, name)
            with open(path, "wb") as f:
                f.write(result.file_bytes)
            print(f"  ✓ {path} ({len(result.file_bytes) / 1024:.1f} KB)")
        else:
            print(f"  ✗ {name} failed: {result.error_message}")


async def main():
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    print("Generating acceptance samples...\n")

    # 1. PDF default config
    await generate_sample(
        "sample_default.pdf",
        questions=[_make_question(f"第 {i} 题的内容") for i in range(10)],
        config=_make_config(title="默认配置测试样卷", total_count=10, file_name="sample_default.pdf"),
        format="pdf",
    )

    # 2. DOCX default config
    await generate_sample(
        "sample_default.docx",
        questions=[_make_question(f"第 {i} 题的内容") for i in range(10)],
        config=_make_config(title="默认配置测试样卷", total_count=10),
        format="docx",
    )

    # 3. DOCX with answer + analysis after question
    await generate_sample(
        "sample_answer_after.docx",
        questions=[_make_question(f"第 {i} 题", answer=f"{chr(65 + i % 4)}", analysis=f"这是第 {i} 题的解析") for i in range(5)],
        config=_make_config(title="答案解析紧跟题后", answer_position="after_question", analysis_position="after_question", total_count=5),
        format="docx",
    )

    # 4. DOCX answer at end, analysis at end
    await generate_sample(
        "sample_answer_at_end.docx",
        questions=[_make_question(f"第 {i} 题", answer=f"{chr(65 + i % 4)}", analysis=f"这是第 {i} 题的解析") for i in range(5)],
        config=_make_config(title="答案解析均在末尾", answer_position="at_end", analysis_position="at_end", total_count=5),
        format="docx",
    )

    # 5. DOCX multi-subject grouping
    subjects = [("数学", "数学题 1"), ("英语", "英语题 1"), ("数学", "数学题 2"), ("政治", "政治题 1")]
    qs = [_make_question(stem, group_title=subj) for subj, stem in subjects]
    await generate_sample(
        "sample_grouped.docx",
        questions=qs,
        config=_make_config(title="多学科分组", group_by="subject", total_count=4),
        format="docx",
    )

    # 6. DOCX with images, tables, formulas, code
    rich_questions = [
        _make_question("包含文本和图片的题目", segments=[
            {"type": "text", "text": "请看下图："},
            {"type": "image", "url": "https://via.placeholder.com/400x200.png?text=Sample+Image", "alt": "示例图片"},
        ]),
        _make_question("包含公式的题目", segments=[
            {"type": "text", "text": "公式 $E=mc^2$ 在文中，另有块级公式："},
            {"type": "text", "text": "$$\\int_{0}^{\\infty} e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}$$"},
        ]),
        _make_question("包含表格的题目", segments=[
            {"type": "text", "text": "数据如下："},
            {"type": "table_markdown", "text": "| 姓名 | 成绩 |\n|------|------|\n| 张三 | 95 |\n| 李四 | 87 |"},
        ]),
        _make_question("包含化学式的题目：指出以下物质 H₂O, CO₂, Na⁺"),
    ]
    await generate_sample(
        "sample_rich_content.docx",
        questions=rich_questions,
        config=_make_config(title="富内容样例（图/公式/表/化学）", total_count=4),
        format="docx",
    )

    # 7. DOCX 100 questions stress test
    many_questions = [_make_question(f"压力测试第 {i} 题的内容，这是一道单选题", f"single_choice") for i in range(100)]
    await generate_sample(
        "sample_100_questions.docx",
        questions=many_questions,
        config=_make_config(title="100 道压力测试", total_count=100),
        format="docx",
    )

    print(f"\nDone. Samples in {SAMPLES_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
