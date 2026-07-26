"""DOCX exporter using python-docx — generates A4 portrait exam paper Word documents.

Content strategy mirrors PdfExporter:
- Uses the same snapshot data (questions + config) from the shared data pipeline.
- Images are downloaded server-side and embedded (no external resource loading).
- LaTeX math expressions are rendered to PNG via matplotlib mathtext and embedded.
- Tables are rendered as Word native tables; markdown tables are parsed.
- Code blocks use monospace font with gray background.

Font strategy:
- Chinese body: SimSun (宋体), fallback DengXian (等线)
- Chinese heading: SimHei (黑体)
- English/numbers: Calibri as primary, Times New Roman as fallback
- Code: Consolas / Courier New
- East Asian font set explicitly via OOXML w:eastAsia attribute.

Important: DOCX declares fonts but does NOT embed them. Display appearance
depends on the receiver's installed fonts. Chinese, math symbols, and
subscript/superscript may render slightly differently across Word, WPS,
and LibreOffice.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor
from docx.table import _Cell

from app.core.config import settings
from app.features.question_type import QUESTION_TYPE_LABELS, QuestionType
from app.services.export.exporter_base import ExportResult, Exporter
from app.services.export.latex_render import find_latex_segments, has_latex, render_latex_to_png
from app.services.export.omml_converter import render_latex_as_omml_or_fallback
from app.services.export.space_allocator import get_answer_space_mm
from app.services.export.table_parser import parse_table
from app.services.export.table_renderer import render_table_to_docx

logger = logging.getLogger(__name__)

# ── Page layout constants ──
PAGE_W_CM = 21.0  # A4 width
PAGE_H_CM = 29.7  # A4 height
MARGIN_L_CM = 2.0
MARGIN_R_CM = 2.0
MARGIN_T_CM = 2.5
MARGIN_B_CM = 2.0
BODY_W_CM = PAGE_W_CM - MARGIN_L_CM - MARGIN_R_CM  # 17.0 cm

# ── Font names ──
_BODY_FONT = "SimSun"  # 宋体 — Chinese body
_BODY_FONT_EA = "SimSun"  # East-Asian body
_HEADING_FONT = "SimHei"  # 黑体 — Chinese heading
_EN_FONT = "Calibri"  # English / numbers
_CODE_FONT = "Consolas"
_CODE_FONT_CJK = "DengXian"  # 等线 — Chinese in code blocks

# ── Image resource limits (same as PdfExporter) ──
_MAX_IMAGE_DOWNLOAD_SEC = 15
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_IMAGE_DIMENSION = 2000
_MAX_CONCURRENT_DOWNLOADS = 4
_MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024

# Thread pool for blocking image downloads
_image_executor = ThreadPoolExecutor(
    max_workers=_MAX_CONCURRENT_DOWNLOADS, thread_name_prefix="docx-img"
)

# Angle-bracket content stripping (defense-in-depth)
_HTML_TAG_RE = re.compile(r"<[^>]*>")


@dataclass
class DocxContext:
    """Per-task context for resource accounting and cleanup."""
    temp_dir: str
    downloaded: dict[str, str] = field(default_factory=dict)
    total_image_bytes: int = 0


class DocxExporter(Exporter):
    """Generate A4 portrait exam-paper DOCX using python-docx."""

    @property
    def format_name(self) -> str:
        return "DOCX"

    async def export(self, snapshot_data: dict, output_dir: str) -> ExportResult:
        """Generate the DOCX document.

        Args:
            snapshot_data: Full snapshot dict (questions + config).
            output_dir: Temp dir for intermediate files (images, cache).

        Returns:
            ExportResult with DOCX bytes.
        """
        questions = snapshot_data.get("questions", [])
        config = snapshot_data.get("config", {})

        ctx = DocxContext(temp_dir=output_dir)

        try:
            docx_bytes = await asyncio.get_running_loop().run_in_executor(
                None, self._generate_sync, questions, config, ctx,
            )
            return ExportResult(
                success=True,
                file_bytes=docx_bytes,
                file_name=config.get("file_name", "export.docx"),
                skip_count=config.get("skip_count", 0),
                skip_reasons=config.get("skip_reasons"),
            )
        except Exception as e:
            logger.exception("DOCX generation failed")
            return ExportResult(
                success=False,
                error_message=str(e)[:500],
            )

    # ── Synchronous generation (runs in executor) ──

    def _generate_sync(
        self,
        questions: list[dict],
        config: dict,
        ctx: DocxContext,
    ) -> bytes:
        """Synchronous DOCX generation."""
        doc = Document()

        # ── Page setup ──
        section = doc.sections[0]
        section.page_width = Cm(PAGE_W_CM)
        section.page_height = Cm(PAGE_H_CM)
        section.orientation = WD_ORIENT.PORTRAIT
        section.top_margin = Cm(MARGIN_T_CM)
        section.bottom_margin = Cm(MARGIN_B_CM)
        section.left_margin = Cm(MARGIN_L_CM)
        section.right_margin = Cm(MARGIN_R_CM)

        # ── Default font ──
        style = doc.styles["Normal"]
        font = style.font
        font.name = _EN_FONT
        font.size = Pt(10.5)
        # Set East-Asian font
        rpr = style.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:eastAsia"), _BODY_FONT_EA)
        rfonts.set(qn("w:ascii"), _EN_FONT)
        rfonts.set(qn("w:hAnsi"), _EN_FONT)

        # Paragraph spacing
        pf = style.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(2)
        pf.line_spacing = 1.5

        # ── Header ──
        self._add_header(doc, config)

        # ── Header and Footer (per section) ──
        self._setup_header_footer(doc, config)

        # ── Questions ──
        answer_section: list[dict] = []
        analysis_section: list[dict] = []

        group_title = config.get("group_by", "none")
        current_group = None

        for idx, q in enumerate(questions):
            q_group = q.get("_group_title", "")
            if group_title != "none" and q_group and q_group != current_group:
                current_group = q_group
                self._add_group_header(doc, q_group)

            question_num = idx + 1

            # ── Question header line: number + type ──
            qt_label = self._get_question_type_label(q.get("question_type", ""))
            header_text = f"{question_num}. [{qt_label}]" if qt_label else f"{question_num}."
            p = doc.add_paragraph()
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(header_text)
            run.bold = False
            run.font.size = Pt(11)
            run.font.name = _HEADING_FONT
            self._set_east_asian_font(run, _HEADING_FONT)

            # ── Question content ──
            content_text = self._get_question_text(q)
            stem_p = doc.add_paragraph()
            stem_p.paragraph_format.keep_with_next = True
            stem_p.paragraph_format.space_after = Pt(2)
            self._write_content_to_paragraph(stem_p, content_text, q, ctx, doc)

            # ── Options ──
            options = q.get("options") or {}
            if options:
                for opt_key in sorted(options.keys()):
                    opt_text = options[opt_key]
                    opt_p = doc.add_paragraph()
                    opt_p.paragraph_format.keep_with_next = True
                    opt_p.paragraph_format.space_after = Pt(1)
                    opt_p.paragraph_format.left_indent = Cm(0.5)
                    run = opt_p.add_run(f"{opt_key}. {opt_text}")
                    run.font.size = Pt(10.5)
                    run.font.name = _BODY_FONT
                    self._set_east_asian_font(run, _BODY_FONT_EA)

            # ── Answer space ──
            space_mm = get_answer_space_mm(
                config.get("space_style", "standard"),
                q.get("question_type"),
            )
            if space_mm > 0:
                self._add_answer_space(doc, space_mm, q.get("question_type", ""))

            # ── Answer after question ──
            if config.get("answer_position") == "after_question":
                ans = q.get("answer", "")
                if ans:
                    ans_p = doc.add_paragraph()
                    ans_p.paragraph_format.keep_with_next = True
                    self._add_shaded_run(ans_p, "【答案】" + ans)

            # ── Analysis after question ──
            if config.get("analysis_position") == "after_question":
                analysis_text = q.get("analysis", "")
                if analysis_text:
                    ana_p = doc.add_paragraph()
                    self._add_shaded_run(ana_p, "【解析】" + analysis_text)

            # ── Collect for end sections ──
            if config.get("answer_position") == "at_end":
                answer_section.append({
                    "num": question_num,
                    "answer": q.get("answer", ""),
                })
            if config.get("analysis_position") == "at_end":
                analysis_section.append({
                    "num": question_num,
                    "analysis": q.get("analysis", ""),
                })

        # ── Answer section at end ──
        if answer_section:
            doc.add_page_break()
            p = doc.add_paragraph()
            run = p.add_run("参考答案")
            run.bold = True
            run.font.size = Pt(14)
            run.font.name = _HEADING_FONT
            self._set_east_asian_font(run, _HEADING_FONT)
            p.paragraph_format.space_after = Pt(6)

            # Compact answer format
            answer_p = doc.add_paragraph()
            answer_p.paragraph_format.space_after = Pt(4)
            lines = [f"{item['num']}. {item['answer']}" for item in answer_section]
            answer_p.add_run("    ".join(lines))

        # ── Analysis section at end ──
        if analysis_section:
            doc.add_page_break()
            p = doc.add_paragraph()
            run = p.add_run("解析")
            run.bold = True
            run.font.size = Pt(14)
            run.font.name = _HEADING_FONT
            self._set_east_asian_font(run, _HEADING_FONT)
            p.paragraph_format.space_after = Pt(6)

            for item in analysis_section:
                if item.get("analysis"):
                    ap = doc.add_paragraph()
                    ap.paragraph_format.space_after = Pt(4)
                    run = ap.add_run(f"{item['num']}. {item['analysis']}")
                    run.font.size = Pt(10.5)
                    run.font.name = _BODY_FONT
                    self._set_east_asian_font(run, _BODY_FONT_EA)

        # ── Save ──
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf.getvalue()

    # ── Document header ──

    def _add_header(self, doc: Document, config: dict):
        """Add document header: product name, title, date, question count."""
        # Product name
        product_name = config.get("product_name", "")
        if product_name:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(product_name)
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
            run.font.name = _EN_FONT
            p.paragraph_format.space_after = Pt(2)

        # Title
        title = config.get("title", "错题巩固练习")
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(title)
        run.bold = False
        run.font.size = Pt(16)
        run.font.name = _HEADING_FONT
        self._set_east_asian_font(run, _HEADING_FONT)

        # Date
        if config.get("show_date", True):
            date_str = config.get("export_date", "")
            if date_str:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_after = Pt(2)
                run = p.add_run(date_str)
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
                run.font.name = _EN_FONT

        # Question count
        total = config.get("total_count", 0)
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(6)
        run = p.add_run(f"共 {total} 题")
        run.font.size = Pt(10)
        run.font.name = _BODY_FONT
        self._set_east_asian_font(run, _BODY_FONT_EA)

    # ── Header / Footer with PAGE/NUMPAGES fields ──

    def _setup_header_footer(self, doc: Document, config: dict):
        """Add header (product name) and footer (page numbers) using Open XML fields."""
        section = doc.sections[0]

        # ── Header: product name ──
        header = section.header
        header.is_linked_to_previous = False
        hp = header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        product_name = config.get("product_name", settings.PRODUCT_NAME)
        run = hp.add_run(product_name)
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        run.font.name = _EN_FONT

        # ── Footer: PAGE / NUMPAGES ──
        footer = section.footer
        footer.is_linked_to_previous = False
        fp = footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # "第 " text
        run = fp.add_run("第 ")
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

        # PAGE field
        self._add_field_to_paragraph(fp, "PAGE")

        # " 页 / 共 " text
        run = fp.add_run(" 页 / 共 ")
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

        # NUMPAGES field
        self._add_field_to_paragraph(fp, "NUMPAGES")

        # " 页" text
        run = fp.add_run(" 页")
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    @staticmethod
    def _add_field_to_paragraph(paragraph, field_name: str):
        """Add a Word field (e.g., PAGE, NUMPAGES) to a paragraph using Open XML.

        This creates the required fldChar / instrText XML structure:
            <w:fldChar w:fldCharType="begin"/>
            <w:instrText> PAGE </w:instrText>
            <w:fldChar w:fldCharType="separate"/>
            <w:fldChar w:fldCharType="end"/>
        """
        run = paragraph.add_run()

        # Begin
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        run._r.append(begin)

        # Instruction text
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = f" {field_name} "
        run._r.append(instr)

        # Separate
        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        run._r.append(separate)

        # End
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        run._r.append(end)

    # ── Content rendering ──

    def _write_content_to_paragraph(
        self, paragraph, text: str, question: dict, ctx: DocxContext, doc: Document,
    ):
        """Write question content, handling segments, images, and LaTeX."""
        segments = (
            question.get("content", {}).get("segments")
            if isinstance(question.get("content"), dict)
            else None
        )

        if segments:
            self._write_segments_to_doc(paragraph, segments, ctx, doc)
        elif has_latex(text):
            self._write_latex_content_to_doc(paragraph, text, ctx)
        else:
            # Plain text — add as a single run
            cleaned = self._sanitize_text(text)
            run = paragraph.add_run(cleaned)
            run.font.size = Pt(10.5)
            run.font.name = _BODY_FONT
            self._set_east_asian_font(run, _BODY_FONT_EA)

    def _write_segments_to_doc(
        self, parent_paragraph, segments: list[dict], ctx: DocxContext, doc: Document,
    ):
        """Render segments array. Returns the last modified paragraph."""

        for seg in segments:
            seg_type = seg.get("type", "text")

            if seg_type == "text":
                text = seg.get("text", "")
                cleaned = self._sanitize_text(text)
                if cleaned:
                    run = parent_paragraph.add_run(cleaned)
                    run.font.size = Pt(10.5)
                    run.font.name = _BODY_FONT
                    self._set_east_asian_font(run, _BODY_FONT_EA)
                self._handle_inline_formatting(parent_paragraph, text)

            elif seg_type == "newline":
                p = self._add_paragraph_to_doc(parent_paragraph)
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(4)
                parent_paragraph = p

            elif seg_type in ("code_image", "math_image", "table_image", "image"):
                url = seg.get("url", "")
                if url:
                    self._embed_image_in_doc(parent_paragraph, url, ctx)
                    alt = seg.get("alt", "")
                    if alt:
                        alt_p = self._add_paragraph_to_doc(parent_paragraph)
                        run = alt_p.add_run(f"({alt})")
                        run.font.size = Pt(8)
                        run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
                        run.font.name = _BODY_FONT
                        self._set_east_asian_font(run, _BODY_FONT_EA)
                        parent_paragraph = alt_p

            elif seg_type == "table_markdown":
                md_text = seg.get("text", "")
                if md_text:
                    blocks = parse_table(md_text, source_type="markdown")
                    if blocks:
                        for block in blocks:
                            render_table_to_docx(doc, block, BODY_W_CM)
                            parent_paragraph = doc.add_paragraph()
                            parent_paragraph.paragraph_format.space_after = Pt(4)

    def _write_latex_content_to_doc(
        self, paragraph, text: str, ctx: DocxContext,
    ):
        """Split text into plain + LaTeX segments and render each."""
        segments = find_latex_segments(text)
        for seg in segments:
            if seg["type"] == "text":
                cleaned = self._sanitize_text(seg["content"])
                if cleaned:
                    run = paragraph.add_run(cleaned)
                    run.font.size = Pt(10.5)
                    run.font.name = _BODY_FONT
                    self._set_east_asian_font(run, _BODY_FONT_EA)
            else:
                # Render LaTeX → PNG → embed in doc
                png = render_latex_to_png(seg["content"], seg.get("display", False))
                if png:
                    img_path = self._save_temp_image(ctx, png, "latex")
                    try:
                        run = paragraph.add_run()
                        run.add_picture(img_path, width=Cm(BODY_W_CM * 0.8))
                    except Exception:
                        # Fallback: raw LaTeX text
                        run = paragraph.add_run(f" [公式] {seg['content']} ")
                        run.font.size = Pt(8)
                        run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
                        run.font.name = _BODY_FONT
                        self._set_east_asian_font(run, _BODY_FONT_EA)
                else:
                    # Fallback: raw LaTeX text
                    run = paragraph.add_run(f" [公式] {seg['content']} ")
                    run.font.size = Pt(8)
                    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
                    run.font.name = _BODY_FONT
                    self._set_east_asian_font(run, _BODY_FONT_EA)

    # ── Image handling ──

    def _embed_image_in_doc(self, paragraph, url: str, ctx: DocxContext) -> bool:
        """Download and embed an image in the document."""
        local_path = ctx.downloaded.get(url)
        if local_path and os.path.exists(local_path):
            try:
                run = paragraph.add_run()
                run.add_picture(local_path, width=Cm(BODY_W_CM))
                return True
            except Exception:
                pass

        # Download
        try:
            local_path = self._download_image_sync(url, ctx)
            if local_path:
                ctx.downloaded[url] = local_path
                run = paragraph.add_run()
                run.add_picture(local_path, width=Cm(BODY_W_CM))
                return True
        except Exception as e:
            logger.warning("Image embed failed for %s: %s", url, e)

        # Fallback text
        run = paragraph.add_run("图片加载失败")
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        run.font.name = _BODY_FONT
        self._set_east_asian_font(run, _BODY_FONT_EA)
        return False

    def _download_image_sync(self, url: str, ctx: DocxContext) -> str | None:
        """Download an image with safety checks (same as PdfExporter)."""
        if not self._is_safe_url(url):
            logger.warning("Blocked unsafe image URL: %s", url)
            return None

        ext = self._guess_extension(url)
        filename = hashlib.md5(url.encode()).hexdigest() + ext
        dest = os.path.join(ctx.temp_dir, filename)

        if os.path.exists(dest):
            return dest

        try:
            import urllib.request

            req = urllib.request.Request(url, headers={"User-Agent": "MemoGrad-Export/2.0"})
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

            # Validate with PIL
            from PIL import Image as PILImage

            try:
                img = PILImage.open(io.BytesIO(data))
                img.verify()
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

    # ── Answer space ──

    def _add_answer_space(self, doc: Document, space_mm: float, question_type: str):
        """Add printable answer space: blank paragraphs with spacing."""
        # Fill-blank: underline-style space
        # Subjective: blank paragraphs with explicit height
        if question_type == "fill_blank":
            # Add underline blank
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            # Create underline run with spaces
            run = p.add_run(" " * 40)
            run.underline = True
            run.font.size = Pt(12)
        else:
            # Subjective / other: blank paragraphs
            height_pt = space_mm / 0.352778  # mm → pt
            num_lines = max(1, int(height_pt / 14))
            for _ in range(num_lines):
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                # Minimal content to reserve space
                run = p.add_run("")
                run.font.size = Pt(12)
                p.paragraph_format.line_spacing = Pt(14)

    # ── Group header ──

    def _add_group_header(self, doc: Document, title: str):
        """Add a group header paragraph with page-break control."""
        p = doc.add_paragraph()
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(title)
        run.bold = True
        run.font.size = Pt(14)
        run.font.name = _HEADING_FONT
        self._set_east_asian_font(run, _HEADING_FONT)

    # ── Helper utilities ──

    @staticmethod
    def _add_paragraph_to_doc(paragraph) -> "Paragraph":
        """Add a new paragraph after the one containing this paragraph's XML element."""
        from docx.text.paragraph import Paragraph

        body = paragraph._element.getparent()
        new_p = OxmlElement("w:p")
        body.append(new_p)
        # Return a Paragraph wrapper
        return Paragraph(new_p, paragraph._element.getparent())

    @staticmethod
    def _add_shaded_run(paragraph, text: str):
        """Add a run with gray background shading."""
        run = paragraph.add_run(text)
        run.font.size = Pt(10)
        run.font.name = _BODY_FONT
        DocxExporter._set_east_asian_font(run, _BODY_FONT_EA)

        # Add shading via Open XML
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), "F5F5F2")
        shading.set(qn("w:val"), "clear")
        run._r.get_or_add_rPr().append(shading)

    @staticmethod
    def _set_east_asian_font(run, font_name: str):
        """Set the East-Asian font on a run via OOXML."""
        rpr = run._r.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:eastAsia"), font_name)

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
    def _is_safe_url(url: str) -> bool:
        """SSRF protection (same as PdfExporter)."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.scheme == "http" and not settings.OCR_ALLOW_HTTP:
            return False

        host = parsed.hostname or ""
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        import ipaddress
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
            if host == "169.254.169.254":
                return False
        except ValueError:
            pass

        return True

    @staticmethod
    def _is_safe_mime(content_type: str) -> bool:
        safe = ("image/", "application/octet-stream")
        return any(content_type.startswith(s) for s in safe) if content_type else True

    @staticmethod
    def _guess_extension(url: str) -> str:
        _, ext = os.path.splitext(url.split("?")[0])
        return ext if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif") else ".png"

    @staticmethod
    def _save_temp_image(ctx: DocxContext, data: bytes, prefix: str) -> str:
        filename = f"{prefix}_{hashlib.md5(data).hexdigest()[:12]}.png"
        dest = os.path.join(ctx.temp_dir, filename)
        with open(dest, "wb") as f:
            f.write(data)
        return dest

    @staticmethod
    def _handle_inline_formatting(paragraph, text: str):
        """Handle basic inline formatting in text (bold, italic, sub/sup).

        This parses simple HTML-like tags in the text content and applies
        the corresponding run formatting. Currently handles:
        - <b>bold</b>
        - <i>italic</i>
        - <sub>subscript</sub>
        - <sup>superscript</sup>
        """
        import re as _re

        # Simple pattern: match tags <b>, </b>, <i>, </i>, <sub>, </sub>, <sup>, </sup>
        parts = _re.split(r"(</?[bisu]p?>)", text)
        in_b = False
        in_i = False
        in_sub = False
        in_sup = False

        for part in parts:
            if part == "<b>":
                in_b = True
            elif part == "</b>":
                in_b = False
            elif part == "<i>":
                in_i = True
            elif part == "</i>":
                in_i = False
            elif part == "<sub>":
                in_sub = True
            elif part == "</sub>":
                in_sub = False
            elif part == "<sup>":
                in_sup = True
            elif part == "</sup>":
                in_sup = False
            elif part:
                run = paragraph.add_run(part)
                run.font.size = Pt(10.5)
                run.font.name = _BODY_FONT
                DocxExporter._set_east_asian_font(run, _BODY_FONT_EA)
                if in_b:
                    run.bold = True
                if in_i:
                    run.italic = True
                if in_sub:
                    run.font.subscript = True
                if in_sup:
                    run.font.superscript = True
