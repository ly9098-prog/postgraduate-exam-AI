"""Server-side LaTeX rendering using matplotlib mathtext.

Since current question data (408 CS exam bank) contains zero LaTeX, this
module is primarily a future-proofing layer. It renders LaTeX expressions
embedded in ``$...$`` (inline) or ``$$...$$`` (display) delimiters to PNG
images that can be embedded in PDF.

Limitations of ``matplotlib.mathtext``:
- Supports basic LaTeX math subset (Greek, operators, fractions, integrals,
  sums, superscript/subscript, \\sqrt, \\frac, \\binom, \\stackrel, \\text)
- Does NOT support: \\begin{cases}, \\begin{aligned}, mhchem/\\ce{}, tikz,
  \\label, \\ref, \\pagebreak
- Chinese characters mixed in math mode are not supported

Fallback: when rendering fails, the raw LaTeX source is returned as plain
text for display in the PDF.
"""

from __future__ import annotations

import io
import logging
import re
import textwrap

logger = logging.getLogger(__name__)

# Match inline $...$ and display $$...$$ LaTeX
_INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)")
_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)


def find_latex_segments(text: str) -> list[dict]:
    """Split text into segments alternating between plain text and LaTeX.

    Returns a list of dicts, each with:
    - ``type``: "text" | "latex"
    - ``content``: the string content
    - ``display``: bool (only for latex type — True for $$...$$)
    """
    segments: list[dict] = []
    pos = 0
    remaining = text

    while remaining:
        # Try display math first
        dm = _DISPLAY_MATH_RE.search(remaining)
        im = _INLINE_MATH_RE.search(remaining)

        candidates = []
        if dm:
            candidates.append((dm.start(), dm.end(), dm.group(1), True))
        if im:
            candidates.append((im.start(), im.end(), im.group(1), False))

        if not candidates:
            segments.append({"type": "text", "content": remaining})
            break

        # Pick the nearest match
        candidates.sort(key=lambda x: x[0])
        start, end, latex, display = candidates[0]

        if start > 0:
            segments.append({"type": "text", "content": remaining[:start]})
        segments.append({"type": "latex", "content": latex, "display": display})

        remaining = remaining[end:]

    return segments


def render_latex_to_png(latex: str, display: bool = False) -> bytes | None:
    """Render a LaTeX expression to PNG bytes using matplotlib mathtext.

    Args:
        latex: LaTeX source without delimiters.
        display: True for display style (larger, centered).

    Returns:
        PNG bytes, or None if rendering fails.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import rcParams

        # Configure mathtext
        rcParams["mathtext.fontset"] = "dejavusans"
        rcParams["font.size"] = 12 if not display else 16

        fig, ax = plt.subplots(figsize=(0.1, 0.1))
        ax.axis("off")

        text_str = f"${latex}$" if not latex.startswith("$") else latex
        ax.text(
            0, 0, text_str,
            fontsize=rcParams["font.size"],
            va="bottom", ha="left",
            usetex=False,
        )

        # Render to PNG
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                    pad_inches=0.02, transparent=True)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        logger.warning("LaTeX rendering failed for '%s': %s",
                       latex[:80], e)
        return None


def has_latex(text: str) -> bool:
    """Check if text contains any LaTeX delimiters."""
    if not text:
        return False
    return bool(_INLINE_MATH_RE.search(text) or _DISPLAY_MATH_RE.search(text))
