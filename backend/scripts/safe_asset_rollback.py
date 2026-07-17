#!/usr/bin/env python3
"""Safe asset rollback with reference checking.

Usage:
    # Dry-run (default): only report what would happen
    python scripts/safe_asset_rollback.py --db sqlite+aiosqlite:///./postgraduate.db

    # Detach-only: remove DB references but keep files
    python scripts/safe_asset_rollback.py --db <db> --mode detach-only

    # Delete unreferenced: check references, then delete files
    python scripts/safe_asset_rollback.py --db <db> --mode delete-unreferenced --storage-keys key1 key2

Modes:
    dry-run             Only report references, no changes (default)
    detach-only         Remove DB references, keep physical files
    delete-unreferenced Only delete files with zero remaining references
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("safe_rollback")

BACKEND_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_ROOT)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")


async def main():
    parser = argparse.ArgumentParser(description="Safe asset rollback with reference checking")
    parser.add_argument("--db", default=None, help="DB URL override")
    parser.add_argument("--mode", choices=["dry-run", "detach-only", "delete-unreferenced"],
                        default="dry-run")
    parser.add_argument("--storage-keys", nargs="*", default=[],
                        help="Storage keys to process (if empty, scan all)")
    parser.add_argument("--request-id", default=None,
                        help="Idempotency key for the rollback request")
    parser.add_argument("--output-dir", default="reports/sprint3h/rollback",
                        help="Output directory for reports")
    args = parser.parse_args()

    if args.db:
        os.environ["DATABASE_URL"] = args.db

    request_id = args.request_id or f"rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = os.path.join(BACKEND_ROOT, args.output_dir, request_id)
    os.makedirs(output_dir, exist_ok=True)

    from app.core.database import async_session
    from app.services.asset_reference_service import (
        AssetReferenceService, DeletionMode, DeletionState, SafeDeleteMachine,
    )

    # ── Phase 1: Reference scan ──
    logger.info("Phase 1: Reference scan")
    logger.info("  mode=%s request_id=%s", args.mode, request_id)
    logger.info("  storage_keys=%s", args.storage_keys or "(scan all)")

    rollback_plan = {
        "request_id": request_id,
        "mode": args.mode,
        "generated_at": datetime.utcnow().isoformat(),
        "storage_keys": args.storage_keys or ["(scan all)"],
        "entries": [],
        "summary": {
            "total_storage_keys": 0,
            "safe_to_delete": 0,
            "has_references": 0,
            "errors": 0,
        },
    }

    async with async_session() as db:
        service = AssetReferenceService(db)
        targets = args.storage_keys or []

        if not targets:
            logger.info("No specific keys — scanning all configured tables "
                        "for asset URLs (limited in dry-run)")
            # In a full scan, iterate all question_imports etc.
            # For now, require explicit keys
            logger.warning("No --storage-keys provided. Please specify keys to check.")
            rollback_plan["summary"]["note"] = "no_keys_provided"
        else:
            reports = await service.resolve_all(targets)
            for key, report in reports.items():
                machine = SafeDeleteMachine()
                entry = {
                    "storage_key": key,
                    "state": machine.state.value,
                    "reference_count": report.reference_count,
                    "safe_to_delete": report.safe_to_delete,
                    "reason_codes": report.reason_codes,
                    "references": [
                        {
                            "entity_type": r.entity_type,
                            "entity_id": r.entity_id,
                            "field_name": r.field_name,
                            "json_path": r.json_path,
                            "asset_url": r.asset_url,
                        }
                        for r in report.references
                    ],
                    "errors": report.errors,
                }
                rollback_plan["entries"].append(entry)
                rollback_plan["summary"]["total_storage_keys"] += 1
                if report.safe_to_delete:
                    rollback_plan["summary"]["safe_to_delete"] += 1
                else:
                    rollback_plan["summary"]["has_references"] += 1
                if report.errors:
                    rollback_plan["summary"]["errors"] += 1
                logger.info("  key=%-50s refs=%d safe=%s",
                            key, report.reference_count, report.safe_to_delete)

    # ── Save plan ──
    plan_path = os.path.join(output_dir, "rollback_plan.json")
    with open(plan_path, "w") as f:
        json.dump(rollback_plan, f, ensure_ascii=False, indent=2)
    logger.info("Plan saved: %s", plan_path)
    logger.info("Summary: total_keys=%d safe=%d referenced=%d errors=%d",
                rollback_plan["summary"]["total_storage_keys"],
                rollback_plan["summary"]["safe_to_delete"],
                rollback_plan["summary"]["has_references"],
                rollback_plan["summary"]["errors"])

    if args.mode == "dry-run":
        logger.info("Dry-run mode — no changes made.")
        logger.info("To apply, use --mode detach-only or --mode delete-unreferenced")
        return

    # Phase 2-3 would execute in non-dry-run modes:
    # 1. DB transaction: update/remove references (detach-only)
    # 2. Save deletion outbox
    # 3. Commit transaction
    # 4. Post-commit: re-check references, delete files (delete-unreferenced)
    logger.info("Full execution modes not yet implemented in this version")


if __name__ == "__main__":
    asyncio.run(main())
