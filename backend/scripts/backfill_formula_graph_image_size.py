#!/usr/bin/env python3
"""Backfill: recompress existing formula graph assets in local storage.

Older uploads stored the original-resolution PNG (up to 8000x8000) without
optimization, which is the main cause of slow graph rendering in the
miniprogram. This script rewrites oversized main images and thumbnails in
place (same object key) using the same compression rules as the upload path
(max dimension 1600, PNG optimize), and updates DB width/height/file_size.

Only meaningful for STORAGE_BACKEND=local. External object storage (COS/CDN)
is left untouched. Re-runnable: already-compressed files are skipped.

Usage (inside backend dir, against the target environment's DB):
    python scripts/backfill_formula_graph_image_size.py --dry-run
    python scripts/backfill_formula_graph_image_size.py --apply
"""

import argparse
import asyncio
import os
import sys
from io import BytesIO
from urllib.parse import unquote, urlsplit

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.models.formula import FormulaGraphAsset
from app.services.formula_graph_asset_service import (
    MAX_STORED_DIMENSION,
    _encode_stored_image,
    _resize_within,
)


def _local_path_for(url: str) -> str | None:
    """Map a stored asset URL to its file path under local storage.

    URLs containing the ``/static/formulas/`` marker resolve to that object
    key regardless of host (upload-time rebasing may have used a stale
    PUBLIC_BASE_URL); the caller's file-existence check protects against
    phantom paths. Marker-less absolute URLs on another host are external
    storage and return None.
    """
    raw = str(url or "").strip()
    if not raw:
        return None

    path = None
    marker = "/static/formulas/"
    if raw.startswith("static/formulas/"):
        path = raw
    elif marker in raw:
        path = marker.lstrip("/") + raw.split(marker, 1)[1].lstrip("/")

    if path is None:
        parsed = urlsplit(raw)
        if parsed.scheme and parsed.netloc:
            base_host = (
                urlsplit(str(settings.PUBLIC_BASE_URL or "")).hostname or ""
            ).lower()
            if (parsed.hostname or "").lower() != base_host:
                return None
        path = parsed.path.lstrip("/") if parsed.path else None

    if not path:
        return None

    rel = unquote(path.split("static/formulas/", 1)[1])
    abs_path = os.path.normpath(os.path.join("static", "formulas", rel))
    if not abs_path.startswith(os.path.normpath("static/formulas/")):
        return None
    return abs_path


def _recompress(abs_path: str) -> tuple[bool, int, int, int]:
    """Rewrite one file in place. Returns (changed, width, height, size)."""
    with open(abs_path, "rb") as f:
        data = f.read()

    img = Image.open(BytesIO(data))
    img.load()
    width, height = img.size

    target = _resize_within(img, MAX_STORED_DIMENSION)
    optimized = _encode_stored_image(target)
    if optimized == data or len(optimized) >= len(data):
        # Already smaller or equal → keep the original bytes.
        return False, width, height, len(data)

    with open(abs_path, "wb") as f:
        f.write(optimized)
    return True, target.width, target.height, len(optimized)


async def run(apply: bool) -> int:
    result = await async_session()
    try:
        assets = (
            (
                await result.execute(
                    select(FormulaGraphAsset).where(
                        FormulaGraphAsset.image_url.isnot(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        scanned = changed = skipped_missing = 0
        total_before = total_after = 0
        for asset in assets:
            for url, kind in (
                (asset.image_url, "main"),
                (asset.thumbnail_url, "thumb"),
            ):
                abs_path = _local_path_for(url)
                if not abs_path or not os.path.exists(abs_path):
                    if url:
                        skipped_missing += 1
                    continue
                scanned += 1
                before = os.path.getsize(abs_path)
                if apply:
                    changed_flag, width, height, after = _recompress(abs_path)
                    if changed_flag:
                        changed += 1
                        total_before += before
                        total_after += after
                        if kind == "main":
                            asset.width = width
                            asset.height = height
                            asset.file_size = after
                else:
                    img = Image.open(abs_path)
                    needs = max(img.size) > MAX_STORED_DIMENSION
                    print(
                        f"[dry-run] {abs_path}: {img.size[0]}x{img.size[1]}, "
                        f"{before / 1024:.0f} KB"
                        + (" → needs recompress" if needs else "")
                    )
                    total_before += before

        if apply:
            await result.commit()
        print()
        print(
            f"mode={'apply' if apply else 'dry-run'} "
            f"files_scanned={scanned} files_recompressed={changed if apply else 'n/a'} "
            f"missing_files={skipped_missing}"
        )
        if apply:
            print(
                f"bytes: {total_before / 1024 / 1024:.1f} MB → {total_after / 1024 / 1024:.1f} MB"
            )
        return 0
    finally:
        await result.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview without writing")
    group.add_argument(
        "--apply", action="store_true", help="Rewrite oversized files in place"
    )
    args = parser.parse_args()
    return asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
