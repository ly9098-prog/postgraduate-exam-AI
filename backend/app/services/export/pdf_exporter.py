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
import logging
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.core.config import settings
from app.features.question_type import QUESTION_TYPE_LABELS, QuestionType
from app.services.export.exporter_base import Exporter, ExportResult
from app.services.export.latex_render import (
    find_latex_segments,
    has_latex,
    render_latex_to_png,
)
from app.services.export.space_allocator import get_answer_space_mm
from app.services.export.table_parser import parse_table
from app.services.export.table_renderer_pdf import render_table_to_pdf

logger = logging.getLogger(__name__)

# ── Page layout constants (mm) ──
PAGE_W = 210  # A4 width
PAGE_H = 297  # A4 height
MARGIN_L = 18
MARGIN_R = 18
MARGIN_T = 17
MARGIN_B = 16
BODY_W = PAGE_W - MARGIN_L - MARGIN_R  # 174 mm

# Monochrome exam-paper palette. Keep the document suitable for ordinary
# black-and-white printing and avoid decorative fills or brand colours.
_COLOR_TEXT = (0, 0, 0)
_COLOR_MUTED = (92, 92, 92)
_COLOR_LINE = (105, 105, 105)
_COLOR_LIGHT_LINE = (205, 205, 205)

# Fonts: a Song-style body and a restrained sans-serif heading mirror the
# conventional Chinese examination typography used by the reference paper.
_DEFAULT_BODY_FONT_PATH = "/usr/share/fonts/truetype/arphic-gbsn00lp/gbsn00lp.ttf"
_DEFAULT_HEADING_FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
_FALLBACK_FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
_BODY_FONT_NAME = "ExamSong"
_HEADING_FONT_NAME = "ExamHei"
_FONT_NAME = _BODY_FONT_NAME

# PDF resource limits
_MAX_IMAGE_DOWNLOAD_SEC = 15
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB per image
_MAX_IMAGE_DIMENSION = 2000  # px
_MAX_CONCURRENT_DOWNLOADS = 4
_MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MB total

# Text sanitisation: strip angle-bracket content as defense-in-depth
_HTML_TAG_RE = re.compile(r"<[^>]*>")

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
        self._body_font_path = font_path or (
            _DEFAULT_BODY_FONT_PATH if os.path.exists(_DEFAULT_BODY_FONT_PATH) else _FALLBACK_FONT_PATH
        )
        self._heading_font_path = (
            _DEFAULT_HEADING_FONT_PATH if os.path.exists(_DEFAULT_HEADING_FONT_PATH) else self._body_font_path
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
                ans = self._sanitize_text(q.get("answer", ""))
                if ans:
                    self._write_labeled_paragraph(pdf, "答案", ans)

            if config.get("analysis_position") == "after_question":
                analysis_text = self._sanitize_text(q.get("analysis", ""))
                if analysis_text:
                    self._write_labeled_paragraph(pdf, "解析", analysis_text)

            if config.get("answer_position") == "at_end":
                answer_section.append({
                    "num": question_num,
                    "answer": self._sanitize_text(q.get("answer", "")),
                })
            if config.get("analysis_position") == "at_end":
                analysis_section.append({
                    "num": question_num,
                    "analysis": self._sanitize_text(q.get("analysis", "")),
                })

            # Traditional exam layout uses whitespace rather than decorative
            # cards or horizontal separators between questions.
            pdf.ln(5)

        if answer_section:
            pdf.add_page()
            self._write_end_section_title(pdf, "参考答案")
            for item in answer_section:
                self._check_page_break(pdf, 10)
                self._write_numbered_item(
                    pdf, item["num"], item.get("answer") or "未提供答案", compact=True,
                )

        if analysis_section:
            pdf.add_page()
            self._write_end_section_title(pdf, "答案解析")
            for item in analysis_section:
                if not item.get("analysis"):
                    continue
                self._check_page_break(pdf, 16)
                self._write_numbered_item(
                    pdf, item["num"], item["analysis"], compact=False,
                )

        self._add_running_headers(pdf, config)
        self._add_page_numbers(pdf)
        return pdf.output()

    # ── Internal helpers ──

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
        pdf.set_font(_HEADING_FONT_NAME, "", 18)
        pdf.multi_cell(
            BODY_W, 10, text=title, new_x="LMARGIN", new_y="NEXT",
            align="C", wrapmode="CHAR",
        )
        # No date, total-count strip, brand line, or decorative rule. The first
        # section heading carries the useful question count instead.
        pdf.ln(8)

    def _write_group_header(self, pdf, title: str, index: int, count: int) -> None:
        self._check_page_break(pdf, 15)
        formal = self._formal_group_title(title)
        suffix = f"（共{count}题）" if count else ""
        text = f"{self._chinese_section_number(index)}、{formal}{suffix}"
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_HEADING_FONT_NAME, "", 13)
        pdf.multi_cell(BODY_W, 7.2, text=text, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
        pdf.ln(3.2)

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
        pdf.set_font(_BODY_FONT_NAME, "", 10.5)

        if stem and not has_latex(stem):
            pdf.multi_cell(
                BODY_W, 6.2, text=f"{prefix}{stem}",
                new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
            )
            # Some records store the textual stem separately and only put
            # figures/tables in segments. Render those supplemental elements
            # without discarding or duplicating the stem.
            visual_segments = [
                seg for seg in segments
                if seg.get("type") in ("code_image", "math_image", "table_image", "image", "table_markdown")
            ]
            if visual_segments:
                self._write_segments(pdf, visual_segments, ctx)
        elif stem:
            pdf.multi_cell(BODY_W, 6.2, text=prefix, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
            self._write_latex_content(pdf, stem, ctx)
            visual_segments = [
                seg for seg in segments
                if seg.get("type") in ("code_image", "math_image", "table_image", "image", "table_markdown")
            ]
            if visual_segments:
                self._write_segments(pdf, visual_segments, ctx)
        elif segments:
            pdf.multi_cell(BODY_W, 6.2, text=prefix, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
            self._write_segments(pdf, segments, ctx)
        else:
            pdf.set_text_color(*_COLOR_MUTED)
            pdf.multi_cell(
                BODY_W, 6.2, text=f"{prefix}（题干内容未提供）",
                new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
            )
            pdf.set_text_color(*_COLOR_TEXT)

        segment_urls = {
            str(seg.get("url")) for seg in segments if seg.get("url")
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
        rendered = [f"{key}．{self._sanitize_text(text)}" for key, text in items]
        for columns in (4, 2):
            cell_w = (BODY_W - indent - gap * (columns - 1)) / columns
            if all(pdf.get_string_width(text) <= cell_w - 1.5 for text in rendered):
                return columns
        return 1

    def _write_options(self, pdf, options: dict) -> None:
        items = [(str(key), str(options[key])) for key in sorted(options.keys())]
        columns = self._choose_option_columns(pdf, items)
        indent = 7.0
        gap = 4.0
        cell_w = (BODY_W - indent - gap * (columns - 1)) / columns
        line_h = 5.8
        pdf.set_font(_BODY_FONT_NAME, "", 10.3)
        pdf.set_text_color(*_COLOR_TEXT)

        for row_start in range(0, len(items), columns):
            row = items[row_start:row_start + columns]
            texts = [f"{key}．{self._sanitize_text(text)}" for key, text in row]
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

    def _write_end_section_title(self, pdf, title: str) -> None:
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_HEADING_FONT_NAME, "", 15)
        pdf.cell(BODY_W, 9, text=title, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(8)

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
        height = self._estimate_wrapped_height(pdf, prefix + content, BODY_W, 6.2)

        segments = (
            q.get("content", {}).get("segments")
            if isinstance(q.get("content"), dict)
            else None
        ) or []
        for seg in segments:
            if seg.get("type") in ("code_image", "math_image", "table_image", "image"):
                height += 45
            elif seg.get("type") == "table_markdown":
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
                        pdf, f"{key}．{self._sanitize_text(text)}", cell_w, 5.8,
                    )
                    for key, text in row
                ) + 0.7

        height += max(0, float(get_answer_space_mm(
            config.get("space_style", "standard"), q.get("question_type"),
        )))
        if config.get("answer_position") == "after_question" and q.get("answer"):
            height += self._estimate_wrapped_height(pdf, f"答案：{q.get('answer')}", BODY_W, 6) + 2
        if config.get("analysis_position") == "after_question" and q.get("analysis"):
            height += self._estimate_wrapped_height(pdf, f"解析：{q.get('analysis')}", BODY_W, 6) + 2
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
                pdf.multi_cell(BODY_W, 5.9, text=seg.get("text", ""), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")

            elif seg_type == "newline":
                pdf.ln(2)

            elif seg_type in ("code_image", "math_image", "table_image", "image"):
                url = seg.get("url", "")
                if url:
                    self._embed_image(pdf, url, ctx)
                    alt = seg.get("alt", "")
                    if alt:
                        pdf.set_font(_FONT_NAME, "", 8)
                        pdf.set_text_color(128, 128, 128)
                        pdf.multi_cell(BODY_W, 4, text=f"({alt})", new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
                        pdf.set_text_color(0, 0, 0)

            elif seg_type == "table_markdown":
                # Parse and render as PDF table using unified TableBlock
                md_text = seg.get("text", "")
                if md_text:
                    blocks = parse_table(md_text, source_type="markdown")
                    if blocks:
                        for block in blocks:
                            render_table_to_pdf(pdf, block)
                            pdf.ln(2)

    def _write_latex_content(self, pdf, text: str, ctx: PdfContext):
        """Split text into plain + LaTeX segments and render each."""
        segments = find_latex_segments(text)
        for seg in segments:
            if seg["type"] == "text":
                pdf.multi_cell(BODY_W, 5.9, text=seg["content"], new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
            else:
                png = render_latex_to_png(seg["content"], seg.get("display", False))
                if png:
                    img_path = self._save_temp_image(ctx, png, "latex")
                    try:
                        pdf.image(img_path, w=BODY_W * 0.8)
                    except Exception:
                        pdf.multi_cell(BODY_W, 5.9, text=seg["content"], new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
                else:
                    # Fallback: raw LaTeX
                    pdf.set_font(_FONT_NAME, "", 8)
                    pdf.set_text_color(128, 128, 128)
                    pdf.multi_cell(
                        BODY_W, 4,
                        text=f"[公式] {seg['content']}",
                        new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR",
                    )
                    pdf.set_text_color(0, 0, 0)

    def _embed_image(self, pdf, url: str, ctx: PdfContext) -> bool:
        """Download and embed an image in the PDF."""
        local_path = ctx.downloaded.get(url)
        if local_path and os.path.exists(local_path):
            try:
                pdf.image(local_path, w=BODY_W)
                return True
            except Exception:
                pass

        # Download image
        try:
            local_path = self._download_image_sync(url, ctx)
            if local_path:
                ctx.downloaded[url] = local_path
                pdf.image(local_path, w=BODY_W)
                return True
        except Exception as e:
            logger.warning("Image embed failed for %s: %s", url, e)

        # Fallback
        pdf.set_font(_FONT_NAME, "", 8)
        pdf.set_text_color(128, 128, 128)
        pdf.multi_cell(BODY_W, 4, text="图片加载失败", new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
        pdf.set_text_color(0, 0, 0)
        return False

    def _download_image_sync(self, url: str, ctx: PdfContext) -> str | None:
        """Download an image to the temp directory with safety checks."""
        import hashlib
        import urllib.parse
        import urllib.request

        # Validate URL — SSRF protection
        if not self._is_safe_url(url):
            logger.warning("Blocked unsafe image URL: %s", url)
            return None

        ext = self._guess_extension(url)
        filename = hashlib.md5(url.encode()).hexdigest() + ext
        dest = os.path.join(ctx.temp_dir, filename)

        if os.path.exists(dest):
            return dest

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MemoGrad-Export/1.0"})
            with urllib.request.urlopen(req, timeout=_MAX_IMAGE_DOWNLOAD_SEC) as resp:
                data = resp.read()

            if len(data) > _MAX_IMAGE_BYTES:
                logger.warning("Image too large: %d bytes from %s", len(data), url)
                return None

            if ctx.total_image_bytes + len(data) > _MAX_TOTAL_IMAGE_BYTES:
                logger.warning("Total image budget exceeded")
                return None

            content_type = resp.headers.get("Content-Type", "")
            if not self._is_safe_mime(content_type):
                logger.warning("Unsafe image MIME: %s", content_type)
                return None

            # Validate actual file content (PIL check)
            import io

            from PIL import Image as PILImage
            try:
                img = PILImage.open(io.BytesIO(data))
                img.verify()
                # Resize if too large
                if max(img.size) > _MAX_IMAGE_DIMENSION:
                    logger.info("Resizing oversized image %s (%dpx)", url, max(img.size))
            except Exception as e:
                logger.warning("Invalid image data from %s: %s", url, e)
                return None

            with open(dest, "wb") as f:
                f.write(data)
            ctx.total_image_bytes += len(data)
            return dest

        except Exception as e:
            logger.warning("Image download failed for %s: %s", url, e)
            return None

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        """SSRF protection: reject private/internal URLs."""
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.scheme == "http" and not settings.OCR_ALLOW_HTTP:
            return False

        host = parsed.hostname or ""
        # Reject localhost
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        # Reject private IP ranges
        import ipaddress
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
            # Cloud metadata
            if host == "169.254.169.254":
                return False
        except ValueError:
            pass  # hostname (not IP) — allow

        # Reject file://, ftp://, etc.
        if parsed.scheme not in ("http", "https"):
            return False

        return True

    @staticmethod
    def _is_safe_mime(content_type: str) -> bool:
        safe = ("image/", "application/octet-stream")
        return any(content_type.startswith(s) for s in safe) if content_type else True

    @staticmethod
    def _guess_extension(url: str) -> str:
        import os
        _, ext = os.path.splitext(url.split("?")[0])
        return ext if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif") else ".png"

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
        """Extract display text with the same fallback order as DataBuilder."""
        content = q.get("content") or {}
        if isinstance(content, dict):
            direct = content.get("stem") or content.get("text")
            if direct:
                return str(direct)
            segment_text = "".join(
                str(seg.get("text") or "")
                for seg in (content.get("segments") or [])
                if isinstance(seg, dict) and seg.get("type", "text") == "text"
            ).strip()
            if segment_text:
                return segment_text
        elif content:
            return str(content)
        return str(q.get("raw_content") or "")

    @staticmethod
    def _sanitize_text(text: str | None) -> str:
        """Strip angle-bracket content as defense-in-depth."""
        if not text:
            return ""
        return _HTML_TAG_RE.sub("", text)

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
            pdf.cell(BODY_W, 4, text=title, align="C", new_x="LMARGIN", new_y="NEXT")
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
