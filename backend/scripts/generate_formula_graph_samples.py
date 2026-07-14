"""
generate_formula_graph_samples — Generate 10 test function graph images
and bind them to existing formula cards.

Usage:
    python scripts/generate_formula_graph_samples.py          # dry-run (default)
    python scripts/generate_formula_graph_samples.py --apply  # write to DB
    python scripts/generate_formula_graph_samples.py --apply --only H-002,H-003

Idempotent: same checksum → skip.
Does NOT modify FormulaCard content or status.
Does NOT create new FormulaCard records.
"""

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from io import BytesIO

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import init_db, async_session
from app.models.formula import FormulaCard, FormulaGraphAsset
from app.services.formula_graph_renderer import render_formula_graph
from app.services.storage_backend import get_storage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Card definitions → renderer parameters
# ═══════════════════════════════════════════════════════════════

CardDef = dict  # type alias

CARDS: list[CardDef] = [
    {
        "source_ref": "H-002",
        "title_match": "一次函数",
        "curves": [
            {"template_type": "linear", "parameters": {"k": 1, "b": 0}, "label": "y=x"},
        ],
        "viewport": {"x_min": -6, "x_max": 6, "y_min": -6, "y_max": 6},
    },
    {
        "source_ref": "H-003",
        "title_match": "二次函数",
        "curves": [
            {"template_type": "quadratic", "parameters": {"a": 1, "h": 0, "k": 0}, "label": "y=x²"},
        ],
        "viewport": {"x_min": -6, "x_max": 6, "y_min": -6, "y_max": 6},
    },
    {
        "source_ref": "H-004",
        "title_match": "y=|x|",
        "curves": [
            {"template_type": "abs", "parameters": {"a": 1, "h": 0, "k": 0}, "label": "y=|x|"},
        ],
        "viewport": {"x_min": -5, "x_max": 5, "y_min": 0, "y_max": 5},
    },
    {
        "source_ref": "H-005",
        "title_match": "y=1/x",
        "curves": [
            {"template_type": "reciprocal", "parameters": {"a": 1, "h": 0, "k": 0}, "label": "y=1/x"},
            {"template_type": "reciprocal_sq", "parameters": {"a": 1, "h": 0, "k": 0}, "label": "y=1/x²"},
        ],
        "viewport": {"x_min": -4, "x_max": 4, "y_min": -4, "y_max": 4},
        "annotations": [
            {"type": "asymptote", "x": 0},
            {"type": "asymptote", "y": 0},
        ],
    },
    {
        "source_ref": "H-009",
        "title_match": "指数函数",
        "curves": [
            {"template_type": "exp", "parameters": {"a": 1, "b": 2, "k": 0}, "label": "y=2ˣ"},
            {"template_type": "exp", "parameters": {"a": 1, "b": 0.5, "k": 0}, "label": "y=(½)ˣ"},
        ],
        "viewport": {"x_min": -3, "x_max": 3, "y_min": 0, "y_max": 6},
        "annotations": [
            {"type": "point", "x": 0, "y": 1, "label": "(0,1)"},
        ],
    },
    {
        "source_ref": "H-010",
        "title_match": "对数函数",
        "curves": [
            {"template_type": "log", "parameters": {"a": 1, "b": 2, "k": 0}, "label": "y=log₂x"},
            {"template_type": "log", "parameters": {"a": 1, "b": 0.5, "k": 0}, "label": "y=log_(½)x"},
        ],
        "viewport": {"x_min": 0.1, "x_max": 4, "y_min": -3, "y_max": 3},
        "annotations": [
            {"type": "point", "x": 1, "y": 0, "label": "(1,0)"},
            {"type": "asymptote", "x": 0},
        ],
    },
    {
        "source_ref": "H-012",
        "title_match": "y=sin x",
        "curves": [
            {"template_type": "sine", "parameters": {"a": 1, "freq": 1, "phase": 0, "d": 0}, "label": "y=sin x"},
        ],
        "viewport": {"x_min": -6.2832, "x_max": 6.2832, "y_min": -1.5, "y_max": 1.5},
    },
    {
        "source_ref": "H-015",
        "title_match": "y=tan x",
        "curves": [
            {"template_type": "tangent", "parameters": {"a": 1, "freq": 1, "c": 0, "d": 0}, "label": "y=tan x"},
        ],
        "viewport": {"x_min": -3.1416, "x_max": 3.1416, "y_min": -4, "y_max": 4},
        "annotations": [
            {"type": "asymptote", "x": -1.5708},
            {"type": "asymptote", "x": 1.5708},
        ],
    },
    {
        "source_ref": "H-028",
        "title_match": "绝对值变换",
        "curves": [
            {"template_type": "sample_quadratic", "parameters": {}, "label": "f(x)=x²+x-1"},
            {"template_type": "sample_quadratic_abs", "parameters": {}, "label": "|f(x)|"},
            {"template_type": "sample_quadratic_absx", "parameters": {}, "label": "f(|x|)"},
        ],
        "viewport": {"x_min": -3, "x_max": 3, "y_min": -2, "y_max": 5},
    },
    {
        "source_ref": "H-032",
        "title_match": "分段函数",
        "curves": [
            {"template_type": "piecewise_sign", "parameters": {}, "label": "sgn x"},
            {"template_type": "piecewise_floor", "parameters": {}, "label": "floor x"},
        ],
        "viewport": {"x_min": -4, "x_max": 4, "y_min": -2, "y_max": 4},
    },
]


def generate_image_bytes(card_def: CardDef) -> tuple[bytes, bytes]:
    """Generate main image and thumbnail. Returns (png_bytes, thumb_bytes)."""
    png = render_formula_graph(
        curves=card_def["curves"],
        viewport=card_def["viewport"],
        annotations=card_def.get("annotations"),
    )

    # Create thumbnail
    img = Image.open(BytesIO(png))
    thumb_buf = BytesIO()
    thumb = img.copy()
    thumb.thumbnail((600, 450), Image.LANCZOS)
    # Letterbox to 600x450
    from app.services.formula_graph_asset_service import _create_thumbnail
    thumb_bytes = _create_thumbnail(img)

    return png, thumb_bytes


async def find_card(db, source_ref: str, title_match: str) -> FormulaCard | None:
    """Find a FormulaCard by source_ref, then by title as fallback."""
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.source_ref == source_ref,
            FormulaCard.deleted_at.is_(None),
        )
    )
    cards = list(result.scalars().all())
    if len(cards) == 1:
        return cards[0]
    if len(cards) > 1:
        logger.warning("  AMBIGUOUS: %s → %d cards found, skipping", source_ref, len(cards))
        return None

    # Fallback: exact title match
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.title.ilike(f"%{title_match}%"),
            FormulaCard.deleted_at.is_(None),
        )
    )
    cards = list(result.scalars().all())
    if len(cards) == 1:
        return cards[0]
    if len(cards) > 1:
        logger.warning("  AMBIGUOUS (title): %s → %d cards, skipping", title_match, len(cards))
        return None

    logger.warning("  NOT FOUND: %s or title containing '%s'", source_ref, title_match)
    return None


async def ensure_template_asset(
    db,
    card: FormulaCard,
    card_def: CardDef,
    png_bytes: bytes,
    thumb_bytes: bytes,
    dry_run: bool,
) -> dict:
    """Create or update a template graph asset. Returns status dict."""
    checksum = hashlib.sha256(png_bytes).hexdigest()
    card_id = card.id

    # Check existing template asset
    result = await db.execute(
        select(FormulaGraphAsset).where(
            FormulaGraphAsset.formula_card_id == card_id,
            FormulaGraphAsset.source_type == "template",
        )
    )
    existing = result.scalar_one_or_none()

    if existing and existing.checksum == checksum:
        return {"status": "skipped", "reason": "same checksum", "asset_id": existing.id}

    if dry_run:
        return {"status": "would_create", "checksum": checksum[:12]}

    # Save files
    storage = get_storage()
    file_uuid = hashlib.sha256(f"{card_id}_template_{checksum}".encode()).hexdigest()[:16]
    asset_dir = f"graphs/{card_id}/template"
    main_filename = f"{asset_dir}/{file_uuid}.png"
    thumb_filename = f"{asset_dir}/{file_uuid}-thumb.png"

    image_url = await storage.upload(main_filename, png_bytes)
    thumbnail_url = await storage.upload(thumb_filename, thumb_bytes)

    # Re-read dimensions
    img = Image.open(BytesIO(png_bytes))
    width, height = img.size

    if existing:
        # Update
        existing.image_url = image_url
        existing.thumbnail_url = thumbnail_url
        existing.mime_type = "image/png"
        existing.width = width
        existing.height = height
        existing.checksum = checksum
        existing.template_type = card_def["curves"][0]["template_type"] if card_def["curves"] else None
        existing.template_parameters = card_def["curves"][0]["parameters"] if card_def["curves"] else None
        existing.viewport = card_def["viewport"]
        db.add(existing)
        await db.flush()
        return {"status": "updated", "asset_id": existing.id, "checksum": checksum[:12]}
    else:
        asset = FormulaGraphAsset(
            formula_card_id=card_id,
            source_type="template",
            template_type=card_def["curves"][0]["template_type"] if card_def["curves"] else None,
            template_parameters=card_def["curves"][0]["parameters"] if card_def["curves"] else None,
            viewport=card_def["viewport"],
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            mime_type="image/png",
            width=width,
            height=height,
            checksum=checksum,
        )
        db.add(asset)
        await db.flush()
        return {"status": "created", "asset_id": asset.id, "checksum": checksum[:12]}


async def main():
    parser = argparse.ArgumentParser(description="Generate 10 test function graph images")
    parser.add_argument("--apply", action="store_true", help="Write to database (default: dry-run)")
    parser.add_argument("--only", type=str, help="Comma-separated source_refs to process (e.g. H-002,H-003)")
    parser.add_argument("--disable-verify", action="store_true", help="Skip image content verification")
    args = parser.parse_args()

    dry_run = not args.apply
    only_refs = set(r.strip() for r in args.only.split(",")) if args.only else None

    cards_to_process = CARDS
    if only_refs:
        cards_to_process = [c for c in CARDS if c["source_ref"] in only_refs]
        found = {c["source_ref"] for c in cards_to_process}
        missing = only_refs - found
        if missing:
            logger.warning("Unknown source_refs: %s", missing)

    print(f"{'=' * 60}")
    print(f"Formula Graph Sample Generator")
    print(f"{'DRY RUN' if dry_run else 'APPLY'} — {len(cards_to_process)} cards")
    print(f"{'=' * 60}")
    print()

    await init_db()
    async with async_session() as db:
        stats = {
            "found": 0,
            "generated": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "failed": [],
        }

        for card_def in cards_to_process:
            ref = card_def["source_ref"]
            title = card_def["title_match"]
            print(f"[{ref}] {title}...")

            # Find card
            card = await find_card(db, ref, title)
            if not card:
                stats["failed"].append({"ref": ref, "reason": "not_found"})
                print(f"  FAIL: card not found")
                continue
            stats["found"] += 1

            # Generate images
            try:
                png_bytes, thumb_bytes = generate_image_bytes(card_def)
            except Exception as e:
                stats["failed"].append({"ref": ref, "reason": f"render_error: {e}"})
                print(f"  FAIL: render error: {e}")
                continue

            stats["generated"] += 1

            # Validate image
            if not args.disable_verify:
                try:
                    img = Image.open(BytesIO(png_bytes))
                    assert img.size == (1200, 900), f"size={img.size}"
                    assert img.format == "PNG"

                    thumb = Image.open(BytesIO(thumb_bytes))
                    assert thumb.size == (600, 450), f"thumb size={thumb.size}"

                    # Basic non-empty check
                    extrema = img.convert("L").getextrema()
                    if extrema == (255, 255):
                        stats["failed"].append({"ref": ref, "reason": "all_white"})
                        print(f"  FAIL: all-white image")
                        continue
                except AssertionError as e:
                    stats["failed"].append({"ref": ref, "reason": f"verify: {e}"})
                    print(f"  FAIL: verification: {e}")
                    continue

            # Save to DB or dry-run
            result = await ensure_template_asset(db, card, card_def, png_bytes, thumb_bytes, dry_run)
            status = result["status"]

            if status == "created":
                stats["created"] += 1
                print(f"  OK   created asset_id={result['asset_id']} cs={result['checksum']}")
            elif status == "updated":
                stats["updated"] += 1
                print(f"  OK   updated asset_id={result['asset_id']} cs={result['checksum']}")
            elif status == "skipped":
                stats["skipped"] += 1
                print(f"  SKIP same checksum, asset_id={result['asset_id']}")
            elif status == "would_create":
                print(f"  DRY  would create (cs={result['checksum']})")
                stats["skipped"] += 1  # count as skipped in dry-run

        if not dry_run:
            await db.commit()

    print(f"\n{'=' * 60}")
    print("Summary:")
    print(f"  Found cards:    {stats['found']}")
    print(f"  Generated:      {stats['generated']}")
    print(f"  Created assets: {stats['created']}")
    print(f"  Updated assets: {stats['updated']}")
    print(f"  Skipped:        {stats['skipped']}")
    print(f"  Failed:         {len(stats['failed'])}")
    for f in stats["failed"]:
        print(f"    - [{f['ref']}] {f['reason']}")
    if dry_run and stats["created"] == 0 and stats["updated"] == 0:
        print(f"\n  This was a DRY RUN. Run with --apply to write to database.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
