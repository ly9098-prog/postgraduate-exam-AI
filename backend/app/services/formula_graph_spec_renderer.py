"""Graph spec renderer — matplotlib + sympy with subprocess isolation.

Validates Chinese font availability at import time.
Renders graph_spec JSON to 1600x1000 PNG bytes in a subprocess.
"""

import asyncio
import concurrent.futures
import io
import logging
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import sympy as sp

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Chinese font check (import-time)
# ═══════════════════════════════════════════════════════════════

_CJK_FONT_CANDIDATES = [
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
    "Noto Sans CJK SC",
    "Noto Sans CJK",
    "SimHei",
    "Microsoft YaHei",
    "Source Han Sans SC",
]


def _find_cjk_font() -> str:
    """Find an installed CJK font or raise RuntimeError."""
    available = {f.name for f in fm.fontManager.ttflist}
    for candidate in _CJK_FONT_CANDIDATES:
        if candidate in available:
            return candidate
    # Fallback: fuzzy match
    for fname in available:
        lower = fname.lower()
        if any(k in lower for k in ["cjk", "wenquanyi", "wqy", "noto", "simsun", "simhei", "songti", "heiti"]):
            return fname
    raise RuntimeError(
        "No CJK-capable font found. Install one:\n"
        "  sudo apt install fonts-wqy-zenhei\n"
        "  sudo apt install fonts-noto-cjk\n"
        "  sudo apt install fonts-wqy-microhei"
    )


_CJK_FONT = None
try:
    _CJK_FONT = _find_cjk_font()
    logger.info("CJK font for graph rendering: %s", _CJK_FONT)
except RuntimeError as e:
    logger.warning("CJK font not found at import time: %s", e)


def _assert_cjk_font() -> str:
    """Ensure a CJK font is available (call at render time). Raises RuntimeError."""
    global _CJK_FONT
    if _CJK_FONT is not None:
        return _CJK_FONT
    _CJK_FONT = _find_cjk_font()
    return _CJK_FONT


# ═══════════════════════════════════════════════════════════════
# Versioned theme
# ═══════════════════════════════════════════════════════════════

RENDERER_VERSION = 1
THEME_VERSION = 1
FONT_VERSION = 1

GRAPH_THEME = {
    "version": THEME_VERSION,
    "colors": ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2"],
    "dash_styles": {
        "solid": "solid",
        "dashed": (6, 3),
        "dotted": (2, 2),
        "dashdot": (6, 2, 2, 2),
    },
    "dpi": 100,
    "width": 1600,
    "height": 1000,
    "thumbnail_size": (600, 450),
    "font": {
        "family": _CJK_FONT,
        "size": {
            "axis_label": 13,
            "tick": 11,
            "legend": 11,
            "title": 15,
            "annotation": 10,
            "panel_title": 12,
        },
    },
    "grid": {"alpha": 0.6, "color": "#d0d0d0"},
    "axis": {"color": "#333333", "width": 1.0},
    "annotation_color": "#b91c1c",
    "asymptote_color": "#94a3b8",
    "asymptote_style": (4, 4),
}

plt.rcParams.update({
    "font.family": _CJK_FONT or "sans-serif",
    "font.sans-serif": [_CJK_FONT] if _CJK_FONT else [],
    "text.usetex": False,
    "axes.unicode_minus": True,
})


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _build_x_grid(
    intervals: list,
    exclude_points: list[float],
    x_range: list[float],
    num_points: int = 4000,
) -> np.ndarray:
    """Build x-sampling grid from domain intervals and range."""
    if intervals:
        parts = []
        for iv in intervals:
            start = iv[0] if iv[0] is not None else x_range[0]
            end = iv[1] if iv[1] is not None else x_range[1]
            if start >= end:
                continue
            # Scale point density to interval width
            n = max(200, int(num_points * (end - start) / (x_range[1] - x_range[0] + 1e-12)))
            parts.append(np.linspace(start, end, n))
        if not parts:
            return np.array([])
        xs = np.concatenate(parts)
    else:
        # If domain interval from front end is empty, use the panel's x_range per 'x_range' directly.
        xs = np.linspace(x_range[0], x_range[1], num_points)

    # Sort and deduplicate
    xs = np.unique(np.sort(xs))

    # Remove excluded points
    if exclude_points:
        mask = np.ones_like(xs, dtype=bool)
        for ep in exclude_points:
            mask &= ~np.isclose(xs, ep, atol=1e-8)
        xs = xs[mask]

    return xs


def _filter_finite(xs: np.ndarray, ys: np.ndarray):
    mask = np.isfinite(ys)
    return xs[mask], ys[mask]


def _discontinuity_gap(
    xs: np.ndarray, ys: np.ndarray, threshold: float | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Split data at large discontinuities (asymptotes, jumps)."""
    if len(xs) < 2:
        return [(xs, ys)] if len(xs) > 0 else []

    if threshold is None:
        y_range = np.ptp(ys[np.isfinite(ys)])
        threshold = max(5.0, y_range * 0.5) if y_range > 0 else 5.0

    segments = []
    start = 0
    for i in range(1, len(xs)):
        dy = abs(ys[i] - ys[i - 1])
        if dy > threshold:
            if i - start > 1:
                segments.append((xs[start:i], ys[start:i]))
            start = i
    if len(xs) - start > 1:
        segments.append((xs[start:], ys[start:]))
    return segments if segments else [(xs, ys)]


def _auto_range(
    xs_list: list[np.ndarray],
    ys_list: list[np.ndarray],
    annotations: list[dict] | None = None,
    mode: str = "auto_robust",
) -> tuple[float, float, float, float]:
    """Compute axis range from data with optional robust estimation."""
    all_x = np.concatenate(xs_list) if xs_list else np.array([])
    all_y = np.concatenate(ys_list) if ys_list else np.array([])

    if len(all_x) == 0:
        return -6, 6, -6, 6

    if mode == "auto":
        x_min, x_max = float(np.min(all_x)), float(np.max(all_x))
        y_min, y_max = float(np.min(all_y)), float(np.max(all_y))
    else:  # auto_robust
        x_min, x_max = float(np.percentile(all_x, 1)), float(np.percentile(all_x, 99))
        y_min, y_max = float(np.percentile(all_y, 1)), float(np.percentile(all_y, 99))

    # Include annotation points
    if annotations:
        for ann in annotations:
            x_min = min(x_min, ann.get("x", x_min))
            x_max = max(x_max, ann.get("x", x_max))
            y_min = min(y_min, ann.get("y", y_min))
            y_max = max(y_max, ann.get("y", y_max))

    # Add padding
    x_pad = max(0.5, (x_max - x_min) * 0.05)
    y_pad = max(0.5, (y_max - y_min) * 0.05)
    return x_min - x_pad, x_max + x_pad, y_min - y_pad, y_max + y_pad


def _sanitize_label(text: str | None) -> str:
    """Remove control characters from label text."""
    if not text:
        return ""
    return "".join(c for c in text if c.isprintable() or c in "\n\r\t").strip()


# ═══════════════════════════════════════════════════════════════
# Per-panel rendering
# ═══════════════════════════════════════════════════════════════

def _render_panel(ax, panel: dict, color_cycle: list[str]) -> dict:
    """Render expressions, annotations, and reference lines on one axes.

    Returns metadata dict with curve_count, total_points, valid_points.
    """
    theme = GRAPH_THEME
    expressions = panel.get("expressions", [])
    domain = panel.get("domain", {})
    x_range = panel.get("x_range", [-6, 6])
    y_range = panel.get("y_range", [-6, 6])
    annotations = panel.get("annotations", [])
    vlines = panel.get("vertical_lines", [])
    hlines = panel.get("horizontal_lines", [])
    axis_mode = panel.get("axis_mode", "auto_robust")
    title = panel.get("title")

    # Axes styling
    ax.set_facecolor("white")
    ax.grid(True, color=theme["grid"]["color"], linewidth=0.5, alpha=theme["grid"]["alpha"])
    ax.set_axisbelow(True)

    ax.spines["left"].set_color(theme["axis"]["color"])
    ax.spines["bottom"].set_color(theme["axis"]["color"])
    ax.spines["left"].set_linewidth(theme["axis"]["width"])
    ax.spines["bottom"].set_linewidth(theme["axis"]["width"])
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    ax.tick_params(colors=theme["axis"]["color"], labelsize=theme["font"]["size"]["tick"])

    # Labels
    x_label = _sanitize_label(panel.get("x_label", "x"))
    y_label = _sanitize_label(panel.get("y_label", "y"))
    ax.set_xlabel(x_label, fontsize=theme["font"]["size"]["axis_label"])
    ax.set_ylabel(y_label, fontsize=theme["font"]["size"]["axis_label"])
    if title:
        ax.set_title(_sanitize_label(title), fontsize=theme["font"]["size"]["panel_title"])

    # Reference lines first (drawn behind curves)
    for vl in vlines:
        val = vl.get("value")
        if val is not None:
            ls = theme["dash_styles"].get(vl.get("style", "dashed"), (4, 4))
            ax.axvline(x=val, color=theme["asymptote_color"], linewidth=1.0, linestyle=ls, alpha=0.7)
            label = _sanitize_label(vl.get("label"))
            if label:
                ax.text(val, ax.get_ylim()[1], label, fontsize=9, color=theme["asymptote_color"],
                        ha="left", va="bottom", rotation=90)

    for hl in hlines:
        val = hl.get("value")
        if val is not None:
            ls = theme["dash_styles"].get(hl.get("style", "dashed"), (4, 4))
            ax.axhline(y=val, color=theme["asymptote_color"], linewidth=1.0, linestyle=ls, alpha=0.7)
            label = _sanitize_label(hl.get("label"))
            if label:
                ax.text(ax.get_xlim()[1], val, label, fontsize=9, color=theme["asymptote_color"],
                        ha="left", va="bottom")

    # Render expressions
    collected_xs = []
    collected_ys = []
    legend_handles = []
    legend_labels = []
    curve_count = 0
    total_points = 0
    valid_points = 0

    for i, expr_data in enumerate(expressions):
        expr_str = expr_data.get("expression", "")
        if not expr_str:
            continue

        try:
            expr_sympy = _parse_expression_cached(expr_str)
        except ValueError:
            continue

        color = color_cycle[i % len(color_cycle)]
        line_style_key = expr_data.get("line_style", "solid")
        dash = theme["dash_styles"].get(line_style_key, "solid")
        label = _sanitize_label(expr_data.get("label", ""))

        # Build x grid
        intervals = domain.get("intervals", [])
        exclude = domain.get("exclude_points", [])
        xs = _build_x_grid(intervals, exclude, x_range)

        # Evaluate
        try:
            f = _lambdify_cached(expr_sympy)
            ys = f(xs)
        except Exception:
            continue

        curve_count += 1
        total_points += len(xs)

        xs, ys = _filter_finite(xs, ys)
        if len(xs) < 2:
            continue

        valid_points += len(xs)
        collected_xs.append(xs)
        collected_ys.append(ys)

        # Draw segments with discontinuity detection
        segments = _discontinuity_gap(xs, ys)
        for j, (seg_x, seg_y) in enumerate(segments):
            (line,) = ax.plot(
                seg_x, seg_y, color=color, linewidth=2.0,
                linestyle=dash, label=label if (j == 0 and label) else None,
            )

        if label:
            legend_handles.append(plt.Line2D([0], [0], color=color, linewidth=2, linestyle=dash))
            legend_labels.append(label)

    # Annotations (drawn on top of curves)
    for ann in annotations:
        x, y = ann.get("x"), ann.get("y")
        if x is None or y is None:
            continue
        ann_label = _sanitize_label(ann.get("label", ""))
        color = ann.get("color", theme["annotation_color"])
        point_style = ann.get("point_style", "filled")

        if point_style == "hollow":
            ax.plot(x, y, "o", color=color, markersize=6, fillstyle="none",
                    markeredgewidth=1.5, markeredgecolor=color)
        else:
            ax.plot(x, y, "o", color=color, markersize=6)

        if ann_label:
            ax.annotate(ann_label, (x, y), xytext=(8, 8),
                        textcoords="offset points", fontsize=theme["font"]["size"]["annotation"],
                        color=color)

    # Legend
    if legend_labels:
        leg = ax.legend(
            legend_handles, legend_labels,
            loc="upper right", fontsize=theme["font"]["size"]["legend"],
            framealpha=0.9, edgecolor=theme["axis"]["color"],
        )

    # Set axis limits
    if axis_mode == "manual":
        ax.set_xlim(x_range[0], x_range[1])
        ax.set_ylim(y_range[0], y_range[1])
    else:
        x0, x1, y0, y1 = _auto_range(collected_xs, collected_ys, annotations, axis_mode)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)

    metadata = {"curve_count": curve_count, "total_points": total_points, "valid_points": valid_points}
    return metadata


# ── Cached parsing/lambdify ──

_parse_cache: dict[str, sp.Expr] = {}
_lambdify_cache: dict[int, callable] = {}


def _parse_expression_cached(expr_str: str):
    """Parse with memoization."""
    from app.services.formula_graph_expr_parser import parse_expression
    if expr_str not in _parse_cache:
        _parse_cache[expr_str] = parse_expression(expr_str)
    return _parse_cache[expr_str]


def _lambdify_cached(expr):
    from app.services.formula_graph_expr_parser import lambdify_expression
    key = id(expr)
    if key not in _lambdify_cache:
        _lambdify_cache[key] = lambdify_expression(expr)
    return _lambdify_cache[key]


# ═══════════════════════════════════════════════════════════════
# Template dispatchers
# ═══════════════════════════════════════════════════════════════

def _render_single_function(spec: dict) -> tuple[plt.Figure, list, list]:
    """Single axes with all panels overlaid (standard use: 1 panel)."""
    theme = GRAPH_THEME
    panels = spec.get("panels", [])
    layout = spec.get("layout", {"rows": 1, "columns": 1})
    fig, ax = plt.subplots(
        figsize=(theme["width"] / theme["dpi"], theme["height"] / theme["dpi"]),
        dpi=theme["dpi"],
    )
    fig.patch.set_facecolor("white")

    all_meta = []
    color_cycle = list(theme["colors"])
    for panel in panels:
        meta = _render_panel(ax, panel, color_cycle)
        all_meta.append(meta)

    # Global title
    title = spec.get("title") or spec.get("panels", [{}])[0].get("title", "") if panels else ""
    if title:
        fig.suptitle(_sanitize_label(title), fontsize=theme["font"]["size"]["title"], y=0.98)

    fig.tight_layout(rect=[0, 0, 1, 0.97] if title else None)
    return fig, all_meta, [ax]


def _render_multi_panel(spec: dict) -> tuple[plt.Figure, list, list]:
    """Multiple subplots per spec panels."""
    theme = GRAPH_THEME
    panels = spec.get("panels", [])
    layout = spec.get("layout", {"rows": 1, "columns": 1})
    rows = layout.get("rows", 1)
    cols = layout.get("columns", 1)

    fig, axes = plt.subplots(
        rows, cols,
        figsize=(theme["width"] / theme["dpi"], theme["height"] / theme["dpi"]),
        dpi=theme["dpi"],
        squeeze=False,
    )
    fig.patch.set_facecolor("white")

    color_cycle = list(theme["colors"])
    all_meta = []

    for idx, panel in enumerate(panels):
        if idx >= rows * cols:
            break
        row, col = divmod(idx, cols)
        ax = axes[row][col]
        meta = _render_panel(ax, panel, color_cycle)
        all_meta.append(meta)

    # Hide unused subplots
    for idx in range(len(panels), rows * cols):
        row, col = divmod(idx, cols)
        axes[row][col].set_visible(False)

    fig.tight_layout(pad=2.0)
    # Global title
    title = spec.get("title", "")
    if title:
        fig.suptitle(_sanitize_label(title), fontsize=theme["font"]["size"]["title"], y=1.01)

    return fig, all_meta, axes


def _render_discontinuity_comparison(spec: dict) -> tuple[plt.Figure, list, list]:
    """2×2 preset with 4 discontinuity types."""
    spec.setdefault("layout", {"rows": 2, "columns": 2})

    # Default expressions if panels empty
    if not spec.get("panels"):
        spec["panels"] = [
            {
                "title": "可去间断点",
                "expressions": [{"expression": "(x**2 - 1)/(x - 1)", "label": "f(x)=(x²-1)/(x-1)"}],
                "x_range": [-3, 3], "y_range": [-1, 5],
                "annotations": [{"x": 1, "y": 2, "label": "可去", "point_style": "hollow"}],
                "axis_mode": "manual",
                "horizontal_lines": [{"value": 2, "style": "dashed"}],
            },
            {
                "title": "跳跃间断点",
                "expressions": [{"expression": "floor(x)", "label": "f(x)=⌊x⌋"}],
                "x_range": [-3, 3], "y_range": [-3, 3],
                "axis_mode": "manual",
            },
            {
                "title": "无穷间断点",
                "expressions": [{"expression": "1/x", "label": "f(x)=1/x"}],
                "x_range": [-3, 3], "y_range": [-10, 10],
                "axis_mode": "manual",
                "vertical_lines": [{"value": 0, "label": "x=0"}],
            },
            {
                "title": "振荡间断点",
                "expressions": [
                    {"expression": "sin(1/x)", "label": "f(x)=sin(1/x)"},
                ],
                "x_range": [-1, 1], "y_range": [-1.5, 1.5],
                "axis_mode": "manual",
                "vertical_lines": [{"value": 0, "style": "dashed"}],
            },
        ]

    return _render_multi_panel(spec)


def _render_inequality_auxiliary(spec: dict) -> tuple[plt.Figure, list, list]:
    """1×3 preset: inequality auxiliary functions."""
    spec.setdefault("layout", {"rows": 1, "columns": 3})

    if not spec.get("panels"):
        spec["panels"] = [
            {
                "title": "y=eˣ 与 y=x+1",
                "expressions": [
                    {"expression": "exp(x)", "label": "y=eˣ"},
                    {"expression": "x+1", "label": "y=x+1"},
                ],
                "x_range": [-3, 3], "y_range": [-1, 8],
                "annotations": [{"x": 0, "y": 1, "label": "(0,1)"}],
                "axis_mode": "manual",
            },
            {
                "title": "y=ln(x) 与 y=x-1",
                "expressions": [
                    {"expression": "ln(x)", "label": "y=ln x"},
                    {"expression": "x-1", "label": "y=x-1"},
                ],
                "domain": {"intervals": [[0.001, 5]]},
                "x_range": [0, 5], "y_range": [-3, 4],
                "annotations": [{"x": 1, "y": 0, "label": "(1,0)"}],
                "axis_mode": "manual",
                "vertical_lines": [{"value": 0, "style": "dashed"}],
            },
            {
                "title": "y=x 与 y=sin(x)",
                "expressions": [
                    {"expression": "x", "label": "y=x"},
                    {"expression": "sin(x)", "label": "y=sin x"},
                ],
                "domain": {"intervals": [[0, 5]]},
                "x_range": [0, 5], "y_range": [-1, 5],
                "annotations": [{"x": 0, "y": 0, "label": "(0,0)"}],
                "axis_mode": "manual",
            },
        ]

    return _render_multi_panel(spec)


_TEMPLATE_DISPATCH = {
    "single_function": _render_single_function,
    "function_comparison": _render_single_function,  # same as single (multiple expr on one axes)
    "multi_panel": _render_multi_panel,
    "discontinuity_comparison": _render_discontinuity_comparison,
    "inequality_auxiliary": _render_inequality_auxiliary,
}


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def _render_spec_sync(spec: dict) -> tuple[bytes, dict]:
    """Render a graph_spec to PNG bytes (synchronous, for subprocess)."""
    template = spec.get("template", "single_function")
    render_mode = spec.get("render_mode", "explicit_2d")

    if render_mode == "manual_only":
        raise ValueError("render_mode 'manual_only' cannot be auto-rendered")

    dispatch = _TEMPLATE_DISPATCH.get(template)
    if dispatch is None:
        raise ValueError(f"Unknown template: '{template}'")

    fig, meta_list, axes = dispatch(spec)

    # Compute summary metadata
    total_curves = sum(m.get("curve_count", 0) for m in meta_list)
    total_pts = sum(m.get("total_points", 0) for m in meta_list)
    valid_pts = sum(m.get("valid_points", 0) for m in meta_list)

    # Save
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=GRAPH_THEME["dpi"],
        bbox_inches="tight", pad_inches=0.2,
        facecolor="white", edgecolor="none",
    )
    plt.close(fig)

    png_bytes = buf.getvalue()
    metadata = {
        "total_curves": total_curves,
        "total_points": total_pts,
        "valid_points": valid_pts,
        "panel_count": len(meta_list),
        "width": GRAPH_THEME["width"],
        "height": GRAPH_THEME["height"],
    }

    return png_bytes, metadata


def _resize_to_canvas(png_bytes: bytes, width: int, height: int) -> bytes:
    """Resize to exact dimensions with letterbox."""
    from PIL import Image
    img_buf = io.BytesIO(png_bytes)
    img = Image.open(img_buf).convert("RGBA")
    if img.size == (width, height):
        return png_bytes

    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    img.thumbnail((width, height), Image.LANCZOS)
    x = (width - img.width) // 2
    y = (height - img.height) // 2
    canvas.paste(img, (x, y), img)
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _create_thumbnail(png_bytes: bytes) -> bytes:
    """Create a 600x450 letterbox thumbnail."""
    from PIL import Image
    w, h = GRAPH_THEME["thumbnail_size"]
    return _resize_to_canvas(png_bytes, w, h)


# ── Quality checks ──

def check_quality(png_bytes: bytes, spec: dict, render_meta: dict) -> dict:
    """Post-render quality check.

    Returns {"errors": [...], "warnings": [...], "passed": bool}.
    """
    errors = []
    warnings = []

    # 1. Blank image check
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    arr = np.array(img)
    white_ratio = np.mean(arr > 250)
    if white_ratio > 0.99:
        errors.append("图像几乎全白，可能渲染失败")

    # 2. Valid points check
    valid = render_meta.get("valid_points", 0)
    if valid < 10:
        errors.append(f"有效数据点不足 (仅 {valid} 个)")

    # 3. All NaN/Inf check
    if render_meta.get("total_points", 0) > 0 and valid == 0:
        errors.append("所有函数均未产生有效数据点")

    # 4. Curve count matches expected
    expected = len(spec.get("panels", []))
    actual = render_meta.get("panel_count", 0)
    if expected != actual:
        errors.append(f"面板数量不匹配: 期望 {expected}, 实际 {actual}")

    # 5. Scale check (y-span vs data range)
    if valid > 0 and render_meta.get("total_curves", 0) > 0:
        # Check if curves fill the image
        non_white = arr[arr < 250]
        if len(non_white) < 100:
            warnings.append("曲线像素较少，可能大部分区域为空")

    # 6. Key annotations outside visible area (can't check without axes limits here)
    # This is best done in the renderer itself; surface as warning if annotations exist

    passed = len(errors) == 0
    return {"errors": errors, "warnings": warnings, "passed": passed}


# ── Subprocess pool ──

_process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=2)
RENDER_TIMEOUT = 30


async def render_spec(spec: dict, timeout: int = RENDER_TIMEOUT) -> tuple[bytes, dict]:
    """Render a graph_spec to PNG bytes in an isolated subprocess.

    Returns ``(png_bytes, metadata_dict)``.

    Raises ``ValueError`` for spec/expression errors and ``TimeoutError``
    for rendering that exceeds the timeout.
    """
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_process_pool, _render_spec_sync, spec)

    try:
        png, metadata = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"Graph rendering timed out after {timeout}s")

    return png, metadata


async def render_and_check(spec: dict, timeout: int = RENDER_TIMEOUT) -> tuple[bytes, dict, dict]:
    """Render and run quality check. Returns ``(png, metadata, quality)``."""
    png, metadata = await render_spec(spec, timeout)
    quality = check_quality(png, spec, metadata)
    return png, metadata, quality
