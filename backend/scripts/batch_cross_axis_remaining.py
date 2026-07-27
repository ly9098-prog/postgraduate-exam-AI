#!/usr/bin/env python3
"""Convert all remaining function_graph cards to cross-axis.

Handles two groups:
  Group A — 10 cards with existing graph_specs (63,64,65,82,83,84,88,90,91,92)
  Group B — 10 cards without graph_specs (59,60,61,62,66,67,69,72,85,89)
"""
import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import init_db, async_session
from app.core.executor_registry import init_executor_registry
from app.core.executors import init_executors_for_role
from app.models.formula import FormulaCard, FormulaGraphAsset, FormulaGraphPreview
from app.services.formula_graph_spec_renderer import render_spec, RENDERER_VERSION, _resize_to_canvas
from app.services.storage_backend import get_storage
from app.services.formula_graph_spec_service import _safe_delete_file_later, _storage_path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = (600, 450)

PI = 3.141592653589793

# ── Default graph_specs for cards without existing specs ──
DEFAULT_SPECS = {
    # 一次函数 y=kx+b
    59: {
        "template": "single_function", "renderer_version": 1, "spec_version": 1,
        "title": "y=kx+b — 一次函数",
        "panels": [{
            "x_range": [-5, 5], "y_range": [-5, 5],
            "axis_mode": "manual", "expressions": [
                {"expression": "x", "label": "y=x (k=1,b=0)"},
                {"expression": "2*x+1", "label": "y=2x+1 (k=2,b=1)"},
            ],
        }]
    },
    # 二次函数 y=ax^2+bx+c
    60: {
        "template": "single_function", "renderer_version": 1, "spec_version": 1,
        "title": "y=ax²+bx+c — 二次函数",
        "panels": [{
            "x_range": [-3, 3], "y_range": [-1, 5],
            "axis_mode": "manual", "expressions": [
                {"expression": "x**2", "label": "y=x² (a=1,b=0,c=0)"},
                {"expression": "x**2-2*x", "label": "y=x²-2x (a=1,b=-2)"},
            ],
            "annotations": [
                {"x": 0, "y": 0, "label": "顶点 (0,0)"},
            ],
        }]
    },
    # y=|x|
    61: {
        "template": "single_function", "renderer_version": 1, "spec_version": 1,
        "title": "y=|x| — 绝对值函数",
        "panels": [{
            "x_range": [-3, 3], "y_range": [-0.5, 3],
            "axis_mode": "manual", "expressions": [
                {"expression": "abs(x)", "label": "y=|x|"},
            ],
            "annotations": [
                {"x": 0, "y": 0, "label": "(0,0)"},
            ],
        }]
    },
    # y=1/x 与 y=1/x^2
    62: {
        "template": "function_comparison", "renderer_version": 1, "spec_version": 1,
        "title": "y=1/x 与 y=1/x²",
        "panels": [{
            "x_range": [-3, 3], "y_range": [-3, 3],
            "axis_mode": "manual", "expressions": [
                {"expression": "1/x", "label": "y=1/x",
                 "domain": {"intervals": [[-3, -0.01], [0.01, 3]]}},
                {"expression": "1/(x**2)", "label": "y=1/x²",
                 "domain": {"intervals": [[-3, -0.01], [0.01, 3]]}},
            ],
        }]
    },
    # 指数函数底数对比 y=a^x
    66: {
        "template": "function_comparison", "renderer_version": 1, "spec_version": 1,
        "title": "指数函数底数对比 y=aˣ",
        "panels": [{
            "x_range": [-2, 3], "y_range": [-0.5, 8],
            "axis_mode": "manual", "expressions": [
                {"expression": "2**x", "label": "y=2ˣ"},
                {"expression": "3**x", "label": "y=3ˣ"},
                {"expression": "0.5**x", "label": "y=(½)ˣ"},
            ],
            "annotations": [
                {"x": 0, "y": 1, "label": "(0,1)"},
            ],
        }]
    },
    # 对数函数底数对比 y=log_a x
    67: {
        "template": "function_comparison", "renderer_version": 1, "spec_version": 1,
        "title": "对数函数底数对比 y=logₐx",
        "panels": [{
            "x_range": [0, 4], "y_range": [-3, 3],
            "axis_mode": "manual", "expressions": [
                {"expression": "ln(x)", "label": "y=ln x",
                 "domain": {"intervals": [[0.01, 4]]}},
                {"expression": "ln(x)/ln(2)", "label": "y=log₂x",
                 "domain": {"intervals": [[0.01, 4]]}},
                {"expression": "ln(x)/ln(0.5)", "label": "y=log_{½}x",
                 "domain": {"intervals": [[0.01, 4]]}},
            ],
            "annotations": [
                {"x": 1, "y": 0, "label": "(1,0)"},
            ],
            "vertical_lines": [{"value": 0, "style": "dotted"}],
        }]
    },
    # y=sin x
    69: {
        "template": "single_function", "renderer_version": 1, "spec_version": 1,
        "title": "y=sin x",
        "panels": [{
            "x_range": [-2*PI, 2*PI], "y_range": [-1.5, 1.5],
            "axis_mode": "manual", "expressions": [
                {"expression": "sin(x)", "label": "y=sin x"},
            ],
            "annotations": [
                {"x": 0, "y": 0, "label": "(0,0)"},
                {"x": PI/2, "y": 1, "label": "(π/2,1)"},
                {"x": PI, "y": 0, "label": "(π,0)"},
            ],
        }]
    },
    # y=tan x
    72: {
        "template": "single_function", "renderer_version": 1, "spec_version": 1,
        "title": "y=tan x",
        "panels": [{
            "x_range": [-2*PI, 2*PI], "y_range": [-5, 5],
            "axis_mode": "manual", "expressions": [
                {"expression": "tan(x)", "label": "y=tan x",
                 "domain": {"intervals": [[-2*PI, -3*PI/2-0.05], [-3*PI/2+0.05, -PI/2-0.05],
                                           [-PI/2+0.05, PI/2-0.05], [PI/2+0.05, 3*PI/2-0.05],
                                           [3*PI/2+0.05, 2*PI]]}},
            ],
            "vertical_lines": [
                {"value": -3*PI/2, "style": "dashed", "label": ""},
                {"value": -PI/2, "style": "dashed", "label": ""},
                {"value": PI/2, "style": "dashed", "label": ""},
                {"value": 3*PI/2, "style": "dashed", "label": ""},
            ],
        }]
    },
    # 绝对值变换对比 y=|f(x)| 与 y=f(|x|)
    85: {
        "template": "function_comparison", "renderer_version": 1, "spec_version": 1,
        "title": "绝对值变换对比",
        "panels": [{
            "x_range": [-3, 3], "y_range": [-1, 5],
            "axis_mode": "manual", "expressions": [
                {"expression": "x**2-1", "label": "f(x)=x²-1"},
                {"expression": "abs(x**2-1)", "label": "y=|f(x)|"},
                {"expression": "(abs(x))**2 - 1", "label": "y=f(|x|)"},
            ],
            "annotations": [
                {"x": 0, "y": -1, "label": "(0,-1)"},
                {"x": -1, "y": 0, "label": "(-1,0)"},
                {"x": 1, "y": 0, "label": "(1,0)"},
            ],
        }]
    },
    # 分段函数：sgn x 与 [x]
    89: {
        "template": "function_comparison", "renderer_version": 1, "spec_version": 1,
        "title": "分段函数典型图像",
        "panels": [{
            "x_range": [-3, 3], "y_range": [-3, 3],
            "axis_mode": "manual", "expressions": [
                {"expression": "sign(x)", "label": "y=sgn x"},
                {"expression": "floor(x)", "label": "y=[x]"},
            ],
            "annotations": [
                {"x": 0, "y": 0, "label": "原点"},
            ],
        }]
    },
}

# Cards with existing graph_specs that need cross-axis + regeneration
EXISTING_SPEC_CARDS = [63, 64, 65, 82, 83, 84, 88, 90, 91, 92]

# Cards that need brand-new specs
NEW_SPEC_CARDS = [59, 60, 61, 62, 66, 67, 69, 72, 85, 89]

ALL_CARDS = sorted(NEW_SPEC_CARDS + EXISTING_SPEC_CARDS)


def _spec_checksum(spec: dict) -> str:
    raw = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


async def render_and_store(db, card: FormulaCard, spec: dict, dry_run: bool = False) -> dict:
    """Render a graph_spec and store it as the card's generated asset."""
    cid = card.id
    result = {"id": cid, "title": card.title, "status": "skip", "reason": ""}

    checksum = _spec_checksum(spec)

    if dry_run:
        template = spec.get("template", "?")
        n_panels = len(spec.get("panels", []))
        result["status"] = "dry_run"
        result["reason"] = f"template={template} panels={n_panels}"
        return result

    card.graph_spec = spec
    card.draft_graph_spec = spec
    card.graph_status = "generating"
    card.graph_last_error = None
    await db.flush()

    try:
        png_bytes, render_meta = await render_spec(spec, timeout=30)
    except Exception as e:
        card.graph_status = "failed"
        card.graph_last_error = f"render error: {e}"
        await db.flush()
        result["status"] = "fail"
        result["reason"] = f"render failed: {e}"
        return result

    # Thumbnail
    thumb_bytes = _resize_to_canvas(png_bytes, THUMBNAIL_SIZE[0], THUMBNAIL_SIZE[1])

    # Upload
    storage = get_storage()
    main_path = _storage_path(cid, "generated", checksum)
    thumb_path = _storage_path(cid, "generated", checksum, "-thumb")
    try:
        image_url = await storage.upload(main_path, png_bytes)
        thumbnail_url = await storage.upload(thumb_path, thumb_bytes)
    except Exception as e:
        card.graph_status = "failed"
        card.graph_last_error = f"upload error: {e}"
        await db.flush()
        result["status"] = "fail"
        result["reason"] = f"upload failed: {e}"
        return result

    # Delete old asset
    r = await db.execute(
        select(FormulaGraphAsset).where(
            FormulaGraphAsset.formula_card_id == cid,
            FormulaGraphAsset.source_type == "generated",
        )
    )
    old_asset = r.scalar_one_or_none()
    if old_asset:
        _safe_delete_file_later(old_asset.image_url)
        _safe_delete_file_later(old_asset.thumbnail_url)
        await db.delete(old_asset)
        await db.flush()

    # Create asset
    now = datetime.now(timezone.utc)
    asset = FormulaGraphAsset(
        formula_card_id=cid, source_type="generated",
        image_url=image_url, thumbnail_url=thumbnail_url,
        mime_type="image/png",
        width=render_meta.get("width", 1600), height=render_meta.get("height", 1000),
        file_size=len(png_bytes), checksum=checksum,
        renderer_version=RENDERER_VERSION,
        reviewed_by=1, reviewed_at=now, published_version=card.version,
        alt_text=f"{card.title} 的函数图像",
    )
    db.add(asset)
    await db.flush()

    # Update card
    card.graph_spec = spec
    card.draft_graph_spec = None
    card.graph_status = "ready"
    card.graph_last_error = None
    card.graph_generated_at = now
    card.graph_confirmed_at = now

    # Clean previews
    r2 = await db.execute(
        select(FormulaGraphPreview).where(FormulaGraphPreview.formula_card_id == cid)
    )
    for prev in r2.scalars().all():
        await db.delete(prev)

    result["status"] = "ok"
    result["reason"] = f"asset={asset.id} size={len(png_bytes)}"
    return result


def add_cross_axis_patch(spec: dict) -> dict:
    """Add axis_style='cross' to all panels in a spec (mutates and returns)."""
    for p in spec.get("panels", []):
        p["axis_style"] = "cross"
        p["x_label"] = ""
        p["y_label"] = ""
    return spec


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch convert all function_graph cards to cross-axis")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    await init_db()

    executors = init_executors_for_role(
        role=os.environ.get("APP_ROLE", "api"), is_production=False,
    )
    init_executor_registry(executors)

    print(f"Processing {len(ALL_CARDS)} cards (dry_run={args.dry_run})...\n")

    async with async_session() as db:
        async with db.begin():
            for cid in ALL_CARDS:
                r = await db.execute(
                    select(FormulaCard).where(
                        FormulaCard.id == cid, FormulaCard.deleted_at.is_(None),
                    )
                )
                card = r.scalar_one_or_none()
                if not card:
                    print(f"  [{cid:>3}] SKIP — not found")
                    continue

                cat = "new" if cid in NEW_SPEC_CARDS else "existing"

                if cid in NEW_SPEC_CARDS:
                    spec = DEFAULT_SPECS[cid]
                else:
                    spec = card.graph_spec
                    if not spec:
                        print(f"  [{cid:>3}] SKIP — existing card has no graph_spec")
                        continue

                add_cross_axis_patch(spec)

                res = await render_and_store(db, card, spec, dry_run=args.dry_run)

                status_icon = {"ok": "OK", "fail": "FAIL", "skip": "SKIP", "dry_run": "DRY"}.get(res["status"], "?")
                title = res.get("title", "?")
                print(f"  [{cid:>3}] {status_icon} [{cat:<8}] {title[:35]:35s} — {res['reason']}")

    if args.dry_run:
        print(f"\nRun without --dry-run to execute.")
    else:
        print(f"\nDone.")

    from app.services.formula_graph_spec_renderer import shutdown_formula_render_pool
    shutdown_formula_render_pool(wait=True)


if __name__ == "__main__":
    asyncio.run(main())
