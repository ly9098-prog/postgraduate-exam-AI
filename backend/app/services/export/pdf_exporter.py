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
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.features.question_type import QUESTION_TYPE_LABELS, QuestionType
from app.services.export.exporter_base import ExportResult, Exporter
from app.services.export.latex_render import find_latex_segments, has_latex, render_latex_to_png
from app.services.export.space_allocator import get_answer_space_mm
from app.services.storage_backend import get_storage

logger = logging.getLogger(__name__)

# ── Page layout constants (mm) ──
PAGE_W = 210  # A4 width
PAGE_H = 297  # A4 height
MARGIN_L = 20
MARGIN_R = 20
MARGIN_T = 25
MARGIN_B = 20
BODY_W = PAGE_W - MARGIN_L - MARGIN_R  # 170 mm

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
        """Synchronous PDF generation — runs in thread pool executor."""
        from fpdf import FPDF

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=MARGIN_B)
        pdf.add_font(_FONT_NAME, "", self._font_path)
        pdf.add_page()
        self._add_header(pdf, config)

        # ── Questions ──
        answer_section: list[dict] = []  # items for end-of-doc answer section
        analysis_section: list[dict] = []  # items for end-of-doc analysis section
        group_title = config.get("group_by", "none")

        current_group = None
        for idx, q in enumerate(questions):
            q_group = q.get("_group_title", "")
            if group_title != "none" and q_group and q_group != current_group:
                current_group = q_group
                self._check_page_break(pdf, 15)
                pdf.set_font(_FONT_NAME, "", 14)
                pdf.multi_cell(BODY_W, 8, text=q_group, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)

            question_num = idx + 1

            # Check if we need a new page for this question (keep whole question together)
            self._check_page_break(pdf, 40)

            # Question type label
            qt_label = self._get_question_type_label(q.get("question_type", ""))

            # Question number + type
            pdf.set_font(_FONT_NAME, "", 11)
            question_header = f"{question_num}. [{qt_label}]" if qt_label else f"{question_num}."
            pdf.multi_cell(BODY_W, 6, text=question_header, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

            # Question content
            pdf.set_font(_FONT_NAME, "", 10)
            content_text = self._get_question_text(q)
            self._write_content(pdf, content_text, q, ctx)

            # Options
            options = q.get("options") or {}
            if options:
                pdf.ln(1)
                pdf.set_font(_FONT_NAME, "", 10)
                for opt_key in sorted(options.keys()):
                    opt_text = options[opt_key]
                    label = f"{opt_key}. {opt_text}"
                    pdf.multi_cell(BODY_W, 6, text=label, new_x="LMARGIN", new_y="NEXT")

            # Answer space
            space_mm = get_answer_space_mm(
                config.get("space_style", "standard"),
                q.get("question_type"),
            )
            if space_mm > 0:
                pdf.ln(2)
                # Draw a thin line or just blank space
                y_before = pdf.get_y()
                pdf.set_y(y_before + space_mm)
                # Ensure we haven't overflowed
                if pdf.get_y() > PAGE_H - MARGIN_B:
                    pdf.add_page()

            # Answer after question
            if config.get("answer_position") == "after_question":
                ans = self._sanitize_text(q.get("answer", ""))
                if ans:
                    pdf.ln(1)
                    pdf.set_fill_color(245, 245, 242)
                    pdf.set_font(_FONT_NAME, "", 10)
                    pdf.multi_cell(
                        BODY_W, 5,
                        text=f"【答案】{ans}",
                        new_x="LMARGIN", new_y="NEXT",
                        fill=True,
                    )

            # Analysis after question
            if config.get("analysis_position") == "after_question":
                analysis_text = self._sanitize_text(q.get("analysis", ""))
                if analysis_text:
                    pdf.ln(1)
                    pdf.set_fill_color(245, 245, 242)
                    pdf.set_font(_FONT_NAME, "", 10)
                    pdf.multi_cell(
                        BODY_W, 5,
                        text=f"【解析】{analysis_text}",
                        new_x="LMARGIN", new_y="NEXT",
                        fill=True,
                    )

            # Collect for end-of-doc sections
            if config.get("answer_position") == "at_end":
                answer_section.append({
                    "num": question_num,
                    "answer": q.get("answer", ""),
                    "question_type": q.get("question_type", ""),
                })
            if config.get("analysis_position") == "at_end":
                analysis_section.append({
                    "num": question_num,
                    "analysis": self._sanitize_text(q.get("analysis", "")),
                })

            # Separator between questions
            pdf.ln(3)

        # ── Answer section (at end) ──
        if answer_section:
            pdf.add_page()
            pdf.set_font(_FONT_NAME, "", 14)
            pdf.multi_cell(BODY_W, 8, text="参考答案", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
            pdf.set_font(_FONT_NAME, "", 10)
            # Compact answer format: "1. B  2. AC  3. 正确"
            lines = []
            for item in answer_section:
                lines.append(f"{item['num']}. {item['answer']}")
            # Wrap into groups of ~8 to avoid overly long lines
            for i in range(0, len(lines), 8):
                chunk = lines[i:i + 8]
                pdf.multi_cell(BODY_W, 6, text="    ".join(chunk), new_x="LMARGIN", new_y="NEXT")

        # ── Analysis section (at end) ──
        if analysis_section:
            pdf.add_page()
            pdf.set_font(_FONT_NAME, "", 14)
            pdf.multi_cell(BODY_W, 8, text="解析", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
            pdf.set_font(_FONT_NAME, "", 10)
            for item in analysis_section:
                if item.get("analysis"):
                    pdf.multi_cell(
                        BODY_W, 5,
                        text=f"{item['num']}. {item['analysis']}",
                        new_x="LMARGIN", new_y="NEXT",
                    )
                    pdf.ln(1)

        # ── Page numbers ──
        self._add_page_numbers(pdf)

        return pdf.output()

    # ── Internal helpers ──

    def _add_header(self, pdf, config: dict):
        """Add the paper header: product name, title, date, question count."""
        # Product name
        product_name = config.get("product_name", "")
        if product_name:
            pdf.set_font(_FONT_NAME, "", 9)
            pdf.set_text_color(128, 128, 128)
            pdf.multi_cell(BODY_W, 5, text=product_name, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        pdf.set_text_color(0, 0, 0)

        # Title
        title = config.get("title", "错题巩固练习")
        pdf.set_font(_FONT_NAME, "", 16)
        pdf.multi_cell(BODY_W, 9, text=title, new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(1)

        # Date (if shown)
        if config.get("show_date", True):
            date_str = config.get("export_date", "")
            if date_str:
                pdf.set_font(_FONT_NAME, "", 9)
                pdf.set_text_color(128, 128, 128)
                pdf.multi_cell(BODY_W, 5, text=date_str, new_x="LMARGIN", new_y="NEXT", align="C")
                pdf.ln(1)

        pdf.set_text_color(0, 0, 0)

        # Question count
        total = config.get("total_count", 0)
        pdf.set_font(_FONT_NAME, "", 10)
        pdf.multi_cell(BODY_W, 6, text=f"共 {total} 题", new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(3)

    def _write_content(self, pdf, text: str, question: dict, ctx: PdfContext):
        """Write question content, handling segments, images, and LaTeX."""
        segments = question.get("content", {}).get("segments") if isinstance(question.get("content"), dict) else None

        if segments:
            self._write_segments(pdf, segments, ctx)
        elif has_latex(text):
            self._write_latex_content(pdf, text, ctx)
        else:
            pdf.multi_cell(BODY_W, 5.5, text=text, new_x="LMARGIN", new_y="NEXT")

    def _write_segments(self, pdf, segments: list[dict], ctx: PdfContext):
        """Render a ``segments`` content array."""
        for seg in segments:
            seg_type = seg.get("type", "text")

            if seg_type == "text":
                pdf.multi_cell(BODY_W, 5.5, text=seg.get("text", ""), new_x="LMARGIN", new_y="NEXT")

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
                # Simple markdown table → render as text
                md_text = seg.get("text", "")
                if md_text:
                    pdf.set_font(_FONT_NAME, "", 8)
                    pdf.multi_cell(BODY_W, 4, text=md_text, new_x="LMARGIN", new_y="NEXT")

    def _write_latex_content(self, pdf, text: str, ctx: PdfContext):
        """Split text into plain + LaTeX segments and render each."""
        segments = find_latex_segments(text)
        for seg in segments:
            if seg["type"] == "text":
                pdf.multi_cell(BODY_W, 5.5, text=seg["content"], new_x="LMARGIN", new_y="NEXT")
            else:
                png = render_latex_to_png(seg["content"], seg.get("display", False))
                if png:
                    img_path = self._save_temp_image(ctx, png, "latex")
                    try:
                        pdf.image(img_path, w=BODY_W * 0.8)
                    except Exception:
                        pdf.multi_cell(BODY_W, 5.5, text=seg["content"], new_x="LMARGIN", new_y="NEXT")
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
            from PIL import Image as PILImage
            import io
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

    def _add_page_numbers(self, pdf):
        """Add page numbers to all pages."""
        total = pdf.page_no()
        for page_num in range(1, total + 1):
            pdf.page = page_num
            pdf.set_y(-15)
            pdf.set_font(_FONT_NAME, "", 8)
            pdf.set_text_color(128, 128, 128)
            pdf.cell(BODY_W, 10, text=f"第 {page_num} 页 / 共 {total} 页", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
