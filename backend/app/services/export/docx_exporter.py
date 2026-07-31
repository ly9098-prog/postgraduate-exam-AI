"""DOCX exporter using python-docx — generates A4 portrait exam paper Word documents.

Content strategy mirrors PdfExporter:
- Uses the same snapshot data (questions + config) from the shared data pipeline.
- Images are downloaded server-side and embedded (no external resource loading).
- LaTeX math expressions are rendered to PNG via matplotlib mathtext and embedded.
- Tables are rendered as Word native tables; markdown tables are parsed.
- Code blocks use monospace font with gray background.

from __future__ import annotations

Font strategy:
- Chinese body: SimSun (宋体), fallback DengXian (等线)
- Chinese heading: SimHei (黑体)
- English/numbers: Times New Roman
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
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.text.paragraph import Paragraph

from app.core.config import settings
from app.features.question_type import QUESTION_TYPE_LABELS, QuestionType
from app.services.export.exporter_base import Exporter, ExportResult
from app.services.export.latex_render import find_latex_segments, has_latex
from app.services.export.omml_converter import render_latex_as_omml_or_fallback
from app.services.export.question_content import (
    clean_printable_text,
    extract_option_text,
    extract_question_text,
)
from app.services.export.space_allocator import get_answer_space_mm
from app.services.export.table_parser import parse_table
from app.services.export.table_renderer import render_table_to_docx
from app.services.safe_remote_fetch import fetch_remote_bytes, is_safe_remote_url

logger = logging.getLogger(__name__)

# ── Page layout constants ──
PAGE_W_CM = 21.0  # A4 width
PAGE_H_CM = 29.7  # A4 height
MARGIN_L_CM = 2.0
MARGIN_R_CM = 2.0
MARGIN_T_CM = 1.8
MARGIN_B_CM = 1.7
BODY_W_CM = PAGE_W_CM - MARGIN_L_CM - MARGIN_R_CM  # 17 cm

# ── Font names ──
_BODY_FONT = "SimSun"  # 宋体 — Chinese body
_BODY_FONT_EA = "SimSun"  # East-Asian body
_HEADING_FONT = "SimHei"  # 黑体 — Chinese heading
_EN_FONT = "Times New Roman"  # English / numbers
_CODE_FONT = "Consolas"
_CODE_FONT_CJK = "DengXian"  # 等线 — Chinese in code blocks
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_LOCAL_ASSET_ROOTS = (
    os.path.join(_BACKEND_ROOT, "static", "question-assets"),
    os.path.join(_BACKEND_ROOT, "static", "formulas"),
)

# ── Image resource limits (same as PdfExporter) ──
_MAX_IMAGE_DOWNLOAD_SEC = 15
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_IMAGE_DIMENSION = 2000
_MAX_IMAGE_PIXELS = 25_000_000
_MAX_CONCURRENT_DOWNLOADS = 4
_MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
_QUESTION_IMAGE_MAX_WIDTH_RATIO = 0.90

# Thread pool for blocking image downloads
_image_executor = ThreadPoolExecutor(
    max_workers=_MAX_CONCURRENT_DOWNLOADS, thread_name_prefix="docx-img"
)

# Inline formatting regex for <b>, <strong>, <i>, <em>, <sub>, <sup>, <br>
_INLINE_FORMAT_RE = re.compile(
    r"(</?(?:b|strong|i|em|sub|sup|br)\s*/?>)",
    re.IGNORECASE,
)


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

        section = doc.sections[0]
        section.page_width = Cm(PAGE_W_CM)
        section.page_height = Cm(PAGE_H_CM)
        section.orientation = WD_ORIENT.PORTRAIT
        section.top_margin = Cm(MARGIN_T_CM)
        section.bottom_margin = Cm(MARGIN_B_CM)
        section.left_margin = Cm(MARGIN_L_CM)
        section.right_margin = Cm(MARGIN_R_CM)

        style = doc.styles["Normal"]
        font = style.font
        font.name = _EN_FONT
        font.size = Pt(10)
        rpr = style.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:eastAsia"), _BODY_FONT_EA)
        rfonts.set(qn("w:ascii"), _EN_FONT)
        rfonts.set(qn("w:hAnsi"), _EN_FONT)

        pf = style.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing = 1.35

        self._add_header(doc, config)
        self._setup_header_footer(doc, config)

        answer_section: list[dict] = []
        analysis_section: list[dict] = []
        group_by = config.get("group_by", "none")
        group_counts = Counter(
            q.get("_group_title", "") for q in questions if q.get("_group_title", "")
        )
        current_group = None
        group_index = 0

        for idx, q in enumerate(questions):
            q_group = q.get("_group_title", "")
            if group_by != "none" and q_group and q_group != current_group:
                current_group = q_group
                group_index += 1
                self._add_group_header(doc, q_group, group_index, group_counts.get(q_group, 0))

            question_num = idx + 1
            qt_label = self._get_question_type_label(q.get("question_type", ""))
            show_type = group_by != "question_type"
            question_paragraphs = []

            # Number and stem share one paragraph, matching conventional exam
            # layout. Text stored outside ``segments`` must not be discarded.
            stem_p = doc.add_paragraph()
            stem_p.paragraph_format.space_before = Pt(3.5)
            stem_p.paragraph_format.space_after = Pt(1.5)
            prefix = f"{question_num}．"
            if show_type and qt_label:
                prefix += f"[{self._formal_group_title(qt_label)}]"
            prefix_run = stem_p.add_run(prefix)
            prefix_run.bold = False
            prefix_run.font.size = Pt(10)
            prefix_run.font.name = _BODY_FONT
            self._set_east_asian_font(prefix_run, _BODY_FONT_EA)

            content_text = self._get_question_text(q)
            content = q.get("content") if isinstance(q.get("content"), dict) else {}
            segments = (content or {}).get("segments") or []
            cleaned_stem = self._sanitize_text(content_text).strip()
            if cleaned_stem:
                if has_latex(cleaned_stem):
                    self._write_latex_content_to_doc(stem_p, cleaned_stem, ctx)
                else:
                    run = stem_p.add_run(cleaned_stem)
                    run.font.size = Pt(10)
                    run.font.name = _BODY_FONT
                    self._set_east_asian_font(run, _BODY_FONT_EA)
                visual_segments = [
                    seg for seg in segments
                    if seg.get("type") in ("code_image", "math_image", "table_image", "image", "table_markdown")
                ]
                if visual_segments:
                    self._write_segments_to_doc(stem_p, visual_segments, ctx, doc)
            elif segments:
                self._write_segments_to_doc(stem_p, segments, ctx, doc)
            else:
                run = stem_p.add_run("（题干内容未提供）")
                run.font.size = Pt(10)
                run.font.name = _BODY_FONT
                self._set_east_asian_font(run, _BODY_FONT_EA)
            question_paragraphs.append(stem_p)

            segment_urls = {
                str(seg.get("url") or seg.get("src"))
                for seg in segments if seg.get("url") or seg.get("src")
            }
            for url in q.get("image_urls") or []:
                if url and str(url) not in segment_urls:
                    self._embed_image_in_doc(stem_p, str(url), ctx)

            options = q.get("options") or {}
            options_table = None
            if options:
                options_table = self._add_options_table(doc, options)
                stem_p.paragraph_format.keep_with_next = True
            space_mm = get_answer_space_mm(
                config.get("space_style", "standard"),
                q.get("question_type"),
            )
            if space_mm > 0:
                question_paragraphs.extend(
                    self._add_answer_space(doc, space_mm, q.get("question_type", ""))
                )

            if config.get("answer_position") == "after_question":
                ans = self._sanitize_text(q.get("answer", ""))
                if ans:
                    ans_p = doc.add_paragraph()
                    ans_p.paragraph_format.space_before = Pt(2)
                    self._add_labeled_text(ans_p, "答案", ans)
                    question_paragraphs.append(ans_p)

            if config.get("analysis_position") == "after_question":
                analysis_text = self._sanitize_text(q.get("analysis", ""))
                if analysis_text:
                    ana_p = doc.add_paragraph()
                    ana_p.paragraph_format.space_before = Pt(2)
                    self._add_labeled_text(ana_p, "解析", analysis_text)
                    question_paragraphs.append(ana_p)

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

            self._keep_question_together(question_paragraphs)
            if options_table is not None:
                # Tie the stem to the first option-table row. Rows themselves
                # are marked cantSplit, so ordinary questions stay intact.
                stem_p.paragraph_format.keep_with_next = True

        if answer_section:
            doc.add_page_break()
            self._add_end_section_title(doc, "参考答案")
            self._add_answer_grid(doc, answer_section)

        analysis_section = [item for item in analysis_section if item.get("analysis")]
        if analysis_section:
            if not answer_section:
                doc.add_page_break()
            else:
                spacer = doc.add_paragraph()
                spacer.paragraph_format.space_after = Pt(7)
            self._add_end_section_title(doc, "答案解析")
            for item in analysis_section:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(6)
                number_run = p.add_run(f"{item['num']}．")
                number_run.bold = True
                number_run.font.size = Pt(10)
                number_run.font.name = _BODY_FONT
                self._set_east_asian_font(number_run, _BODY_FONT_EA)
                run = p.add_run(item["analysis"])
                run.font.size = Pt(10)
                run.font.name = _BODY_FONT
                self._set_east_asian_font(run, _BODY_FONT_EA)

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf.getvalue()

    # ── Document header ──

    def _add_header(self, doc: Document, config: dict) -> None:
        """Add a clean first-page exam title without metadata or rules."""
        title = self._sanitize_text(config.get("title", "错题巩固练习")) or "错题巩固练习"
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(13)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(title)
        run.bold = False
        run.font.size = Pt(16)
        run.font.name = _HEADING_FONT
        self._set_east_asian_font(run, _HEADING_FONT)

    def _setup_header_footer(self, doc: Document, config: dict) -> None:
        """Use a later-page title header and centered ``· PAGE ·`` footer."""
        section = doc.sections[0]
        section.different_first_page_header_footer = True
        section.header_distance = Cm(0.65)
        section.footer_distance = Cm(0.65)
        title = self._sanitize_text(config.get("title", "错题巩固练习")) or "错题巩固练习"

        first_header = section.first_page_header
        first_header.is_linked_to_previous = False
        first_header.paragraphs[0].text = ""

        header = section.header
        header.is_linked_to_previous = False
        hp = header.paragraphs[0]
        hp.text = ""
        hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        hp.paragraph_format.space_after = Pt(2)
        run = hp.add_run(title)
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x60, 0x60, 0x60)
        run.font.name = _BODY_FONT
        self._set_east_asian_font(run, _BODY_FONT_EA)
        self._set_paragraph_bottom_border(hp, color="B7B7B7", size="3", space="2")

        for footer in (section.first_page_footer, section.footer):
            footer.is_linked_to_previous = False
            fp = footer.paragraphs[0]
            fp.text = ""
            fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = fp.add_run("· ")
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0x68, 0x68, 0x68)
            run.font.name = _EN_FONT
            self._add_field_to_paragraph(fp, "PAGE")
            run = fp.add_run(" ·")
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0x68, 0x68, 0x68)
            run.font.name = _EN_FONT

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

    @staticmethod
    def _add_paragraph_to_doc(paragraph) -> Paragraph:
        """Insert a paragraph immediately after another paragraph."""
        new_element = OxmlElement("w:p")
        paragraph._p.addnext(new_element)
        return Paragraph(new_element, paragraph._parent)

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
            run.font.size = Pt(10)
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
                # Use inline formatting for tagged content, plain text otherwise
                if _has_inline_formatting(text):
                    self._handle_inline_formatting(parent_paragraph, text)
                else:
                    cleaned = self._sanitize_text(text)
                    if cleaned:
                        run = parent_paragraph.add_run(cleaned)
                        run.font.size = Pt(10)
                        run.font.name = _BODY_FONT
                        self._set_east_asian_font(run, _BODY_FONT_EA)

            elif seg_type == "newline":
                p = self._add_paragraph_to_doc(parent_paragraph)
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(4)
                parent_paragraph = p

            elif seg_type in ("code_image", "math_image", "table_image", "image"):
                url = seg.get("url") or seg.get("src") or ""
                if url:
                    self._embed_image_in_doc(parent_paragraph, url, ctx)

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
        """Split text into plain + LaTeX segments and render each.

        Rendering priority for LaTeX:
        1. OMML (native Word formula)
        2. PNG image (via matplotlib)
        3. Raw text fallback
        """
        segments = find_latex_segments(text)
        for seg in segments:
            if seg["type"] == "text":
                cleaned = self._sanitize_text(seg["content"])
                if cleaned:
                    run = paragraph.add_run(cleaned)
                    run.font.size = Pt(10)
                    run.font.name = _BODY_FONT
                    self._set_east_asian_font(run, _BODY_FONT_EA)
            else:
                # Attempt OMML first, then PNG, then raw text
                latex = seg["content"]
                display = seg.get("display", False)
                if not render_latex_as_omml_or_fallback(
                    latex, display, paragraph,
                    fallback_png=True,
                    body_width_cm=BODY_W_CM,
                ):
                    # Ultimate fallback: raw LaTeX text
                    run = paragraph.add_run(f" [公式] {latex} ")
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
                run.add_picture(local_path, width=Cm(self._image_width_cm(local_path)))
                return True
            except Exception:
                pass

        # Download
        try:
            local_path = self._download_image_sync(url, ctx)
            if local_path:
                ctx.downloaded[url] = local_path
                run = paragraph.add_run()
                run.add_picture(local_path, width=Cm(self._image_width_cm(local_path)))
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

    @staticmethod
    def _image_width_cm(image_path: str) -> float:
        from PIL import Image as PILImage

        with PILImage.open(image_path) as image:
            px_w, px_h = image.size
            dpi = image.info.get("dpi") or (96, 96)
        natural_w = max(0.8, px_w * 2.54 / float(dpi[0] or 96))
        natural_h = max(0.8, px_h * 2.54 / float(dpi[1] or 96))
        scale = min(1.0, (BODY_W_CM * _QUESTION_IMAGE_MAX_WIDTH_RATIO) / natural_w, 20.0 / natural_h)
        return max(0.8, natural_w * scale)

    def _download_image_sync(self, url: str, ctx: DocxContext) -> str | None:
        """Download an image with safety checks (same as PdfExporter)."""
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
        from urllib.parse import unquote, urlsplit

        parsed = urlsplit(str(url))
        path = unquote(parsed.path or str(url).split("?", 1)[0])
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
        from urllib.parse import urljoin, urlsplit

        if urlsplit(str(url)).scheme:
            return str(url)
        base = str(getattr(settings, "PUBLIC_BASE_URL", "") or "").strip()
        if not base:
            return None
        return urljoin(base.rstrip("/") + "/", str(url).lstrip("/"))

    @staticmethod
    def _save_normalized_image(data: bytes, dest: str, source: str, ctx: DocxContext) -> str | None:
        from PIL import Image as PILImage

        try:
            with PILImage.open(io.BytesIO(data)) as image:
                width, height = image.size
                if width < 1 or height < 1 or width * height > _MAX_IMAGE_PIXELS:
                    logger.warning("Image pixel budget exceeded for %s", source)
                    return None
                image.load()
                if max(image.size) > _MAX_IMAGE_DIMENSION:
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
    def _display_units(text: str) -> int:
        units = 0
        for char in str(text):
            units += 2 if unicodedata.east_asian_width(char) in ("W", "F", "A") else 1
        return units

    def _choose_option_columns(self, items: list[tuple[str, str]]) -> int:
        rendered = [f"{key}．{extract_option_text(text)}" for key, text in items]
        # Approximate capacities at 10.5 pt in a 17.4 cm body width. These
        # thresholds match conventional four/two/one-column exam choices.
        if rendered and all(self._display_units(text) <= 20 for text in rendered):
            return 4
        if rendered and all(self._display_units(text) <= 46 for text in rendered):
            return 2
        return 1

    def _add_options_table(self, doc: Document, options: dict):
        items = [(str(key), extract_option_text(options[key])) for key in sorted(options.keys())]
        columns = self._choose_option_columns(items)
        rows = (len(items) + columns - 1) // columns
        table = doc.add_table(rows=rows, cols=columns)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.autofit = False
        self._set_table_borders_none(table)
        self._set_table_indent(table, 0.55)

        cell_width = Cm((BODY_W_CM - 0.55) / columns)
        for row_index, row in enumerate(table.rows):
            self._set_row_cant_split(row)
            for col_index, cell in enumerate(row.cells):
                cell.width = cell_width
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
                self._set_cell_margins(cell, top=0, left=0.03, bottom=0, right=0.08)
                item_index = row_index * columns + col_index
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(1)
                p.paragraph_format.line_spacing = 1.25
                if item_index < len(items):
                    key, value = items[item_index]
                    run = p.add_run(f"{key}．{self._sanitize_text(value)}")
                    run.font.size = Pt(9.8)
                    run.font.name = _BODY_FONT
                    self._set_east_asian_font(run, _BODY_FONT_EA)
        return table

    def _add_answer_grid(self, doc: Document, items: list[dict]):
        answers = [self._sanitize_text(item.get("answer")) or "—" for item in items]
        max_units = max((self._display_units(answer) for answer in answers), default=1)
        columns = 8 if max_units <= 4 else 4 if max_units <= 16 else 2 if max_units <= 36 else 1
        rows = (len(items) + columns - 1) // columns
        table = doc.add_table(rows=rows, cols=columns)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.autofit = False
        self._set_table_borders_none(table)
        self._set_table_indent(table, 0)
        cell_width = Cm(BODY_W_CM / columns)

        for row_index, row in enumerate(table.rows):
            self._set_row_cant_split(row)
            for col_index, cell in enumerate(row.cells):
                cell.width = cell_width
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
                self._set_cell_margins(cell, top=0, left=0, bottom=0.02, right=0.08)
                item_index = row_index * columns + col_index
                paragraph = cell.paragraphs[0]
                paragraph.paragraph_format.space_after = Pt(1.5)
                paragraph.paragraph_format.line_spacing = 1.15
                if item_index < len(items):
                    item = items[item_index]
                    answer = self._sanitize_text(item.get("answer")) or "—"
                    run = paragraph.add_run(f"{item['num']}．{answer}")
                    run.font.size = Pt(9.5)
                    run.font.name = _BODY_FONT
                    self._set_east_asian_font(run, _BODY_FONT_EA)
        return table

    @staticmethod
    def _set_table_borders_none(table) -> None:
        tbl_pr = table._tbl.tblPr
        borders = tbl_pr.find(qn("w:tblBorders"))
        if borders is None:
            borders = OxmlElement("w:tblBorders")
            tbl_pr.append(borders)
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "nil")
            borders.append(el)

    @staticmethod
    def _set_table_indent(table, indent_cm: float) -> None:
        tbl_pr = table._tbl.tblPr
        tbl_ind = tbl_pr.find(qn("w:tblInd"))
        if tbl_ind is None:
            tbl_ind = OxmlElement("w:tblInd")
            tbl_pr.append(tbl_ind)
        tbl_ind.set(qn("w:w"), str(int(round(indent_cm * 1440 / 2.54))))
        tbl_ind.set(qn("w:type"), "dxa")

    @staticmethod
    def _set_cell_margins(cell, top=0, left=0, bottom=0, right=0) -> None:
        tc = cell._tc
        tc_pr = tc.get_or_add_tcPr()
        tc_mar = tc_pr.first_child_found_in("w:tcMar")
        if tc_mar is None:
            tc_mar = OxmlElement("w:tcMar")
            tc_pr.append(tc_mar)
        for m, value in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
            node = tc_mar.find(qn(f"w:{m}"))
            if node is None:
                node = OxmlElement(f"w:{m}")
                tc_mar.append(node)
            node.set(qn("w:w"), str(int(round(value * 1440 / 2.54))))
            node.set(qn("w:type"), "dxa")

    @staticmethod
    def _set_row_cant_split(row) -> None:
        tr_pr = row._tr.get_or_add_trPr()
        cant_split = OxmlElement("w:cantSplit")
        tr_pr.append(cant_split)

    # ── Answer space ──

    def _add_answer_space(self, doc: Document, space_mm: float, question_type: str) -> list:
        """Reserve unruled writing space and return its paragraphs."""
        height_pt = max(1.0, float(space_mm)) / 0.352778
        line_height = 14.0
        num_lines = max(1, int(round(height_pt / line_height)))
        paragraphs = []
        for _ in range(num_lines):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = Pt(line_height)
            run = p.add_run(" ")
            run.font.size = Pt(1)
            paragraphs.append(p)
        return paragraphs

    def _add_group_header(self, doc: Document, title: str, index: int, count: int) -> None:
        """Add a numbered, monochrome section heading."""
        p = doc.add_paragraph()
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.keep_together = True
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(4)
        text = f"{self._chinese_section_number(index)}、{self._formal_group_title(title)}" + (f"（共{count}题）" if count else "")
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(11)
        run.font.name = _HEADING_FONT
        self._set_east_asian_font(run, _HEADING_FONT)

    def _add_end_section_title(self, doc: Document, title: str) -> None:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_after = Pt(10)
        run = p.add_run(title)
        run.bold = True
        run.font.size = Pt(14)
        run.font.name = _HEADING_FONT
        self._set_east_asian_font(run, _HEADING_FONT)

    @staticmethod
    def _add_labeled_text(paragraph, label: str, text: str) -> None:
        label_run = paragraph.add_run(f"{label}：")
        label_run.bold = True
        label_run.font.size = Pt(10)
        label_run.font.name = _BODY_FONT
        DocxExporter._set_east_asian_font(label_run, _BODY_FONT_EA)
        run = paragraph.add_run(text)
        run.font.size = Pt(10)
        run.font.name = _BODY_FONT
        DocxExporter._set_east_asian_font(run, _BODY_FONT_EA)

    @staticmethod
    def _keep_question_together(paragraphs: list) -> None:
        """Keep ordinary questions on one page where Word can do so."""
        if not paragraphs:
            return
        for idx, paragraph in enumerate(paragraphs):
            paragraph.paragraph_format.keep_together = True
            paragraph.paragraph_format.keep_with_next = idx < len(paragraphs) - 1
        paragraphs[-1].paragraph_format.space_after = Pt(8)

    @staticmethod
    def _set_paragraph_bottom_border(paragraph, color: str, size: str, space: str) -> None:
        p_pr = paragraph._p.get_or_add_pPr()
        p_bdr = p_pr.find(qn("w:pBdr"))
        if p_bdr is None:
            p_bdr = OxmlElement("w:pBdr")
            p_pr.append(p_bdr)
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), size)
        bottom.set(qn("w:space"), space)
        bottom.set(qn("w:color"), color)
        p_bdr.append(bottom)

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
        return {
            "单选题": "单项选择题",
            "多选题": "多项选择题",
            "问答题": "简答题",
        }.get(title, title)

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
    def _handle_inline_formatting(paragraph, text: str) -> None:
        """Handle basic inline formatting in text (bold, italic, sub, sup, br)."""
        parts = _INLINE_FORMAT_RE.split(text)
        in_b = False
        in_i = False
        in_sub = False
        in_sup = False

        for part in parts:
            lower = part.lower()
            if lower in ("<b>", "<strong>"):
                in_b = True
            elif lower in ("</b>", "</strong>"):
                in_b = False
            elif lower in ("<i>", "<em>"):
                in_i = True
            elif lower in ("</i>", "</em>"):
                in_i = False
            elif lower == "<sub>":
                in_sub = True
            elif lower == "</sub>":
                in_sub = False
            elif lower == "<sup>":
                in_sup = True
            elif lower == "</sup>":
                in_sup = False
            elif lower in ("<br>", "<br/>"):
                run = paragraph.add_run("\n")
                run.font.size = Pt(8)
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


def _has_inline_formatting(text: str) -> bool:
    """Check if text contains inline formatting tags."""
    return bool(_INLINE_FORMAT_RE.search(text))
