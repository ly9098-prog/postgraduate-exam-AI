"""Convert LaTeX to OMML (Office Math Markup Language) for DOCX embedding.

Pipeline:
1. LaTeX → MathML via ``latex2mathml``
2. MathML → OMML via direct element mapping
3. OMML inserted into DOCX paragraph

Fallback chain: OMML → PNG (via ``latex_render``) → raw text.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from lxml import etree

from app.services.export.latex_render import render_latex_to_png

logger = logging.getLogger(__name__)

# ── OMML namespace ──
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_M = "{%s}" % M_NS
_W = "{%s}" % W_NS

# Max input length to prevent DoS
_MAX_LATEX_LENGTH = 5000
# Max recursion depth
_MAX_RECURSION = 50

# ── Public API ──


def latex_to_omml_xml(latex: str, display: bool = False) -> bytes | None:
    """Convert a LaTeX expression to OMML XML bytes.

    Args:
        latex: LaTeX source (without ``$`` delimiters).
        display: ``True`` for block-level formula.

    Returns:
        OMML XML bytes ready to insert into ``w:p``, or ``None`` on failure.
    """
    if len(latex) > _MAX_LATEX_LENGTH:
        logger.warning("LaTeX too long (%d chars), skipping OMML", len(latex))
        return None

    try:
        mathml = _latex_to_mathml(latex, display)
        if not mathml:
            return None
        omml = _mathml_to_omml(mathml, display)
        return omml
    except Exception:
        logger.debug("OMML conversion failed for '%s'", latex[:80], exc_info=True)
        return None


def try_latex_to_omml(latex: str, display: bool = False) -> bytes | None:
    """Attempt OMML conversion with fallback logging.

    This is the main entry point used by the DOCX exporter.
    Returns OMML XML bytes or ``None`` (caller should fall back to PNG/text).
    """
    return latex_to_omml_xml(latex, display)


# ── Step 1: LaTeX → MathML ──


def _latex_to_mathml(latex: str, display: bool) -> str | None:
    """Convert LaTeX to MathML string using latex2mathml."""
    try:
        from latex2mathml.converter import convert as latex2mathml_convert

        result = latex2mathml_convert(latex, display="block" if display else "inline")
        return result
    except Exception:
        logger.debug("latex2mathml failed for '%s'", latex[:80])
        return None


# ── Step 2: MathML → OMML ──

# Mapping from MathML tag names to OMML tag names
_MATHML_TO_OMML = {
    "mi": "r",
    "mn": "r",
    "mo": "r",
    "mtext": "r",
    "msup": "sSup",
    "msub": "sSub",
    "msubsup": "sSubSup",
    "mfrac": "f",
    "msqrt": "rad",
    "mroot": "rad",
    "munder": "limLow",
    "mover": "limUpp",
    "munderover": "lim",
    "mrow": "e",
    "mtd": None,  # table cells not rendered as OMML tables
    "mtr": None,
    "mtable": None,
}


def _mathml_to_omml(mathml_str: str, display: bool) -> bytes | None:
    """Convert MathML string to OMML XML bytes using lxml."""
    try:
        root = etree.fromstring(mathml_str.encode("utf-8"))
    except etree.XMLSyntaxError:
        logger.debug("Failed to parse MathML XML")
        return None

    # Create OMML wrapper
    if display:
        omml_root = etree.Element(_M + "oMathPara")
        omml_math = etree.SubElement(omml_root, _M + "oMath")
    else:
        omml_root = etree.Element(_M + "oMath")

    _convert_element(root, omml_root if not display else omml_math, depth=0)

    try:
        return etree.tostring(omml_root, xml_declaration=False, encoding="unicode").encode("utf-8")
    except Exception:
        return None


def _convert_element(mathml_elem, omml_parent: etree.Element, depth: int) -> None:
    """Recursively convert a MathML element tree to OMML.

    Args:
        mathml_elem: Current MathML element (lxml Element).
        omml_parent: Parent OMML element to attach to.
        depth: Current recursion depth (prevents stack overflow).
    """
    if depth > _MAX_RECURSION:
        logger.warning("OMML conversion max recursion depth reached")
        return

    tag = etree.QName(mathml_elem).localname if mathml_elem.tag is etree.Comment else (
        etree.QName(mathml_elem).localname if isinstance(mathml_elem.tag, str) else ""
    )

    # Handle text content in the math element root
    if tag == "math":
        for child in mathml_elem:
            _convert_element(child, omml_parent, depth + 1)
        return

    # Map MathML tag to OMML tag
    omml_tag_name = _MATHML_TO_OMML.get(tag)

    if omml_tag_name is None:
        # Unsupported tag — try to process children
        if tag in ("mtd", "mtr", "mtable"):
            logger.debug("Skipping table MathML element '%s' in OMML conversion", tag)
            return
        # For unknown elements, just process children (flatten)
        for child in mathml_elem:
            _convert_element(child, omml_parent, depth + 1)
        return

    # Special handling for text runs (mi, mn, mo, mtext → m:r)
    if tag in ("mi", "mn", "mo", "mtext"):
        text = mathml_elem.text or ""
        r_elem = etree.SubElement(omml_parent, _M + omml_tag_name)

        # Run properties
        rpr = etree.SubElement(r_elem, _M + "rPr")
        # Font size
        sz = etree.SubElement(rpr, _M + "sz")
        sz.set(_M + "val", "20")  # 10pt * 2
        sz_ea = etree.SubElement(rpr, _M + "szCs")
        sz_ea.set(_M + "val", "20")

        if tag == "mo" and text in ("∑", "∫", "∏"):
            pass  # Keep default

        # Italic for identifiers
        if tag == "mi":
            italic = etree.SubElement(rpr, _M + "italic")
            italic.set(_M + "val", "1")

        # Text content
        t_elem = etree.SubElement(r_elem, _M + "t")
        t_elem.text = text
        return

    # Handle mfrac → m:f
    if tag == "mfrac":
        f_elem = etree.SubElement(omml_parent, _M + "f")
        # Numerator
        num = etree.SubElement(f_elem, _M + "num")
        children = list(mathml_elem)
        if len(children) >= 1:
            _convert_element(children[0], num, depth + 1)
        # Denominator
        den = etree.SubElement(f_elem, _M + "den")
        if len(children) >= 2:
            _convert_element(children[1], den, depth + 1)
        return

    # Handle superscript: msup → sSup (m:e for base, m:sup for superscript)
    if tag == "msup":
        ssup = etree.SubElement(omml_parent, _M + "sSup")
        base = etree.SubElement(ssup, _M + "e")
        sup = etree.SubElement(ssup, _M + "sup")
        children = list(mathml_elem)
        if len(children) >= 1:
            _convert_element(children[0], base, depth + 1)
        if len(children) >= 2:
            _convert_element(children[1], sup, depth + 1)
        return

    # Handle subscript: msub → sSub
    if tag == "msub":
        ssub = etree.SubElement(omml_parent, _M + "sSub")
        base = etree.SubElement(ssub, _M + "e")
        sub = etree.SubElement(ssub, _M + "sub")
        children = list(mathml_elem)
        if len(children) >= 1:
            _convert_element(children[0], base, depth + 1)
        if len(children) >= 2:
            _convert_element(children[1], sub, depth + 1)
        return

    # Handle sub+superscript: msubsup → sSubSup
    if tag == "msubsup":
        ssubsup = etree.SubElement(omml_parent, _M + "sSubSup")
        base = etree.SubElement(ssubsup, _M + "e")
        sub = etree.SubElement(ssubsup, _M + "sub")
        sup = etree.SubElement(ssubsup, _M + "sup")
        children = list(mathml_elem)
        if len(children) >= 1:
            _convert_element(children[0], base, depth + 1)
        if len(children) >= 2:
            _convert_element(children[1], sub, depth + 1)
        if len(children) >= 3:
            _convert_element(children[2], sup, depth + 1)
        return

    # Handle square root: msqrt → rad (with empty deg)
    if tag == "msqrt":
        rad = etree.SubElement(omml_parent, _M + "rad")
        deg = etree.SubElement(rad, _M + "deg")
        e = etree.SubElement(rad, _M + "e")
        for child in mathml_elem:
            _convert_element(child, e, depth + 1)
        return

    # Handle nth root: mroot → rad
    if tag == "mroot":
        rad = etree.SubElement(omml_parent, _M + "rad")
        children = list(mathml_elem)
        e = etree.SubElement(rad, _M + "e")
        if len(children) >= 1:
            _convert_element(children[0], e, depth + 1)
        deg = etree.SubElement(rad, _M + "deg")
        if len(children) >= 2:
            _convert_element(children[1], deg, depth + 1)
        return

    # Handle under/over scripts
    if tag == "munder":
        lim_low = etree.SubElement(omml_parent, _M + "limLow")
        e = etree.SubElement(lim_low, _M + "e")
        lim = etree.SubElement(lim_low, _M + "lim")
        children = list(mathml_elem)
        for i, child in enumerate(children):
            target = e if i == 0 else lim
            _convert_element(child, target, depth + 1)
        return

    if tag == "mover":
        lim_upp = etree.SubElement(omml_parent, _M + "limUpp")
        e = etree.SubElement(lim_upp, _M + "e")
        lim = etree.SubElement(lim_upp, _M + "lim")
        children = list(mathml_elem)
        for i, child in enumerate(children):
            target = e if i == 0 else lim
            _convert_element(child, target, depth + 1)
        return

    if tag == "munderover":
        lim = etree.SubElement(omml_parent, _M + "lim")
        e = etree.SubElement(lim, _M + "e")
        lim_sub = etree.SubElement(lim, _M + "lim")
        lim_sup = etree.SubElement(lim, _M + "lim")
        children = list(mathml_elem)
        for i, child in enumerate(children):
            target = e if i == 0 else (lim_sub if i == 1 else lim_sup)
            _convert_element(child, target, depth + 1)
        return

    # Handle mrow → m:e (expression container)
    if tag == "mrow":
        e_elem = etree.SubElement(omml_parent, _M + "e") if omml_parent.tag != _M + "e" else omml_parent
        for child in mathml_elem:
            _convert_element(child, e_elem if omml_parent.tag == _M + "e" else e_elem, depth + 1)
        return

    # Default: process children
    for child in mathml_elem:
        _convert_element(child, omml_parent, depth + 1)


# ── Insert OMML into DOCX paragraph ──


def insert_omml_into_paragraph(paragraph, omml_bytes: bytes) -> None:
    """Insert OMML XML at the end of a python-docx paragraph.

    The OMML is placed after any existing runs in the paragraph.
    """
    p_elem = paragraph._p

    omml_str = omml_bytes.decode("utf-8") if isinstance(omml_bytes, bytes) else omml_bytes
    omml_elem = etree.fromstring(omml_str.encode("utf-8"))

    # Append the OMML element directly to the paragraph
    p_elem.append(omml_elem)


# ── High-level helper for DOCX exporter ──


def render_latex_as_omml_or_fallback(
    latex: str,
    display: bool,
    paragraph,
    fallback_png: bool = True,
    body_width_cm: float = 17.0,
) -> bool:
    """Render LaTeX as OMML in a DOCX paragraph with fallback.

    Priority:
    1. OMML (native)
    2. PNG image (via matplotlib)
    3. Raw text fallback

    Args:
        latex: LaTeX source (without $ delimiters).
        display: Display-style formula.
        paragraph: python-docx paragraph to insert into.
        fallback_png: Whether to attempt PNG fallback.
        body_width_cm: Body width for PNG sizing.

    Returns:
        ``True`` if any rendering succeeded.
    """
    # Attempt 1: OMML
    omml = latex_to_omml_xml(latex, display)
    if omml:
        try:
            insert_omml_into_paragraph(paragraph, omml)
            return True
        except Exception:
            logger.debug("OMML insertion failed for '%s'", latex[:80])

    # Attempt 2: PNG
    if fallback_png:
        try:
            png = render_latex_to_png(latex, display)
            if png:
                from docx.shared import Cm
                import hashlib, os, tempfile

                # Write PNG to temp file and embed
                fname = f"latex_{hashlib.md5(png).hexdigest()[:12]}.png"
                tmpdir = tempfile.gettempdir()
                path = os.path.join(tmpdir, fname)
                with open(path, "wb") as f:
                    f.write(png)
                run = paragraph.add_run()
                run.add_picture(path, width=Cm(body_width_cm * 0.8))
                try:
                    os.remove(path)
                except OSError:
                    pass
                return True
        except Exception:
            logger.debug("PNG fallback failed for '%s'", latex[:80])

    # Attempt 3: raw text
    run = paragraph.add_run(f" [公式] {latex} ")
    run.font.size = _pt(8)
    from app.services.export.docx_exporter import _BODY_FONT, DocxExporter
    run.font.name = _BODY_FONT
    DocxExporter._set_east_asian_font(run, _BODY_FONT)
    return False


def _pt(val: float) -> Any:
    """Return a Pt value compatible with python-docx."""
    from docx.shared import Pt as _Pt
    return _Pt(val)
