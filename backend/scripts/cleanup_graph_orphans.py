#!/usr/bin/env python3
"""Orphan graph file cleanup.

Scans the graph storage directory and removes files not referenced
by any FormulaGraphAsset or FormulaGraphPreview record.

Usage:
    python scripts/cleanup_graph_orphans.py --dry-run
    python scripts/cleanup_graph_orphans.py --apply
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from app.core.database import engine

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "formulas", "graphs")


async def find_orphans(dry_run: bool = True) -> list[str]:
    """Find orphaned graph files not referenced in the database."""
    if not os.path.isdir(STORAGE_DIR):
        print(f"Storage directory not found: {STORAGE_DIR}")
        return []

    async with engine.connect() as conn:
        # Collect all referenced URLs from assets and previews
        result = await conn.execute(text("""
            SELECT image_url FROM formula_graph_assets WHERE image_url IS NOT NULL
            UNION
            SELECT thumbnail_url FROM formula_graph_assets WHERE thumbnail_url IS NOT NULL
            UNION
            SELECT preview_url FROM formula_graph_previews WHERE preview_url IS NOT NULL
            UNION
            SELECT thumbnail_url FROM formula_graph_previews WHERE thumbnail_url IS NOT NULL
        """))
        referenced_urls = set(row[0] for row in result.fetchall())

    # Build set of expected relative paths from URLs
    prefix = "/static/formulas/"
    referenced_paths = set()
    for url in referenced_urls:
        if prefix in url:
            rel = url.split(prefix, 1)[1]
            abs_path = os.path.normpath(os.path.join(STORAGE_DIR, rel))
            if abs_path.startswith(os.path.normpath(STORAGE_DIR)):
                referenced_paths.add(abs_path)

    # Scan disk
    orphans = []
    for root, dirs, files in os.walk(STORAGE_DIR):
        for fname in files:
            fpath = os.path.join(root, fname)
            if fpath not in referenced_paths:
                orphans.append(fpath)

    return sorted(orphans)


async def main(dry_run: bool):
    print("=" * 60)
    print("Orphan Graph File Cleanup")
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")
    print("=" * 60)
    print(f"Storage: {STORAGE_DIR}")

    orphans = await find_orphans(dry_run)

    if not orphans:
        print("\n✓ No orphan files found.")
        return

    total_size = sum(os.path.getsize(f) for f in orphans if os.path.isfile(f))
    print(f"\nFound {len(orphans)} orphan file(s), {total_size / 1024:.1f} KB total\n")

    for f in orphans:
        size = os.path.getsize(f) if os.path.isfile(f) else 0
        print(f"  {f} ({size / 1024:.1f} KB)")
        if not dry_run:
            os.remove(f)
            print(f"    → deleted")

    if dry_run:
        print(f"\n⚠  DRY RUN — no files deleted. Re-run with --apply to execute.")
    else:
        print(f"\n✓ {len(orphans)} orphan file(s) deleted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean up orphaned graph files")
    parser.add_argument("--apply", action="store_true", help="Apply deletions (default: dry-run)")
    args = parser.parse_args()

    import asyncio
    asyncio.run(main(dry_run=not args.apply))
