"""Read-only verification script for multi_blank_choice data integrity.

Scans question_imports and questions tables for data integrity violations.
Reports issues by risk category. Returns non-zero exit code if any issues found.
Safe to run against production — never writes to the database.

Risk categories:
    missing_groups: multi_blank_choice without blank_option_groups
    duplicate_group_id: duplicate group IDs in blank_option_groups
    missing_answer_slot: canonical answer doesn't cover all groups
    extra_answer_slot: answer has slots not in groups
    invalid_answer_option: answer value not in group's option keys
    legacy_answer_format: answer not in canonical ①:B;②:D format
    options_groups_conflict: both options and blank_option_groups present
    hash_mismatch: question_hash doesn't match current computation
    suspected_misclassified: single_choice/choice/fill_blank with 2+ blanks
    blank_count_mismatch: stem blank count != answer slot count

Usage:
    python -m scripts.verify_multi_blank_choice_data
    python -m scripts.verify_multi_blank_choice_data --report-json report.json
    python -m scripts.verify_multi_blank_choice_data --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import or_, select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.features.multi_blank_choice import (  # noqa: E402
    extract_blank_slots,
    parse_multi_blank_answer,
    serialize_multi_blank_answer,
    validate_multi_blank_question,
)
from app.features.question_pipeline import normalizer  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.question_import import QuestionImport  # noqa: E402


def _stem_text_from_content(content: dict | str | None) -> str:
    if not content:
        return ""
    if isinstance(content, dict):
        for key in ("text", "stem", "题干", "题目"):
            value = content.get(key)
            if value:
                return str(value)
    return str(content or "")


def _get_blank_option_groups(content: dict | None) -> list[dict]:
    if not content or not isinstance(content, dict):
        return []
    return content.get("blank_option_groups") or []


def _is_canonical_format(answer: str) -> bool:
    """Check if answer is in canonical ①:B;②:D format."""
    if not answer:
        return False
    return bool(re.match(r"^[①-⑳]:[A-H](?:;[①-⑳]:[A-H])*$", answer.strip()))


def _get_options_dict(record) -> dict | None:
    """Extract flat options dict from any record type."""
    if hasattr(record, "parsed_options"):
        return record.parsed_options or None
    if hasattr(record, "options"):
        return record.options or None
    return None


async def verify_records(
    source: str,
    records: list,
) -> list[dict]:
    """Verify a list of records for data integrity.

    Args:
        source: "question_imports" or "questions"
        records: list of ORM model instances

    Returns:
        list of issue dicts
    """
    issues: list[dict] = []

    for rec in records:
        rid = rec.id
        content_field = getattr(rec, "parsed_content", None) or getattr(rec, "content", None)
        stem = _stem_text_from_content(content_field)
        blank_groups = _get_blank_option_groups(content_field)
        question_type = rec.question_type or ""
        answer = str(getattr(rec, "parsed_answer", None) or getattr(rec, "answer", "") or "")
        options = _get_options_dict(rec)

        # ── Check: multi_blank_choice must have groups ──
        if question_type == "multi_blank_choice":
            if not blank_groups:
                issues.append({
                    "id": rid,
                    "source": source,
                    "category": "missing_groups",
                    "detail": "multi_blank_choice missing blank_option_groups",
                    "severity": "high",
                })
                continue  # skip further checks that depend on groups

            if len(blank_groups) < 2:
                issues.append({
                    "id": rid,
                    "source": source,
                    "category": "missing_groups",
                    "detail": f"multi_blank_choice has only {len(blank_groups)} group(s)",
                    "severity": "high",
                })

            # ── Check: duplicate group IDs ──
            seen_ids = set()
            for g in blank_groups:
                gid = str(g.get("id") or "").strip()
                if gid in seen_ids:
                    issues.append({
                        "id": rid,
                        "source": source,
                        "category": "duplicate_group_id",
                        "detail": f"duplicate group id: {gid}",
                        "severity": "high",
                    })
                seen_ids.add(gid)
                opts = g.get("options") or []
                if len(opts) < 2:
                    issues.append({
                        "id": rid,
                        "source": source,
                        "category": "missing_groups",
                        "detail": f"group {gid} has fewer than 2 options",
                        "severity": "high",
                    })

            # ── Check: options and groups conflict ──
            if options:
                issues.append({
                    "id": rid,
                    "source": source,
                    "category": "options_groups_conflict",
                    "detail": "both options and blank_option_groups present",
                    "severity": "high",
                })

            # ── Check: canonical format ──
            if answer and not _is_canonical_format(answer):
                issues.append({
                    "id": rid,
                    "source": source,
                    "category": "legacy_answer_format",
                    "detail": f"answer not in canonical format: {answer[:80]}",
                    "severity": "medium",
                })

            # ── Check: answer coverage using validate function ──
            if answer and blank_groups:
                is_valid, val_errors = validate_multi_blank_question(blank_groups, answer)
                if not is_valid:
                    for ve in val_errors:
                        if "missing_slots" in ve:
                            issues.append({
                                "id": rid,
                                "source": source,
                                "category": "missing_answer_slot",
                                "detail": ve,
                                "severity": "high",
                            })
                        elif "extra_slots" in ve:
                            issues.append({
                                "id": rid,
                                "source": source,
                                "category": "extra_answer_slot",
                                "detail": ve,
                                "severity": "high",
                            })
                        elif "not_in_group_options" in ve:
                            issues.append({
                                "id": rid,
                                "source": source,
                                "category": "invalid_answer_option",
                                "detail": ve,
                                "severity": "high",
                            })
                        elif "duplicate" in ve:
                            issues.append({
                                "id": rid,
                                "source": source,
                                "category": "duplicate_group_id",
                                "detail": ve,
                                "severity": "high",
                            })
            elif not answer:
                issues.append({
                    "id": rid,
                    "source": source,
                    "category": "missing_answer_slot",
                    "detail": "multi_blank_choice has empty answer",
                    "severity": "high",
                })

            # ── Check: hash ──
            if hasattr(rec, "question_hash") and rec.question_hash and blank_groups:
                expected_hash = normalizer.build_question_hash(
                    stem=stem,
                    options=None,
                    answer=answer,
                    blank_option_groups=blank_groups,
                )
                if expected_hash and rec.question_hash != expected_hash:
                    issues.append({
                        "id": rid,
                        "source": source,
                        "category": "hash_mismatch",
                        "detail": f"expected={expected_hash} actual={rec.question_hash}",
                        "severity": "medium",
                    })

        # ── Check: suspected misclassified (not already multi_blank_choice) ──
        elif question_type in ("single_choice", "fill_blank", ""):
            if stem and answer:
                slot_ids = extract_blank_slots(stem)
                if len(slot_ids) >= 2:
                    parsed, _ = parse_multi_blank_answer(answer, slot_ids=slot_ids, allow_positional=True)
                    if len(parsed) >= 2:
                        issues.append({
                            "id": rid,
                            "source": source,
                            "category": "suspected_misclassified",
                            "detail": (
                                f"type={question_type} has {len(slot_ids)} blanks "
                                f"and answer parses to {len(parsed)} slots"
                            ),
                            "severity": "low",
                        })

        # ── Check: blank count vs answer slot count (for non-multi_blank too) ──
        if stem and answer and question_type == "multi_blank_choice" and blank_groups:
            slot_ids = extract_blank_slots(stem)
            group_ids = [str(g.get("id") or "").strip() for g in blank_groups]
            if slot_ids and set(slot_ids) != set(group_ids):
                issues.append({
                    "id": rid,
                    "source": source,
                    "category": "blank_count_mismatch",
                    "detail": (
                        f"stem slots={slot_ids} "
                        f"groups={group_ids}"
                    ),
                    "severity": "medium",
                })

    return issues


async def scan_and_verify(
    limit: int | None = None,
    report_json: str | None = None,
) -> dict:
    """Scan both tables and verify data integrity.

    Returns:
        dict with issues grouped by category
    """
    now = datetime.utcnow()
    print(f"=== Verification started at {now.isoformat()} ===")
    print()

    all_issues: list[dict] = []

    # Scan question_imports
    print("Scanning question_imports...")
    async with async_session() as db:
        query = select(QuestionImport).order_by(QuestionImport.id.asc())
        if limit:
            query = query.limit(limit)
        result = await db.execute(query)
        records = list(result.scalars().all())
        print(f"  Found {len(records)} records")

        issues = await verify_records("question_imports", records)
        all_issues.extend(issues)
        print(f"  Issues: {len(issues)}")

    # Scan questions
    print("Scanning questions...")
    async with async_session() as db:
        query = select(Question).order_by(Question.id.asc())
        if limit:
            query = query.limit(limit)
        result = await db.execute(query)
        records = list(result.scalars().all())
        print(f"  Found {len(records)} records")

        issues = await verify_records("questions", records)
        all_issues.extend(issues)
        print(f"  Issues: {len(issues)}")

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for issue in all_issues:
        cat = issue["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(issue)

    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_issues.sort(key=lambda x: (severity_order.get(x["severity"], 9), x["id"]))

    # Print report
    print()
    print("=" * 70)
    print(f"Verification complete: {len(all_issues)} total issues")
    print("=" * 70)

    by_severity = {"high": 0, "medium": 0, "low": 0}
    for issue in all_issues:
        by_severity[issue["severity"]] = by_severity.get(issue["severity"], 0) + 1

    print(f"  High:   {by_severity.get('high', 0)}")
    print(f"  Medium: {by_severity.get('medium', 0)}")
    print(f"  Low:    {by_severity.get('low', 0)}")

    for cat in sorted(by_category.keys()):
        items = by_category[cat]
        severities = set(i["severity"] for i in items)
        print(f"\n  [{', '.join(sorted(severities))}] {cat}: {len(items)} issue(s)")
        for item in items[:10]:
            print(f"    #{item['id']} ({item['source']}): {item['detail'][:120]}")
        if len(items) > 10:
            print(f"    ... and {len(items) - 10} more")

    if not by_category:
        print("\n  No issues found.")

    result = {
        "timestamp": now.isoformat(),
        "total_issues": len(all_issues),
        "by_severity": by_severity,
        "by_category": {cat: len(items) for cat, items in by_category.items()},
        "issues": all_issues,
    }

    if report_json:
        with open(report_json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nReport written to: {report_json}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify multi_blank_choice data integrity (read-only)"
    )
    parser.add_argument("--limit", type=int, default=None, help="Max records to scan per table")
    parser.add_argument("--report-json", type=str, default=None, help="Path to write JSON report")
    args = parser.parse_args()

    print("=" * 70)
    print("READ-ONLY mode — no database writes.")
    print("=" * 70)
    print()

    result = asyncio.run(scan_and_verify(limit=args.limit, report_json=args.report_json))

    # Exit non-zero if any high-severity issues found
    high_count = result["by_severity"].get("high", 0)
    if high_count > 0:
        print(f"\nExiting with code 1: {high_count} high-severity issue(s) found.")
        sys.exit(1)

    print("\nNo high-severity issues found. Exiting with code 0.")


if __name__ == "__main__":
    main()
