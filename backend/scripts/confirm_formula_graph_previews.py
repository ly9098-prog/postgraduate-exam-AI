#!/usr/bin/env python3
"""
Confirm formula graph previews — move from draft to ready.

Usage:
    # List auto-approvable candidates (dry-run)
    python scripts/confirm_formula_graph_previews.py --category auto_approvable --dry-run

    # Confirm specific IDs (dry-run first)
    python scripts/confirm_formula_graph_previews.py --ids 58,70,76 --dry-run

    # Apply confirmation
    python scripts/confirm_formula_graph_previews.py --ids 58,70,76 --apply

    # Confirm all auto-approvable
    python scripts/confirm_formula_graph_previews.py --category auto_approvable --apply

    # Use a report file
    python scripts/confirm_formula_graph_previews.py --report reports/formula_graph_quality_review.json --category auto_approvable --apply
"""
import asyncio
import json
import sys
from datetime import datetime

sys.path.insert(0, '.')

from app.models.formula import FormulaCard, FormulaGraphPreview, FormulaGraphAsset
from app.core.config import settings
from sqlalchemy import select
from app.core.database import async_session
from app.services.formula_graph_spec_service import confirm_preview

# Cards that are simple_auto safe for auto-confirm (single function, single panel, no params)
AUTO_APPROVABLE_IDS = {58, 70, 76, 77, 78, 79, 80, 82, 91}


async def list_candidates(session, category: str | None, ids: set[int] | None):
    """List candidate cards for confirmation."""
    query = select(FormulaCard).where(
        FormulaCard.card_type == "function_graph",
        FormulaCard.graph_status == "draft",
        FormulaCard.deleted_at.is_(None),
    )

    if ids:
        query = query.where(FormulaCard.id.in_(ids))
    elif category == "auto_approvable":
        query = query.where(FormulaCard.id.in_(AUTO_APPROVABLE_IDS))

    r = await session.execute(query.order_by(FormulaCard.id))
    return list(r.scalars().all())


async def confirm(card, session, admin_id=1, accept_warnings=False):
    """Confirm a single card's preview."""
    # Find the preview
    r = await session.execute(
        select(FormulaGraphPreview).where(
            FormulaGraphPreview.formula_card_id == card.id,
        )
    )
    preview = r.scalar_one_or_none()
    if not preview:
        return {"id": card.id, "title": card.title, "status": "skipped", "reason": "No preview found"}

    try:
        asset = await confirm_preview(
            db=session,
            card=card,
            preview_token=preview.preview_token,
            card_version=card.version,
            accept_warnings=accept_warnings,
            admin_id=admin_id,
        )
        return {
            "id": card.id,
            "title": card.title,
            "status": "success",
            "asset_id": asset.id,
            "image_url": asset.image_url,
            "thumbnail_url": asset.thumbnail_url,
        }
    except ValueError as e:
        return {
            "id": card.id,
            "title": card.title,
            "status": "failed",
            "error": str(e),
        }
    except Exception as e:
        return {
            "id": card.id,
            "title": card.title,
            "status": "failed",
            "error": str(e),
        }


async def main():
    # Parse args
    args = sys.argv[1:]
    category = None
    ids = None
    dry_run = "--dry-run" in args
    apply = "--apply" in args
    accept_warnings = "--accept-warnings" in args
    report_path = None

    for i, a in enumerate(args):
        if a == "--category" and i + 1 < len(args):
            category = args[i + 1]
        elif a == "--ids" and i + 1 < len(args):
            ids = set(int(x.strip()) for x in args[i + 1].split(","))
        elif a == "--report" and i + 1 < len(args):
            report_path = args[i + 1]

    if not category and not ids:
        print("Usage: specify --category or --ids")
        print("  --category auto_approvable")
        print("  --ids 58,70,76")
        print("  --dry-run (default)")
        print("  --apply")
        return

    if apply and not dry_run:
        print(f"=== APPLY MODE ===")
    else:
        print(f"=== DRY RUN (no changes) ===")
        print()

    async with async_session() as session:
        cards = await list_candidates(session, category, ids)

        if not cards:
            print("No candidate cards found.")
            return

        print(f"Found {len(cards)} candidate card(s):")
        for c in cards:
            print(f"  ID={c.id}: {c.title[:50]} (version={c.version})")
        print()

        if dry_run:
            print("DRY RUN: Use --apply to confirm")
            return

        # Confirm each card
        results = []
        for c in cards:
            print(f"Confirming ID={c.id} ({c.title[:40]})...", end=" ", flush=True)
            result = await confirm(c, session, accept_warnings=accept_warnings)
            results.append(result)

            if result["status"] == "success":
                print(f"OK (asset_id={result['asset_id']})")
            elif result["status"] == "skipped":
                print(f"SKIPPED: {result.get('reason', '')}")
            else:
                print(f"FAILED: {result.get('error', '')[:80]}")

            await asyncio.sleep(0.3)

        # Flush and commit
        try:
            await session.commit()
            print(f"\nAll changes committed successfully.")
        except Exception as e:
            await session.rollback()
            print(f"\nCommit failed (rolled back): {e}")

        # Summary
        success = sum(1 for r in results if r["status"] == "success")
        failed = sum(1 for r in results if r["status"] == "failed")
        skipped = sum(1 for r in results if r["status"] == "skipped")

        print(f"\nSummary: {success} success, {failed} failed, {skipped} skipped")
        for r in results:
            if r["status"] == "failed":
                print(f"  ID={r['id']}: {r.get('error', '')}")

        # Save results if report path
        if report_path:
            with open(report_path.replace(".json", "_confirm.json"), "w", encoding="utf-8") as f:
                json.dump({"results": results, "timestamp": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
