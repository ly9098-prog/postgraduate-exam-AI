"""Controlled formula graph renderer — whitelist-based matplotlib rendering.

No eval/exec. Only known template types are supported.
"""

import io
import logging
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ──

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 900
DPI = 100

# Style
AXIS_COLOR = "#333333"
GRID_COLOR = "#e0e0e0"
CURVE_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2"]
EMPTY_COLOR = "#94a3b8"  # for placeholder shapes


def _setup_plot(viewport: dict, width: int, height: int):
    """Set up a matplotlib figure with grid, axes, and styling."""
    fig, ax = plt.subplots(figsize=(width / DPI, height / DPI), dpi=DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    x_min, x_max = viewport.get("x_min", -6), viewport.get("x_max", 6)
    y_min, y_max = viewport.get("y_min", -6), viewport.get("y_max", 6)

    # Add small padding so curves don't touch edges
    x_pad = max(0.5, (x_max - x_min) * 0.03)
    y_pad = max(0.5, (y_max - y_min) * 0.03)
    ax.set_xlim(x_min - x_pad, x_max + x_pad)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    # Grid
    ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)

    # Axes at origin if 0 is in range
    if x_min <= 0 <= x_max:
        ax.spines["left"].set_position(("data", 0))
    else:
        ax.spines["left"].set_position(("outward", 10))
    if y_min <= 0 <= y_max:
        ax.spines["bottom"].set_position(("data", 0))
    else:
        ax.spines["bottom"].set_position(("outward", 10))

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["bottom", "left"]:
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    # Tick params
    ax.tick_params(colors=AXIS_COLOR, labelsize=10)

    # Labels
    ax.set_xlabel("x", fontsize=12, color=AXIS_COLOR)
    ax.set_ylabel("y", fontsize=12, color=AXIS_COLOR)

    return fig, ax


def _save_figure(fig) -> bytes:
    """Render figure to PNG bytes with consistent canvas size."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight", pad_inches=0.0,
                facecolor="white", edgecolor="none")
    plt.close(fig)
    return buf.getvalue()


def _resize_to_canvas(png_bytes: bytes, width: int, height: int) -> bytes:
    """Resize a PNG to exactly width×height using Pillow (letterbox with white)."""
    from PIL import Image
    buf = io.BytesIO(png_bytes)
    img = Image.open(buf).convert("RGBA")

    if img.size == (width, height):
        return png_bytes

    # Create white canvas
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))

    # Resize maintaining aspect ratio
    img.thumbnail((width, height), Image.LANCZOS)

    # Paste centered
    x = (width - img.width) // 2
    y = (height - img.height) // 2
    canvas.paste(img, (x, y), img)

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _draw_asymptote(ax, x: float | None, y: float | None, x_range: tuple[float, float], y_range: tuple[float, float]):
    """Draw a dashed asymptote line."""
    if x is not None:
        ax.axvline(x=x, color="#94a3b8", linewidth=1.0, linestyle="--", alpha=0.7)
    if y is not None:
        ax.axhline(y=y, color="#94a3b8", linewidth=1.0, linestyle="--", alpha=0.7)


def _draw_legend(ax, labels: list[str], colors: list[str]):
    """Draw legend if there are labels."""
    valid = [(l, c) for l, c in zip(labels, colors) if l]
    if not valid:
        return
    handles = [plt.Line2D([0], [0], color=c, linewidth=2, label=l) for l, c in valid]
    ax.legend(handles=handles, loc="upper right", fontsize=10, framealpha=0.9)


def _sample_function(func, x_start: float, x_end: float, num_points: int = 2000) -> tuple[np.ndarray, np.ndarray]:
    """Sample a function over [x_start, x_end] with dense points."""
    xs = np.linspace(x_start, x_end, num_points)
    try:
        ys = func(xs)
    except Exception:
        return np.array([]), np.array([])
    return xs, ys


def _sample_piecewise(segments: list[tuple[float, float, callable]], num_points: int = 500) -> list[tuple[np.ndarray, np.ndarray]]:
    """Sample a piecewise function.

    Each segment: (x_start, x_end, func).
    """
    results = []
    for x_start, x_end, func in segments:
        xs = np.linspace(x_start, x_end, num_points)
        try:
            ys = func(xs)
        except Exception:
            continue
        # Filter out NaN/Inf
        mask = np.isfinite(ys)
        if np.any(mask):
            results.append((xs[mask], ys[mask]))
    return results


def _filter_finite(xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Remove NaN/Inf values."""
    mask = np.isfinite(ys)
    return xs[mask], ys[mask]


def _discontinuity_gap(xs: np.ndarray, ys: np.ndarray, threshold: float = 5.0) -> list[tuple[np.ndarray, np.ndarray]]:
    """Split data at large discontinuities (e.g., asymptotes)."""
    if len(xs) < 2:
        return [(xs, ys)]
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


# ═══════════════════════════════════════════════════════════════
# Template renderers
# ═══════════════════════════════════════════════════════════════


def render_linear(ax, params: dict, color: str, label: str):
    """y = kx + b"""
    k = params.get("k", 1.0)
    b = params.get("b", 0.0)
    x_min, x_max = ax.get_xlim()
    xs = np.linspace(x_min, x_max, 200)
    ys = k * xs + b
    ax.plot(xs, ys, color=color, linewidth=2, label=label or None)


def render_quadratic(ax, params: dict, color: str, label: str):
    """y = a(x - h)^2 + k"""
    a = params.get("a", 1.0)
    h = params.get("h", 0.0)
    k = params.get("k", 0.0)
    x_min, x_max = ax.get_xlim()
    xs = np.linspace(x_min, x_max, 400)
    ys = a * (xs - h) ** 2 + k
    ax.plot(xs, ys, color=color, linewidth=2, label=label or None)

    # Vertex
    vertex_x, vertex_y = h, k
    if x_min <= vertex_x <= x_max:
        ax.plot(vertex_x, vertex_y, "o", color=color, markersize=4)
        ax.annotate(f"({vertex_x:.0f},{vertex_y:.0f})", (vertex_x, vertex_y),
                    xytext=(5, 10), textcoords="offset points", fontsize=9, color=color)

    # Axis of symmetry
    ax.axvline(x=vertex_x, color=color, linewidth=0.8, linestyle=":", alpha=0.5)


def render_abs(ax, params: dict, color: str, label: str):
    """y = a|x - h| + k"""
    a = params.get("a", 1.0)
    h = params.get("h", 0.0)
    k = params.get("k", 0.0)
    x_min, x_max = ax.get_xlim()
    xs = np.linspace(x_min, x_max, 400)
    ys = a * np.abs(xs - h) + k
    ax.plot(xs, ys, color=color, linewidth=2, label=label or None)

    # Cusp point
    if x_min <= h <= x_max:
        ax.plot(h, k, "o", color=color, markersize=4)


def render_reciprocal(ax, params: dict, color: str, label: str):
    """y = a / (x - h) + k"""
    a = params.get("a", 1.0)
    h = params.get("h", 0.0)
    k = params.get("k", 0.0)

    # Asymptotes
    ax.axvline(x=h, color="#94a3b8", linewidth=1.0, linestyle="--", alpha=0.7)
    ax.axhline(y=k, color="#94a3b8", linewidth=1.0, linestyle="--", alpha=0.7)

    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    # Left branch (x < h)
    left_end = min(x_max, h - 1e-6)
    x_left = np.linspace(max(x_min, h - 10), left_end, 1000)
    y_left = a / (x_left - h) + k
    mask = np.isfinite(y_left) & (np.abs(y_left) < max(abs(y_min), abs(y_max)) * 2)
    if np.any(mask):
        for seg in _discontinuity_gap(x_left[mask], y_left[mask]):
            ax.plot(*seg, color=color, linewidth=2, label=label or None if seg is not None else None)

    # Right branch (x > h)
    right_start = max(x_min, h + 1e-6)
    x_right = np.linspace(right_start, min(x_max, h + 10), 1000)
    y_right = a / (x_right - h) + k
    mask = np.isfinite(y_right) & (np.abs(y_right) < max(abs(y_min), abs(y_max)) * 2)
    if np.any(mask):
        for seg in _discontinuity_gap(x_right[mask], y_right[mask]):
            ax.plot(*seg, color=color, linewidth=2)


def render_reciprocal_sq(ax, params: dict, color: str, label: str):
    """y = a / (x - h)^2 + k"""
    a = params.get("a", 1.0)
    h = params.get("h", 0.0)
    k = params.get("k", 0.0)

    ax.axvline(x=h, color="#94a3b8", linewidth=1.0, linestyle="--", alpha=0.7)
    ax.axhline(y=k, color="#94a3b8", linewidth=1.0, linestyle="--", alpha=0.7)

    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    for side_start, side_end in [
        (max(x_min, h - 10), h - 1e-6),
        (h + 1e-6, min(x_max, h + 10)),
    ]:
        xs = np.linspace(side_start, side_end, 1000)
        ys = a / (xs - h) ** 2 + k
        mask = np.isfinite(ys) & (np.abs(ys) < max(abs(y_min), abs(y_max)) * 2)
        if np.any(mask):
            for seg in _discontinuity_gap(xs[mask], ys[mask]):
                ax.plot(*seg, color=color, linewidth=2, label=label or None if seg is not None else None)


def render_exp(ax, params: dict, color: str, label: str):
    """y = a * b^x + k"""
    a = params.get("a", 1.0)
    b = params.get("b", 2.0)
    k = params.get("k", 0.0)
    x_min, x_max = ax.get_xlim()
    xs = np.linspace(x_min, x_max, 500)
    ys = a * b ** xs + k
    xs, ys = _filter_finite(xs, ys)
    ax.plot(xs, ys, color=color, linewidth=2, label=label or None)


def render_log(ax, params: dict, color: str, label: str):
    """y = a * log_b(x) + k"""
    a = params.get("a", 1.0)
    b = params.get("b", math.e)
    k = params.get("k", 0.0)
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    # Vertical asymptote at x=0
    ax.axvline(x=0, color="#94a3b8", linewidth=1.0, linestyle="--", alpha=0.7)

    # Only sample x > 0
    xs = np.linspace(max(x_min, 0.001), x_max, 500)
    ys = a * np.log(xs) / np.log(b) + k
    xs, ys = _filter_finite(xs, ys)
    mask = np.abs(ys) < max(abs(y_min), abs(y_max)) * 2
    if np.any(mask):
        for seg in _discontinuity_gap(xs[mask], ys[mask]):
            ax.plot(*seg, color=color, linewidth=2, label=label or None if seg is not None else None)


def render_sine(ax, params: dict, color: str, label: str):
    """y = a*sin(bx + c) + d"""
    a = params.get("a", 1.0)
    freq = params.get("freq", 1.0)
    phase = params.get("phase", 0.0)
    d = params.get("d", 0.0)
    x_min, x_max = ax.get_xlim()
    xs = np.linspace(x_min, x_max, 2000)
    ys = a * np.sin(freq * xs + phase) + d
    ax.plot(xs, ys, color=color, linewidth=2, label=label or None)


def render_tangent(ax, params: dict, color: str, label: str):
    """y = a*tan(bx + c) + d — with asymptotes at bx+c = π/2 + nπ"""
    a = params.get("a", 1.0)
    freq = params.get("freq", 1.0)
    c = params.get("c", 0.0)
    d = params.get("d", 0.0)
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    # Find asymptotes in range: freq*x + c = π/2 + nπ → x = (π/2 + nπ - c)/freq
    n_start = math.ceil((freq * x_min + c - math.pi / 2) / math.pi)
    n_end = math.floor((freq * x_max + c - math.pi / 2) / math.pi)
    asymptotes = [(math.pi / 2 + n * math.pi - c) / freq for n in range(n_start, n_end + 1)]
    asymptotes = [x for x in asymptotes if x_min <= x <= x_max]

    for a_pos in asymptotes:
        ax.axvline(x=a_pos, color="#94a3b8", linewidth=1.0, linestyle="--", alpha=0.7)

    # Draw segments between asymptotes
    bounds = [x_min] + asymptotes + [x_max]
    epsilon = 1e-4  # small offset from asymptote
    for i in range(len(bounds) - 1):
        lo = bounds[i] + (epsilon if i > 0 else 0)
        hi = bounds[i + 1] - (epsilon if i < len(bounds) - 1 else 0)
        if hi - lo < epsilon * 2:
            continue
        xs = np.linspace(lo, hi, 500)
        ys = a * np.tan(freq * xs + c) + d
        mask = np.isfinite(ys) & (np.abs(ys) < max(abs(y_min), abs(y_max)) * 1.5)
        if np.any(mask):
            for seg in _discontinuity_gap(xs[mask], ys[mask], 10):
                ax.plot(*seg, color=color, linewidth=2, label=label or None if seg is not None else None)


def render_sample_quadratic(ax, params: dict, color: str, label: str):
    """Standard quadratic f(x) = x^2 + x - 1"""
    x_min, x_max = ax.get_xlim()
    xs = np.linspace(x_min, x_max, 400)
    ys = xs ** 2 + xs - 1
    ax.plot(xs, ys, color=color, linewidth=2, label=label or None)


def render_sample_quadratic_abs(ax, params: dict, color: str, label: str):
    """|f(x)| for f(x) = x^2 + x - 1"""
    x_min, x_max = ax.get_xlim()
    xs = np.linspace(x_min, x_max, 400)
    ys = np.abs(xs ** 2 + xs - 1)
    ax.plot(xs, ys, color=color, linewidth=2, label=label or None)


def render_sample_quadratic_absx(ax, params: dict, color: str, label: str):
    """f(|x|) for f(x) = x^2 + x - 1"""
    x_min, x_max = ax.get_xlim()
    xs = np.linspace(x_min, x_max, 400)
    ys = np.abs(xs) ** 2 + np.abs(xs) - 1
    ax.plot(xs, ys, color=color, linewidth=2, label=label or None)


def render_piecewise_sign(ax, params: dict, color: str, label: str):
    """sgn(x): returns -1 for x<0, 0 for x=0, 1 for x>0"""
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    # Left branch: y=-1, x<0
    x_left = np.linspace(max(x_min, -10), -0.01, 200)
    ax.plot(x_left, np.full_like(x_left, -1), color=color, linewidth=2, label=label or None)
    ax.plot(-0.01, -1, "o", color=color, markersize=5, fillstyle="full")  # closed at 0-

    # Jump at 0
    ax.plot(0, -1, "o", color=color, markersize=5, fillstyle="full")  # solid at -1
    ax.plot(0, 1, "o", color=color, markersize=5, fillstyle="full")   # solid at +1

    # Right branch: y=1, x>0
    x_right = np.linspace(0.01, min(x_max, 10), 200)
    ax.plot(x_right, np.full_like(x_right, 1), color=color, linewidth=2)

    # sgn(0) = 0
    ax.plot(0, 0, "o", color=color, markersize=5, fillstyle="full")

    # Label
    ax.text(0.3, 1.1, "sgn x", fontsize=10, color=color)


def render_piecewise_floor(ax, params: dict, color: str, label: str):
    """floor(x): greatest integer ≤ x"""
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    x_start = math.floor(x_min)
    x_end = math.ceil(x_max)

    for n in range(x_start, x_end + 1):
        left = max(x_min, n)
        right = min(x_max, n + 1)
        if right > left:
            xs = np.array([left, right - 0.001])
            ys = np.full_like(xs, n)
            ax.plot(xs, ys, color=color, linewidth=2)

        # Closed point at left end of each step
        if x_min <= n <= x_max:
            ax.plot(n, n, "o", color=color, markersize=4, fillstyle="full")

        # Open point at right end
        if x_min <= n + 1 <= x_max:
            ax.plot(n + 1, n, "o", color=color, markersize=4, fillstyle="none",
                    markeredgewidth=1.5, markeredgecolor=color)


# ── Template registry ──

TEMPLATE_RENDERERS = {
    "linear": render_linear,
    "quadratic": render_quadratic,
    "abs": render_abs,
    "reciprocal": render_reciprocal,
    "reciprocal_sq": render_reciprocal_sq,
    "exp": render_exp,
    "log": render_log,
    "sine": render_sine,
    "tangent": render_tangent,
    "sample_quadratic": render_sample_quadratic,
    "sample_quadratic_abs": render_sample_quadratic_abs,
    "sample_quadratic_absx": render_sample_quadratic_absx,
    "piecewise_sign": render_piecewise_sign,
    "piecewise_floor": render_piecewise_floor,
}


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════


def render_formula_graph(
    curves: list[dict],
    viewport: dict,
    display_options: dict | None = None,
    annotations: list[dict] | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> bytes:
    """Render a formula graph from controlled template descriptions.

    Args:
        curves: List of curve dicts, each with:
            - template_type: str (must be in TEMPLATE_RENDERERS)
            - parameters: dict
            - label: str (optional legend label)
        viewport: dict with x_min, x_max, y_min, y_max
        display_options: optional dict with display hints
        annotations: optional list of annotation dicts
        width: output image width in pixels
        height: output image height in pixels

    Returns:
        PNG image bytes.

    Raises:
        ValueError: if any curve has an unknown template_type or invalid params.
    """
    fig, ax = _setup_plot(viewport, width, height)

    _y_min, _y_max = viewport.get("y_min", -6), viewport.get("y_max", 6)

    # Draw asymptotes from annotations first
    if annotations:
        for ann in annotations:
            if ann.get("type") == "asymptote":
                x = ann.get("x")
                y = ann.get("y")
                if x is not None or y is not None:
                    _draw_asymptote(ax, x, y, ax.get_xlim(), ax.get_ylim())

    # Draw curves
    labels = []
    colors_used = []
    for i, curve in enumerate(curves):
        template_type = curve.get("template_type", "")
        parameters = curve.get("parameters", {})
        label = curve.get("label", "")

        renderer = TEMPLATE_RENDERERS.get(template_type)
        if renderer is None:
            raise ValueError(
                f"Unknown template type '{template_type}'. "
                f"Supported: {', '.join(TEMPLATE_RENDERERS.keys())}"
            )

        color = CURVE_COLORS[i % len(CURVE_COLORS)]
        renderer(ax, parameters, color, label)

        labels.append(label)
        colors_used.append(color)

    # Draw annotations (non-asymptote)
    if annotations:
        for ann in annotations:
            ann_type = ann.get("type")
            if ann_type == "point":
                x, y_coord = ann.get("x"), ann.get("y")
                ann_label = ann.get("label", "")
                if x is not None and y_coord is not None:
                    ax.plot(x, y_coord, "o", color="#dc2626", markersize=5)
                    if ann_label:
                        ax.annotate(ann_label, (x, y_coord),
                                    xytext=(8, 8), textcoords="offset points",
                                    fontsize=10, color="#dc2626")

    # Legend
    _draw_legend(ax, labels, colors_used)

    png = _save_figure(fig)
    return _resize_to_canvas(png, width, height)
