"""Build acceptance input through the real exporter, without local sample files."""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from docx import Document

from app.services.export.docx_exporter import DocxExporter


def acceptance_snapshot() -> dict:
    stem = (
        "线性代数表格，并说明 H₂O 与 CO₂ 中的元素。"
        "<b>保留题意</b>，x<sup>2</sup>。"
    )
    table = {
        "type": "table",
        "rows": [
            {"cells": [{"text": "合并列", "col_span": 2, "is_header": True}]},
            {"cells": [{"text": "第一列"}, {"text": "第二列"}]},
        ],
    }
    return {
        "questions": [
            {
                "content": {"stem": stem, "text": stem, "segments": [
                    {"type": "text", "text": stem}, table,
                ]},
                "question_type": "short_answer", "answer": "略", "analysis": "表格分析",
                "options": {}, "subject": {"id": 1, "label": "数学"}, "_group_title": "",
            },
            {
                "content": {"text": r"计算矩阵 $\begin{pmatrix}1 & 2 \\ 3 & 4\end{pmatrix}$"},
                "question_type": "short_answer", "answer": "略", "analysis": "矩阵分析",
                "options": {}, "subject": {"id": 1, "label": "数学"}, "_group_title": "",
            },
        ],
        "config": {
            "title": "线性代数回归样本", "file_name": "phase3_acceptance.docx",
            "show_date": False, "export_date": "2026-10-20", "group_by": "none",
            "answer_position": "none", "analysis_position": "none",
            "space_style": "standard", "total_count": 2, "skip_count": 0,
        },
    }


def generate_acceptance_docx(directory: Path) -> Path:
    result = asyncio.run(DocxExporter().export(acceptance_snapshot(), str(directory)))
    assert result.success, f"Acceptance export failed: {result.error_message}"
    assert result.file_bytes
    with ZipFile(BytesIO(result.file_bytes)) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(archive.read(name))
    assert Document(BytesIO(result.file_bytes)).paragraphs
    output = directory / "phase3_acceptance.docx"
    output.write_bytes(result.file_bytes)
    return output
