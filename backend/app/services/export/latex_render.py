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

logger = logging.getLogger(__name__)

# Match inline $...$ and display $$...$$ LaTeX
_INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)")
_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)


_LATEX_SYMBOLS = {
    r"\cdot": "·",
    r"\times": "×",
    r"\div": "÷",
    r"\pm": "±",
    r"\mp": "∓",
    r"\leq": "≤",
    r"\le": "≤",
    r"\geq": "≥",
    r"\ge": "≥",
    r"\neq": "≠",
    r"\ne": "≠",
    r"\approx": "≈",
    r"\equiv": "≡",
    r"\infty": "∞",
    r"\rightarrow": "→",
    r"\to": "→",
    r"\leftarrow": "←",
    r"\Rightarrow": "⇒",
    r"\Leftarrow": "⇐",
    r"\in": "∈",
    r"\notin": "∉",
    r"\subseteq": "⊆",
    r"\subset": "⊂",
    r"\supseteq": "⊇",
    r"\supset": "⊃",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\sum": "∑",
    r"\prod": "∏",
    r"\int": "∫",
    r"\partial": "∂",
    r"\nabla": "∇",
    r"\ldots": "…",
    r"\cdots": "…",
    r"\dots": "…",
    r"\forall": "∀",
    r"\exists": "∃",
    r"\land": "∧",
    r"\lor": "∨",
    r"\neg": "¬",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\varepsilon": "ε",
    r"\theta": "θ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\pi": "π",
    r"\rho": "ρ",
    r"\sigma": "σ",
    r"\phi": "φ",
    r"\varphi": "φ",
    r"\omega": "ω",
    r"\Delta": "Δ",
    r"\Theta": "Θ",
    r"\Lambda": "Λ",
    r"\Pi": "Π",
    r"\Sigma": "Σ",
    r"\Omega": "Ω",
}


def _replace_braced_command(text: str, command: str) -> str:
    """Remove a one-argument formatting command while preserving its content."""
    pattern = re.compile(rf"\\{command}\s*\{{([^{{}}]*)\}}")
    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(r"\1", text)
    return text


def latex_expression_to_text(latex: str) -> str:
    """Convert common inline LaTeX into compact, printable Unicode text.

    PDF body text cannot reliably flow bitmap formula images inline.  This
    converter intentionally targets the common notation used in question
    stems and options so expressions such as ``$2n$`` and ``$a_i$`` remain on
    the surrounding line instead of becoming page-wide images.  Unsupported
    commands are preserved without the leading backslash rather than dropped.
    """
    value = str(latex or "").strip()
    if not value:
        return ""

    value = re.sub(r"\\(?:displaystyle|textstyle|scriptstyle|scriptscriptstyle)\b", "", value)
    value = re.sub(r"\\(?:left|right)\b", "", value)
    value = re.sub(r"\\(?:,|;|:|!)", " ", value)
    value = re.sub(r"\\(?:quad|qquad)\b", " ", value)

    # Resolve simple fractions and roots repeatedly so nested basic formulas
    # degrade into readable text rather than leaking TeX control sequences.
    fraction_re = re.compile(r"\\(?:d?frac)\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
    root_re = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
    previous = None
    while previous != value:
        previous = value
        value = fraction_re.sub(lambda m: f"({m.group(1)})/({m.group(2)})", value)
        value = root_re.sub(lambda m: f"√({m.group(1)})", value)

    for command in ("text", "textrm", "textit", "textbf", "mathrm", "mathbf", "mathit", "operatorname"):
        value = _replace_braced_command(value, command)

    # Replace longest commands first (e.g. \subseteq before \subset).
    for source in sorted(_LATEX_SYMBOLS, key=len, reverse=True):
        value = value.replace(source, _LATEX_SYMBOLS[source])

    value = re.sub(r"_\{([^{}]+)\}", r"_\1", value)
    value = re.sub(r"\^\{([^{}]+)\}", r"^\1", value)
    value = value.replace("{", "(").replace("}", ")")
    value = re.sub(r"\\([A-Za-z]+)", r"\1", value)
    value = value.replace(r"\_", "_").replace(r"\%", "%").replace(r"\$", "$")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def latex_to_plain_text(text: str) -> str:
    """Replace all inline/display LaTeX delimiters with printable text."""
    if not text:
        return ""
    parts: list[str] = []
    for segment in find_latex_segments(str(text)):
        if segment["type"] == "text":
            parts.append(segment["content"])
        else:
            rendered = latex_expression_to_text(segment["content"])
            if segment.get("display"):
                if parts and not parts[-1].endswith("\n"):
                    parts.append("\n")
                parts.append(rendered)
                parts.append("\n")
            else:
                parts.append(rendered)
    return "".join(parts).strip()


def find_latex_segments(text: str) -> list[dict]:
    """Split text into segments alternating between plain text and LaTeX.

    Returns a list of dicts, each with:
    - ``type``: "text" | "latex"
    - ``content``: the string content
    - ``display``: bool (only for latex type — True for $$...$$)
    """
    segments: list[dict] = []
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
