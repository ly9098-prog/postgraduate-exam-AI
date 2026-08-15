"""Export helpers for the admin question bank.

This module intentionally keeps admin exports synchronous and lightweight:
CSV is generated in-memory for spreadsheet review, while DOCX is generated
with python-docx for printable/shareable question-bank snapshots.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.question import Question
from app.schemas.admin_questions import AdminQuestionExportRequest
from app.services.admin_question_service import list_admin_questions
from app.services.knowledge_point_service import load_question_kps

_MAX_EXPORT_QUESTIONS = 5000

_TYPE_LABELS = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "true_false": "判断题",
    "fill_blank": "填空题",
    "multi_blank_choice": "多空选择题",
    "subjective": "问答题",
}
_DIFFICULTY_LABELS = {1: "简单", 2: "较易", 3: "中等", 4: "较难", 5: "困难"}


def _content_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, dict):
        return str(content)

    for key in ("stem", "text", "question", "title"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    segments = content.get("segments")
    if isinstance(segments, list):
        chunks: list[str] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            if segment.get("type") == "newline":
                chunks.append("\n")
                continue
            text = segment.get("text")
            if isinstance(text, str):
                chunks.append(text)
        joined = "".join(chunks).strip()
        if joined:
            return joined

    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _option_value_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        image_url = value.get("image_url") or value.get("imageUrl") or value.get("url")
        if isinstance(text, str) and image_url:
            return f"{text} [图片: {image_url}]"
        if isinstance(text, str):
            return text
        if image_url:
            return f"[图片: {image_url}]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _options_text(options: object) -> str:
    if options is None:
        return ""
    if isinstance(options, str):
        return options
    if isinstance(options, dict):
        return "\n".join(
            f"{key}. {_option_value_text(value)}" for key, value in options.items()
        )
    if isinstance(options, list):
        rows: list[str] = []
        for index, value in enumerate(options):
            if isinstance(value, dict) and isinstance(value.get("key"), str):
                key = value["key"]
            else:
                key = chr(ord("A") + index) if index < 26 else str(index + 1)
            rows.append(f"{key}. {_option_value_text(value)}")
        return "\n".join(rows)
    return json.dumps(options, ensure_ascii=False, separators=(",", ":"))


async def _resolve_questions(
    db: AsyncSession,
    request: AdminQuestionExportRequest,
) -> list[Question]:
    if request.ids:
        result = await db.execute(
            select(Question)
            .options(selectinload(Question.subject_ref))
            .where(Question.id.in_(request.ids))
            .order_by(Question.updated_at.desc(), Question.id.desc())
        )
        questions = list(result.scalars().all())
        if not questions:
            raise ValueError("没有可导出的题目")
        return questions

    questions, total = await list_admin_questions(
        db,
        page=1,
        page_size=_MAX_EXPORT_QUESTIONS + 1,
        subject_id=request.subject_id,
        review_status=request.review_status,
        is_active=request.is_active,
        question_type=request.question_type,
        keyword=request.keyword,
        year=request.year,
        import_batch_id=request.import_batch_id,
        difficulty=request.difficulty,
    )
    if total == 0:
        raise ValueError("没有可导出的题目")
    if total > _MAX_EXPORT_QUESTIONS:
        raise ValueError(f"单次最多导出 {_MAX_EXPORT_QUESTIONS} 道题，请缩小筛选范围")
    return questions


def _rows(
    questions: Iterable[Question],
    kp_map: dict[int, list[str]],
) -> Iterable[list[str]]:
    for question in questions:
        subject_name = ""
        if getattr(question, "subject_ref", None) is not None:
            subject_name = question.subject_ref.name or question.subject_ref.code or ""
        yield [
            str(question.id),
            subject_name,
            _TYPE_LABELS.get(question.question_type, question.question_type),
            _DIFFICULTY_LABELS.get(question.difficulty, str(question.difficulty)),
            "启用" if question.is_active else "停用",
            str(question.year or ""),
            _content_text(question.content),
            _options_text(question.options),
            question.answer or "",
            question.analysis or "",
            "、".join(kp_map.get(question.id, [])),
            question.source or "",
            question.updated_at.strftime("%Y-%m-%d %H:%M:%S") if question.updated_at else "",
        ]


def _build_csv(questions: list[Question], kp_map: dict[int, list[str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "题目ID",
            "科目",
            "题型",
            "难度",
            "状态",
            "年份",
            "题干",
            "选项",
            "答案",
            "解析",
            "知识点",
            "来源",
            "更新时间",
        ]
    )
    writer.writerows(_rows(questions, kp_map))
    # UTF-8 BOM keeps Chinese text readable when opened directly in Excel.
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _set_east_asia_font(run, font_name: str = "微软雅黑") -> None:
    from docx.oxml.ns import qn

    run.font.name = font_name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)


def _build_docx(questions: list[Question], kp_map: dict[int, list[str]]) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = Document()
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run("正式题库导出")
    title_run.bold = True
    title_run.font.size = Pt(18)
    _set_east_asia_font(title_run)

    summary = document.add_paragraph()
    summary_run = summary.add_run(
        f"共 {len(questions)} 道题 · 导出时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    summary_run.font.size = Pt(9)
    _set_east_asia_font(summary_run)

    for index, question in enumerate(questions, start=1):
        subject_name = ""
        if getattr(question, "subject_ref", None) is not None:
            subject_name = question.subject_ref.name or question.subject_ref.code or ""

        heading = document.add_paragraph()
        heading_run = heading.add_run(f"{index}. [#{question.id}] {_content_text(question.content)}")
        heading_run.bold = True
        heading_run.font.size = Pt(11)
        _set_east_asia_font(heading_run)

        meta = document.add_paragraph()
        meta_parts = [
            _TYPE_LABELS.get(question.question_type, question.question_type),
            _DIFFICULTY_LABELS.get(question.difficulty, str(question.difficulty)),
            "启用" if question.is_active else "停用",
        ]
        if subject_name:
            meta_parts.insert(0, subject_name)
        if question.year:
            meta_parts.append(str(question.year))
        meta_run = meta.add_run(" · ".join(meta_parts))
        meta_run.font.size = Pt(8.5)
        _set_east_asia_font(meta_run)

        options = _options_text(question.options)
        if options:
            p = document.add_paragraph()
            r = p.add_run(options)
            r.font.size = Pt(10)
            _set_east_asia_font(r)

        answer = document.add_paragraph()
        answer_run = answer.add_run(f"答案：{question.answer or '—'}")
        answer_run.bold = True
        answer_run.font.size = Pt(10)
        _set_east_asia_font(answer_run)

        if question.analysis:
            analysis = document.add_paragraph()
            analysis_run = analysis.add_run(f"解析：{question.analysis}")
            analysis_run.font.size = Pt(9.5)
            _set_east_asia_font(analysis_run)

        kps = kp_map.get(question.id, [])
        if kps:
            kp_paragraph = document.add_paragraph()
            kp_run = kp_paragraph.add_run(f"知识点：{'、'.join(kps)}")
            kp_run.font.size = Pt(8.5)
            _set_east_asia_font(kp_run)

        if index != len(questions):
            document.add_paragraph("—" * 28)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def build_admin_question_export(
    db: AsyncSession,
    request: AdminQuestionExportRequest,
) -> tuple[bytes, str, str]:
    questions = await _resolve_questions(db, request)
    kp_map = await load_question_kps(db, [question.id for question in questions])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if request.format == "docx":
        return (
            await asyncio.to_thread(_build_docx, questions, kp_map),
            f"question-bank_{timestamp}.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    return (
        await asyncio.to_thread(_build_csv, questions, kp_map),
        f"question-bank_{timestamp}.csv",
        "text/csv; charset=utf-8",
    )
