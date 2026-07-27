#!/usr/bin/env python3
"""Batch convert all function-graph cards to cross-axis style (axis_style: 'cross')."""
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

# Cards to convert — all have origin inside visible range and single-axis layout
CARD_IDS = [
    58,   # 常数函数 y=C
    68,   # 指数函数与对数函数反函数关系
    70,   # y=cos x
    71,   # 正弦与余弦对比
    73,   # y=cot x
    74,   # 正切与余切对比
    75,   # y=sec x, y=csc x
    76,   # y=arcsin x
    77,   # y=arccos x
    78,   # y=arctan x
    79,   # y=arccot x
    80,   # y=x+1/x
    81,   # y=xe^{-x} 与 y=x^n e^{-x}
    86,   # 原函数与导函数图像关系
    87,   # 常见有理函数及其渐近线
]

SPEC_VERSION = 2


def _spec_checksum(spec: dict) -> str:
    raw = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


async def convert_card(db, card: FormulaCard, dry_run: bool = False) -> dict:
    """Convert a single card's graph to cross-axis style."""
    cid = card.id
    result = {"id": cid, "title": card.title, "status": "skip", "reason": ""}

    if not card.graph_spec:
        result["reason"] = "no graph_spec"
        return result

    spec = card.graph_spec
    if not isinstance(spec, dict):
        try:
            spec = json.loads(spec) if isinstance(spec, str) else {}
        except Exception:
            result["reason"] = "invalid graph_spec JSON"
            return result

    panels = spec.get("panels", [])
    if not panels:
        result["reason"] = "no panels"
        return result

    # Check if already cross-axis
    already_cross = all(p.get("axis_style") == "cross" for p in panels)
    if already_cross:
        result["status"] = "skip"
        result["reason"] = "already cross-axis"
        return result

    # Add axis_style: "cross" to every panel
    for p in panels:
        p["axis_style"] = "cross"
        # Suppress default axis labels — renderer handles them
        p["x_label"] = ""
        p["y_label"] = ""

    spec["spec_version"] = SPEC_VERSION

    if dry_run:
        result["status"] = "dry_run"
        result["reason"] = f"would convert ({len(panels)} panels)"
        return result

    # Update spec in DB
    card.graph_spec = spec
    card.draft_graph_spec = spec
    card.graph_status = "generating"
    card.graph_last_error = None
    await db.flush()

    # Render
    checksum = _spec_checksum(spec)
    try:
        png_bytes, render_meta = await render_spec(spec, timeout=30)
    except Exception as e:
        card.graph_status = "failed"
        card.graph_last_error = f"render error: {e}"
        await db.flush()
        result["status"] = "fail"
        result["reason"] = f"render failed: {e}"
        return result

    # Create thumbnail
    thumb_bytes = _resize_to_canvas(png_bytes, THUMBNAIL_SIZE[0], THUMBNAIL_SIZE[1])

    # Storage
    storage = get_storage()
    main_path = _storage_path(cid, "generated", checksum)
    thumb_path = _storage_path(cid, "generated", checksum, "-thumb")

    try:
        image_url = await storage.upload(main_path, png_bytes)
        thumbnail_url = await storage.upload(thumb_path, thumb_bytes)
    except Exception as e:
        card.graph_status = "failed"
        card.graph_last_error = f"storage upload error: {e}"
        await db.flush()
        result["status"] = "fail"
        result["reason"] = f"upload failed: {e}"
        return result

    # Delete old generated asset
    r = await db.execute(
        select(FormulaGraphAsset).where(
            FormulaGraphAsset.formula_card_id == cid,
            FormulaGraphAsset.source_type == "generated",
        )
    )
    old_asset = r.scalar_one_or_none()
    if old_asset:
        old_image_url = old_asset.image_url
        old_thumbnail = old_asset.thumbnail_url
        await db.delete(old_asset)
        await db.flush()
        _safe_delete_file_later(old_image_url)
        _safe_delete_file_later(old_thumbnail)

    # Create new asset
    now = datetime.now(timezone.utc)
    asset = FormulaGraphAsset(
        formula_card_id=cid,
        source_type="generated",
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        mime_type="image/png",
        width=render_meta.get("width", 1600),
        height=render_meta.get("height", 1000),
        file_size=len(png_bytes),
        checksum=checksum,
        renderer_version=RENDERER_VERSION,
        reviewed_by=1,
        reviewed_at=now,
        published_version=card.version,
        alt_text=f"{card.title} 的函数图像",
    )
    db.add(asset)
    await db.flush()

    # Update card
    card.graph_spec = card.draft_graph_spec
    card.draft_graph_spec = None
    card.graph_status = "ready"
    card.graph_last_error = None
    card.graph_generated_at = now
    card.graph_confirmed_at = now

    # Delete any old previews
    r2 = await db.execute(
        select(FormulaGraphPreview).where(
            FormulaGraphPreview.formula_card_id == cid,
        )
    )
    for prev in r2.scalars().all():
        await db.delete(prev)

    result["status"] = "ok"
    result["reason"] = f"asset_id={asset.id} size={len(png_bytes)}"
    return result


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch convert function graphs to cross-axis")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be converted")
    parser.add_argument("--ids", type=str, help="Comma-separated subset of card IDs")
    args = parser.parse_args()

    await init_db()

    executors = init_executors_for_role(
        role=os.environ.get("APP_ROLE", "api"),
        is_production=False,
    )
    init_executor_registry(executors)

    card_ids = [int(x.strip()) for x in args.ids.split(",")] if args.ids else CARD_IDS

    print(f"Converting {len(card_ids)} cards (dry_run={args.dry_run})...\n")

    async with async_session() as db:
        async with db.begin():
            for cid in card_ids:
                r = await db.execute(
                    select(FormulaCard).where(
                        FormulaCard.id == cid,
                        FormulaCard.deleted_at.is_(None),
                    )
                )
                card = r.scalar_one_or_none()
                if not card:
                    print(f"  [{cid:>3}] SKIP — not found")
                    continue

                res = await convert_card(db, card, dry_run=args.dry_run)
                status = res["status"]
                reason = res["reason"]
                title = res.get("title", "?")
                icon = {"ok": "OK", "fail": "FAIL", "skip": "SKIP", "dry_run": "DRY"}.get(status, "?")
                print(f"  [{cid:>3}] {icon} {title[:35]:35s} — {reason}")

            if args.dry_run:
                print(f"\nRun without --dry-run to execute.")
            else:
                print(f"\nDone. Some cards may need manual review.")

    # Shutdown render pool
    from app.services.formula_graph_spec_renderer import shutdown_formula_render_pool
    shutdown_formula_render_pool(wait=True)


if __name__ == "__main__":
    asyncio.run(main())
