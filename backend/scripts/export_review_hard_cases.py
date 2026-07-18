#!/usr/bin/env python3
"""Export hard cases from review rejections/modifications to OCR regression suite.

Usage:
  cd backend
  PYTHONPATH=. python scripts/export_review_hard_cases.py
  PYTHONPATH=. python scripts/export_review_hard_cases.py --limit 20 --export-dir tests/ocr_regression/cases/hard_cases

This script collects questions from ``question_imports`` that were:
- Rejected by reviewer (quality_gate failed)
- Manually corrected after AI import
- Flagged as needing attention

Each hard case is exported as a JSON file in the OCR regression case format,
ready for regression testing with the existing ``tests/ocr_regression/runner.py``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPORTS_DIR = "reports/sprint4e"


def _build_case(import_record: dict, source_preview: str) -> dict:
    """Build a regression case from an import record."""
    return {
        "case_id": f"hard_case_import_{import_record.get('id', 'unknown')}",
        "source_type": import_record.get("source_type", "pdf"),
        "source_preview": source_preview[:200],
        "import_id": import_record.get("id"),
        "review_decision": import_record.get("status", "unknown"),
        "reject_reason": import_record.get("reject_reason", ""),
        "tags": ["hard_case", "review_feedback"],
        "exported_at": datetime.now().isoformat(),
    }


def find_hard_cases(
    db_path: str,
    *,
    limit: int = 50,
    since_days: int = 30,
) -> list[dict]:
    """Query question_imports for hard cases (rejected/corrected imports)."""
    import sqlite3

    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    since_ts = (datetime.now() - timedelta(days=since_days)).isoformat()

    rows = cursor.execute(
        """
        SELECT id, source_type, status, reject_reason,
               source_file, raw_text_preview,
               created_at, batch_id, subject_id
        FROM question_imports
        WHERE created_at >= ?
          AND (status IN ('rejected', 'draft')
               OR (status = 'approved' AND reviewed_at IS NOT NULL))
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (since_ts, limit),
    ).fetchall()

    conn.close()

    cases = []
    for r in rows:
        record = dict(r)
        source_preview = record.pop("raw_preview", "") or ""
        case = _build_case(record, source_preview)
        cases.append(case)

    return cases


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export review hard cases to regression suite"
    )
    parser.add_argument(
        "--db", default="postgraduate.db",
        help="Path to SQLite database (default: postgraduate.db)",
    )
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Max hard cases to export (default: 50)",
    )
    parser.add_argument(
        "--since-days", type=int, default=30,
        help="Look back N days (default: 30)",
    )
    parser.add_argument(
        "--export-dir",
        default="tests/ocr_regression/cases/hard_cases",
        help="Export directory (default: tests/ocr_regression/cases/hard_cases)",
    )
    args = parser.parse_args()

    print(f"Scanning {args.db} for review hard cases (past {args.since_days}d, limit {args.limit})...")

    cases = find_hard_cases(
        args.db,
        limit=args.limit,
        since_days=args.since_days,
    )

    if not cases:
        print("No hard cases found. Skipping export.")
        # Still write empty report
        report = {
            "scan_time": datetime.now().isoformat(),
            "db": args.db,
            "since_days": args.since_days,
            "hard_cases_found": 0,
            "export_dir": args.export_dir,
            "exported": [],
        }
        report_path = f"{REPORTS_DIR}/hard_cases_export.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Report: {report_path}")
        return 0

    export_path = Path(args.export_dir)
    export_path.mkdir(parents=True, exist_ok=True)

    exported = []
    for case in cases:
        case_id = case["case_id"]
        file_path = export_path / f"{case_id}.json"
        with open(file_path, "w") as f:
            json.dump(case, f, indent=2, ensure_ascii=False)
        exported.append(case_id)

    report = {
        "scan_time": datetime.now().isoformat(),
        "db": args.db,
        "since_days": args.since_days,
        "hard_cases_found": len(cases),
        "export_dir": str(export_path),
        "exported": exported,
    }
    report_path = f"{REPORTS_DIR}/hard_cases_export.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Exported {len(cases)} hard cases to {export_path}/")
    print(f"Report: {report_path}")
    print(f"\nTip: review cases with:")
    print(f"  ls {export_path}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
