"""PDF exporter using fpdf2 — generates A4 portrait exam paper documents.

Content strategy:
- 86% of current questions are plain text content with JSON option dicts.
- 14% use segments with pre-rendered image references (code, math, table images).
- No HTML/Markdown/LaTeX in current question data (408 CS exam bank).
- For future LaTeX content: rendered to PNG via ``latex_render``.
- All images are fetched server-side and embedded (no external resource loading
  during PDF generation).

Safe HTML handling:
- ``fpdf2`` only processes raw text — no HTML parsing or script execution.
- ``<script>``, event attributes, ``file://``, ``javascript:`` etc. are
  inherently inert. The module explicitly strips angle-bracket content
  from text fields as a defense-in-depth measure.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.core.config import settings
from app.features.question_type import QUESTION_TYPE_LABELS, QuestionType
from app.services.export.exporter_base import Exporter, ExportResult
from app.services.export.analysis_content import split_analysis_sections
from app.services.export.latex_render import (
    find_latex_segments,
    has_latex,
    latex_expression_to_text,
    latex_to_plain_text,
    render_latex_to_png,
)
from app.services.export.question_content import (
    clean_printable_text,
    extract_option_text,
    extract_question_text,
)
from app.services.export.space_allocator import get_answer_space_mm
from app.services.export.table_parser import parse_table
from app.services.export.table_renderer_pdf import render_table_to_pdf
from app.services.safe_remote_fetch import fetch_remote_bytes, is_safe_remote_url

logger = logging.getLogger(__name__)

# ── Page layout constants (mm) ──
PAGE_W = 210  # A4 width
PAGE_H = 297  # A4 height
MARGIN_L = 20
MARGIN_R = 20
MARGIN_T = 18
MARGIN_B = 17
BODY_W = PAGE_W - MARGIN_L - MARGIN_R  # 170 mm

# Monochrome exam-paper palette. Keep the document suitable for ordinary
# black-and-white printing and avoid decorative fills or brand colours.
_COLOR_TEXT = (0, 0, 0)
_COLOR_MUTED = (92, 92, 92)
_COLOR_LINE = (105, 105, 105)
_COLOR_LIGHT_LINE = (205, 205, 205)

# Fonts: a Song-style body and a restrained sans-serif heading mirror the
# conventional Chinese examination typography used by the reference paper.
_BODY_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic-gbsn00lp/gbsn00lp.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)
_HEADING_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)
_BODY_FONT_NAME = "ExamSong"
_HEADING_FONT_NAME = "ExamHei"
_FONT_NAME = _BODY_FONT_NAME

# PDF resource limits
_MAX_IMAGE_DOWNLOAD_SEC = 15
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB per image
_MAX_IMAGE_DIMENSION = 2000  # px
_MAX_IMAGE_PIXELS = 25_000_000
_MAX_CONCURRENT_DOWNLOADS = 4
_MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MB total
_QUESTION_IMAGE_MAX_WIDTH_RATIO = 0.90

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_LOCAL_ASSET_ROOTS = (
    os.path.join(_BACKEND_ROOT, "static", "question-assets"),
    os.path.join(_BACKEND_ROOT, "static", "formulas"),
)

# Thread pool for blocking image downloads
_image_executor = ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_DOWNLOADS, thread_name_prefix="pdf-img")


@dataclass
class PdfContext:
    """Per-task context for resource accounting and cleanup."""
    temp_dir: str
    downloaded: dict[str, str]  # cache: url -> local path
    total_image_bytes: int = 0


class PdfExporter(Exporter):
    """Generate A4 portrait exam-paper PDF using fpdf2."""

    def __init__(self, font_path: str | None = None):
        configured_body = getattr(settings, "EXPORT_PDF_BODY_FONT", "")
        configured_heading = getattr(settings, "EXPORT_PDF_HEADING_FONT", "")
        self._body_font_path = self._first_existing_font(
            font_path, configured_body, *_BODY_FONT_CANDIDATES,
        )
        self._heading_font_path = self._first_existing_font(
            configured_heading, *_HEADING_FONT_CANDIDATES, self._body_font_path,
        )

    @property
    def format_name(self) -> str:
        return "PDF"

    async def export(self, snapshot_data: dict, output_dir: str) -> ExportResult:
        """Generate the PDF document.

        Args:
            snapshot_data: Full snapshot dict (questions + config).
            output_dir: Temp dir for intermediate files (images, cache).

        Returns:
            ExportResult with PDF bytes.
        """
        questions = snapshot_data.get("questions", [])
        config = snapshot_data.get("config", {})

        ctx = PdfContext(
            temp_dir=output_dir,
            downloaded={},
        )

        try:
            pdf_bytes = await asyncio.get_running_loop().run_in_executor(
                None, self._generate_sync, questions, config, ctx,
            )
            return ExportResult(
                success=True,
                file_bytes=pdf_bytes,
                file_name=config.get("file_name", "export.pdf"),
                skip_count=config.get("skip_count", 0),
                skip_reasons=config.get("skip_reasons"),
            )
        except Exception as e:
            logger.exception("PDF generation failed")
            return ExportResult(
                success=False,
                error_message=str(e)[:200],
            )

    def _generate_sync(
        self,
        questions: list[dict],
        config: dict,
        ctx: PdfContext,
    ) -> bytes:
        """Synchronous PDF generation — runs in a thread-pool executor."""
        from fpdf import FPDF

        if not self._body_font_path:
            raise RuntimeError("未找到可用的中文 PDF 字体，请配置 EXPORT_PDF_BODY_FONT")

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
        pdf.set_auto_page_break(auto=True, margin=MARGIN_B)
        pdf.add_font(_BODY_FONT_NAME, "", self._body_font_path)
        pdf.add_font(_HEADING_FONT_NAME, "", self._heading_font_path)
        pdf.add_page()
        self._add_header(pdf, config)

        answer_section: list[dict] = []
        analysis_section: list[dict] = []
        group_by = config.get("group_by", "none")
        group_counts = Counter(
            q.get("_group_title", "") for q in questions if q.get("_group_title", "")
        )
        current_group = None
        group_index = 0

        for idx, q in enumerate(questions):
            question_num = idx + 1
            q_group = q.get("_group_title", "")
            new_group = bool(group_by != "none" and q_group and q_group != current_group)
            estimated = self._estimate_question_height(pdf, q, config, group_by)
            group_height = 13 if new_group else 0
            usable_height = PAGE_H - MARGIN_T - MARGIN_B

            # Move a normal-sized question (and its section heading) together to
            # the next page when it would otherwise be split. Very long
            # questions are allowed to flow naturally across pages.
            if estimated + group_height <= usable_height:
                remaining = PAGE_H - MARGIN_B - pdf.get_y()
                if remaining < estimated + group_height:
                    pdf.add_page()

            if new_group:
                current_group = q_group
                group_index += 1
                self._write_group_header(pdf, q_group, group_index, group_counts.get(q_group, 0))

            qt_label = self._get_question_type_label(q.get("question_type", ""))
            content_text = self._get_question_text(q)
            show_type = group_by != "question_type"
            self._write_question_stem(
                pdf, question_num, qt_label, content_text, q, ctx, show_type,
            )

            options = q.get("options") or {}
            if options:
                pdf.ln(0.8)
                self._write_options(pdf, options)

            space_mm = get_answer_space_mm(
                config.get("space_style", "standard"),
                q.get("question_type"),
            )
            if space_mm > 0:
                self._write_answer_space(pdf, space_mm)

            if config.get("answer_position") == "after_question":
                ans = latex_to_plain_text(self._sanitize_text(q.get("answer", "")))
                if ans:
                    self._write_labeled_paragraph(pdf, "答案", ans)

            if config.get("analysis_position") == "after_question":
                analysis_text = latex_to_plain_text(self._sanitize_text(q.get("analysis", "")))
                if analysis_text:
                    self._write_analysis_after_question(pdf, analysis_text)

            if config.get("answer_position") == "at_end":
                answer_section.append({
                    "num": question_num,
                    "answer": latex_to_plain_text(self._sanitize_text(q.get("answer", ""))),
                })
            if config.get("analysis_position") == "at_end":
                analysis_section.append({
                    "num": question_num,
                    "analysis": latex_to_plain_text(self._sanitize_text(q.get("analysis", ""))),
                })

            # Traditional exam layout uses whitespace rather than decorative
            # cards or horizontal separators between questions.
            pdf.ln(5)

        if answer_section:
            pdf.add_page()
            self._write_end_section_title(pdf, "参考答案")
            self._write_answer_grid(pdf, answer_section)

        analysis_section = [item for item in analysis_section if item.get("analysis")]
        if analysis_section:
            if not answer_section or PAGE_H - MARGIN_B - pdf.get_y() < 38:
                pdf.add_page()
            else:
                pdf.ln(6)
            self._write_end_section_title(pdf, "答案解析")
            for item in analysis_section:
                self._write_analysis_item(pdf, item["num"], item["analysis"])

        self._add_running_headers(pdf, config)
        self._add_page_numbers(pdf)
        return bytes(pdf.output())

    # ── Internal helpers ──

    @staticmethod
    def _first_existing_font(*paths: str | None) -> str | None:
        for path in paths:
            if path and os.path.isfile(path):
                return path
        return None

    @staticmethod
    def _chinese_section_number(value: int) -> str:
        numerals = [
            "零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
            "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
        ]
        if 0 <= value < len(numerals):
            return numerals[value]
        return str(value)

    @staticmethod
    def _formal_group_title(title: str) -> str:
        mapping = {
            "单选题": "单项选择题",
            "多选题": "多项选择题",
            "问答题": "简答题",
        }
        return mapping.get(title, title)

    def _add_header(self, pdf, config: dict) -> None:
        """Render a clean, centered first-page title like a printed exam."""
        title = self._sanitize_text(config.get("title", "错题巩固练习")) or "错题巩固练习"
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_HEADING_FONT_NAME, "", 16)
        pdf.multi_cell(
            BODY_W, 8.8, text=title, new_x="LMARGIN", new_y="NEXT",
            align="C", wrapmode="CHAR",
        )
        # No date, total-count strip, brand line, or decorative rule. The first
        # section heading carries the useful question count instead.
        pdf.ln(6.5)

    def _write_group_header(self, pdf, title: str, index: int, count: int) -> None:
        self._check_page_break(pdf, 15)
        formal = self._formal_group_title(title)
        suffix = f"（共{count}题）" if count else ""
        text = f"{self._chinese_section_number(index)}、{formal}{suffix}"
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_HEADING_FONT_NAME, "", 11)
        pdf.multi_cell(BODY_W, 6.5, text=text, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
        pdf.ln(2.6)

    def _write_question_stem(
        self,
        pdf,
        question_num: int,
        qt_label: str,
        content_text: str,
        question: dict,
        ctx: PdfContext,
        show_type: bool,
    ) -> None:
        prefix = f"{question_num}．"
        if show_type and qt_label:
            prefix += f"[{self._formal_group_title(qt_label)}]"

        content = question.get("content") if isinstance(question.get("content"), dict) else {}
        segments = (content or {}).get("segments") or []
        stem = self._sanitize_text(content_text).strip()

        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_BODY_FONT_NAME, "", 10)

        if stem and not has_latex(stem):
            pdf.multi_cell(
                BODY_W, 5.9, text=f"{prefix}{stem}",
                new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
            )
            # Some records store the textual stem separately and only put
            # figures/tables in segments. Render those supplemental elements
            # without discarding or duplicating the stem.
            visual_segments = [
                seg for seg in segments
                if seg.get("type") in ("code_image", "math_image", "table_image", "image", "table", "table_markdown")
            ]
            if visual_segments:
                self._write_segments(pdf, visual_segments, ctx)
        elif stem:
            self._write_latex_content(pdf, f"{prefix}{stem}", ctx)
            visual_segments = [
                seg for seg in segments
                if seg.get("type") in ("code_image", "math_image", "table_image", "image", "table", "table_markdown")
            ]
            if visual_segments:
                self._write_segments(pdf, visual_segments, ctx)
        elif segments:
            pdf.multi_cell(BODY_W, 5.9, text=prefix, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
            self._write_segments(pdf, segments, ctx)
        else:
            pdf.set_text_color(*_COLOR_MUTED)
            pdf.multi_cell(
                BODY_W, 5.9, text=f"{prefix}（题干内容未提供）",
                new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
            )
            pdf.set_text_color(*_COLOR_TEXT)

        segment_urls = {
            str(seg.get("url") or seg.get("src"))
            for seg in segments if seg.get("url") or seg.get("src")
        }
        for url in question.get("image_urls") or []:
            if url and str(url) not in segment_urls:
                self._embed_image(pdf, str(url), ctx)

    def _choose_option_columns(self, pdf, items: list[tuple[str, str]]) -> int:
        """Choose 4, 2, or 1 columns from actual rendered text width."""
        if not items:
            return 1
        indent = 7.0
        gap = 4.0
        rendered = [
            f"{key}．{latex_to_plain_text(extract_option_text(text))}"
            for key, text in items
        ]
        for columns in (4, 2):
            cell_w = (BODY_W - indent - gap * (columns - 1)) / columns
            if all(pdf.get_string_width(text) <= cell_w - 1.5 for text in rendered):
                return columns
        return 1

    def _write_options(self, pdf, options: dict) -> None:
        items = [(str(key), extract_option_text(options[key])) for key in sorted(options.keys())]
        columns = self._choose_option_columns(pdf, items)
        indent = 7.0
        gap = 4.0
        cell_w = (BODY_W - indent - gap * (columns - 1)) / columns
        line_h = 5.8
        pdf.set_font(_BODY_FONT_NAME, "", 9.8)
        pdf.set_text_color(*_COLOR_TEXT)

        for row_start in range(0, len(items), columns):
            row = items[row_start:row_start + columns]
            texts = [
                f"{key}．{latex_to_plain_text(self._sanitize_text(text))}"
                for key, text in row
            ]
            heights = [self._estimate_wrapped_height(pdf, text, cell_w, line_h) for text in texts]
            row_h = max(heights or [line_h])
            self._check_page_break(pdf, row_h + 1.2)
            y = pdf.get_y()
            for col, text in enumerate(texts):
                x = MARGIN_L + indent + col * (cell_w + gap)
                pdf.set_xy(x, y)
                pdf.multi_cell(
                    cell_w, line_h, text=text, new_x="RIGHT", new_y="TOP", wrapmode="CHAR",
                )
            pdf.set_xy(MARGIN_L, y + row_h + 0.7)

    def _write_answer_space(self, pdf, space_mm: float) -> None:
        # Blank writing area only; no decorative guide lines.
        space_mm = max(5, float(space_mm))
        remaining = PAGE_H - MARGIN_B - pdf.get_y()
        usable_height = PAGE_H - MARGIN_T - MARGIN_B
        if space_mm <= usable_height and remaining < space_mm:
            pdf.add_page()
        pdf.ln(space_mm)

    def _write_labeled_paragraph(self, pdf, label: str, text: str) -> None:
        self._check_page_break(pdf, 12)
        pdf.ln(1)
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_BODY_FONT_NAME, "", 10)
        pdf.multi_cell(
            BODY_W, 6, text=f"{label}：{text}",
            new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
        )

    def _write_analysis_after_question(self, pdf, text: str) -> None:
        """Render inline analysis with bold-ish section labels and body indent."""
        sections = split_analysis_sections(text)
        if not sections or not any(label for label, _ in sections):
            self._write_labeled_paragraph(pdf, "解析", text)
            return

        self._check_page_break(pdf, 14)
        pdf.ln(1)
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_HEADING_FONT_NAME, "", 10)
        pdf.cell(BODY_W, 6, text="解析", new_x="LMARGIN", new_y="NEXT")
        for label, body in sections:
            self._write_analysis_subsection(pdf, label, body, indent_mm=6)
        pdf.ln(1.5)

    def _write_analysis_item(self, pdf, number: int, text: str) -> None:
        """Render one end-of-document analysis entry with clear hierarchy."""
        sections = split_analysis_sections(text)
        if not sections or not any(label for label, _ in sections):
            self._check_page_break(pdf, 16)
            self._write_numbered_item(pdf, number, text, compact=False)
            return

        self._check_page_break(pdf, 18)
        first = True
        for label, body in sections:
            self._check_page_break(pdf, 12)
            heading = f"{number}．{label}" if first else label
            x = MARGIN_L if first else MARGIN_L + 6
            width = BODY_W if first else BODY_W - 6
            pdf.set_x(x)
            pdf.set_text_color(*_COLOR_TEXT)
            pdf.set_font(_HEADING_FONT_NAME, "", 10)
            pdf.multi_cell(
                width, 5.8, text=heading,
                new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
            )
            if body:
                self._write_analysis_body(pdf, body, indent_mm=8)
            pdf.ln(1.1)
            first = False
        pdf.ln(2.5)

    def _write_analysis_subsection(self, pdf, label: str, body: str, indent_mm: float = 6) -> None:
        self._check_page_break(pdf, 11)
        pdf.set_x(MARGIN_L + indent_mm)
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_HEADING_FONT_NAME, "", 9.8)
        pdf.cell(
            BODY_W - indent_mm, 5.6, text=label,
            new_x="LMARGIN", new_y="NEXT",
        )
        if body:
            self._write_analysis_body(pdf, body, indent_mm=indent_mm + 2)
        pdf.ln(0.8)

    def _write_analysis_body(self, pdf, body: str, indent_mm: float = 8) -> None:
        pdf.set_x(MARGIN_L + indent_mm)
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_BODY_FONT_NAME, "", 10)
        pdf.multi_cell(
            BODY_W - indent_mm, 6.1, text=body,
            new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
        )

    def _write_end_section_title(self, pdf, title: str) -> None:
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_HEADING_FONT_NAME, "", 14)
        pdf.cell(BODY_W, 8, text=title, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

    @staticmethod
    def _display_units(text: str) -> int:
        units = 0
        for char in str(text):
            units += 2 if unicodedata.east_asian_width(char) in ("W", "F", "A") else 1
        return units

    def _choose_answer_columns(self, items: list[dict]) -> int:
        answers = [self._sanitize_text(item.get("answer")) or "—" for item in items]
        max_units = max((self._display_units(answer) for answer in answers), default=1)
        if max_units <= 4:
            preferred = 6
        elif max_units <= 12:
            preferred = 4
        elif max_units <= 28:
            preferred = 2
        else:
            preferred = 1
        # Do not create a full-width six-column grid for only a few answers.
        return max(1, min(preferred, len(items)))

    def _write_answer_grid(self, pdf, items: list[dict]) -> None:
        """Render end answers as a bordered two-row-per-block answer table."""
        if not items:
            return
        columns = self._choose_answer_columns(items)
        self._write_answer_grid_group(pdf, items, columns)

    def _write_answer_grid_group(self, pdf, items: list[dict], columns: int) -> None:
        # Keep the answer key visually compact: short answers use a fixed,
        # narrow cell width and the whole table is centered instead of
        # stretching across the full printable page width.
        max_cell_w = 15.0 if columns >= 4 else 24.0 if columns == 2 else 56.0
        table_w = min(BODY_W, max_cell_w * columns)
        cell_w = table_w / columns
        table_x = MARGIN_L + (BODY_W - table_w) / 2

        num_h = 5.2
        line_h = 4.0
        pdf.set_draw_color(*_COLOR_TEXT)
        pdf.set_line_width(0.25)
        pdf.set_text_color(*_COLOR_TEXT)

        number_font_size = 9.2 if columns >= 4 else 9.0
        answer_font_size = 11.5 if columns >= 4 else 10.5

        for row_start in range(0, len(items), columns):
            row = items[row_start:row_start + columns]
            answers = [self._sanitize_text(item.get("answer")) or "—" for item in row]
            pdf.set_font(_BODY_FONT_NAME, "", answer_font_size)
            text_heights = [
                self._estimate_wrapped_height(pdf, answer, max(cell_w - 4, 10), line_h)
                for answer in answers
            ]
            answer_h = max(7.8, max(text_heights, default=line_h) + 1.8)
            block_h = num_h + answer_h
            self._check_page_break(pdf, block_h + 4)
            y = pdf.get_y()

            for col in range(columns):
                x = table_x + col * cell_w
                pdf.rect(x, y, cell_w, num_h)
                pdf.rect(x, y + num_h, cell_w, answer_h)

                if col < len(row):
                    item = row[col]
                    answer = answers[col]

                    pdf.set_xy(x, y)
                    pdf.set_font(_HEADING_FONT_NAME, "", number_font_size)
                    pdf.cell(cell_w, num_h, text=str(item["num"]), align="C")

                    pdf.set_font(_HEADING_FONT_NAME, "", answer_font_size)
                    text_h = text_heights[col]
                    text_y = y + num_h + max((answer_h - text_h) / 2, 0.35)
                    pdf.set_xy(x + 0.5, text_y)
                    pdf.multi_cell(
                        cell_w - 1.0, line_h, text=answer, align="C",
                        new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
                    )

            pdf.set_xy(MARGIN_L, y + block_h + 1.8)

    def _write_numbered_item(self, pdf, number: int, text: str, compact: bool) -> None:
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_BODY_FONT_NAME, "", 10.3 if compact else 10)
        pdf.multi_cell(
            BODY_W,
            6 if compact else 6.2,
            text=f"{number}．{text}",
            new_x="LMARGIN",
            new_y="NEXT",
            wrapmode="CHAR",
        )
        pdf.ln(2.5 if compact else 4)

    def _estimate_wrapped_height(self, pdf, text: str, width: float, line_height: float) -> float:
        """Conservative character-level line-wrap estimate for page planning."""
        if not text:
            return line_height
        lines = 1
        current = 0.0
        for char in str(text):
            if char == "\n":
                lines += 1
                current = 0.0
                continue
            char_w = max(0.2, pdf.get_string_width(char))
            if current + char_w > width and current > 0:
                lines += 1
                current = char_w
            else:
                current += char_w
        return lines * line_height

    def _estimate_question_height(self, pdf, q: dict, config: dict, group_by: str) -> float:
        qt_label = self._get_question_type_label(q.get("question_type", ""))
        prefix = "1．" + (f"[{self._formal_group_title(qt_label)}]" if group_by != "question_type" and qt_label else "")
        content = self._get_question_text(q)
        height = self._estimate_wrapped_height(
            pdf, prefix + latex_to_plain_text(content), BODY_W, 6.2,
        )

        segments = (
            q.get("content", {}).get("segments")
            if isinstance(q.get("content"), dict)
            else None
        ) or []
        for seg in segments:
            if seg.get("type") in ("code_image", "math_image", "table_image", "image"):
                height += 45
            elif seg.get("type") in ("table", "table_markdown"):
                height += 25

        options = q.get("options") or {}
        if options:
            items = [(str(key), str(options[key])) for key in sorted(options.keys())]
            columns = self._choose_option_columns(pdf, items)
            gap = 4.0
            cell_w = (BODY_W - 7.0 - gap * (columns - 1)) / columns
            height += 1.5
            for row_start in range(0, len(items), columns):
                row = items[row_start:row_start + columns]
                height += max(
                    self._estimate_wrapped_height(
                        pdf,
                        f"{key}．{latex_to_plain_text(self._sanitize_text(text))}",
                        cell_w,
                        5.8,
                    )
                    for key, text in row
                ) + 0.7

        height += max(0, float(get_answer_space_mm(
            config.get("space_style", "standard"), q.get("question_type"),
        )))
        if config.get("answer_position") == "after_question" and q.get("answer"):
            height += self._estimate_wrapped_height(
                pdf,
                f"答案：{latex_to_plain_text(self._sanitize_text(q.get('answer')))}",
                BODY_W,
                6,
            ) + 2
        if config.get("analysis_position") == "after_question" and q.get("analysis"):
            height += self._estimate_wrapped_height(
                pdf,
                f"解析：{latex_to_plain_text(self._sanitize_text(q.get('analysis')))}",
                BODY_W,
                6,
            ) + 2
        return height + 6

    def _write_content(self, pdf, text: str, question: dict, ctx: PdfContext):
        """Write question content, handling segments, images, and LaTeX."""
        segments = question.get("content", {}).get("segments") if isinstance(question.get("content"), dict) else None

        if segments:
            self._write_segments(pdf, segments, ctx)
        elif has_latex(text):
            self._write_latex_content(pdf, text, ctx)
        else:
            pdf.multi_cell(BODY_W, 5.9, text=text, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")

    def _write_segments(self, pdf, segments: list[dict], ctx: PdfContext):
        """Render a ``segments`` content array."""
        for seg in segments:
            seg_type = seg.get("type", "text")

            if seg_type == "text":
                text = self._sanitize_text(seg.get("text", ""))
                if text:
                    if has_latex(text):
                        self._write_latex_content(pdf, text, ctx)
                    else:
                        pdf.multi_cell(BODY_W, 5.9, text=text, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")

            elif seg_type == "newline":
                pdf.ln(2)

            elif seg_type in ("code_image", "math_image", "table_image", "image"):
                url = seg.get("url") or seg.get("src") or ""
                if url:
                    self._embed_image(pdf, url, ctx)

            elif seg_type in ("table", "table_markdown"):
                # Parse and render canonical or legacy tables through the
                # unified TableBlock model.
                blocks = parse_table(seg, source_type="segment")
                if blocks:
                    for block in blocks:
                        render_table_to_pdf(pdf, block)
                        pdf.ln(2)

    def _write_latex_content(self, pdf, text: str, ctx: PdfContext):
        """Render mixed text without promoting inline formulas to block images.

        Inline math is converted to compact Unicode/plain text and written in
        the same paragraph.  Display math remains an image, but is placed at
        its natural size with a conservative page-width cap.
        """
        segments = find_latex_segments(text)
        inline_parts: list[str] = []

        def flush_inline() -> None:
            content = "".join(inline_parts)
            inline_parts.clear()
            if content:
                pdf.multi_cell(
                    BODY_W, 5.9, text=content,
                    new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
                )

        for seg in segments:
            if seg["type"] == "text":
                inline_parts.append(seg["content"])
            elif not seg.get("display", False):
                inline_parts.append(latex_expression_to_text(seg["content"]))
            else:
                flush_inline()
                png = render_latex_to_png(seg["content"], True)
                if png:
                    img_path = self._save_temp_image(ctx, png, "latex")
                    try:
                        self._place_latex_image(pdf, img_path)
                    except Exception:
                        fallback = latex_expression_to_text(seg["content"])
                        pdf.multi_cell(BODY_W, 5.9, text=fallback, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
                else:
                    fallback = latex_expression_to_text(seg["content"])
                    pdf.multi_cell(
                        BODY_W, 5.9, text=fallback,
                        new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
                    )

        flush_inline()

    @staticmethod
    def _place_latex_image(pdf, image_path: str) -> None:
        """Place a display formula at natural size instead of page-wide scale."""
        from PIL import Image as PILImage

        with PILImage.open(image_path) as image:
            px_w, px_h = image.size
            dpi = image.info.get("dpi") or (150, 150)
        dpi_x = float(dpi[0] or 150)
        natural_w = max(5.0, px_w * 25.4 / dpi_x)
        draw_w = min(BODY_W * 0.85, natural_w)
        draw_h = draw_w * px_h / max(1, px_w)
        remaining = PAGE_H - MARGIN_B - pdf.get_y()
        if remaining < draw_h + 2 and pdf.get_y() > MARGIN_T + 5:
            pdf.add_page()
        x = MARGIN_L + max(0, (BODY_W - draw_w) / 2)
        y = pdf.get_y()
        pdf.image(image_path, x=x, y=y, w=draw_w, h=draw_h)
        pdf.set_y(y + draw_h + 2)

    def _embed_image(self, pdf, url: str, ctx: PdfContext) -> bool:
        """Resolve, validate, and embed an image at a readable natural size."""
        local_path = ctx.downloaded.get(url)
        if local_path and os.path.exists(local_path):
            try:
                self._place_image(pdf, local_path)
                return True
            except Exception:
                pass

        try:
            local_path = self._download_image_sync(url, ctx)
            if local_path:
                ctx.downloaded[url] = local_path
                self._place_image(pdf, local_path)
                return True
        except Exception as e:
            logger.warning("Image embed failed for %s: %s", url, e)

        # Fallback
        pdf.set_font(_FONT_NAME, "", 8)
        pdf.set_text_color(128, 128, 128)
        pdf.multi_cell(BODY_W, 4, text="图片加载失败", new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
        pdf.set_text_color(0, 0, 0)
        return False

    @staticmethod
    def _place_image(pdf, image_path: str) -> None:
        from PIL import Image as PILImage

        with PILImage.open(image_path) as image:
            px_w, px_h = image.size
            dpi = image.info.get("dpi") or (96, 96)
        dpi_x = float(dpi[0] or 96)
        natural_w = max(8.0, px_w * 25.4 / dpi_x)
        draw_w = min(BODY_W * _QUESTION_IMAGE_MAX_WIDTH_RATIO, natural_w)
        draw_h = draw_w * px_h / max(1, px_w)
        remaining = PAGE_H - MARGIN_B - pdf.get_y()
        if remaining < min(draw_h, 45) and pdf.get_y() > MARGIN_T + 5:
            pdf.add_page()
            remaining = PAGE_H - MARGIN_B - pdf.get_y()
        if draw_h > remaining:
            scale = remaining / draw_h
            draw_w *= scale
            draw_h *= scale
        x = MARGIN_L + max(0, (BODY_W - draw_w) / 2)
        y = pdf.get_y()
        pdf.image(image_path, x=x, y=y, w=draw_w, h=draw_h)
        pdf.set_y(y + draw_h + 2)

    def _download_image_sync(self, url: str, ctx: PdfContext) -> str | None:
        """Download an image to the temp directory with safety checks."""
        import hashlib
        filename = hashlib.md5(url.encode()).hexdigest() + ".png"
        dest = os.path.join(ctx.temp_dir, filename)

        if os.path.exists(dest):
            return dest

        try:
            local_source = self._resolve_local_asset(url)
            if local_source:
                with open(local_source, "rb") as source:
                    data = source.read(_MAX_IMAGE_BYTES + 1)
            else:
                remote_url = self._normalize_remote_url(url)
                if not remote_url or not self._is_safe_url(remote_url):
                    logger.warning("Blocked unsafe image URL: %s", url)
                    return None
                response = fetch_remote_bytes(
                    remote_url,
                    max_bytes=_MAX_IMAGE_BYTES,
                    timeout=_MAX_IMAGE_DOWNLOAD_SEC,
                    allow_http=settings.EXPORT_ALLOW_HTTP_IMAGE_URLS,
                    headers={"User-Agent": "MemoGrad-Export/2.0"},
                )
                if not self._is_safe_mime(response.content_type):
                    logger.warning("Unsafe image MIME: %s", response.content_type)
                    return None
                data = response.data

            if len(data) > _MAX_IMAGE_BYTES:
                logger.warning("Image too large: %d bytes from %s", len(data), url)
                return None
            if ctx.total_image_bytes + len(data) > _MAX_TOTAL_IMAGE_BYTES:
                logger.warning("Total image budget exceeded")
                return None
            return self._save_normalized_image(data, dest, url, ctx)

        except Exception as e:
            logger.warning("Image download failed for %s: %s", url, e)
            return None

    @staticmethod
    def _resolve_local_asset(url: str) -> str | None:
        import urllib.parse

        parsed = urllib.parse.urlsplit(str(url))
        path = urllib.parse.unquote(parsed.path or str(url).split("?", 1)[0])
        if not path.startswith(("/static/question-assets/", "/static/formulas/")):
            return None
        candidate = os.path.abspath(os.path.join(_BACKEND_ROOT, path.lstrip("/")))
        if not any(
            os.path.commonpath((candidate, root)) == root
            for root in _LOCAL_ASSET_ROOTS
        ):
            return None
        return candidate if os.path.isfile(candidate) else None

    @staticmethod
    def _normalize_remote_url(url: str) -> str | None:
        import urllib.parse

        parsed = urllib.parse.urlsplit(str(url))
        if parsed.scheme:
            return str(url)
        base = str(getattr(settings, "PUBLIC_BASE_URL", "") or "").strip()
        if not base:
            return None
        return urllib.parse.urljoin(base.rstrip("/") + "/", str(url).lstrip("/"))

    @staticmethod
    def _save_normalized_image(data: bytes, dest: str, source: str, ctx: PdfContext) -> str | None:
        from PIL import Image as PILImage

        try:
            with PILImage.open(io.BytesIO(data)) as image:
                width, height = image.size
                if width < 1 or height < 1 or width * height > _MAX_IMAGE_PIXELS:
                    logger.warning("Image pixel budget exceeded for %s", source)
                    return None
                image.load()
                if max(image.size) > _MAX_IMAGE_DIMENSION:
                    logger.info("Resizing oversized image %s (%dpx)", source, max(image.size))
                    image.thumbnail((_MAX_IMAGE_DIMENSION, _MAX_IMAGE_DIMENSION))
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                image.save(dest, format="PNG", optimize=True)
        except Exception as exc:
            logger.warning("Invalid image data from %s: %s", source, exc)
            return None
        ctx.total_image_bytes += len(data)
        return dest

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        return is_safe_remote_url(
            url,
            allow_http=settings.EXPORT_ALLOW_HTTP_IMAGE_URLS,
        )

    @staticmethod
    def _is_safe_mime(content_type: str) -> bool:
        safe = ("image/", "application/octet-stream")
        return any(content_type.startswith(s) for s in safe) if content_type else True

    @staticmethod
    def _save_temp_image(ctx: PdfContext, data: bytes, prefix: str) -> str:
        import hashlib
        filename = f"{prefix}_{hashlib.md5(data).hexdigest()[:12]}.png"
        dest = os.path.join(ctx.temp_dir, filename)
        with open(dest, "wb") as f:
            f.write(data)
        return dest

    @staticmethod
    def _get_question_text(q: dict) -> str:
        return extract_question_text(q)

    @staticmethod
    def _sanitize_text(text) -> str:
        return clean_printable_text(text)

    @staticmethod
    def _get_question_type_label(qt: str | None) -> str:
        if not qt:
            return ""
        try:
            return QUESTION_TYPE_LABELS.get(QuestionType(qt), "")
        except (ValueError, KeyError):
            return ""

    @staticmethod
    def _check_page_break(pdf, needed_mm: float, check_only: bool = False):
        """Check if there's enough room and add page if needed."""
        remaining = PAGE_H - MARGIN_B - pdf.get_y()
        if remaining < needed_mm:
            if not check_only:
                pdf.add_page()

    def _add_running_headers(self, pdf, config: dict) -> None:
        """Add the compact paper title to pages after the first."""
        title = self._sanitize_text(config.get("title", "错题巩固练习")) or "错题巩固练习"
        total = pdf.page_no()
        pdf.set_auto_page_break(False)
        for page_num in range(2, total + 1):
            pdf.page = page_num
            pdf.set_xy(MARGIN_L, 6.2)
            pdf.set_font(_BODY_FONT_NAME, "", 7.8)
            pdf.set_text_color(*_COLOR_MUTED)
            pdf.cell(BODY_W, 4, text=title, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(175, 175, 175)
            pdf.set_line_width(0.15)
            pdf.line(MARGIN_L, 12.2, PAGE_W - MARGIN_R, 12.2)
        pdf.page = total
        pdf.set_auto_page_break(True, margin=MARGIN_B)

    def _add_page_numbers(self, pdf) -> None:
        """Add the restrained centered ``· n ·`` footer used by exam papers."""
        total = pdf.page_no()
        pdf.set_auto_page_break(False)
        for page_num in range(1, total + 1):
            pdf.page = page_num
            pdf.set_xy(MARGIN_L, PAGE_H - 10.5)
            pdf.set_font(_BODY_FONT_NAME, "", 8)
            pdf.set_text_color(*_COLOR_MUTED)
            pdf.cell(
                BODY_W, 4.5, text=f"· {page_num} ·",
                align="C", new_x="LMARGIN", new_y="NEXT",
            )
        pdf.page = total
        pdf.set_auto_page_break(True, margin=MARGIN_B)
