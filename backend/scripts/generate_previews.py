#!/usr/bin/env python3
"""
Phase 3: Generate preview images for all cards with draft_graph_spec.

Usage:
    python scripts/generate_previews.py [--batch N]
"""
import asyncio
import json
import sys
import time
from datetime import datetime

sys.path.insert(0, '.')

from app.models.formula import FormulaCard, FormulaGraphPreview
from app.core.config import settings
from sqlalchemy import select
from app.core.database import async_session
from app.services.formula_graph_spec_service import generate_preview


REPORT = {
    "database_url": str(settings.DATABASE_URL),
    "timestamp": datetime.now().isoformat(),
    "cards": [],
    "summary": {
        "total": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
    }
}


async def process_card(session, card, admin_id=1):
    """Generate preview for a single card."""
    spec = card.draft_graph_spec
    if not spec:
        return {"id": card.id, "title": card.title, "status": "skipped", "reason": "No draft_graph_spec"}

    try:
        result = await generate_preview(
            db=session,
            card=card,
            spec_dict=spec,
            admin_id=admin_id,
        )
        return {
            "id": card.id,
            "title": card.title,
            "status": "success",
            "preview_token": result.get("preview_token"),
            "checksum": result.get("checksum"),
            "preview_url": result.get("preview_url"),
            "thumbnail_url": result.get("thumbnail_url"),
            "errors": result.get("quality", {}).get("errors", []),
            "warnings": result.get("quality", {}).get("warnings", []),
            "quality_passed": result.get("quality", {}).get("passed", False),
        }
    except ValueError as e:
        error_msg = str(e)
        # Try to get status code
        status_code = "422"
        if len(e.args) > 1:
            status_code = str(e.args[1])
        return {
            "id": card.id,
            "title": card.title,
            "status": "failed",
            "error": error_msg,
            "error_code": status_code,
        }
    except Exception as e:
        return {
            "id": card.id,
            "title": card.title,
            "status": "failed",
            "error": str(e),
        }


async def main():
    BATCH_SIZE = 5  # Process in small batches to manage load
    if "--batch" in sys.argv:
        idx = sys.argv.index("--batch")
        if idx + 1 < len(sys.argv):
            BATCH_SIZE = int(sys.argv[idx + 1])

    async with async_session() as session:
        # Load cards with draft_graph_spec and graph_status = unconfigured
        r = await session.execute(
            select(FormulaCard).where(
                FormulaCard.card_type == "function_graph",
                FormulaCard.draft_graph_spec.isnot(None),
                FormulaCard.graph_status.in_(["unconfigured"]),
                FormulaCard.deleted_at.is_(None),
            ).order_by(FormulaCard.id)
        )
        cards = list(r.scalars().all())

        print(f"Found {len(cards)} cards to generate previews for")
        print(f"Batch size: {BATCH_SIZE}")
        print()

        total = len(cards)
        REPORT["summary"]["total"] = total

        # Process in batches
        for batch_start in range(0, total, BATCH_SIZE):
            batch = cards[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"\n--- Batch {batch_num}/{total_batches} ---")

            for card in batch:
                print(f"  Generating preview for ID={card.id} ({card.title[:40]})...", end=" ", flush=True)
                result = await process_card(session, card)
                REPORT["cards"].append(result)

                if result["status"] == "success":
                    REPORT["summary"]["success"] += 1
                    warnings = result.get("warnings", [])
                    errors = result.get("errors", [])
                    print(f"OK (warnings={len(warnings)}, errors={len(errors)})")
                elif result["status"] == "failed":
                    REPORT["summary"]["failed"] += 1
                    print(f"FAILED: {result.get('error', 'Unknown error')[:80]}")
                else:
                    REPORT["summary"]["skipped"] += 1
                    print(f"SKIPPED: {result.get('reason', '')}")

                # Add small delay between cards
                await asyncio.sleep(0.5)

            # Flush batch
            try:
                await session.flush()
            except Exception as e:
                print(f"  Flush error: {e}")

            if batch_start + BATCH_SIZE < total:
                print(f"  Waiting before next batch...")
                await asyncio.sleep(1)

        # Commit all at once
        try:
            await session.commit()
            print(f"\nAll previews committed successfully.")
        except Exception as e:
            await session.rollback()
            print(f"\nCommit error (rolled back): {e}")

    # Save report
    report_path = "reports/formula_graph_generation_report.json"
    import os
    os.makedirs("reports", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)

    print(f"\nReport saved to {report_path}")
    print(f"Summary: {json.dumps(REPORT['summary'], ensure_ascii=False)}")


if __name__ == "__main__":
    asyncio.run(main())
