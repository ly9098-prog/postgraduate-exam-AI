"""
Integration test: Three real formula graph examples.
Tests the full renderer pipeline with real images and quality checks.

Usage: python scripts/test_three_examples.py
"""
import json
import sys
import os
from pathlib import Path

# Ensure backend is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.services.formula_graph_spec_renderer import _render_spec_sync, check_quality
from PIL import Image
import io


def test_example(name: str, spec: dict):
    """Render a spec, verify output, run quality check."""
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")

    # 1. Render
    print("  [1/6] Rendering...")
    png_bytes, metadata = _render_spec_sync(spec)
    print(f"        {len(png_bytes)} bytes, {metadata.get('width')}x{metadata.get('height')}")
    print(f"        meta: {json.dumps({k: v for k, v in metadata.items() if k != 'panel_curves'}, default=str)}")

    # 2. Quality check
    print("  [2/6] Quality check...")
    quality_result = check_quality(png_bytes, spec, metadata)
    print(f"        passed={quality_result['passed']}")
    if quality_result["warnings"]:
        for w in quality_result["warnings"]:
            print(f"        ⚠  {w}")
    if quality_result["errors"]:
        for e in quality_result["errors"]:
            print(f"        ✗  {e}")

    # 3. Verify PNG is real and not blank
    print("  [3/6] PNG verification...")
    img = Image.open(io.BytesIO(png_bytes))
    print(f"        format={img.format}, mode={img.mode}, size={img.size}")

    # Check not blank
    img_rgb = img.convert("RGB")
    pixels = list(img_rgb.getdata())
    total = len(pixels)
    white = sum(1 for p in pixels if p[0] > 250 and p[1] > 250 and p[2] > 250)
    white_pct = white / total * 100
    print(f"        white pixels: {white_pct:.1f}%")
    assert white_pct < 99, f"Image is {white_pct:.1f}% white - looks blank!"
    print(f"        ✓ Image has meaningful content")

    # 4. Verify dimensions
    print("  [4/6] Dimension check...")
    expected_w = spec.get("viewport", {}).get("width", 1600)
    expected_h = spec.get("viewport", {}).get("height", 1000)
    # Actual dimensions from metadata
    actual_w = metadata.get("width", 0)
    actual_h = metadata.get("height", 0)
    print(f"        expected: ~{expected_w}x{expected_h}, got: {actual_w}x{actual_h}")
    assert actual_w > 0 and actual_h > 0

    # 5. Save files
    print("  [5/6] Saving...")
    output_dir = Path("/tmp/formula-examples")
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = name.replace(" ", "_").replace("/", "_")
    png_path = output_dir / f"{safe_name}.png"
    png_path.write_bytes(png_bytes)
    print(f"        saved to: {png_path}")

    # Generate thumbnail
    thumb = img.copy()
    thumb.thumbnail((600, 450))
    thumb_path = output_dir / f"{safe_name}-thumb.png"
    thumb.save(thumb_path, "PNG")
    print(f"        thumbnail: {thumb_path}")

    # 6. Print spec summary
    print("  [6/6] Spec JSON preview...")
    print(f"        {json.dumps(spec, ensure_ascii=False, indent=2)[:500]}...")

    return {
        "name": name,
        "png_path": str(png_path),
        "thumb_path": str(thumb_path),
        "size": len(png_bytes),
        "dimensions": (actual_w, actual_h),
        "quality": quality_result,
        "spec": spec,
    }


def main():
    results = []

    # ── Example 1: 指数对数不等式常用辅助函数 ──
    spec1 = {
        "schema_version": 1,
        "render_mode": "explicit_2d",
        "template": "inequality_auxiliary",
        "layout": {"rows": 1, "columns": 3},
        "panels": [
            {
                "title": "e^x ≥ x+1",
                "expressions": [
                    {"expression": "exp(x)", "display_latex": "e^x", "label": "e^x", "line_style": "solid"},
                    {"expression": "x+1", "display_latex": "x+1", "label": "x+1", "line_style": "dashed"},
                ],
                "domain": {"intervals": [], "exclude_points": []},
                "axis_mode": "manual",
                "x_range": [-3, 3],
                "y_range": [-2, 8],
                "annotations": [
                    {"x": 0, "y": 1, "label": "(0,1) 切点", "color": "#b91c1c", "point_style": "filled"},
                ],
                "vertical_lines": [],
                "horizontal_lines": [],
                "x_label": "x",
                "y_label": "y",
            },
            {
                "title": "ln x ≤ x-1",
                "expressions": [
                    {"expression": "log(x)", "display_latex": "\\ln x", "label": "ln x", "line_style": "solid"},
                    {"expression": "x-1", "display_latex": "x-1", "label": "x-1", "line_style": "dashed"},
                ],
                "domain": {"intervals": [[0.001, None]], "exclude_points": []},
                "axis_mode": "manual",
                "x_range": [0.05, 4],
                "y_range": [-3, 3],
                "annotations": [
                    {"x": 1, "y": 0, "label": "(1,0) 切点", "color": "#b91c1c", "point_style": "filled"},
                ],
                "vertical_lines": [],
                "horizontal_lines": [],
                "x_label": "x",
                "y_label": "y",
            },
            {
                "title": "x ≥ sin(x), x≥0",
                "expressions": [
                    {"expression": "x", "label": "y=x", "line_style": "solid"},
                    {"expression": "sin(x)", "label": "sin x", "line_style": "dashed"},
                ],
                "domain": {"intervals": [[0, None]], "exclude_points": []},
                "axis_mode": "manual",
                "x_range": [0, 8],
                "y_range": [-2, 8],
                "annotations": [
                    {"x": 0, "y": 0, "label": "(0,0) 切点", "color": "#b91c1c", "point_style": "filled"},
                ],
                "vertical_lines": [],
                "horizontal_lines": [],
                "x_label": "x",
                "y_label": "y",
            },
        ],
    }

    # ── Example 2: 幂指辅助函数 y=x^x ──
    spec2 = {
        "schema_version": 1,
        "render_mode": "explicit_2d",
        "template": "single_function",
        "layout": {"rows": 1, "columns": 1},
        "panels": [
            {
                "title": "y=x^x",
                "expressions": [
                    {"expression": "x**x", "display_latex": "y=x^x", "label": "y=x^x", "line_style": "solid"},
                ],
                "domain": {"intervals": [[0.001, 3]], "exclude_points": []},
                "axis_mode": "manual",
                "x_range": [0.01, 3],
                "y_range": [-0.5, 8],
                "annotations": [
                    {"x": 0.3679, "y": 0.6922, "label": "极小值 (1/e, e^{-1/e})", "color": "#b91c1c", "point_style": "filled"},
                ],
                "vertical_lines": [
                    {"value": 0.3679, "label": "x=1/e", "style": "dashed", "is_vertical": True},
                ],
                "horizontal_lines": [
                    {"value": 0.6922, "label": "y=e^{-1/e}", "style": "dotted", "is_vertical": False},
                ],
                "x_label": "x",
                "y_label": "y",
            }
        ],
    }

    # ── Example 3: 四类间断点图像对比 ──
    import math
    spec3 = {
        "schema_version": 1,
        "render_mode": "explicit_2d",
        "template": "discontinuity_comparison",
        "layout": {"rows": 2, "columns": 2},
        "panels": [
            {
                "title": "可去间断点",
                "expressions": [
                    {"expression": "(x**2 - 1) / (x - 1)", "label": "y=(x²-1)/(x-1)", "line_style": "solid"},
                ],
                "domain": {"intervals": [[-3, 0.999], [1.001, 3]], "exclude_points": [1]},
                "axis_mode": "manual",
                "x_range": [-3, 3],
                "y_range": [-1, 5],
                "annotations": [
                    {"x": 1, "y": 2, "label": "x=1 可去间断", "color": "#b91c1c", "point_style": "hollow"},
                ],
                "vertical_lines": [],
                "horizontal_lines": [],
                "x_label": "x",
                "y_label": "y",
            },
            {
                "title": "跳跃间断点",
                "expressions": [
                    {"expression": "1 / (1 + exp(-x))", "label": "σ(x)", "line_style": "solid"},
                ],
                "domain": {"intervals": [[-6, 0]], "exclude_points": []},
                "axis_mode": "manual",
                "x_range": [-6, 6],
                "y_range": [-0.5, 1.5],
                "annotations": [],
                "vertical_lines": [],
                "horizontal_lines": [],
                "x_label": "x",
                "y_label": "y",
            },
            {
                "title": "无穷间断点",
                "expressions": [
                    {"expression": "1 / x", "label": "y=1/x", "line_style": "solid"},
                ],
                "domain": {"intervals": [[-3, -0.01], [0.01, 3]], "exclude_points": [0]},
                "axis_mode": "manual",
                "x_range": [-3, 3],
                "y_range": [-10, 10],
                "annotations": [
                    {"x": 0, "y": 0, "label": "x=0 无穷间断", "color": "#b91c1c", "point_style": "hollow"},
                ],
                "vertical_lines": [
                    {"value": 0, "label": "x=0", "style": "dashed", "is_vertical": True},
                ],
                "horizontal_lines": [
                    {"value": 0, "label": "y=0", "style": "dotted", "is_vertical": False},
                ],
                "x_label": "x",
                "y_label": "y",
            },
            {
                "title": "振荡间断点",
                "expressions": [
                    {"expression": "sin(1 / x)", "label": "y=sin(1/x)", "line_style": "solid"},
                ],
                # Use a bounded interval to avoid insane oscillation near 0
                "domain": {"intervals": [[0.03, 0.5]], "exclude_points": [0]},
                "axis_mode": "manual",
                "x_range": [-0.1, 0.5],
                "y_range": [-1.5, 1.5],
                "annotations": [
                    {"x": 0, "y": 0, "label": "x=0 振荡间断", "color": "#b91c1c", "point_style": "hollow"},
                ],
                "vertical_lines": [
                    {"value": 0, "label": "x=0", "style": "dashed", "is_vertical": True},
                ],
                "horizontal_lines": [],
                "x_label": "x",
                "y_label": "y",
            },
        ],
    }

    examples = [
        ("指数对数不等式辅助函数 (Panel 1: e^x≥x+1, Panel 2: ln x≤x-1, Panel 3: x≥sin x)", spec1),
        ("幂指辅助函数 y=x^x", spec2),
        ("四类间断点图像对比 (可去/跳跃/无穷/振荡)", spec3),
    ]

    for name, spec in examples:
        try:
            result = test_example(name, spec)
            results.append(result)
            status = "✓ PASS" if result["quality"]["passed"] else "✗ QUALITY_WARN"
            print(f"\n  → {status} ({result['dimensions'][0]}x{result['dimensions'][1]}, {result['size']} bytes)")
        except Exception as e:
            print(f"\n  → ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")
    passed = sum(1 for r in results if r["quality"]["passed"])
    total = len(examples)
    print(f"  {passed}/{total} examples passed quality checks")
    print(f"  Images saved to: /tmp/formula-examples/")
    for r in results:
        status = "✓" if r["quality"]["passed"] else "⚠"
        print(f"    {status} {r['name'][:60]}: {r['dimensions'][0]}x{r['dimensions'][1]} {r['size']//1024}KB")


if __name__ == "__main__":
    main()
