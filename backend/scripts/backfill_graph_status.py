#!/usr/bin/env python3
"""Backfill graph_status for existing formula cards.

Re-runnable. Supports --dry-run to preview changes without applying.

Usage:
    python scripts/backfill_graph_status.py --dry-run
    python scripts/backfill_graph_status.py --apply
"""

import argparse
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import engine
from sqlalchemy import text


BACKFILL_STEPS = [
    {
        "name": "pure_formula → not_applicable",
        "sql": """
            UPDATE formula_cards
            SET graph_status = 'not_applicable'
            WHERE card_type = 'pure_formula'
              AND deleted_at IS NULL
              AND graph_status IS DISTINCT FROM 'not_applicable'
        """,
        "where_count": """
            SELECT COUNT(*) FROM formula_cards
            WHERE card_type = 'pure_formula'
              AND deleted_at IS NULL
              AND graph_status IS DISTINCT FROM 'not_applicable'
        """,
    },
    {
        "name": "function_graph/auto with asset → ready",
        "sql": """
            UPDATE formula_cards
            SET graph_status = 'ready'
            WHERE card_type IN ('function_graph', 'auto')
              AND deleted_at IS NULL
              AND id IN (SELECT DISTINCT formula_card_id FROM formula_graph_assets WHERE image_url IS NOT NULL)
              AND graph_status IS DISTINCT FROM 'ready'
        """,
        "where_count": """
            SELECT COUNT(*) FROM formula_cards
            WHERE card_type IN ('function_graph', 'auto')
              AND deleted_at IS NULL
              AND id IN (SELECT DISTINCT formula_card_id FROM formula_graph_assets WHERE image_url IS NOT NULL)
              AND graph_status IS DISTINCT FROM 'ready'
        """,
    },
    {
        "name": "function_graph/auto with graph_spec → missing",
        "sql": """
            UPDATE formula_cards
            SET graph_status = 'missing'
            WHERE card_type IN ('function_graph', 'auto')
              AND deleted_at IS NULL
              AND graph_spec IS NOT NULL
              AND graph_status IS DISTINCT FROM 'missing'
              AND graph_status IS DISTINCT FROM 'ready'
        """,
        "where_count": """
            SELECT COUNT(*) FROM formula_cards
            WHERE card_type IN ('function_graph', 'auto')
              AND deleted_at IS NULL
              AND graph_spec IS NOT NULL
              AND graph_status IS DISTINCT FROM 'missing'
              AND graph_status IS DISTINCT FROM 'ready'
        """,
    },
    {
        "name": "remaining function_graph/auto → unconfigured",
        "sql": """
            UPDATE formula_cards
            SET graph_status = 'unconfigured'
            WHERE card_type IN ('function_graph', 'auto')
              AND deleted_at IS NULL
              AND graph_status IS NULL
        """,
        "where_count": """
            SELECT COUNT(*) FROM formula_cards
            WHERE card_type IN ('function_graph', 'auto')
              AND deleted_at IS NULL
              AND graph_status IS NULL
        """,
    },
]


async def run_backfill(dry_run: bool = True) -> None:
    async with engine.connect() as conn:
        print("=" * 60)
        print("Formula Card graph_status Backfill")
        print(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")
        print("=" * 60)

        # Current distribution
        result = await conn.execute(
            text("""
                SELECT graph_status, COUNT(*) as cnt
                FROM formula_cards
                WHERE deleted_at IS NULL
                GROUP BY graph_status
                ORDER BY cnt DESC
            """)
        )
        rows = result.fetchall()
        print("\nCurrent distribution:")
        for row in rows:
            status = row[0] or "NULL"
            count = row[1]
            print(f"  {status:20s} {count}")
        total = sum(row[1] for row in rows)
        print(f"  {'TOTAL':20s} {total}")

        # Count cards not covered
        result = await conn.execute(
            text("""
                SELECT COUNT(*) FROM formula_cards
                WHERE deleted_at IS NULL
                  AND graph_status IS NULL
            """)
        )
        null_count = result.scalar() or 0
        if null_count > 0:
            print(f"\n⚠  {null_count} cards have NULL graph_status (will be updated)")
        else:
            print("\n✓ All cards have a graph_status")

        # Run each step
        print(f"\n{'Steps':-^60}")
        total_affected = 0
        for step in BACKFILL_STEPS:
            result = await conn.execute(text(step["where_count"]))
            count = result.scalar() or 0
            if count == 0:
                print(f"  ✓ {step['name']}: 0 rows (already up to date)")
                continue

            print(f"  → {step['name']}: {count} rows")
            total_affected += count

            if not dry_run:
                await conn.execute(text(step["sql"]))

        print(f"\n{'Summary':-^60}")
        print(f"  Total affected: {total_affected}")
        if dry_run:
            print(f"  ⚠  DRY RUN — no changes applied. Re-run with --apply to execute.")
        else:
            print(f"  ✓ Changes applied.")
            # Verify
            result = await conn.execute(
                text("""
                    SELECT COUNT(*) FROM formula_cards
                    WHERE deleted_at IS NULL AND graph_status IS NULL
                """)
            )
            remaining = result.scalar() or 0
            if remaining > 0:
                print(f"  ⚠  {remaining} cards still have NULL graph_status")
            else:
                print(f"  ✓ All cards now have a graph_status")


def main():
    parser = argparse.ArgumentParser(description="Backfill graph_status for formula cards")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    args = parser.parse_args()

    import asyncio
    asyncio.run(run_backfill(dry_run=not args.apply))


if __name__ == "__main__":
    main()
