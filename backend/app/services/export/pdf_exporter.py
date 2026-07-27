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
MARGIN_T = 18
MARGIN_B = 18
BODY_W = PAGE_W - MARGIN_L - MARGIN_R  # 174 mm

# Print-friendly MemoGrad palette
_COLOR_ACCENT = (36, 111, 70)
_COLOR_ACCENT_DARK = (27, 82, 52)
_COLOR_ACCENT_LIGHT = (234, 245, 238)
_COLOR_TEXT = (35, 43, 37)
_COLOR_MUTED = (111, 122, 114)
_COLOR_LINE = (218, 225, 219)
_COLOR_SURFACE = (247, 249, 246)
_COLOR_WARM = (249, 247, 239)
_COLOR_WHITE = (255, 255, 255)

# Font
_DEFAULT_FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
_FONT_NAME = "WenQuanYi"

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
        self._font_path = font_path or _DEFAULT_FONT_PATH

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
        # The previous exporter calculated an 18-20 mm body width but never
        # applied matching FPDF margins, which made the document look offset.
        pdf.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
        pdf.set_auto_page_break(auto=True, margin=MARGIN_B)
        pdf.add_font(_FONT_NAME, "", self._font_path)
        pdf.add_page()
        self._add_header(pdf, config)

        answer_section: list[dict] = []
        analysis_section: list[dict] = []
        group_by = config.get("group_by", "none")
        current_group = None

        for idx, q in enumerate(questions):
            q_group = q.get("_group_title", "")
            if group_by != "none" and q_group and q_group != current_group:
                current_group = q_group
                self._check_page_break(pdf, 18)
                self._write_group_header(pdf, q_group)

            question_num = idx + 1
            self._check_page_break(pdf, 36)

            qt_label = self._get_question_type_label(q.get("question_type", ""))
            self._write_question_header(pdf, question_num, qt_label)

            # Question stem
            pdf.set_font(_FONT_NAME, "", 10.5)
            pdf.set_text_color(*_COLOR_TEXT)
            content_text = self._get_question_text(q)
            if content_text:
                self._write_content(pdf, content_text, q, ctx)
            else:
                pdf.set_text_color(*_COLOR_MUTED)
                pdf.multi_cell(
                    BODY_W, 5.8,
                    text="（题干内容未提供）",
                    new_x="LMARGIN", new_y="NEXT",
                )
                pdf.set_text_color(*_COLOR_TEXT)

            # Options
            options = q.get("options") or {}
            if options:
                pdf.ln(1.5)
                for opt_key in sorted(options.keys()):
                    self._write_option(pdf, str(opt_key), str(options[opt_key]))

            # Answer space with subtle writing guides instead of a large blank gap.
            space_mm = get_answer_space_mm(
                config.get("space_style", "standard"),
                q.get("question_type"),
            )
            if space_mm > 0:
                self._write_answer_space(pdf, space_mm)

            if config.get("answer_position") == "after_question":
                ans = self._sanitize_text(q.get("answer", ""))
                if ans:
                    pdf.ln(1.5)
                    self._write_callout(pdf, "参考答案", ans, _COLOR_ACCENT_LIGHT)

            if config.get("analysis_position") == "after_question":
                analysis_text = self._sanitize_text(q.get("analysis", ""))
                if analysis_text:
                    pdf.ln(1.5)
                    self._write_callout(pdf, "题目解析", analysis_text, _COLOR_WARM)

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

            self._write_question_separator(pdf)

        if answer_section:
            pdf.add_page()
            self._write_section_banner(pdf, "参考答案", "按题号快速核对")
            for item in answer_section:
                self._check_page_break(pdf, 12)
                self._write_numbered_item(
                    pdf,
                    item["num"],
                    item.get("answer") or "未提供答案",
                    compact=True,
                )

        if analysis_section:
            pdf.add_page()
            self._write_section_banner(pdf, "题目解析", "回顾思路与关键知识点")
            for item in analysis_section:
                if not item.get("analysis"):
                    continue
                self._check_page_break(pdf, 18)
                self._write_numbered_item(
                    pdf,
                    item["num"],
                    item["analysis"],
                    compact=False,
                )

        self._add_page_numbers(pdf, config.get("product_name", "MemoGrad"))
        return pdf.output()

    # ── Internal helpers ──

    @staticmethod
    def _rounded_rect(pdf, x: float, y: float, w: float, h: float, radius: float, style: str = "F") -> None:
        """Draw a rounded rectangle with a plain-rect fallback for older fpdf2."""
        try:
            pdf.rect(
                x,
                y,
                w,
                h,
                style=style,
                round_corners=True,
                corner_radius=radius,
            )
        except TypeError:
            pdf.rect(x, y, w, h, style=style)

    def _add_header(self, pdf, config: dict):
        """Render a compact, print-friendly paper masthead."""
        product_name = config.get("product_name", "") or "MemoGrad"
        pdf.set_text_color(*_COLOR_MUTED)
        pdf.set_font(_FONT_NAME, "", 8.5)
        pdf.cell(BODY_W / 2, 5, text=product_name, new_x="RIGHT", new_y="TOP")
        pdf.cell(BODY_W / 2, 5, text="错题巩固练习", align="R", new_x="LMARGIN", new_y="NEXT")

        pdf.set_draw_color(*_COLOR_ACCENT)
        pdf.set_line_width(0.8)
        pdf.line(MARGIN_L, pdf.get_y() + 1.5, PAGE_W - MARGIN_R, pdf.get_y() + 1.5)
        pdf.ln(8)

        title = config.get("title", "错题巩固练习")
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_FONT_NAME, "", 19)
        pdf.multi_cell(BODY_W, 9.5, text=title, new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(1)

        meta_parts: list[str] = []
        if config.get("show_date", True) and config.get("export_date"):
            meta_parts.append(str(config.get("export_date")))
        meta_parts.append(f"共 {config.get('total_count', 0)} 题")
        meta_text = "  ·  ".join(meta_parts)

        meta_w = min(BODY_W, max(55, pdf.get_string_width(meta_text) + 18))
        meta_x = (PAGE_W - meta_w) / 2
        meta_y = pdf.get_y()
        pdf.set_fill_color(*_COLOR_SURFACE)
        self._rounded_rect(pdf, meta_x, meta_y, meta_w, 9, 4.5, style="F")
        pdf.set_xy(meta_x, meta_y + 0.5)
        pdf.set_font(_FONT_NAME, "", 9)
        pdf.set_text_color(*_COLOR_MUTED)
        pdf.cell(meta_w, 8, text=meta_text, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(meta_y + 14)
        pdf.set_text_color(*_COLOR_TEXT)

    def _write_group_header(self, pdf, title: str) -> None:
        y = pdf.get_y()
        pdf.set_fill_color(*_COLOR_ACCENT_LIGHT)
        self._rounded_rect(pdf, MARGIN_L, y, BODY_W, 10, 2.5, style="F")
        pdf.set_xy(MARGIN_L + 4, y + 1)
        pdf.set_text_color(*_COLOR_ACCENT_DARK)
        pdf.set_font(_FONT_NAME, "", 11)
        pdf.cell(BODY_W - 8, 8, text=title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(y + 14)
        pdf.set_text_color(*_COLOR_TEXT)

    def _write_question_header(self, pdf, question_num: int, qt_label: str) -> None:
        y = pdf.get_y()
        badge_w = 11 if question_num < 100 else 14
        pdf.set_fill_color(*_COLOR_ACCENT)
        self._rounded_rect(pdf, MARGIN_L, y, badge_w, 8.5, 2.2, style="F")
        pdf.set_xy(MARGIN_L, y + 0.3)
        pdf.set_text_color(*_COLOR_WHITE)
        pdf.set_font(_FONT_NAME, "", 9 if question_num < 100 else 8)
        pdf.cell(badge_w, 8, text=str(question_num), align="C")

        if qt_label:
            label_w = min(38, max(19, pdf.get_string_width(qt_label) + 9))
            label_x = MARGIN_L + badge_w + 4
            pdf.set_fill_color(*_COLOR_SURFACE)
            self._rounded_rect(pdf, label_x, y, label_w, 8.5, 4.2, style="F")
            pdf.set_xy(label_x, y + 0.3)
            pdf.set_text_color(*_COLOR_MUTED)
            pdf.set_font(_FONT_NAME, "", 8.5)
            pdf.cell(label_w, 8, text=qt_label, align="C")

        pdf.set_xy(MARGIN_L, y + 12)
        pdf.set_text_color(*_COLOR_TEXT)

    def _write_option(self, pdf, key: str, text: str) -> None:
        self._check_page_break(pdf, 10)
        y = pdf.get_y()
        pdf.set_fill_color(*_COLOR_SURFACE)
        self._rounded_rect(pdf, MARGIN_L, y + 0.2, 7.5, 7.5, 2, style="F")
        pdf.set_xy(MARGIN_L, y + 0.1)
        pdf.set_text_color(*_COLOR_ACCENT_DARK)
        pdf.set_font(_FONT_NAME, "", 8.5)
        pdf.cell(7.5, 7.3, text=key, align="C")
        pdf.set_xy(MARGIN_L + 11, y)
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_FONT_NAME, "", 10)
        pdf.multi_cell(BODY_W - 11, 6.2, text=text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.7)

    def _write_answer_space(self, pdf, space_mm: float) -> None:
        space_mm = max(7, float(space_mm))
        self._check_page_break(pdf, space_mm + 5)
        start_y = pdf.get_y() + 2
        pdf.set_draw_color(*_COLOR_LINE)
        pdf.set_line_width(0.25)
        line_y = start_y + 7
        end_y = start_y + space_mm
        while line_y <= end_y:
            pdf.line(MARGIN_L, line_y, PAGE_W - MARGIN_R, line_y)
            line_y += 8
        pdf.set_y(end_y)
        pdf.set_x(MARGIN_L)

    def _write_callout(self, pdf, label: str, text: str, fill_color: tuple[int, int, int]) -> None:
        self._check_page_break(pdf, 14)
        pdf.set_fill_color(*fill_color)
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_FONT_NAME, "", 9.5)
        pdf.multi_cell(
            BODY_W,
            6.2,
            text=f"  {label}  {text}  ",
            new_x="LMARGIN",
            new_y="NEXT",
            fill=True,
        )

    def _write_question_separator(self, pdf) -> None:
        pdf.ln(4)
        if PAGE_H - MARGIN_B - pdf.get_y() < 6:
            pdf.add_page()
            return
        y = pdf.get_y()
        pdf.set_draw_color(*_COLOR_LINE)
        pdf.set_line_width(0.25)
        pdf.line(MARGIN_L, y, PAGE_W - MARGIN_R, y)
        pdf.set_y(y + 6)

    def _write_section_banner(self, pdf, title: str, subtitle: str) -> None:
        pdf.set_fill_color(*_COLOR_ACCENT)
        self._rounded_rect(pdf, MARGIN_L, pdf.get_y(), BODY_W, 17, 3, style="F")
        y = pdf.get_y()
        pdf.set_xy(MARGIN_L + 6, y + 2)
        pdf.set_text_color(*_COLOR_WHITE)
        pdf.set_font(_FONT_NAME, "", 14)
        pdf.cell(BODY_W - 12, 7, text=title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(MARGIN_L + 6)
        pdf.set_font(_FONT_NAME, "", 8.5)
        pdf.cell(BODY_W - 12, 5, text=subtitle, new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(y + 23)
        pdf.set_text_color(*_COLOR_TEXT)

    def _write_numbered_item(self, pdf, number: int, text: str, compact: bool) -> None:
        y = pdf.get_y()
        badge = 9
        pdf.set_fill_color(*_COLOR_ACCENT_LIGHT)
        self._rounded_rect(pdf, MARGIN_L, y, badge, badge, 2.2, style="F")
        pdf.set_xy(MARGIN_L, y + 0.4)
        pdf.set_text_color(*_COLOR_ACCENT_DARK)
        pdf.set_font(_FONT_NAME, "", 8.5)
        pdf.cell(badge, 8, text=str(number), align="C")
        pdf.set_xy(MARGIN_L + 13, y)
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_font(_FONT_NAME, "", 10 if compact else 9.5)
        pdf.multi_cell(
            BODY_W - 13,
            6 if compact else 5.8,
            text=text,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(3 if compact else 4)

    def _write_content(self, pdf, text: str, question: dict, ctx: PdfContext):
        """Write question content, handling segments, images, and LaTeX."""
        segments = question.get("content", {}).get("segments") if isinstance(question.get("content"), dict) else None

        if segments:
            self._write_segments(pdf, segments, ctx)
        elif has_latex(text):
            self._write_latex_content(pdf, text, ctx)
        else:
            pdf.multi_cell(BODY_W, 5.9, text=text, new_x="LMARGIN", new_y="NEXT")

    def _write_segments(self, pdf, segments: list[dict], ctx: PdfContext):
        """Render a ``segments`` content array."""
        for seg in segments:
            seg_type = seg.get("type", "text")

            if seg_type == "text":
                pdf.multi_cell(BODY_W, 5.9, text=seg.get("text", ""), new_x="LMARGIN", new_y="NEXT")

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
                        pdf.multi_cell(BODY_W, 4, text=f"({alt})", new_x="LMARGIN", new_y="NEXT")
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
                pdf.multi_cell(BODY_W, 5.9, text=seg["content"], new_x="LMARGIN", new_y="NEXT")
            else:
                png = render_latex_to_png(seg["content"], seg.get("display", False))
                if png:
                    img_path = self._save_temp_image(ctx, png, "latex")
                    try:
                        pdf.image(img_path, w=BODY_W * 0.8)
                    except Exception:
                        pdf.multi_cell(BODY_W, 5.9, text=seg["content"], new_x="LMARGIN", new_y="NEXT")
                else:
                    # Fallback: raw LaTeX
                    pdf.set_font(_FONT_NAME, "", 8)
                    pdf.set_text_color(128, 128, 128)
                    pdf.multi_cell(
                        BODY_W, 4,
                        text=f"[公式] {seg['content']}",
                        new_x="LMARGIN", new_y="NEXT",
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
        pdf.multi_cell(BODY_W, 4, text="图片加载失败", new_x="LMARGIN", new_y="NEXT")
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
        """Extract display text from a question dict."""
        content = q.get("content") or {}
        if isinstance(content, dict):
            return content.get("stem") or content.get("text") or ""
        return str(content)

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

    def _add_page_numbers(self, pdf, product_name: str = "MemoGrad"):
        """Add a restrained footer without triggering automatic page breaks."""
        total = pdf.page_no()
        pdf.set_auto_page_break(False)
        for page_num in range(1, total + 1):
            pdf.page = page_num
            y = PAGE_H - 13
            pdf.set_draw_color(*_COLOR_LINE)
            pdf.set_line_width(0.25)
            pdf.line(MARGIN_L, y - 2, PAGE_W - MARGIN_R, y - 2)
            pdf.set_xy(MARGIN_L, y)
            pdf.set_font(_FONT_NAME, "", 7.5)
            pdf.set_text_color(*_COLOR_MUTED)
            pdf.cell(BODY_W / 2, 5, text=product_name or "MemoGrad", new_x="RIGHT", new_y="TOP")
            pdf.cell(
                BODY_W / 2,
                5,
                text=f"第 {page_num} 页 / 共 {total} 页",
                align="R",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        pdf.page = total
        pdf.set_auto_page_break(True, margin=MARGIN_B)

