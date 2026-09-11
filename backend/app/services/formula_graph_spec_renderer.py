"""Graph spec renderer — matplotlib + sympy with subprocess isolation.

Validates Chinese font availability at import time.
Renders graph_spec JSON to 1600x1000 PNG bytes in a subprocess.
"""

import asyncio
import atexit
import concurrent.futures
import io
import logging
import os
import threading

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
    # Fallback: fuzzy match on ttflist names
    for fname in available:
        lower = fname.lower()
        if any(
            k in lower
            for k in [
                "cjk",
                "wenquanyi",
                "wqy",
                "noto",
                "simsun",
                "simhei",
                "songti",
                "heiti",
            ]
        ):
            return fname
    # Fallback: try fontconfig via findfont (covers system fonts not in ttflist)
    for candidate in _CJK_FONT_CANDIDATES:
        try:
            fpath = fm.findfont(candidate, fallback_to_default=False)
            if fpath and not fpath.endswith("DejaVu Sans"):
                fm.fontManager.addfont(fpath)
                logger.info(
                    "CJK font discovered via findfont: %s -> %s", candidate, fpath
                )
                return candidate
        except Exception:
            continue
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
        "dashed": (0, (6, 3)),
        "dotted": (0, (2, 2)),
        "dashdot": (0, (6, 2, 2, 2)),
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
    "asymptote_style": (0, (4, 4)),
}

plt.rcParams.update(
    {
        "font.family": _CJK_FONT or "sans-serif",
        "font.sans-serif": [_CJK_FONT] if _CJK_FONT else [],
        "text.usetex": False,
        "axes.unicode_minus": False,
    }
)


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
            n = max(
                200, int(num_points * (end - start) / (x_range[1] - x_range[0] + 1e-12))
            )
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
    xs: np.ndarray,
    ys: np.ndarray,
    threshold: float | None = None,
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


def _render_shading(ax, shading: list[dict], x_range: list[float]) -> None:
    """Render filled regions between two curves.

    Supports both vertical (fill_between) and horizontal (fill_betweenx)
    orientation via the ``orientation`` field ("vertical" / "horizontal").
    """
    for region in shading:
        y1_str = region.get("y1_expression", "")
        y2_str = region.get("y2_expression", "0")
        color = region.get("color", "#2563eb")
        alpha = region.get("alpha", 0.25)
        label = _sanitize_label(region.get("label", ""))
        rx = region.get("x_range", x_range)
        orientation = region.get("orientation", "vertical")

        if not y1_str:
            continue

        try:
            expr1 = _parse_expression_cached(y1_str)
            f1 = _lambdify_cached(expr1)
        except ValueError:
            continue

        f2 = None
        if y2_str:
            try:
                expr2 = _parse_expression_cached(y2_str)
                f2 = _lambdify_cached(expr2)
            except ValueError:
                pass

        xs = np.linspace(rx[0], rx[1], 800)
        with np.errstate(all="ignore"):
            y1 = f1(xs)
            y2 = f2(xs) if f2 else np.zeros_like(xs)

        # Ensure arrays (lambdify of constant returns scalar)
        if np.ndim(y1) == 0:
            y1 = np.full_like(xs, y1)
        if np.ndim(y2) == 0:
            y2 = np.full_like(xs, y2)

        mask = np.isfinite(y1) & np.isfinite(y2)
        if not np.any(mask):
            continue

        if orientation == "horizontal":
            # For Y-type regions: shade horizontally between x=g₁(y) and x=g₂(y)
            # y1 gves x=g₁(y), y2 gives x=g₂(y) — shade between them at each y
            ax.fill_betweenx(
                xs[mask],
                y1[mask],
                y2[mask],
                color=color,
                alpha=alpha,
                label=label or None,
            )
        else:
            ax.fill_between(
                xs[mask],
                y1[mask],
                y2[mask],
                color=color,
                alpha=alpha,
                label=label or None,
            )


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

    # Shading regions (fill_between) — drawn first, behind curves
    shading = panel.get("shading", [])
    _render_shading(ax, shading, x_range)

    # Axes styling
    ax.set_facecolor("white")

    axis_style = panel.get("axis_style", "box")
    if axis_style == "cross":
        ax.grid(True, linewidth=0.6, alpha=0.18)
    else:
        ax.grid(
            True,
            color=theme["grid"]["color"],
            linewidth=0.5,
            alpha=theme["grid"]["alpha"],
        )
    ax.set_axisbelow(True)

    ax.spines["left"].set_color(theme["axis"]["color"])
    ax.spines["bottom"].set_color(theme["axis"]["color"])
    ax.spines["left"].set_linewidth(theme["axis"]["width"])
    ax.spines["bottom"].set_linewidth(theme["axis"]["width"])
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    if axis_style == "cross":
        ax.spines["bottom"].set_position(("data", 0))
        ax.spines["left"].set_position(("data", 0))
        ax.spines["bottom"].set_linewidth(1.4)
        ax.spines["left"].set_linewidth(1.4)
        ax.xaxis.set_ticks_position("bottom")
        ax.yaxis.set_ticks_position("left")

    ax.tick_params(
        colors=theme["axis"]["color"], labelsize=theme["font"]["size"]["tick"]
    )

    # Custom ticks (optional — backward compatible)
    x_ticks = panel.get("x_ticks")
    if x_ticks is not None:
        x_tick_labels = panel.get("x_tick_labels")
        ax.set_xticks(x_ticks)
        if x_tick_labels is not None:
            ax.set_xticklabels(x_tick_labels, fontsize=theme["font"]["size"]["tick"])
    y_ticks = panel.get("y_ticks")
    if y_ticks is not None:
        y_tick_labels = panel.get("y_tick_labels")
        ax.set_yticks(y_ticks)
        if y_tick_labels is not None:
            ax.set_yticklabels(y_tick_labels, fontsize=theme["font"]["size"]["tick"])

    # Labels (skip for cross-axis — handled by _add_cross_axis_arrows)
    if axis_style != "cross":
        x_label = _sanitize_label(panel.get("x_label", "x"))
        y_label = _sanitize_label(panel.get("y_label", "y"))
        ax.set_xlabel(x_label, fontsize=theme["font"]["size"]["axis_label"])
        ax.set_ylabel(y_label, fontsize=theme["font"]["size"]["axis_label"])
    if title:
        ax.set_title(
            _sanitize_label(title), fontsize=theme["font"]["size"]["panel_title"]
        )

    # Reference lines first (drawn behind curves)
    for vl in vlines:
        val = vl.get("value")
        if val is not None:
            ls = theme["dash_styles"].get(vl.get("style", "dashed"), (0, (4, 4)))
            ax.axvline(
                x=val,
                color=theme["asymptote_color"],
                linewidth=1.0,
                linestyle=ls,
                alpha=0.7,
            )
            label = _sanitize_label(vl.get("label"))
            if label:
                ax.text(
                    val,
                    ax.get_ylim()[1],
                    label,
                    fontsize=9,
                    color=theme["asymptote_color"],
                    ha="left",
                    va="bottom",
                    rotation=90,
                )

    for hl in hlines:
        val = hl.get("value")
        if val is not None:
            ls = theme["dash_styles"].get(hl.get("style", "dashed"), (0, (4, 4)))
            ax.axhline(
                y=val,
                color=theme["asymptote_color"],
                linewidth=1.0,
                linestyle=ls,
                alpha=0.7,
            )
            label = _sanitize_label(hl.get("label"))
            if label:
                ax.text(
                    ax.get_xlim()[1],
                    val,
                    label,
                    fontsize=9,
                    color=theme["asymptote_color"],
                    ha="left",
                    va="bottom",
                )

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

        # Build x grid — expression-level domain with panel-level fallback
        # expr_data.get("domain") returns None when JSON has "domain": null
        expr_domain = expr_data.get("domain") or domain
        intervals = expr_domain.get("intervals", [])
        exclude = expr_domain.get("exclude_points", [])
        xs = _build_x_grid(intervals, exclude, x_range)

        # Evaluate
        with np.errstate(all="ignore"):
            try:
                f = _lambdify_cached(expr_sympy)
                ys = f(xs)
            except Exception:
                continue

            # Handle scalar result (e.g., constant function simplified by sympy)
            if np.ndim(ys) == 0:
                ys = np.full_like(xs, ys, dtype=float)

            # Replace non-finite values with NaN silently
            ys = np.where(np.isfinite(ys), ys, np.nan)

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
                seg_x,
                seg_y,
                color=color,
                linewidth=2.0,
                linestyle=dash,
                label=label if (j == 0 and label) else None,
            )

        if label:
            legend_handles.append(
                plt.Line2D([0], [0], color=color, linewidth=2, linestyle=dash)
            )
            legend_labels.append(label)

    # Shading region legend entries (patch proxies)
    for region in shading:
        region_label = _sanitize_label(region.get("label", ""))
        if region_label:
            from matplotlib.patches import Patch

            legend_handles.append(
                Patch(
                    facecolor=region.get("color", "#2563eb"),
                    alpha=region.get("alpha", 0.25),
                )
            )
            legend_labels.append(region_label)

    # Annotations (drawn on top of curves)
    for ann in annotations:
        ann_type = ann.get("type", "point")

        if ann_type == "label":
            x, y = ann.get("x"), ann.get("y")
            label = _sanitize_label(ann.get("label", ""))
            if not label or x is None or y is None:
                continue
            fontsize = ann.get("fontsize", theme["font"]["size"]["annotation"])
            color = ann.get("color", theme["axis"]["color"])
            ha = ann.get("ha", "center")
            va = ann.get("va", "center")
            offset = ann.get("offset")
            if offset:
                ax.annotate(
                    label,
                    xy=(x, y),
                    xytext=offset,
                    textcoords="offset points",
                    fontsize=fontsize,
                    color=color,
                    ha=ha,
                    va=va,
                    clip_on=False,
                )
            else:
                ax.text(
                    x,
                    y,
                    label,
                    fontsize=fontsize,
                    color=color,
                    ha=ha,
                    va=va,
                    clip_on=False,
                )
            continue

        if ann_type == "arrow":
            x_start, y_start = ann.get("x_start"), ann.get("y_start")
            x_end, y_end = ann.get("x_end"), ann.get("y_end")
            if x_start is None or y_start is None or x_end is None or y_end is None:
                continue
            ann_label = _sanitize_label(ann.get("label", ""))
            color = ann.get("color", theme["annotation_color"])

            # Unified annotate with arrowprops (stable on zoom, supports
            # data-relative labels, backward-compatible with existing specs)
            ax.annotate(
                ann_label,
                xy=(x_end, y_end),
                xytext=(x_start, y_start),
                arrowprops={
                    "arrowstyle": "->",
                    "color": color,
                    "linewidth": ann.get("line_width", 1.5),
                },
                fontsize=theme["font"]["size"]["annotation"],
                color=color,
                fontweight="bold",
            )
            continue

        x, y = ann.get("x"), ann.get("y")
        if x is None or y is None:
            continue
        ann_label = _sanitize_label(ann.get("label", ""))
        color = ann.get("color", theme["annotation_color"])
        point_style = ann.get("point_style", "filled")

        if point_style == "hollow":
            ax.plot(
                x,
                y,
                "o",
                color=color,
                markersize=6,
                fillstyle="none",
                markeredgewidth=1.5,
                markeredgecolor=color,
            )
        else:
            ax.plot(x, y, "o", color=color, markersize=6)

        if ann_label:
            ax.annotate(
                ann_label,
                (x, y),
                xytext=(8, 8),
                textcoords="offset points",
                fontsize=theme["font"]["size"]["annotation"],
                color=color,
            )

    # Legend
    show_legend = panel.get("show_legend", True)
    if legend_labels and show_legend:
        ax.legend(
            legend_handles,
            legend_labels,
            loc="upper right",
            fontsize=theme["font"]["size"]["legend"],
            framealpha=0.9,
            edgecolor=theme["axis"]["color"],
        )

    # Set axis limits and aspect
    if axis_mode == "equal":
        ax.set_xlim(x_range[0], x_range[1])
        ax.set_ylim(y_range[0], y_range[1])
        ax.set_aspect("equal")
    elif axis_mode == "manual":
        ax.set_xlim(x_range[0], x_range[1])
        ax.set_ylim(y_range[0], y_range[1])
    else:
        x0, x1, y0, y1 = _auto_range(collected_xs, collected_ys, annotations, axis_mode)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)

    # Cross-axis arrows
    if axis_style == "cross":
        _add_cross_axis_arrows(ax)

    metadata = {
        "curve_count": curve_count,
        "total_points": total_points,
        "valid_points": valid_points,
    }
    return metadata


def _add_cross_axis_arrows(ax):
    """Draw arrows, axis-end labels (x/y), and origin O for cross-axis style."""
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    x_range = x_max - x_min
    y_range = y_max - y_min

    arrow_len_x = x_range * 0.06
    arrow_len_y = y_range * 0.04
    arrow_style = dict(
        arrowstyle="->", linewidth=1.4, color="black", shrinkA=0, shrinkB=0
    )
    # x-axis positive
    ax.annotate(
        "",
        xy=(x_max, 0),
        xytext=(x_max - arrow_len_x, 0),
        arrowprops=arrow_style,
        annotation_clip=False,
        zorder=10,
    )
    # x-axis negative
    ax.annotate(
        "",
        xy=(x_min, 0),
        xytext=(x_min + arrow_len_x, 0),
        arrowprops=arrow_style,
        annotation_clip=False,
        zorder=10,
    )
    # y-axis positive
    ax.annotate(
        "",
        xy=(0, y_max),
        xytext=(0, y_max - arrow_len_y),
        arrowprops=arrow_style,
        annotation_clip=False,
        zorder=10,
    )

    # Axis labels at ends
    ax.text(
        x_max + x_range * 0.02,
        -x_range * 0.005,
        "x",
        fontsize=14,
        ha="left",
        va="top",
        clip_on=False,
    )
    ax.text(
        0,
        y_max + y_range * 0.01,
        "y",
        fontsize=14,
        ha="left",
        va="bottom",
        clip_on=False,
    )

    # O at origin
    ax.annotate(
        "O",
        xy=(0, 0),
        xytext=(-10, -12),
        textcoords="offset points",
        fontsize=13,
        color="black",
        ha="right",
        va="top",
    )

    # Clear tick label at origin to avoid overlap with O (use Text.set_text to avoid warning)
    eps = 1e-9
    for get_ticks, get_labels in [
        (ax.get_xticks, ax.get_xticklabels),
        (ax.get_yticks, ax.get_yticklabels),
    ]:
        tick_values = list(get_ticks())
        text_objects = get_labels()
        for i, (t, text_obj) in enumerate(zip(tick_values, text_objects)):
            if abs(t) < eps:
                try:
                    text_obj.set_text("")
                except Exception:
                    pass


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
    spec.get("layout", {"rows": 1, "columns": 1})
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
    title = (
        spec.get("title") or spec.get("panels", [{}])[0].get("title", "")
        if panels
        else ""
    )
    if title:
        fig.suptitle(
            _sanitize_label(title), fontsize=theme["font"]["size"]["title"], y=0.98
        )

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
        rows,
        cols,
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
        fig.suptitle(
            _sanitize_label(title), fontsize=theme["font"]["size"]["title"], y=1.01
        )

    return fig, all_meta, axes


def _render_discontinuity_comparison(spec: dict) -> tuple[plt.Figure, list, list]:
    """2×2 preset with 4 discontinuity types."""
    spec.setdefault("layout", {"rows": 2, "columns": 2})

    # Default expressions if panels empty
    if not spec.get("panels"):
        spec["panels"] = [
            {
                "title": "可去间断点",
                "expressions": [
                    {"expression": "(x**2 - 1)/(x - 1)", "label": "f(x)=(x²-1)/(x-1)"}
                ],
                "x_range": [-3, 3],
                "y_range": [-1, 5],
                "annotations": [
                    {"x": 1, "y": 2, "label": "可去", "point_style": "hollow"}
                ],
                "axis_mode": "manual",
                "horizontal_lines": [{"value": 2, "style": "dashed"}],
            },
            {
                "title": "跳跃间断点",
                "expressions": [{"expression": "floor(x)", "label": "f(x)=⌊x⌋"}],
                "x_range": [-3, 3],
                "y_range": [-3, 3],
                "axis_mode": "manual",
            },
            {
                "title": "无穷间断点",
                "expressions": [{"expression": "1/x", "label": "f(x)=1/x"}],
                "x_range": [-3, 3],
                "y_range": [-10, 10],
                "axis_mode": "manual",
                "vertical_lines": [{"value": 0, "label": "x=0"}],
            },
            {
                "title": "振荡间断点",
                "expressions": [
                    {"expression": "sin(1/x)", "label": "f(x)=sin(1/x)"},
                ],
                "x_range": [-1, 1],
                "y_range": [-1.5, 1.5],
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
                "title": "y=e^x 与 y=x+1",
                "expressions": [
                    {"expression": "exp(x)", "label": "y=e^x"},
                    {"expression": "x+1", "label": "y=x+1"},
                ],
                "x_range": [-3, 3],
                "y_range": [-1, 8],
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
                "x_range": [0, 5],
                "y_range": [-3, 4],
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
                "x_range": [0, 5],
                "y_range": [-1, 5],
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
        buf,
        format="png",
        dpi=GRAPH_THEME["dpi"],
        bbox_inches="tight",
        pad_inches=0.2,
        facecolor="white",
        edgecolor="none",
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


# ── Subprocess pool (lazy, thread-safe) ──

_process_pool: concurrent.futures.ProcessPoolExecutor | None = None
_process_pool_lock = threading.Lock()
_pool_stopping = False
_pool_generation = 0
RENDER_TIMEOUT = 30


def get_formula_render_pool() -> concurrent.futures.ProcessPoolExecutor:
    """Get or create the formula render process pool (lazy, thread-safe)."""
    global _process_pool, _pool_generation
    if _process_pool is not None:
        return _process_pool
    with _process_pool_lock:
        if _process_pool is not None:
            return _process_pool
        if _pool_stopping:
            raise RuntimeError("Formula render pool is shutting down")
        _process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=2)
        _pool_generation += 1
        logger.info(
            "Formula render pool created (generation=%d, pid=%d)",
            _pool_generation,
            os.getpid(),
        )
        return _process_pool


def shutdown_formula_render_pool(
    *,
    wait: bool = True,
    cancel_futures: bool = True,
) -> None:
    """Shut down the formula render process pool (idempotent).

    Once shut down, new submissions will raise ``RuntimeError`` until
    :func:`reset_formula_render_pool` is called (if ever).

    Args:
        wait: If True, wait for running tasks to finish.
            If False, return immediately (non-blocking).
        cancel_futures: If True, cancel pending futures.
    """
    global _process_pool, _pool_stopping
    with _process_pool_lock:
        if _process_pool is None:
            return
        _pool_stopping = True
        pool = _process_pool
        _process_pool = None
    try:
        pool.shutdown(wait=wait, cancel_futures=cancel_futures)
        logger.info(
            "Formula render pool shut down (wait=%s, cancel_futures=%s)",
            wait,
            cancel_futures,
        )
    except Exception as exc:
        logger.warning("Formula render pool shutdown error: %s", exc)


# Last-ditch fallback: if the process exits without going through
# lifespan shutdown (e.g. sys.exit() during a request), at least
# shut down non-blockingly so child processes aren't orphaned.
# Idempotent — safe because shutdown() early-returns on None.
atexit.register(shutdown_formula_render_pool, wait=False, cancel_futures=True)


def reset_formula_render_pool() -> None:
    """Reset the pool stopping flag so a new pool can be created.

    Call after shutdown if the application continues running (e.g.,
    after a timeout-triggered pool replacement).
    """
    global _pool_stopping
    _pool_stopping = False


async def render_spec(spec: dict, timeout: int = RENDER_TIMEOUT) -> tuple[bytes, dict]:
    """Render a graph_spec to PNG bytes in an isolated subprocess.

    Returns ``(png_bytes, metadata_dict)``.

    Raises ``ValueError`` for spec/expression errors, ``TimeoutError``
    for rendering that exceeds the timeout, and ``RuntimeError``
    if the pool is shut down.
    """
    pool = get_formula_render_pool()
    gen = _pool_generation
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(pool, _render_spec_sync, spec)

    try:
        png, metadata = await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        # Pool generation hasn't changed — this pool is still healthy.
        # Only escalate to forced shutdown if we see repeated timeouts
        # by checking whether the pool was already replaced.
        if _process_pool is pool:
            logger.warning(
                "Graph rendering timed out after %ds (generation=%d), recycling pool",
                timeout,
                gen,
            )
            shutdown_formula_render_pool(wait=False, cancel_futures=False)
            reset_formula_render_pool()
        raise TimeoutError(f"Graph rendering timed out after {timeout}s")

    return png, metadata


async def render_and_check(
    spec: dict, timeout: int = RENDER_TIMEOUT
) -> tuple[bytes, dict, dict]:
    """Render and run quality check. Returns ``(png, metadata, quality)``."""
    png, metadata = await render_spec(spec, timeout)
    quality = check_quality(png, spec, metadata)
    return png, metadata, quality
