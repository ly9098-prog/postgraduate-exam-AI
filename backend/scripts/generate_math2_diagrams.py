#!/usr/bin/env python3
"""
generate_math2_diagrams — Phase 2: generate 11 mathematical diagram assets.

Links each diagram to an existing formula card (found by source_ref).
Uses the GraphSpec → preview → confirm workflow.
Idempotent: same spec checksum → skip.

Modes:
    --dry-run               preview what would happen (default)
    --generate-previews     generate preview images (stops at draft)
    --confirm               confirm previews to create official assets
    --only <slug1,slug2>    process specific diagrams only

Usage:
    python scripts/generate_math2_diagrams.py
    python scripts/generate_math2_diagrams.py --generate-previews
    python scripts/generate_math2_diagrams.py --generate-previews --only curvature_circle
    python scripts/generate_math2_diagrams.py --confirm --reviewer-id <id>
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import init_db, async_session
from app.models.formula import FormulaCard, FormulaGraphSpec, FormulaGraphPreview, FormulaGraphAsset
from app.services.formula_graph_spec_service import generate_preview, confirm_preview

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Diagram definitions
# ═══════════════════════════════════════════════════════════════════

DIAGRAM_VERSION = 1

DIAGRAMS = [
    # ── 1. 曲率圆示意图 ──────────────────────────────────────────
    {
        "slug": "curvature_circle",
        "source_ref": "math2_diagram_v1:curvature_circle",
        "card_source_ref": "math2_core_v2:calculus:curvature_circle",
        "alt_text": "曲率圆示意图 — 曲线 x=y² 在点 P(0,0) 处的曲率圆",
        "description": "曲线 x=y²（开口向右的抛物线）在 P(0,0) 处的曲率圆，圆心 C(½,0)，半径 ρ=½。切线为 y 轴，法线为 x 轴。",
        "graph_spec": {
            "template": "single_function",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "曲率圆示意图",
            "panels": [
                {
                    "title": "",
                    "x_range": [-0.3, 1.3],
                    "y_range": [-0.8, 0.8],
                    "axis_mode": "equal",
                    "x_label": "x",
                    "y_label": "y",
                    "expressions": [
                        {
                            "expression": "sqrt(x)",
                            "label": "x=y²",
                            "domain": {"intervals": [[0.001, 0.6]]},
                        },
                        {
                            "expression": "-sqrt(x)",
                            "label": "",
                            "domain": {"intervals": [[0.001, 0.6]]},
                        },
                        {
                            "expression": "sqrt(0.25 - (x-0.5)**2)",
                            "label": "曲率圆",
                            "line_style": "dashed",
                            "domain": {"intervals": [[0, 1]]},
                        },
                        {
                            "expression": "-sqrt(0.25 - (x-0.5)**2)",
                            "label": "",
                            "line_style": "dashed",
                            "domain": {"intervals": [[0, 1]]},
                        },
                    ],
                    "annotations": [
                        {"x": 0, "y": 0, "label": "P(0,0)"},
                        {"x": 0.5, "y": 0, "label": "C(½,0)"},
                        {
                            "type": "arrow",
                            "x_start": 0.2,
                            "y_start": 0,
                            "x_end": 0.48,
                            "y_end": 0,
                            "label": "ρ=½",
                            "color": "#7c3aed",
                            "label_offset_x": -10,
                            "label_offset_y": 15,
                        },
                        {
                            "type": "arrow",
                            "x_start": 0,
                            "y_start": 0.3,
                            "x_end": 0,
                            "y_end": 0.55,
                            "label": "切线",
                            "color": "#16a34a",
                        },
                        {
                            "type": "arrow",
                            "x_start": 0.3,
                            "y_start": 0,
                            "x_end": 0.55,
                            "y_end": 0,
                            "label": "法线",
                            "color": "#d97706",
                        },
                    ],
                    "vertical_lines": [{"value": 0, "style": "dashed"}],
                    "horizontal_lines": [{"value": 0, "style": "dashed"}],
                }
            ],
        },
    },
    # ── 2. 弧微分示意图 ──────────────────────────────────────────
    {
        "slug": "arc_differential",
        "source_ref": "math2_diagram_v1:arc_differential",
        "card_source_ref": "math2_core_v2:calculus:arc_length",
        "alt_text": "弧微分示意图 — 曲线 y=x² 上的弧微分直角三角形",
        "description": "曲线 y=x² 在点 P 处的弧微分 ds 与 dx、dy 构成的直角三角形。ds²=dx²+dy²。",
        "graph_spec": {
            "template": "single_function",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "弧微分示意图",
            "panels": [
                {
                    "x_range": [0, 0.95],
                    "y_range": [0, 0.7],
                    "axis_mode": "manual",
                    "x_label": "x",
                    "y_label": "y",
                    "expressions": [
                        {
                            "expression": "x**2",
                            "label": "y=x²",
                            "domain": {"intervals": [[0.3, 0.85]]},
                        }
                    ],
                    "annotations": [
                        {"x": 0.5, "y": 0.25, "label": "P"},
                        {
                            "type": "arrow",
                            "x_start": 0.5,
                            "y_start": 0.25,
                            "x_end": 0.72,
                            "y_end": 0.25,
                            "label": "dx",
                            "color": "#2563eb",
                            "label_offset_y": -15,
                        },
                        {
                            "type": "arrow",
                            "x_start": 0.72,
                            "y_start": 0.25,
                            "x_end": 0.72,
                            "y_end": 0.43,
                            "label": "dy",
                            "color": "#dc2626",
                            "label_offset_x": 12,
                            "label_offset_y": 0,
                        },
                        {
                            "type": "arrow",
                            "x_start": 0.5,
                            "y_start": 0.25,
                            "x_end": 0.72,
                            "y_end": 0.43,
                            "label": "ds",
                            "color": "#16a34a",
                            "label_offset_x": 5,
                            "label_offset_y": -12,
                        },
                    ],
                    "vertical_lines": [{"value": 0.5, "style": "dotted"}],
                    "horizontal_lines": [{"value": 0.25, "style": "dotted"}],
                }
            ],
        },
    },
    # ── 3. 旋转曲面侧面积示意图 ──────────────────────────────────
    {
        "slug": "surface_revolution",
        "source_ref": "math2_diagram_v1:surface_revolution",
        "card_source_ref": "math2_core_v2:calculus:surface_revolution",
        "alt_text": "旋转曲面侧面积示意图 — 曲线 y=√x 绕 x 轴旋转",
        "description": "曲线 y=√x 绕 x 轴旋转形成旋转曲面。微元 dS=2πr·ds 中 r=y 为曲线上点到旋转轴的距离，ds 为弧微分。",
        "graph_spec": {
            "template": "single_function",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "旋转曲面侧面积示意图",
            "panels": [
                {
                    "x_range": [0, 2.2],
                    "y_range": [-0.2, 1.8],
                    "axis_mode": "manual",
                    "x_label": "x",
                    "y_label": "y",
                    "expressions": [
                        {
                            "expression": "sqrt(x)",
                            "label": "y=√x",
                            "domain": {"intervals": [[0.1, 2.0]]},
                        },
                    ],
                    "shading": [
                        {
                            "y1_expression": "sqrt(x)",
                            "y2_expression": "0",
                            "color": "#2563eb",
                            "alpha": 0.12,
                            "x_range": [0.1, 2.0],
                        }
                    ],
                    "annotations": [
                        {"x": 1, "y": 1, "label": "P(x,y)"},
                        {
                            "type": "arrow",
                            "x_start": 1,
                            "y_start": 1,
                            "x_end": 1.22,
                            "y_end": 1.12,
                            "label": "ds",
                            "color": "#dc2626",
                        },
                        {
                            "type": "arrow",
                            "x_start": 1,
                            "y_start": 0,
                            "x_end": 1,
                            "y_end": 0.95,
                            "label": "r=y",
                            "color": "#7c3aed",
                            "label_offset_x": 8,
                        },
                    ],
                    "vertical_lines": [{"value": 0, "style": "solid"}],
                    "horizontal_lines": [{"value": 0, "style": "solid"}],
                }
            ],
        },
    },
    # ── 4+5. 二重积分 X 型与 Y 型区域（组合为 2 面板）─────────
    {
        "slug": "double_int_regions",
        "source_ref": "math2_diagram_v1:double_int_regions",
        "card_source_ref": "math2_core_v2:calculus:exchange_order",
        "alt_text": "二重积分区域 — X 型与 Y 型区域对比",
        "description": "同一区域 D={(x,y): 0≤x≤1, x²≤y≤x} 的 X 型与 Y 型描述。X 型：a≤x≤b, φ₁(x)≤y≤φ₂(x)；Y 型：c≤y≤d, ψ₁(y)≤x≤ψ₂(y)。",
        "graph_spec": {
            "template": "multi_panel",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "二重积分区域类型",
            "layout": {"rows": 1, "columns": 2},
            "panels": [
                {
                    "title": "X 型区域",
                    "x_range": [0, 1.2],
                    "y_range": [0, 1.2],
                    "axis_mode": "manual",
                    "x_label": "x",
                    "y_label": "y",
                    "expressions": [
                        {
                            "expression": "x",
                            "label": "y=x (φ₂)",
                        },
                        {
                            "expression": "x**2",
                            "label": "y=x² (φ₁)",
                        },
                    ],
                    "shading": [
                        {
                            "y1_expression": "x",
                            "y2_expression": "x**2",
                            "color": "#2563eb",
                            "alpha": 0.3,
                            "x_range": [0, 1],
                            "label": "D",
                        }
                    ],
                    "annotations": [
                        {"x": 0.6, "y": 0.5, "label": "D"},
                        {"x": 1, "y": 1, "label": "(1,1)"},
                        {"x": 0.55, "y": -0.12, "label": "a≤x≤b", "color": "#666666"},
                    ],
                    "vertical_lines": [{"value": 0, "style": "dotted"}],
                },
                {
                    "title": "Y 型区域",
                    "x_range": [0, 1.2],
                    "y_range": [0, 1.2],
                    "axis_mode": "manual",
                    "x_label": "x",
                    "y_label": "y",
                    "expressions": [
                        {
                            "expression": "x",
                            "label": "x=y (ψ₁)",
                        },
                        {
                            "expression": "x**2",
                            "label": "x=√y (ψ₂)",
                        },
                    ],
                    "shading": [
                        {
                            "orientation": "horizontal",
                            "y1_expression": "x",
                            "y2_expression": "sqrt(x)",
                            "color": "#dc2626",
                            "alpha": 0.3,
                            "x_range": [0, 1],
                            "label": "D",
                        }
                    ],
                    "annotations": [
                        {"x": 0.6, "y": 0.5, "label": "D"},
                        {"x": 1, "y": 1, "label": "(1,1)"},
                        {"x": 0.1, "y": 0.55, "label": "c≤y≤d", "color": "#666666"},
                    ],
                    "horizontal_lines": [{"value": 0, "style": "dotted"}],
                },
            ],
        },
    },
    # ── 6. 交换次序需分区的区域 ──────────────────────────────────
    {
        "slug": "exchange_order_split",
        "source_ref": "math2_diagram_v1:exchange_order_split",
        "card_source_ref": "math2_core_v2:calculus:exchange_order",
        "alt_text": "交换积分次序需分区的区域 — D={(x,y): 0≤x≤1, x²≤y≤2-x}",
        "description": "交换积分次序时需要分区的区域 D={(x,y): 0≤x≤1, x²≤y≤2-x}。交换后分为 D₁={(x,y): 0≤y≤1, 0≤x≤√y} 和 D₂={(x,y): 1≤y≤2, 0≤x≤2-y}。分界线 y=1。",
        "graph_spec": {
            "template": "single_function",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "需分区的交换次序",
            "panels": [
                {
                    "x_range": [0, 1.5],
                    "y_range": [0, 2.2],
                    "axis_mode": "manual",
                    "x_label": "x",
                    "y_label": "y",
                    "expressions": [
                        {
                            "expression": "x**2",
                            "label": "y=x²",
                        },
                        {
                            "expression": "2 - x",
                            "label": "y=2-x",
                        },
                    ],
                    "shading": [
                        {
                            "y1_expression": "x**2",
                            "y2_expression": "1",
                            "color": "#2563eb",
                            "alpha": 0.25,
                            "x_range": [0, 1],
                            "label": "D₁",
                        },
                        {
                            "y1_expression": "1",
                            "y2_expression": "2 - x",
                            "color": "#dc2626",
                            "alpha": 0.25,
                            "x_range": [0, 1],
                            "label": "D₂",
                        },
                    ],
                    "annotations": [
                        {"x": 0.3, "y": 0.6, "label": "D₁", "color": "#2563eb"},
                        {"x": 0.5, "y": 1.5, "label": "D₂", "color": "#dc2626"},
                        {"x": 1, "y": 1, "label": "(1,1)"},
                        {"x": 0, "y": 2, "label": "(0,2)"},
                        {"x": 1, "y": 0, "label": "(1,0)"},
                    ],
                    "horizontal_lines": [
                        {"value": 1, "label": "y=1", "style": "dashed"}
                    ],
                    "vertical_lines": [{"value": 0, "style": "dotted"}],
                }
            ],
        },
    },
    # ── 7. 双曲线与射线围成的区域 ────────────────────────────────
    {
        "slug": "hyperbola_sector",
        "source_ref": "math2_diagram_v1:hyperbola_sector",
        "card_source_ref": "math2_core_v2:calculus:exchange_order",
        "alt_text": "双曲线 xy=1, xy=2 与射线 y=x, y=2x 围成的区域",
        "description": "第一象限内双曲线 xy=1, xy=2 与射线 y=x, y=2x 围成的曲线四边形区域。四个交点均以标注。",
        "graph_spec": {
            "template": "single_function",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "双曲线与射线围成的区域",
            "panels": [
                {
                    "x_range": [0, 2],
                    "y_range": [0, 2.5],
                    "axis_mode": "manual",
                    "x_label": "x",
                    "y_label": "y",
                    "expressions": [
                        {
                            "expression": "1/x",
                            "label": "xy=1",
                            "domain": {"intervals": [[0.1, 2.0]]},
                        },
                        {
                            "expression": "2/x",
                            "label": "xy=2",
                            "domain": {"intervals": [[0.1, 2.0]]},
                        },
                        {"expression": "x", "label": "y=x"},
                        {"expression": "2*x", "label": "y=2x"},
                    ],
                    "shading": [
                        {
                            "y1_expression": "1/x",
                            "y2_expression": "2*x",
                            "color": "#2563eb",
                            "alpha": 0.25,
                            "x_range": [0.707, 1.0],
                            "label": "",
                        },
                        {
                            "y1_expression": "x",
                            "y2_expression": "2/x",
                            "color": "#2563eb",
                            "alpha": 0.25,
                            "x_range": [1.0, 1.414],
                            "label": "D",
                        },
                    ],
                    "annotations": [
                        {"x": 1, "y": 1, "label": "(1,1)"},
                        {"x": 1, "y": 2, "label": "(1,2)"},
                        {"x": 0.707, "y": 1.414, "label": "A", "color": "#7c3aed"},
                        {"x": 1.414, "y": 1.414, "label": "B", "color": "#7c3aed"},
                    ],
                    "vertical_lines": [{"value": 0, "style": "dotted"}],
                    "horizontal_lines": [{"value": 0, "style": "dotted"}],
                }
            ],
        },
    },
    # ── 8. 常见二次曲线（4 面板 2×2）───────────────────────────
    {
        "slug": "conic_sections",
        "source_ref": "math2_diagram_v1:conic_sections",
        "card_source_ref": "math2_core_v2:calculus:conic_sections",
        "alt_text": "常见二次曲线对比 — 圆、椭圆、抛物线、双曲线",
        "description": "四种常见二次曲线：圆 x²+y²=1，椭圆 x²/4+y²=1，抛物线 y²=4x，双曲线 x²-y²=1。均使用等轴坐标系。",
        "graph_spec": {
            "template": "multi_panel",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "常见二次曲线",
            "layout": {"rows": 2, "columns": 2},
            "panels": [
                {
                    "title": "圆 x²+y²=1",
                    "x_range": [-1.5, 1.5],
                    "y_range": [-1.5, 1.5],
                    "axis_mode": "equal",
                    "expressions": [
                        {
                            "expression": "sqrt(1 - x**2)",
                            "domain": {"intervals": [[-1, 1]]},
                        },
                        {
                            "expression": "-sqrt(1 - x**2)",
                            "domain": {"intervals": [[-1, 1]]},
                        },
                    ],
                    "annotations": [
                        {"x": 1, "y": 0, "label": "(1,0)"},
                        {"x": 0, "y": 1, "label": "(0,1)"},
                    ],
                },
                {
                    "title": "椭圆 x²/4+y²=1",
                    "x_range": [-2.5, 2.5],
                    "y_range": [-1.5, 1.5],
                    "axis_mode": "equal",
                    "expressions": [
                        {
                            "expression": "sqrt(1 - x**2 / 4)",
                            "domain": {"intervals": [[-2, 2]]},
                        },
                        {
                            "expression": "-sqrt(1 - x**2 / 4)",
                            "domain": {"intervals": [[-2, 2]]},
                        },
                    ],
                    "annotations": [
                        {"x": 2, "y": 0, "label": "(2,0)"},
                        {"x": 0, "y": 1, "label": "(0,1)"},
                    ],
                },
                {
                    "title": "抛物线 y²=4x",
                    "x_range": [0, 3],
                    "y_range": [-3, 3],
                    "axis_mode": "equal",
                    "expressions": [
                        {
                            "expression": "2*sqrt(x)",
                            "label": "y>0",
                            "domain": {"intervals": [[0, 3]]},
                        },
                        {
                            "expression": "-2*sqrt(x)",
                            "label": "y<0",
                            "domain": {"intervals": [[0, 3]]},
                        },
                    ],
                    "annotations": [
                        {"x": 0, "y": 0, "label": "顶点", "color": "#7c3aed"},
                    ],
                },
                {
                    "title": "双曲线 x²-y²=1",
                    "x_range": [-3, 3],
                    "y_range": [-3, 3],
                    "axis_mode": "equal",
                    "expressions": [
                        {
                            "expression": "sqrt(x**2 - 1)",
                            "label": "上支",
                            "domain": {"intervals": [[-3, -1], [1, 3]]},
                        },
                        {
                            "expression": "-sqrt(x**2 - 1)",
                            "label": "下支",
                            "domain": {"intervals": [[-3, -1], [1, 3]]},
                        },
                        {"expression": "x", "label": "渐近线", "line_style": "dashed"},
                        {
                            "expression": "-x",
                            "label": "",
                            "line_style": "dashed",
                        },
                    ],
                    "annotations": [
                        {"x": 1, "y": 0, "label": "(1,0)"},
                    ],
                },
            ],
        },
    },
    # ── 9. 三个基本极限（3 面板）────────────────────────────────
    {
        "slug": "three_basic_limits",
        "source_ref": "math2_diagram_v1:three_basic_limits",
        "card_source_ref": "",
        "card_title_match": "两个重要极限",
        "alt_text": "三个基本极限 — sin(x)/x, (e^x-1)/x, ln(1+x)/x 在 x→0 时趋于 1",
        "description": "三个重要极限的辅助图：sin(x)/x→1, (e^x-1)/x→1, ln(1+x)/x→1 当 x→0。每个面板在 (0,1) 处有开圈标记，虚线 y=1 为参考线。",
        "graph_spec": {
            "template": "multi_panel",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "三个基本极限",
            "layout": {"rows": 1, "columns": 3},
            "panels": [
                {
                    "title": "lim sin(x)/x = 1",
                    "x_range": [-4, 4],
                    "y_range": [0, 1.4],
                    "axis_mode": "manual",
                    "expressions": [
                        {
                            "expression": "sin(x)/x",
                            "domain": {"exclude_points": [0]},
                        },
                    ],
                    "annotations": [
                        {
                            "x": 0,
                            "y": 1,
                            "label": "(0,1)",
                            "point_style": "hollow",
                        },
                    ],
                    "horizontal_lines": [{"value": 1, "style": "dashed"}],
                },
                {
                    "title": "lim (e^x-1)/x = 1",
                    "x_range": [-4, 4],
                    "y_range": [0, 1.4],
                    "axis_mode": "manual",
                    "expressions": [
                        {
                            "expression": "(exp(x) - 1)/x",
                            "domain": {"exclude_points": [0]},
                        },
                    ],
                    "annotations": [
                        {
                            "x": 0,
                            "y": 1,
                            "label": "(0,1)",
                            "point_style": "hollow",
                        },
                    ],
                    "horizontal_lines": [{"value": 1, "style": "dashed"}],
                },
                {
                    "title": "lim ln(1+x)/x = 1",
                    "x_range": [-0.95, 4],
                    "y_range": [0, 1.4],
                    "axis_mode": "manual",
                    "expressions": [
                        {
                            "expression": "ln(1 + x)/x",
                            "domain": {
                                "intervals": [[-0.9, 0], [0, 4]],
                                "exclude_points": [0],
                            },
                        },
                    ],
                    "annotations": [
                        {
                            "x": 0,
                            "y": 1,
                            "label": "(0,1)",
                            "point_style": "hollow",
                        },
                    ],
                    "horizontal_lines": [{"value": 1, "style": "dashed"}],
                },
            ],
        },
    },
    # ── 10. 第二重要极限（2 面板）────────────────────────────────
    {
        "slug": "second_important_limit",
        "source_ref": "math2_diagram_v1:second_important_limit",
        "card_source_ref": "",
        "card_title_match": "两个重要极限",
        "alt_text": "第二重要极限 — (1+x)^{1/x}→e 和 (1+1/x)^x→e",
        "description": "第二重要极限的两种形式：左图 (1+x)^{1/x}→e 当 x→0，右图 (1+1/x)^x→e 当 x→∞。虚线 y=e≈2.718 为参考线。",
        "graph_spec": {
            "template": "multi_panel",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "第二重要极限",
            "layout": {"rows": 1, "columns": 2},
            "panels": [
                {
                    "title": "lim_{x→0} (1+x)^{1/x} = e",
                    "x_range": [-0.9, 2],
                    "y_range": [0, 3.5],
                    "axis_mode": "manual",
                    "expressions": [
                        {
                            "expression": "(1 + x)**(1/x)",
                            "domain": {
                                "intervals": [[-0.85, 0], [0.001, 2]],
                                "exclude_points": [0],
                            },
                        },
                    ],
                    "annotations": [
                        {
                            "x": 0,
                            "y": 2.71828,
                            "label": "e",
                            "point_style": "hollow",
                        },
                    ],
                    "horizontal_lines": [
                        {"value": 2.71828, "label": "y=e", "style": "dashed"}
                    ],
                    "vertical_lines": [{"value": 0, "style": "dotted"}],
                },
                {
                    "title": "lim_{x→∞} (1+1/x)^x = e",
                    "x_range": [0, 10],
                    "y_range": [0, 3.5],
                    "axis_mode": "manual",
                    "expressions": [
                        {
                            "expression": "(1 + 1/x)**x",
                            "domain": {"intervals": [[0.01, 10]]},
                        },
                    ],
                    "annotations": [
                        {"x": 0.01, "y": 1, "label": "(0→1)"},
                    ],
                    "horizontal_lines": [
                        {"value": 2.71828, "label": "y=e", "style": "dashed"}
                    ],
                },
            ],
        },
    },
    # ── 11. 指数衰减型函数族 ────────────────────────────────────
    {
        "slug": "exponential_decay_family",
        "source_ref": "math2_diagram_v1:exponential_decay_family",
        "card_source_ref": "math2_core_v2:calculus:exponential_decay",
        "alt_text": "指数衰减型函数族 — y=x^α·e^{-βx} 在不同 (α,β) 下的图像",
        "description": "指数衰减型函数族 f(x)=x^α·e^{-βx} 在三组参数下的图像。极大值点均在 x=α/β 处。",
        "graph_spec": {
            "template": "single_function",
            "renderer_version": 1,
            "spec_version": 1,
            "title": "指数衰减型函数族",
            "panels": [
                {
                    "x_range": [0, 6],
                    "y_range": [0, 0.8],
                    "axis_mode": "manual",
                    "x_label": "x",
                    "y_label": "y",
                    "expressions": [
                        {
                            "expression": "x**1 * exp(-1*x)",
                            "label": "α=1, β=1",
                            "domain": {"intervals": [[0.01, 6]]},
                        },
                        {
                            "expression": "x**2 * exp(-1*x)",
                            "label": "α=2, β=1",
                            "domain": {"intervals": [[0.01, 6]]},
                        },
                        {
                            "expression": "x**2 * exp(-2*x)",
                            "label": "α=2, β=2",
                            "domain": {"intervals": [[0.01, 6]]},
                        },
                    ],
                    "annotations": [
                        {"x": 1, "y": 0.3679, "label": "x_max=1", "color": "#2563eb"},
                        {
                            "x": 2,
                            "y": 0.5413,
                            "label": "x_max=2",
                            "color": "#dc2626",
                        },
                        {"x": 1, "y": 0.2707, "label": "x_max=1", "color": "#16a34a"},
                    ],
                    "vertical_lines": [
                        {"value": 1, "style": "dotted"},
                        {"value": 2, "style": "dotted"},
                    ],
                }
            ],
        },
    },
]


def _spec_checksum(spec: dict) -> str:
    """Deterministic checksum from spec JSON + diagram version."""
    raw = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"v{DIAGRAM_VERSION}:{raw}".encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════
# DB helpers
# ═══════════════════════════════════════════════════════════════════


async def find_card_by_source_ref(db, source_ref: str, title_match: str | None = None) -> FormulaCard | None:
    """Find a FormulaCard by source_ref, then by title as fallback."""
    if not source_ref:
        if title_match:
            return await find_card_by_title(db, title_match)
        return None
    r = await db.execute(
        select(FormulaCard).where(
            FormulaCard.source_ref == source_ref,
            FormulaCard.deleted_at.is_(None),
        )
    )
    cards = list(r.scalars().all())
    if len(cards) == 1:
        return cards[0]
    if len(cards) > 1:
        logger.warning("  AMBIGUOUS: source_ref=%s → %d cards", source_ref, len(cards))
        return None
    # Fallback: title match
    if title_match:
        return await find_card_by_title(db, title_match)
    return None


async def find_card_by_title(db, title_match: str) -> FormulaCard | None:
    """Find a FormulaCard by title substring match."""
    r = await db.execute(
        select(FormulaCard).where(
            FormulaCard.title.ilike(f"%{title_match}%"),
            FormulaCard.deleted_at.is_(None),
        )
    )
    cards = list(r.scalars().all())
    if len(cards) == 1:
        return cards[0]
    if len(cards) > 1:
        logger.warning("  AMBIGUOUS: title=%s → %d cards", title_match, len(cards))
    return None


# ═══════════════════════════════════════════════════════════════════
# FormulaGraphSpec helpers
# ═══════════════════════════════════════════════════════════════════


async def find_or_create_spec(
    db,
    card: FormulaCard,
    diagram: dict,
    checksum: str,
) -> FormulaGraphSpec:
    """Find existing FormulaGraphSpec by slug, or create one."""
    slug = diagram["slug"]
    r = await db.execute(
        select(FormulaGraphSpec).where(
            FormulaGraphSpec.formula_card_id == card.id,
            FormulaGraphSpec.slug == slug,
        )
    )
    spec = r.scalar_one_or_none()
    if spec:
        return spec

    spec = FormulaGraphSpec(
        formula_card_id=card.id,
        slug=slug,
        source_ref=diagram["source_ref"],
        title=diagram.get("graph_spec", {}).get("title", slug),
        description=diagram.get("description", ""),
        alt_text=diagram.get("alt_text", ""),
        spec_json=diagram["graph_spec"],
        spec_hash=checksum,
        schema_version=diagram["graph_spec"].get("spec_version", 1),
        renderer_version=diagram["graph_spec"].get("renderer_version", 1),
        status="draft",
        sort_order=0,
    )
    db.add(spec)
    await db.flush()
    return spec


async def update_spec_after_confirm(
    db,
    spec: FormulaGraphSpec,
    asset: FormulaGraphAsset,
) -> None:
    """Update FormulaGraphSpec after successful confirmation."""
    spec.status = "ready"
    spec.confirmed_asset_id = asset.id
    spec.reviewed_at = datetime.now(timezone.utc)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════


async def main():
    parser = argparse.ArgumentParser(description="Generate Phase 2 mathematical diagram assets")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default if no mode given)")
    parser.add_argument("--generate-previews", action="store_true", help="Generate preview images (stops at draft)")
    parser.add_argument("--confirm", action="store_true", help="Confirm previews to create official assets")
    parser.add_argument("--only", type=str, help="Comma-separated slugs to process")
    parser.add_argument("--reviewer-id", type=int, default=1, help="Admin user ID for confirmation")
    args = parser.parse_args()

    # Determine mode
    mode = "dry_run"
    if args.generate_previews:
        mode = "generate_previews"
    if args.confirm:
        mode = "confirm"

    only_slugs = set(s.strip() for s in args.only.split(",")) if args.only else None

    # Filter diagrams
    diagrams = DIAGRAMS
    if only_slugs:
        diagrams = [d for d in DIAGRAMS if d["slug"] in only_slugs]
        found = {d["slug"] for d in diagrams}
        missing = only_slugs - found
        if missing:
            logger.warning("Unknown slugs: %s", missing)

    print(f"{'=' * 60}")
    print(f"Phase 2 — Mathematical Diagram Generator")
    print(f"Mode: {mode.upper()}")
    print(f"Diagrams: {len(diagrams)}")
    if only_slugs:
        print(f"Filtered: {', '.join(sorted(only_slugs))}")
    print(f"{'=' * 60}")
    print()

    await init_db()

    stats = {
        "found_cards": 0,
        "specs_created": 0,
        "previews_generated": 0,
        "previews_skipped": 0,
        "confirmed": 0,
        "no_card": [],
        "errors": [],
    }

    async with async_session() as db:
        async with db.begin():
            for diagram in diagrams:
                slug = diagram["slug"]
                card_sr = diagram["card_source_ref"]
                spec = diagram["graph_spec"]
                checksum = _spec_checksum(spec)

                print(f"[{slug}] ...")

                # Find card
                title_match = diagram.get("card_title_match")
                card = await find_card_by_source_ref(db, card_sr, title_match) if card_sr or title_match else None
                if not card and (card_sr or title_match):
                    stats["no_card"].append(f"{slug} (looked for sr={card_sr}, title={title_match})")
                    print(f"  WARN: card not found for source_ref={card_sr}")
                    if not card_sr:
                        print(f"  INFO: standalone diagram (no card link)")
                    else:
                        continue

                if card:
                    stats["found_cards"] += 1
                    print(f"  Card: ID={card.id} title={card.title}")

                if mode == "dry_run":
                    stats["specs_created"] += 1
                    print(f"  DRY: would create FormulaGraphSpec (cs={checksum[:12]})")
                    print(f"  DRY: would generate preview")
                    continue

                # Ensure FormulaGraphSpec exists
                if card:
                    graph_spec = await find_or_create_spec(db, card, diagram, checksum)
                    stats["specs_created"] += 1
                    print(f"  Spec: ID={graph_spec.id} slug={graph_spec.slug} status={graph_spec.status}")

                if mode == "generate_previews":
                    if not card:
                        print(f"  SKIP: no card to attach to")
                        continue
                    try:
                        result = await generate_preview(db, card, spec, admin_id=args.reviewer_id)
                        stats["previews_generated"] += 1
                        print(f"  OK   preview_token={result['preview_token'][:12]}... cs={checksum[:12]}")
                    except ValueError as e:
                        if "already running" in str(e):
                            stats["previews_skipped"] += 1
                            print(f"  SKIP generation already running")
                        elif "same checksum" in str(e).lower() or "existing" in str(e).lower():
                            stats["previews_skipped"] += 1
                            print(f"  SKIP same checksum")
                        else:
                            stats["errors"].append({"slug": slug, "error": str(e)})
                            print(f"  FAIL: {e}")

                elif mode == "confirm":
                    if not card:
                        print(f"  SKIP: no card to confirm on")
                        continue
                    try:
                        r = await db.execute(
                            select(FormulaGraphPreview).where(
                                FormulaGraphPreview.formula_card_id == card.id,
                            ).order_by(FormulaGraphPreview.created_at.desc())
                        )
                        preview = r.scalar_one_or_none()
                        if not preview:
                            print(f"  SKIP: no pending preview")
                            stats["previews_skipped"] += 1
                            continue

                        asset = await confirm_preview(
                            db, card,
                            preview_token=preview.preview_token,
                            card_version=card.version,
                            accept_warnings=True,
                            admin_id=args.reviewer_id,
                            alt_text=diagram.get("alt_text"),
                            description=diagram.get("description"),
                        )
                        stats["confirmed"] += 1
                        print(f"  OK   asset_id={asset.id} confirmed")

                        # Update FormulaGraphSpec
                        graph_spec = await find_or_create_spec(db, card, diagram, checksum)
                        await update_spec_after_confirm(db, graph_spec, asset)
                        print(f"  Spec: ID={graph_spec.id} status=ready")

                    except ValueError as e:
                        stats["errors"].append({"slug": slug, "error": str(e)})
                        print(f"  FAIL: {e}")

    # ── Report ──
    print(f"\n{'=' * 60}")
    print("Summary:")
    print(f"  Cards found:      {stats['found_cards']}")
    print(f"  Specs created:    {stats['specs_created']}")
    print(f"  Previews gen:     {stats['previews_generated']}")
    print(f"  Previews skipped: {stats['previews_skipped']}")
    print(f"  Confirmed:        {stats['confirmed']}")
    print(f"  No card:          {len(stats['no_card'])}")
    for s in stats["no_card"]:
        print(f"    - {s}")
    print(f"  Errors:           {len(stats['errors'])}")
    for e in stats["errors"]:
        print(f"    - [{e['slug']}] {e['error']}")
    if mode == "dry_run":
        print(f"\n  This was a DRY RUN. Use --generate-previews to generate.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
