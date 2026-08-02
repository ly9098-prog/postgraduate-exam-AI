#!/usr/bin/env python3
"""Publish the zhangyu nonprob draft formula cards on the target database.

Applies the documented review state machine via the app's own
``_apply_formula_action`` / ``_create_version_snapshot``:

    draft →approve→ pending_review →approve→ published

Each transition bumps the card version and records an ``approve`` version
snapshot (mirroring the admin review endpoint). Attribution uses admin id 1.

Works against whichever DB ``DATABASE_URL`` resolves to — local SQLite in dev,
production PostgreSQL when run inside the app container.

Usage:
    python scripts/publish_zhangyu_nonprob_formulas.py            # dry-run
    python scripts/publish_zhangyu_nonprob_formulas.py --apply    # publish
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import async_session
from app.core.time_utils import utcnow
from app.models.formula import FormulaCard
from app.api.v1.admin_formulas import (
    _apply_formula_action,
    _create_version_snapshot,
)

PREFIX = "zhangyu_formula_manual:nonprob:"
ADMIN_ID = 1


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually publish")
    args = parser.parse_args()

    async with async_session() as db:
        # _create_version_snapshot internally awaits DB queries; after a sync
        # _apply_formula_action mutation the autoflush at that await fails in
        # aiosqlite's greenlet context. Disable autoflush; the explicit commit
        # at the end flushes card UPDATEs + version INSERTs in one batch.
        db.autoflush = False
        result = await db.execute(
            select(FormulaCard).where(
                FormulaCard.source_ref.like(PREFIX + "%"),
                FormulaCard.deleted_at.is_(None),
            ).order_by(FormulaCard.id)
        )
        cards = result.scalars().all()
        print(f"Found {len(cards)} nonprob cards")

        stats = {"published": 0, "already_published": 0, "failed": 0}
        now = utcnow()
        for card in cards:
            if card.status == "published":
                stats["already_published"] += 1
                continue
            if not args.apply:
                stats["published"] += 1
                continue
            try:
                # draft → pending_review
                _apply_formula_action(card, "approve", ADMIN_ID, now=now)
                await _create_version_snapshot(db, card, "approve", ADMIN_ID)
                # pending_review → published
                _apply_formula_action(card, "approve", ADMIN_ID, now=now)
                await _create_version_snapshot(db, card, "approve", ADMIN_ID)
                stats["published"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["failed"] += 1
                print(f"  FAILED card {card.id} {card.title}: {exc}")

        if args.apply:
            await db.commit()

    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"  published: {stats['published']}")
    print(f"  already_published: {stats['already_published']}")
    print(f"  failed: {stats['failed']}")


if __name__ == "__main__":
    asyncio.run(main())
