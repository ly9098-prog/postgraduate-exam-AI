#!/usr/bin/env python3
"""Apply formula graph_specs from deployment JSON to production PostgreSQL.
Safe to run inside the app container:  docker compose exec -T app python scripts/apply_prod_formula_specs.py"""
import asyncio, json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.core.database import init_db, async_session
from app.models.formula import FormulaCard

SPECS_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "formula_library" / "deploy_formula_specs.json"

async def main():
    if not SPECS_FILE.exists():
        print(f"ERROR: {SPECS_FILE} not found")
        sys.exit(1)

    with open(SPECS_FILE, encoding="utf-8") as f:
        deploy = json.load(f)

    cards_data = deploy.get("cards", {})
    print(f"Loaded {len(cards_data)} card specs from deployment file\n")

    await init_db()
    async with async_session() as db:
        updated = 0
        skipped = 0
        for cid_str, data in cards_data.items():
            cid = int(cid_str)
            spec = data["graph_spec"]
            title = data["title"]

            r = await db.execute(
                select(FormulaCard).where(
                    FormulaCard.id == cid,
                    FormulaCard.deleted_at.is_(None),
                )
            )
            card = r.scalar_one_or_none()
            if not card:
                print(f"  [{cid:>3}] SKIP — not found: {title[:35]}")
                skipped += 1
                continue

            # Always update — local specs are authoritative
            card.graph_spec = spec
            card.draft_graph_spec = None
            # Reset graph_status to "unconfigured" — images need separate deploy
            if card.graph_status == "ready":
                card.graph_status = "ready"  # keep ready, image URLs still work if files exist
            await db.flush()
            updated += 1

        await db.commit()
        print(f"\n✅ Updated {updated} cards")
        print(f"   Skipped {skipped} (not found)")

    print("\nTo sync graph images to production:")
    print("  rsync -az -e 'ssh -i loginkey.pem' backend/static/formulas/graphs/ root@8.163.56.109:/opt/2240ai-v2/backend/static/formulas/graphs/")
    print("\nTo regenerate images on server (if CJK fonts available):")
    print("  docker compose exec -T app python scripts/batch_cross_axis_remaining.py")

if __name__ == "__main__":
    asyncio.run(main())
