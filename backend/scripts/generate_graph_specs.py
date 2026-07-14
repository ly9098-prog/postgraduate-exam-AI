#!/usr/bin/env python3
"""
Phase 2: Generate draft_graph_spec for all function_graph cards.

1. Dry-run first (--dry-run)
2. Then apply (--apply)

Usage:
    python scripts/generate_graph_specs.py --dry-run
    python scripts/generate_graph_specs.py --apply
"""
import asyncio
import json
import sys
from datetime import datetime

sys.path.insert(0, '.')

from app.models.formula import FormulaCard, FormulaGraphAsset
from app.core.config import settings
from sqlalchemy import select
from app.core.database import async_session

logger = None  # will init after import


# ═══════════════════════════════════════════════════════════════
# GraphSpec definitions per card
# ═══════════════════════════════════════════════════════════════

def build_graph_spec(card) -> dict | None:
    """Build a GraphSpec dict based on formula content. Returns None if unsupported."""
    cid = card.id
    title = (card.title or "").strip()
    blocks = card.formula_blocks or []

    specs = {
        # ── simple_auto ──
        58: _spec_constant(),
        70: _spec_cos(),
        73: _spec_cot(),
        76: _spec_arcsin(),
        77: _spec_arccos(),
        78: _spec_arctan(),
        79: _spec_arccot(),
        80: _spec_x_plus_1_over_x(),
        82: _spec_lnx_over_x(),
        91: _spec_x_pow_x(),

        # ── comparison_auto ──
        68: _spec_exp_vs_ln(),
        71: _spec_sin_vs_cos(),
        74: _spec_tan_vs_cot(),
        75: _spec_sec_vs_csc(),
        81: _spec_xn_exp_x(),
        87: _spec_rational_function(),
        88: _spec_growth_comparison(),

        # ── multi_panel_auto ──
        63: _spec_power_positive_negative(),
        64: _spec_power_rational(),
        65: _spec_power_alpha(),
        83: _spec_translation(),
        84: _spec_composite_transform(),
        86: _spec_primitive_derivative(),
        90: _spec_discontinuity(),
        92: _spec_inequality_auxiliary(),
    }

    return specs.get(cid)


# ── simple_auto specs ──

def _base_single(title: str, expr: str, label: str | None = None,
                 x_range=None, y_range=None, domain_intervals=None,
                 annotations=None, vlines=None, hlines=None) -> dict:
    if x_range is None:
        x_range = [-6, 6]
    if y_range is None:
        y_range = [-6, 6]
    spec = {
        "schema_version": 1,
        "template": "single_function",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": title,
        "x_label": "x",
        "y_label": "y",
        "legend": True,
        "grid": True,
        "panels": [
            {
                "title": title,
                "expressions": [
                    {"expression": expr, "display_latex": label or expr, "label": label or expr}
                ],
                "x_range": x_range,
                "y_range": y_range,
                "axis_mode": "manual",
                "x_label": "x",
                "y_label": "y",
                "grid": True,
            }
        ],
    }
    if domain_intervals:
        spec["panels"][0]["domain"] = {"intervals": domain_intervals}
    if annotations:
        spec["panels"][0]["annotations"] = annotations
    if vlines:
        spec["panels"][0]["vertical_lines"] = vlines
    if hlines:
        spec["panels"][0]["horizontal_lines"] = hlines
    return spec


def _spec_constant():
    return _base_single(
        "常数函数 y=C（示例 C=2）",
        "0*x + 2", "y=2",
        x_range=[-5, 5], y_range=[-1, 5],
        annotations=[{"x": 0, "y": 2, "label": "(0,2)"}],
    )


def _spec_cos():
    pi = 3.14159
    return _base_single(
        "y=cos x",
        "cos(x)", "y=cos x",
        x_range=[-2 * pi, 2 * pi], y_range=[-1.5, 1.5],
        annotations=[
            {"x": 0, "y": 1, "label": "cos0=1"},
            {"x": pi, "y": -1, "label": "cosπ=-1"},
        ],
    )


def _spec_cot():
    pi = 3.14159
    return _base_single(
        "y=cot x",
        "cos(x)/sin(x)", "y=cot x",
        x_range=[-2 * pi, 2 * pi], y_range=[-5, 5],
        annotations=[{"x": pi / 2, "y": 0, "label": "cot(π/2)=0"}],
    )


def _spec_arcsin():
    pi = 3.14159
    return _base_single(
        "y=arcsin x",
        "asin(x)", "y=arcsin x",
        x_range=[-1.5, 1.5], y_range=[-pi / 2 - 0.5, pi / 2 + 0.5],
        annotations=[
            {"x": 1, "y": pi / 2, "label": "(1,π/2)"},
            {"x": -1, "y": -pi / 2, "label": "(-1,-π/2)"},
            {"x": 0, "y": 0, "label": "(0,0)"},
        ],
    )


def _spec_arccos():
    pi = 3.14159
    return _base_single(
        "y=arccos x",
        "acos(x)", "y=arccos x",
        x_range=[-1.5, 1.5], y_range=[-0.5, pi + 0.5],
        annotations=[
            {"x": 1, "y": 0, "label": "(1,0)"},
            {"x": -1, "y": pi, "label": "(-1,π)"},
            {"x": 0, "y": pi / 2, "label": "(0,π/2)"},
        ],
    )


def _spec_arctan():
    pi = 3.14159
    return _base_single(
        "y=arctan x",
        "atan(x)", "y=arctan x",
        x_range=[-5, 5], y_range=[-pi / 2 - 0.5, pi / 2 + 0.5],
        annotations=[
            {"x": 0, "y": 0, "label": "(0,0)"},
        ],
        hlines=[
            {"value": pi / 2, "label": "y=π/2"},
            {"value": -pi / 2, "label": "y=-π/2"},
        ],
    )


def _spec_arccot():
    pi = 3.14159
    return _base_single(
        "y=arccot x",
        "pi/2 - atan(x)", "y=arccot x",
        x_range=[-5, 5], y_range=[-0.5, pi + 0.5],
        annotations=[
            {"x": 0, "y": pi / 2, "label": "(0,π/2)"},
        ],
        hlines=[
            {"value": pi, "label": "y=π"},
            {"value": 0, "label": "y=0"},
        ],
    )


def _spec_x_plus_1_over_x():
    return _base_single(
        "y=x+1/x",
        "x + 1/x", "y=x+1/x",
        x_range=[-5, 5], y_range=[-6, 6],
        domain_intervals=[[-5, -0.01], [0.01, 5]],
        annotations=[
            {"x": 1, "y": 2, "label": "(1,2)"},
            {"x": -1, "y": -2, "label": "(-1,-2)"},
        ],
        vlines=[{"value": 0, "label": "x=0"}],
    )


def _spec_lnx_over_x():
    e = 2.71828
    return _base_single(
        "y=ln x / x",
        "ln(x)/x", "y=ln x/x",
        x_range=[0, 10], y_range=[-0.5, 0.6],
        domain_intervals=[[0.01, 10]],
        annotations=[
            {"x": e, "y": 1 / e, "label": f"(e, 1/e)"},
            {"x": 1, "y": 0, "label": "(1,0)"},
        ],
    )


def _spec_x_pow_x():
    e = 2.71828
    return _base_single(
        "幂指辅助函数 y=x^x",
        "x**x", "y=x^x",
        x_range=[0.01, 2], y_range=[0, 2.5],
        domain_intervals=[[0.01, 2]],
        annotations=[
            {"x": 1 / e, "y": e ** (-1 / e), "label": f"极小值点"},
            {"x": 1, "y": 1, "label": "(1,1)"},
        ],
        vlines=[{"value": 1 / e, "label": "x=1/e"}],
    )


# ── comparison_auto specs ──

def _spec_exp_vs_ln():
    """y=e^x, y=ln x, y=x — inverse function relationship"""
    spec = {
        "schema_version": 1,
        "template": "function_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": "指数函数与对数函数反函数关系",
        "x_label": "x",
        "y_label": "y",
        "legend": True,
        "grid": True,
        "panels": [{
            "title": "y=e^x, y=ln x, y=x",
            "expressions": [
                {"expression": "exp(x)", "display_latex": "y=e^x", "label": "y=e^x"},
                {"expression": "ln(x)", "display_latex": "y=ln x", "label": "y=ln x",
                 "domain": {"intervals": [[0.01, 5]]}},
                {"expression": "x", "display_latex": "y=x", "label": "y=x",
                 "line_style": "dashed"},
            ],
            "x_range": [-2, 5],
            "y_range": [-2, 5],
            "axis_mode": "manual",
            "x_label": "x", "y_label": "y",
            "grid": True,
        }]
    }
    return spec


def _spec_sin_vs_cos():
    pi = 3.14159
    return {
        "schema_version": 1,
        "template": "function_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": "正弦与余弦对比",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [{
            "title": "y=sin x, y=cos x",
            "expressions": [
                {"expression": "sin(x)", "display_latex": "y=sin x", "label": "y=sin x"},
                {"expression": "cos(x)", "display_latex": "y=cos x", "label": "y=cos x"},
            ],
            "x_range": [-2 * pi, 2 * pi],
            "y_range": [-1.5, 1.5],
            "axis_mode": "manual",
            "x_label": "x", "y_label": "y",
            "grid": True,
        }]
    }


def _spec_tan_vs_cot():
    pi = 3.14159
    return {
        "schema_version": 1,
        "template": "function_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": "正切与余切对比",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [{
            "title": "y=tan x, y=cot x",
            "expressions": [
                {"expression": "tan(x)", "display_latex": "y=tan x", "label": "y=tan x"},
                {"expression": "cos(x)/sin(x)", "display_latex": "y=cot x", "label": "y=cot x"},
            ],
            "x_range": [-2 * pi, 2 * pi],
            "y_range": [-5, 5],
            "axis_mode": "manual",
            "x_label": "x", "y_label": "y",
            "grid": True,
        }]
    }


def _spec_sec_vs_csc():
    pi = 3.14159
    return {
        "schema_version": 1,
        "template": "function_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": "正割与余割",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [{
            "title": "y=sec x, y=csc x",
            "expressions": [
                {"expression": "1/cos(x)", "display_latex": "y=sec x", "label": "y=sec x"},
                {"expression": "1/sin(x)", "display_latex": "y=csc x", "label": "y=csc x"},
            ],
            "x_range": [-2 * pi, 2 * pi],
            "y_range": [-5, 5],
            "axis_mode": "manual",
            "x_label": "x", "y_label": "y",
            "grid": True,
        }]
    }


def _spec_xn_exp_x():
    """y=xe^{-x} 与 y=x^n e^{-x} — show n=1,2"""
    return {
        "schema_version": 1,
        "template": "function_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": "y=xⁿe⁻ˣ（n=1,2）",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [{
            "title": "y=xe⁻ˣ, y=x²e⁻ˣ",
            "expressions": [
                {"expression": "x*exp(-x)", "display_latex": "y=xe^{-x}", "label": "n=1: y=xe⁻ˣ"},
                {"expression": "x**2*exp(-x)", "display_latex": "y=x^2 e^{-x}", "label": "n=2: y=x²e⁻ˣ"},
            ],
            "x_range": [-1, 6],
            "y_range": [-1, 2],
            "axis_mode": "manual",
            "x_label": "x", "y_label": "y",
            "grid": True,
            "annotations": [
                {"x": 1, "y": 1 / 2.71828, "label": "(1,1/e)"},
            ],
        }]
    }


def _spec_rational_function():
    """y=(x+1)/(x²-1) — a common rational function with asymptotes"""
    return {
        "schema_version": 1,
        "template": "function_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": "常见有理函数 y=(x+1)/(x²-1)",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [{
            "title": "y=(x+1)/(x²-1)",
            "expressions": [
                {"expression": "(x+1)/(x**2-1)", "display_latex": "y=\\frac{x+1}{x^2-1}",
                 "label": "y=(x+1)/(x²-1)"},
            ],
            "x_range": [-4, 4],
            "y_range": [-6, 6],
            "axis_mode": "manual",
            "x_label": "x", "y_label": "y",
            "grid": True,
            "annotations": [
                {"x": -1, "y": 0, "label": "可去间断点 x=-1", "point_style": "hollow"},
            ],
            "vertical_lines": [{"value": 1, "label": "x=1 渐近线"}],
            "horizontal_lines": [{"value": 0, "label": "y=0 水平渐近线"}],
        }]
    }


def _spec_growth_comparison():
    """y=ln x, y=x^0.5, y=x, y=x^2, y=e^x — growth rates comparison"""
    return {
        "schema_version": 1,
        "template": "function_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": "对数·幂·指数增长速度对比",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [{
            "title": "增长速度对比",
            "expressions": [
                {"expression": "ln(x)", "display_latex": "y=ln x", "label": "ln x",
                 "domain": {"intervals": [[0.01, 5]]}},
                {"expression": "x**0.5", "display_latex": "y=x^{0.5}", "label": "x^0.5"},
                {"expression": "x", "display_latex": "y=x", "label": "x"},
                {"expression": "x**2", "display_latex": "y=x^2", "label": "x²"},
                {"expression": "exp(x)", "display_latex": "y=e^x", "label": "e^x"},
            ],
            "x_range": [0, 5],
            "y_range": [-1, 10],
            "axis_mode": "manual",
            "x_label": "x", "y_label": "y",
            "grid": True,
        }]
    }


# ── multi_panel_auto specs ──

def _spec_power_positive_negative():
    """y=x, x², x³ (positive) and 1/x, 1/x² (negative) — 2 panels"""
    return {
        "schema_version": 1,
        "template": "multi_panel",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 2},
        "title": "幂函数（正整数与负整数）",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [
            {
                "title": "y=xⁿ（n=1,2,3）",
                "expressions": [
                    {"expression": "x", "display_latex": "y=x", "label": "n=1"},
                    {"expression": "x**2", "display_latex": "y=x²", "label": "n=2"},
                    {"expression": "x**3", "display_latex": "y=x³", "label": "n=3"},
                ],
                "x_range": [-3, 3], "y_range": [-3, 3],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
            },
            {
                "title": "y=x⁻ⁿ（n=1,2）",
                "expressions": [
                    {"expression": "1/x", "display_latex": "y=1/x", "label": "n=1"},
                    {"expression": "1/(x**2)", "display_latex": "y=1/x²", "label": "n=2"},
                ],
                "x_range": [-3, 3], "y_range": [-5, 5],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
                "vertical_lines": [{"value": 0, "label": "x=0"}],
            },
        ]
    }


def _spec_power_rational():
    """y=x^{1/2}, x^{1/3}, x^{2/3} — root functions"""
    return {
        "schema_version": 1,
        "template": "multi_panel",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 2},
        "title": "幂函数（有理指数）",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [
            {
                "title": "y=x^{1/n}",
                "expressions": [
                    {"expression": "x**0.5", "display_latex": "y=x^{1/2}", "label": "n=2"},
                    {"expression": "x**(1/3)", "display_latex": "y=x^{1/3}", "label": "n=3"},
                ],
                "x_range": [0, 4], "y_range": [0, 2],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
                "annotations": [{"x": 1, "y": 1, "label": "(1,1)"}],
            },
            {
                "title": "y=x^{2/3}",
                "expressions": [
                    {"expression": "x**(2/3)", "display_latex": "y=x^{2/3}", "label": "y=x^{2/3}"},
                ],
                "x_range": [-3, 3], "y_range": [0, 3],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
            },
        ]
    }


def _spec_power_alpha():
    """y=x², x, x^0.5, 1/x — alpha comparison on single panel"""
    return {
        "schema_version": 1,
        "template": "function_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": "幂函数 α 值对比",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [{
            "title": "y=x^α（α=2,1,0.5,-1）",
            "expressions": [
                {"expression": "x**2", "display_latex": "y=x²", "label": "α=2"},
                {"expression": "x", "display_latex": "y=x", "label": "α=1"},
                {"expression": "x**0.5", "display_latex": "y=x^{0.5}", "label": "α=0.5",
                 "domain": {"intervals": [[0.01, 4]]}},
                {"expression": "1/x", "display_latex": "y=1/x", "label": "α=-1",
                 "domain": {"intervals": [[0.01, 4]]}},
            ],
            "x_range": [0, 4],
            "y_range": [0, 4],
            "axis_mode": "manual",
            "x_label": "x", "y_label": "y",
            "grid": True,
            "annotations": [{"x": 1, "y": 1, "label": "(1,1)"}],
        }]
    }


def _spec_translation():
    """y=f(x), y=f(x-a), y=f(x)+b — translation demonstration"""
    return {
        "schema_version": 1,
        "template": "multi_panel",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 3},
        "title": "平移变换 y=f(x-a)+b",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [
            {
                "title": "原函数 y=x²",
                "expressions": [{"expression": "x**2", "display_latex": "y=x²", "label": "y=x²"}],
                "x_range": [-3, 5], "y_range": [-1, 5],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
            },
            {
                "title": "水平平移 y=(x-2)²",
                "expressions": [{"expression": "(x-2)**2", "display_latex": "y=(x-2)²", "label": "y=(x-2)²"}],
                "x_range": [-3, 5], "y_range": [-1, 5],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
            },
            {
                "title": "竖直平移 y=x²+1",
                "expressions": [{"expression": "x**2+1", "display_latex": "y=x²+1", "label": "y=x²+1"}],
                "x_range": [-3, 5], "y_range": [-1, 5],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
            },
        ]
    }


def _spec_composite_transform():
    """y=af(bx+c)+d — demonstrate multiple transforms"""
    return {
        "schema_version": 1,
        "template": "multi_panel",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 3},
        "title": "综合变换 y=af(bx+c)+d",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [
            {
                "title": "基准 y=x²",
                "expressions": [{"expression": "x**2", "display_latex": "y=x²", "label": "基准"}],
                "x_range": [-4, 4], "y_range": [-1, 5],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
            },
            {
                "title": "伸缩 y=2x²",
                "expressions": [{"expression": "2*x**2", "display_latex": "y=2x²", "label": "a=2"}],
                "x_range": [-4, 4], "y_range": [-1, 5],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
            },
            {
                "title": "反射+平移 y=-(x+1)²+2",
                "expressions": [{"expression": "-(x+1)**2+2", "display_latex": "y=-(x+1)²+2", "label": "a=-1,h=-1,k=2"}],
                "x_range": [-4, 4], "y_range": [-3, 3],
                "axis_mode": "manual", "x_label": "x", "y_label": "y", "grid": True,
            },
        ]
    }


def _spec_primitive_derivative():
    """f(x)=x³-3x and f'(x)=3x²-3 — relationship between function and derivative"""
    return {
        "schema_version": 1,
        "template": "function_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 1},
        "title": "原函数与导函数图像关系",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [{
            "title": "f(x)=x³-3x, f'(x)=3x²-3",
            "expressions": [
                {"expression": "x**3-3*x", "display_latex": "y=x³-3x", "label": "f(x)=x³-3x"},
                {"expression": "3*x**2-3", "display_latex": "y=3x²-3", "label": "f'(x)=3x²-3"},
            ],
            "x_range": [-3, 3],
            "y_range": [-4, 4],
            "axis_mode": "manual",
            "x_label": "x", "y_label": "y",
            "grid": True,
            "annotations": [
                {"x": -1, "y": 2, "label": "f(-1)=2, f'(-1)=0"},
                {"x": 1, "y": -2, "label": "f(1)=-2, f'(1)=0"},
            ],
        }]
    }


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def classify_existing_asset(card, assets):
    """Create a basic graph_spec from existing template asset."""
    for a in assets:
        if a.template_type and a.image_url:
            return {
                "schema_version": 1,
                "template": "single_function",
                "render_mode": "explicit_2d",
                "layout": {"rows": 1, "columns": 1},
                "title": card.title or "",
                "x_label": "x", "y_label": "y",
                "legend": True, "grid": True,
                "panels": [{
                    "title": card.title or "",
                    "expressions": [{"expression": "x", "display_latex": card.title or "", "label": card.title or ""}],
                    "x_range": [-6, 6], "y_range": [-6, 6],
                    "axis_mode": "auto_robust",
                    "x_label": "x", "y_label": "y",
                    "grid": True,
                }]
            }
    return None


def _spec_discontinuity():
    """四类间断点图像对比 — customized to match formula content"""
    pi = 3.14159
    return {
        "schema_version": 1,
        "template": "discontinuity_comparison",
        "render_mode": "explicit_2d",
        "layout": {"rows": 2, "columns": 2},
        "title": "四类间断点图像对比",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [
            {
                "title": "可去间断点",
                "expressions": [
                    {"expression": "sin(x)/x", "label": "f(x)=sin x/x"},
                ],
                "x_range": [-4*pi, 4*pi], "y_range": [-0.5, 1.5],
                "axis_mode": "manual",
                "annotations": [{"x": 0, "y": 1, "label": "可去间断点", "point_style": "hollow"}],
                "horizontal_lines": [{"value": 1, "style": "dashed"}],
            },
            {
                "title": "跳跃间断点",
                "expressions": [
                    {"expression": "sign(x)", "label": "f(x)=sgn x"},
                ],
                "x_range": [-3, 3], "y_range": [-2, 2],
                "axis_mode": "manual",
            },
            {
                "title": "无穷间断点",
                "expressions": [
                    {"expression": "1/x", "label": "f(x)=1/x"},
                ],
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
    }


def _spec_inequality_auxiliary():
    """指数对数不等式常用辅助函数 — 1×3 panels matching formula content"""
    e = 2.71828
    return {
        "schema_version": 1,
        "template": "inequality_auxiliary",
        "render_mode": "explicit_2d",
        "layout": {"rows": 1, "columns": 3},
        "title": "指数对数不等式常用辅助函数",
        "x_label": "x", "y_label": "y",
        "legend": True, "grid": True,
        "panels": [
            {
                "title": "y=e^x 与 y=x+1",
                "expressions": [
                    {"expression": "exp(x)", "label": "y=e^x"},
                    {"expression": "x+1", "label": "y=x+1"},
                ],
                "x_range": [-3, 3], "y_range": [-2, 8],
                "axis_mode": "manual",
                "annotations": [{"x": 0, "y": 1, "label": "(0,1)"}],
            },
            {
                "title": "y=ln x 与 y=x-1",
                "expressions": [
                    {"expression": "ln(x)", "label": "y=ln x"},
                    {"expression": "x-1", "label": "y=x-1"},
                ],
                "domain": {"intervals": [[0.001, 5]]},
                "x_range": [0, 5], "y_range": [-3, 4],
                "axis_mode": "manual",
                "annotations": [{"x": 1, "y": 0, "label": "(1,0)"}],
                "vertical_lines": [{"value": 0, "style": "dashed"}],
            },
            {
                "title": "y=x 与 y=sin x",
                "expressions": [
                    {"expression": "x", "label": "y=x"},
                    {"expression": "sin(x)", "label": "y=sin x"},
                ],
                "domain": {"intervals": [[0, 5]]},
                "x_range": [0, 5], "y_range": [-1, 5],
                "axis_mode": "manual",
                "annotations": [{"x": 0, "y": 0, "label": "(0,0)"}],
            },
        ]
    }


async def generate(apply: bool):
    async with async_session() as session:
        # Load all function_graph cards
        r = await session.execute(
            select(FormulaCard).where(
                FormulaCard.card_type == "function_graph",
                FormulaCard.deleted_at.is_(None),
            ).order_by(FormulaCard.id)
        )
        cards = list(r.scalars().all())

        # Load all assets
        card_ids = [c.id for c in cards]
        assets_r = await session.execute(
            select(FormulaGraphAsset).where(
                FormulaGraphAsset.formula_card_id.in_(card_ids)
            )
        )
        assets_map = {}
        for a in assets_r.scalars().all():
            assets_map.setdefault(a.formula_card_id, []).append(a)

        changes = []
        existing_asset_updates = []

        for c in cards:
            existing_assets = assets_map.get(c.id, [])
            has_valid_image = any(a.image_url for a in existing_assets)

            if has_valid_image:
                # Card already has image — just update status
                if c.graph_status != "ready":
                    existing_asset_updates.append({
                        "id": c.id,
                        "title": c.title,
                        "old_status": c.graph_status,
                        "new_status": "ready",
                    })
                    if apply:
                        c.graph_status = "ready"
                continue

            # No image — generate GraphSpec
            spec = build_graph_spec(c)
            if spec is None:
                print(f"  SKIP ID={c.id} ({c.title}): no spec generated")
                continue

            changes.append({
                "id": c.id,
                "title": c.title,
                "old_status": c.graph_status,
                "new_status": "unconfigured",  # Will be set to draft after preview
                "has_draft": c.draft_graph_spec is not None,
            })

            if apply:
                c.draft_graph_spec = spec
                if c.graph_status == "not_applicable":
                    c.graph_status = "unconfigured"
                print(f"  SET draft_graph_spec for ID={c.id} ({c.title})")

        if apply:
            await session.flush()
            # Commit if apply
            await session.commit()
        else:
            await session.rollback()

    print()
    print(f"Cards with existing assets (status → ready): {len(existing_asset_updates)}")
    for u in existing_asset_updates:
        print(f"  ID={u['id']}: {u['title']}: {u['old_status']} → {u['new_status']}")

    print()
    print(f"Cards with new GraphSpec drafts: {len(changes)}")
    for ch in changes:
        print(f"  ID={ch['id']}: {ch['title']}: had_draft={ch['has_draft']}, will_set_draft={apply}")

    if not apply:
        print()
        print("DRY-RUN: No changes applied. Re-run with --apply to persist.")
    else:
        print()
        print("APPLIED: draft_graph_spec saved.")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    dry_run = not apply

    if dry_run:
        print("=== DRY RUN: No changes will be applied ===")
    else:
        print("=== APPLY: Changes will be persisted ===")

    asyncio.run(generate(apply))
