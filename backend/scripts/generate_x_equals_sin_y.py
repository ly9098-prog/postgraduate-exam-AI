#!/usr/bin/env python3
"""Generate x=sin y function graph for card 201.

Idempotent: same spec checksum → skip.

Usage:
    python scripts/generate_x_equals_sin_y.py              # dry-run
    python scripts/generate_x_equals_sin_y.py --generate   # generate preview
    python scripts/generate_x_equals_sin_y.py --confirm    # confirm preview
"""
import argparse
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
from app.models.formula import FormulaCard, FormulaGraphSpec, FormulaGraphPreview, FormulaGraphAsset
from app.services.formula_graph_spec_service import generate_preview, confirm_preview

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PI = 3.141592653589793

X_SIN_Y_SPEC = {
    "template": "single_function",
    "renderer_version": 1,
    "spec_version": 2,
    "title": r"$x=\sin y,\quad 0\leq y\leq 2\pi$",
    "panels": [
        {
            "x_range": [-1.35, 1.35],
            "y_range": [-0.28, 6.663185307179586],
            "axis_mode": "manual",
            "axis_style": "cross",
            "show_legend": False,
            "x_label": "",
            "y_label": "",
            "x_ticks": [-1, 0, 1],
            "x_tick_labels": ["-1", "", "1"],
            "y_ticks": [
                0,
                1.5707963267948966,
                3.141592653589793,
                4.71238898038469,
                6.283185307179586,
            ],
            "y_tick_labels": [
                "",
                r"$\frac{\pi}{2}$",
                r"$\pi$",
                r"$\frac{3\pi}{2}$",
                r"$2\pi$",
            ],
            "expressions": [
                {
                    "expression": "asin(x)",
                    "label": "y=arcsin x",
                    "domain": {
                        "intervals": [[0, 1]],
                        "exclude_points": [],
                    },
                },
                {
                    "expression": "pi-asin(x)",
                    "label": "y=π-arcsin x",
                    "domain": {
                        "intervals": [[-1, 1]],
                        "exclude_points": [],
                    },
                },
                {
                    "expression": "2*pi+asin(x)",
                    "label": "y=2π+arcsin x",
                    "domain": {
                        "intervals": [[-1, 0]],
                        "exclude_points": [],
                    },
                },
            ],
            "annotations": [
                {
                    "type": "label",
                    "x": 1.39,
                    "y": -0.08,
                    "label": "x",
                    "fontsize": 14,
                    "color": "#333333",
                    "ha": "left",
                    "va": "top",
                },
                {
                    "type": "label",
                    "x": 0.04,
                    "y": 6.693185307179586,
                    "label": "y",
                    "fontsize": 14,
                    "color": "#333333",
                    "ha": "left",
                    "va": "bottom",
                },
                {
                    "type": "label",
                    "x": 0,
                    "y": 0,
                    "label": "O",
                    "fontsize": 13,
                    "color": "#333333",
                    "ha": "right",
                    "va": "top",
                    "offset": [-10, -12],
                },
                {"x": 1, "y": 1.5707963267948966, "label": r"$(1,\frac{\pi}{2})$"},
                {"x": 0, "y": 3.141592653589793, "label": r"$(0,\pi)$"},
                {"x": -1, "y": 4.71238898038469, "label": r"$(-1,\frac{3\pi}{2})$"},
                {"x": 0, "y": 6.283185307179586, "label": r"$(0,2\pi)$"},
            ],
        }
    ],
}


def _spec_checksum(spec: dict) -> str:
    raw = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


async def main():
    parser = argparse.ArgumentParser(description="Generate x=sin y graph")
    parser.add_argument("--generate", action="store_true", help="Generate preview")
    parser.add_argument("--confirm", action="store_true", help="Confirm preview")
    args = parser.parse_args()

    spec = X_SIN_Y_SPEC
    checksum = _spec_checksum(spec)

    await init_db()

    # Initialize executor registry for image processing
    executors = init_executors_for_role(
        role=os.environ.get("APP_ROLE", "api"),
        is_production=False,
    )
    init_executor_registry(executors)

    print(f"Spec checksum: {checksum[:16]}...")

    async with async_session() as db:
        async with db.begin():
            # Find card by source_ref
            r = await db.execute(
                select(FormulaCard).where(
                    FormulaCard.source_ref == "math2_manual:function:x_equals_sin_y_branches",
                    FormulaCard.deleted_at.is_(None),
                )
            )
            card = r.scalar_one_or_none()
            if not card:
                print("ERROR: Card not found!")
                return

            card_id = card.id
            print(f"Card: ID={card_id} title={card.title}")
            print(f"Current graph_status: {card.graph_status}")

            if not args.generate and not args.confirm:
                print("DRY RUN: would generate preview and confirm")
                print(f"  graph_spec: {json.dumps(spec, ensure_ascii=False)[:100]}...")
                return

            # Update card's graph_spec and set generating status
            card.graph_spec = spec
            card.draft_graph_spec = spec
            card.graph_status = "draft"
            card.graph_last_error = None
            await db.flush()

            if args.generate:
                print("\nGenerating preview...")
                try:
                    result = await generate_preview(db, card, spec, admin_id=1)
                    token = result.get("preview_token", "?")[:12]
                    print(f"  OK preview_token={token}...")
                except ValueError as e:
                    print(f"  FAIL: {e}")
                    return

            if args.confirm:
                print("\nConfirming preview...")
                # Find the latest preview
                r2 = await db.execute(
                    select(FormulaGraphPreview).where(
                        FormulaGraphPreview.formula_card_id == card.id,
                    ).order_by(FormulaGraphPreview.created_at.desc())
                )
                preview = r2.scalar_one_or_none()
                if not preview:
                    print("  FAIL: no preview found")
                    return

                if not preview.preview_url:
                    print("  FAIL: preview has no image url")
                    return

                # Store the preview files as generated asset
                from app.services.formula_graph_spec_service import (
                    _safe_delete_file_later, _storage_path,
                )
                from app.services.storage_backend import get_storage
                from app.services.formula_graph_spec_renderer import RENDERER_VERSION

                try:
                    storage = get_storage()
                    checksum = preview.checksum
                    main_path = _storage_path(card.id, "generated", checksum)
                    thumb_path = _storage_path(card.id, "generated", checksum, "-thumb")

                    # Read preview files synchronously
                    from app.core.config import settings

                    def _read_local_file(file_url):
                        prefix = f"{settings.PUBLIC_BASE_URL}/static/formulas/"
                        if not file_url or not file_url.startswith(prefix):
                            return None
                        rel = file_url[len(prefix):]
                        abs_path = os.path.normpath(os.path.join("static/formulas", rel))
                        if not abs_path.startswith(os.path.normpath("static/formulas/")):
                            return None
                        try:
                            with open(abs_path, "rb") as f:
                                return f.read()
                        except FileNotFoundError:
                            return None

                    loop = asyncio.get_running_loop()
                    preview_data = await loop.run_in_executor(None, _read_local_file, preview.preview_url)
                    thumb_data = await loop.run_in_executor(None, _read_local_file, preview.thumbnail_url)

                    if preview_data is None:
                        print(f"  FAIL: cannot read preview file: {preview.preview_url}")
                        return

                    new_image_url = await storage.upload(main_path, preview_data)
                    new_thumbnail_url = (await storage.upload(thumb_path, thumb_data)
                                         if thumb_data else preview.thumbnail_url or "")

                    # Delete old generated asset if exists
                    r3 = await db.execute(
                        select(FormulaGraphAsset).where(
                            FormulaGraphAsset.formula_card_id == card.id,
                            FormulaGraphAsset.source_type == "generated",
                        )
                    )
                    old_asset = r3.scalar_one_or_none()
                    if old_asset:
                        old_image_url = old_asset.image_url
                        old_thumbnail = old_asset.thumbnail_url
                        await db.delete(old_asset)
                        await db.flush()
                        _safe_delete_file_later(old_image_url)
                        _safe_delete_file_later(old_thumbnail)

                    now = datetime.now(timezone.utc)
                    asset = FormulaGraphAsset(
                        formula_card_id=card.id,
                        source_type="generated",
                        image_url=new_image_url,
                        thumbnail_url=new_thumbnail_url,
                        mime_type=preview.mime_type or "image/png",
                        width=preview.width,
                        height=preview.height,
                        file_size=preview.file_size,
                        checksum=checksum,
                        renderer_version=RENDERER_VERSION,
                        reviewed_by=1,
                        reviewed_at=now,
                        published_version=card.version,
                        alt_text="关系 x=sin y 在 0≤y≤2π 上的图像，由三个反正弦分支组成",
                        description="横轴为 x，纵轴为 y。曲线依次经过 (0,0)、(1,π/2)、(0,π)、(-1,3π/2)、(0,2π)，表示关系 x=sin y 在一个完整周期内的三个反正弦分支。",
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

                    # Delete preview record
                    await db.delete(preview)
                    await db.flush()

                    print(f"  OK asset_id={asset.id} confirmed")
                    print(f"  image_url: {asset.image_url}")
                    print(f"  thumbnail_url: {asset.thumbnail_url}")

                except Exception as e:
                    print(f"  FAIL: {e}")
                    import traceback
                    traceback.print_exc()

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
