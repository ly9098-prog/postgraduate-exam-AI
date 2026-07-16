"""Non-destructive backfill for misclassified multi-blank choice questions.

Scans `question_imports` and `questions` for records that were incorrectly
classified as `single_choice` / `choice` / `unknown` but have:
- At least 2 blank slots in the stem
- A set of at least 2 options
- An answer parseable into at least 2 slot values

Converts them to the unified multi_blank_choice data contract:
    question_type = "multi_blank_choice"
    options = None (questions) / parsed_options = None (imports)
    content.blank_option_groups = [...]
    answer = canonical "①:B;②:D"

Usage:
    cd backend
    python -m scripts.backfill_multi_blank_choice --dry-run
    python -m scripts.backfill_multi_blank_choice --apply --batch-size 200
"""

from __future__ import annotations

import argparse
import asyncio
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
    build_blank_option_groups,
    parse_multi_blank_answer,
    serialize_multi_blank_answer,
    extract_blank_slots,
)
from app.features.question_pipeline import normalizer  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.question_import import QuestionImport  # noqa: E402


TARGET_TYPES = {"single_choice"}


def _stem_text_from_content(content: dict | str | None) -> str:
    if not content:
        return ""
    if isinstance(content, dict):
        for key in ("text", "stem", "题干", "题目"):
            value = content.get(key)
            if value:
                return str(value)
    return str(content or "")


def _extract_options_from_import(qi: QuestionImport) -> list[dict] | None:
    """Extract flat option list from an import record."""
    # Check parsed_options first
    if qi.parsed_options and isinstance(qi.parsed_options, dict):
        opts = qi.parsed_options
        return [{"key": k.upper(), "text": str(v or "")} for k, v in sorted(opts.items())]

    # Check raw_data for options
    raw = qi.raw_data or {}
    raw_opts = raw.get("options") or raw.get("选项")
    if raw_opts:
        if isinstance(raw_opts, dict):
            return [{"key": k.upper(), "text": str(v or "")} for k, v in sorted(raw_opts.items())]
        if isinstance(raw_opts, list):
            result = []
            for item in raw_opts:
                if isinstance(item, dict):
                    key = str(item.get("key") or item.get("label") or "").upper()
                    text = str(item.get("text") or item.get("value") or item.get("content") or "")
                    if key:
                        result.append({"key": key, "text": text})
            return result if result else None

    return None


def _extract_options_from_question(q: Question) -> list[dict] | None:
    """Extract flat option list from a published question record."""
    if q.options and isinstance(q.options, dict):
        return [{"key": k.upper(), "text": str(v or "")} for k, v in sorted(q.options.items())]
    return None


def _assess_candidate(
    record_id: int,
    source_table: str,
    stem: str,
    options: list[dict] | None,
    answer: str | None,
    current_type: str | None,
) -> dict:
    """Assess if a record is a misclassified multi-blank choice candidate.

    Returns assessment dict (always, even when not a candidate).

    Safety rules (Phase 5):
    - Stem blank count must equal answer slot count (no ambiguous mismatches)
    - Each answer value must exist in the corresponding group's option keys
    - Group IDs must be unique
    - OCR circled digit differences are safely normalized (1 ↔ ①)
    - When uncertainty exists, record is marked as ambiguous and SKIPPED
    """
    result = {
        "id": record_id,
        "table": source_table,
        "current_type": current_type or "",
        "candidate": False,
        "ambiguous": False,
        "slot_count": 0,
        "option_count": 0,
        "parsed_answer_keys": [],
        "risks": [],
        "reason_detail": "",
    }

    # Already correct?
    if current_type == "multi_blank_choice":
        result["risks"].append("already_multi_blank_choice")
        return result

    # Check stem for blank slots
    slot_ids = extract_blank_slots(stem)
    result["slot_count"] = len(slot_ids)
    if len(slot_ids) < 2:
        result["risks"].append("less_than_2_slots")
        return result

    # Check options
    if not options:
        result["risks"].append("no_options")
        return result
    result["option_count"] = len(options)
    if len(options) < 2:
        result["risks"].append("less_than_2_options")
        return result

    # Parse answer
    if not answer:
        result["risks"].append("no_answer")
        return result

    parsed, parse_errors = parse_multi_blank_answer(answer, slot_ids=slot_ids, allow_positional=True)
    result["parsed_answer_keys"] = list(parsed.keys())

    if parse_errors:
        result["risks"].extend(parse_errors)

    parsed_slot_ids = list(parsed.keys())
    if len(parsed) < 2:
        result["risks"].append(f"answer_parses_to_{len(parsed)}_slots_only")
        return result

    # ── Slot count reconciliation ──
    # If stem has anonymous blanks (1, 2) and answer has circled digits (①, ②),
    # use answer-derived IDs. Otherwise enforce strict equality.
    effective_slot_ids = slot_ids
    if parsed_slot_ids and set(parsed_slot_ids) != set(slot_ids):
        stem_is_anonymous = all(sid.isdigit() for sid in slot_ids)
        answer_has_circled = any(re.search(r"[①-⑳]", sid) for sid in parsed_slot_ids)
        if stem_is_anonymous and answer_has_circled and len(parsed_slot_ids) == len(slot_ids):
            # Safe normalization: anonymous → circled digits, same count
            effective_slot_ids = parsed_slot_ids
        else:
            # Ambiguous: different count or incompatible ID types
            result["ambiguous"] = True
            result["reason_detail"] = (
                f"blank_count_mismatch: "
                f"detected_blank_count={len(slot_ids)} "
                f"answer_slot_count={len(parsed_slot_ids)} "
                f"stem_ids={slot_ids} answer_ids={parsed_slot_ids}"
            )
            result["risks"].append(result["reason_detail"])
            return result

    # Check answer existing in group options
    opt_keys = {o["key"].upper() for o in (options or [])}
    for sid, val in parsed.items():
        if val not in opt_keys:
            result["ambiguous"] = True
            result["reason_detail"] = (
                f"answer_value_not_in_options: "
                f"slot={sid} value={val} valid_keys={sorted(opt_keys)}"
            )
            result["risks"].append(result["reason_detail"])
            return result

    # Build blank option groups to validate group IDs are unique
    groups = build_blank_option_groups(effective_slot_ids, options or [])
    seen_ids = set()
    for g in groups:
        gid = g.get("id", "")
        if gid in seen_ids:
            result["ambiguous"] = True
            result["reason_detail"] = f"duplicate_group_id_{gid}"
            result["risks"].append(result["reason_detail"])
            return result
        seen_ids.add(gid)

    # All checks passed - it's a valid candidate
    result["candidate"] = True
    result["slot_ids"] = effective_slot_ids
    result["serialized_answer"] = serialize_multi_blank_answer(parsed, effective_slot_ids)
    result["canonical_answer"] = serialize_multi_blank_answer(parsed, effective_slot_ids)
    result["option_keys"] = sorted(opt_keys)

    return result


async def scan_imports(
    apply: bool, batch_size: int, limit: int | None,
    import_ids: list[int] | None = None,
) -> tuple[list[dict], list[dict], int]:
    """Scan question_imports for misclassified multi-blank choice records.

    Returns:
        (candidates, ambiguous, scanned)
    """
    candidates: list[dict] = []
    ambiguous: list[dict] = []
    scanned = 0
    last_id = 0

    async with async_session() as db:
        while True:
            if limit is not None and scanned >= limit:
                break

            if import_ids:
                query = (
                    select(QuestionImport)
                    .where(
                        QuestionImport.id.in_(import_ids),
                    )
                    .order_by(QuestionImport.id.asc())
                )
            else:
                query = (
                    select(QuestionImport)
                    .where(
                        QuestionImport.id > last_id,
                        or_(
                            QuestionImport.question_type.in_(TARGET_TYPES),
                            QuestionImport.question_type.is_(None),
                        ),
                    )
                    .order_by(QuestionImport.id.asc())
                    .limit(batch_size)
                )
            result = await db.execute(query)
            records = list(result.scalars().all())
            if not records:
                break

            for rec in records:
                last_id = rec.id
                if limit is not None and scanned >= limit:
                    break
                scanned += 1

                stem = _stem_text_from_content(rec.parsed_content)
                if not stem:
                    stem = _stem_text_from_content(rec.raw_data)

                options = _extract_options_from_import(rec)
                answer = rec.parsed_answer or ""

                assessment = _assess_candidate(
                    rec.id, "question_imports", stem, options, answer, rec.question_type
                )
                if assessment["candidate"]:
                    candidates.append({**assessment, "_record": rec})
                elif assessment.get("ambiguous"):
                    ambiguous.append(assessment)
                else:
                    _log_candidate(assessment)

            if scanned % (batch_size * 5) == 0 and scanned > 0:
                print(f"  [imports] scanned={scanned} candidates={len(candidates)} ambiguous={len(ambiguous)} last_id={last_id}")

    return candidates, ambiguous, scanned


async def scan_questions(
    apply: bool, batch_size: int, limit: int | None,
    question_ids: list[int] | None = None,
) -> tuple[list[dict], list[dict], int]:
    """Scan questions table for misclassified multi-blank choice records.

    Returns:
        (candidates, ambiguous, scanned)
    """
    candidates: list[dict] = []
    ambiguous: list[dict] = []
    scanned = 0
    last_id = 0

    async with async_session() as db:
        while True:
            if limit is not None and scanned >= limit:
                break

            if question_ids:
                query = (
                    select(Question)
                    .where(
                        Question.id.in_(question_ids),
                    )
                    .order_by(Question.id.asc())
                )
            else:
                query = (
                    select(Question)
                    .where(
                        Question.id > last_id,
                        Question.question_type.in_(TARGET_TYPES),
                    )
                    .order_by(Question.id.asc())
                    .limit(batch_size)
                )
            result = await db.execute(query)
            records = list(result.scalars().all())
            if not records:
                break

            for rec in records:
                last_id = rec.id
                if limit is not None and scanned >= limit:
                    break
                scanned += 1

                stem = _stem_text_from_content(rec.content)
                options = _extract_options_from_question(rec)
                answer = rec.answer or ""

                assessment = _assess_candidate(
                    rec.id, "questions", stem, options, answer, rec.question_type
                )
                if assessment["candidate"]:
                    candidates.append({**assessment, "_record": rec})
                elif assessment.get("ambiguous"):
                    ambiguous.append(assessment)

            if scanned % (batch_size * 5) == 0 and scanned > 0:
                print(f"  [questions] scanned={scanned} candidates={len(candidates)} ambiguous={len(ambiguous)} last_id={last_id}")

    return candidates, ambiguous, scanned


def _log_candidate(assessment: dict) -> None:
    """Log a non-candidate/non-ambiguous assessment (debug info)."""
    if not assessment.get("risks"):
        return
    if assessment.get("slot_count", 0) >= 2:
        print(
            f"  SKIP {assessment['table']}#{assessment['id']}: "
            f"type={assessment['current_type']} slots={assessment['slot_count']} "
            f"opts={assessment['option_count']} answer_keys={assessment['parsed_answer_keys']} "
            f"risks={assessment['risks']}"
        )


def _transform_import(record: QuestionImport, assessment: dict) -> dict:
    """Build the update dict for a question_imports record."""
    slot_ids = assessment["slot_ids"]
    options_raw = _extract_options_from_import(record)
    groups = build_blank_option_groups(slot_ids, options_raw or [])

    parsed_content = dict(record.parsed_content or {}) if record.parsed_content else {}
    stem = _stem_text_from_content(record.parsed_content) or _stem_text_from_content(record.raw_data)
    parsed_content["text"] = stem
    parsed_content["blank_option_groups"] = groups

    return {
        "question_type": "multi_blank_choice",
        "parsed_content": parsed_content,
        "parsed_options": None,
        "parsed_answer": assessment["serialized_answer"],
    }


async def apply_import_transform(
    db, record: QuestionImport, transform: dict
) -> None:
    """Apply the transform to a question_imports record.

    Uses db.merge() to ensure the record is attached to the current session
    (records may be detached from scan_imports' session context).
    """
    merged = await db.merge(record)
    for key, value in transform.items():
        setattr(merged, key, value)

    groups = (transform["parsed_content"] or {}).get("blank_option_groups") or []
    stem = (transform["parsed_content"] or {}).get("text") or ""
    merged.question_hash = normalizer.build_question_hash(
        stem=stem, options=None, answer=transform.get("parsed_answer") or "",
        blank_option_groups=groups,
    )
    merged.duplicate_status = "normal"
    merged.duplicate_of_question_id = None


def _build_report(
    import_candidates: list[dict],
    question_candidates: list[dict],
    import_ambiguous: list[dict],
    question_ambiguous: list[dict],
    scanned_imports: int,
    scanned_questions: int,
    applied_imports: int,
    applied_questions: int,
    *,
    apply: bool,
) -> dict:
    """Build a machine-readable report dict of the scan/apply results."""
    candidate_details = []
    for c in import_candidates + question_candidates:
        candidate_details.append({
            "id": c["id"],
            "table": c["table"],
            "current_type": c["current_type"],
            "slot_count": c["slot_count"],
            "option_count": c["option_count"],
            "parsed_answer_keys": c["parsed_answer_keys"],
            "option_keys": c.get("option_keys", []),
            "canonical_answer": c["canonical_answer"],
        })
    ambiguous_details = []
    for a in import_ambiguous + question_ambiguous:
        ambiguous_details.append({
            "id": a["id"],
            "table": a["table"],
            "current_type": a["current_type"],
            "slot_count": a["slot_count"],
            "option_count": a["option_count"],
            "parsed_answer_keys": a["parsed_answer_keys"],
            "reason_detail": a.get("reason_detail", ""),
            "risks": a.get("risks", []),
        })
    return {
        "summary": {
            "mode": "apply" if apply else "dry_run",
            "scanned_imports": scanned_imports,
            "scanned_questions": scanned_questions,
            "total_scanned": scanned_imports + scanned_questions,
            "candidates_imports": len(import_candidates),
            "candidates_questions": len(question_candidates),
            "total_candidates": len(import_candidates) + len(question_candidates),
            "ambiguous_imports": len(import_ambiguous),
            "ambiguous_questions": len(question_ambiguous),
            "total_ambiguous": len(import_ambiguous) + len(question_ambiguous),
            "applied_imports": applied_imports,
            "applied_questions": applied_questions,
            "total_applied": applied_imports + applied_questions,
        },
        "candidates": candidate_details,
        "ambiguous": ambiguous_details,
    }


def _print_report(report: dict) -> None:
    """Print a human-readable summary of the report."""
    s = report["summary"]
    print()
    print("=" * 70)
    print(f"Mode: {s['mode']}")
    print(f"Scanned: {s['total_scanned']} ({s['scanned_imports']} imports + {s['scanned_questions']} questions)")
    print(f"Candidates: {s['total_candidates']} ({s['candidates_imports']} imports + {s['candidates_questions']} questions)")
    print(f"Ambiguous (skipped): {s['total_ambiguous']} ({s['ambiguous_imports']} imports + {s['ambiguous_questions']} questions)")
    if s["mode"] == "apply":
        print(f"Applied: {s['total_applied']} ({s['applied_imports']} imports + {s['applied_questions']} questions)")

    if report["ambiguous"]:
        print()
        print("--- Ambiguous records (requires manual review) ---")
        for a in report["ambiguous"]:
            print(f"  [{a['table']}#{a['id']}] type={a['current_type']} reason={a['reason_detail']}")

    if report["candidates"]:
        print()
        print("--- Candidate details ---")
        for c in report["candidates"]:
            print(
                f"  [{c['table']}#{c['id']}] "
                f"type={c['current_type']} → multi_blank_choice "
                f"slots={c['slot_count']} opts={c['option_count']} "
                f"answer={c['canonical_answer']} keys={c['option_keys']}"
            )


async def scan_and_backfill(
    *, apply: bool, batch_size: int, limit: int | None,
    import_ids: list[int] | None = None,
    question_ids: list[int] | None = None,
    report_json: str | None = None,
) -> dict:
    """Scan both tables and optionally apply transforms."""
    print()
    print("=== Scanning question_imports ===")
    import_candidates, import_ambiguous, scanned_imports = await scan_imports(
        apply, batch_size, limit, import_ids=import_ids,
    )
    print(f"  Done: {len(import_candidates)} candidate(s), {len(import_ambiguous)} ambiguous")

    print()
    print("=== Scanning questions ===")
    question_candidates, question_ambiguous, scanned_questions = await scan_questions(
        apply, batch_size, limit, question_ids=question_ids,
    )
    print(f"  Done: {len(question_candidates)} candidate(s), {len(question_ambiguous)} ambiguous")

    all_candidates = import_candidates + question_candidates
    all_ambiguous = import_ambiguous + question_ambiguous

    if not all_candidates:
        print()
        print("No candidates found.")
        report = _build_report(
            [], [], import_ambiguous, question_ambiguous,
            scanned_imports, scanned_questions, 0, 0, apply=apply,
        )
        if report_json:
            _write_report(report, report_json)
        return report["summary"]

    # Print summary
    print()
    print("=" * 70)
    print(f"Candidates: {len(all_candidates)}")
    print("=" * 70)
    for c in all_candidates:
        risks = ", ".join(c.get("risks", []) or [])
        print(
            f"  [{c['table']}#{c['id']}] "
            f"type={c['current_type']} → multi_blank_choice "
            f"slots={c['slot_count']} opts={c['option_count']} "
            f"answer={c['serialized_answer']}"
            + (f" risks=[{risks}]" if risks else "")
        )

    if not apply:
        print()
        print("DRY RUN — no changes written. Re-run with --apply to write.")
        report = _build_report(
            import_candidates, question_candidates,
            import_ambiguous, question_ambiguous,
            scanned_imports, scanned_questions, 0, 0, apply=False,
        )
        if report_json:
            _write_report(report, report_json)
        _print_report(report)
        return report["summary"]

    # ── Apply ──
    print()
    print("=== Applying transforms ===")

    applied_imports = 0
    applied_questions = 0

    async with async_session() as db:
        # Apply import transforms
        for c in import_candidates:
            record: QuestionImport = c["_record"]
            transform = _transform_import(record, c)
            await apply_import_transform(db, record, transform)
            applied_imports += 1
            if applied_imports % 100 == 0:
                print(f"  [imports] applied={applied_imports}/{len(import_candidates)}")

        # Commit import changes
        if applied_imports > 0:
            await db.commit()
            print(f"  [imports] committed {applied_imports} changes")

        # Apply question transforms
        for c in question_candidates:
            record = await db.merge(c["_record"])
            slot_ids = c["slot_ids"]
            options_raw = _extract_options_from_question(record)
            groups = build_blank_option_groups(slot_ids, options_raw or [])

            content = dict(record.content or {})
            stem = _stem_text_from_content(record.content)
            content["text"] = stem
            content["blank_option_groups"] = groups

            record.question_type = "multi_blank_choice"
            record.content = content
            record.options = None
            record.answer = c["serialized_answer"]

            # Recalculate hash
            question_hash = normalizer.build_question_hash(
                stem=stem, options=None, answer=record.answer,
                blank_option_groups=groups,
            )
            record.question_hash = question_hash or record.question_hash

            # Bump sync version
            record.sync_version = (record.sync_version or 0) + 1

            applied_questions += 1
            if applied_questions % 100 == 0:
                print(f"  [questions] applied={applied_questions}/{len(question_candidates)}")

        if applied_questions > 0:
            await db.commit()
            print(f"  [questions] committed {applied_questions} changes")

    print()
    print(f"Applied: {applied_imports} imports + {applied_questions} questions")

    report = _build_report(
        import_candidates, question_candidates,
        import_ambiguous, question_ambiguous,
        scanned_imports, scanned_questions,
        applied_imports, applied_questions, apply=True,
    )
    if report_json:
        _write_report(report, report_json)
    _print_report(report)

    return report["summary"]


def _write_report(report: dict, path: str) -> None:
    """Write the report to a JSON file."""
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Report written to: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill misclassified multi-blank choice questions"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Scan and report only (default mode)")
    mode.add_argument("--apply", action="store_true", help="Write changes to database")
    parser.add_argument("--batch-size", type=int, default=200, help="Batch size per query")
    parser.add_argument("--limit", type=int, default=None, help="Max records to scan")
    parser.add_argument(
        "--question-id", type=int, action="append", dest="question_ids",
        help="Only check specific question IDs (repeatable)",
    )
    parser.add_argument(
        "--import-id", type=int, action="append", dest="import_ids",
        help="Only check specific import IDs (repeatable)",
    )
    parser.add_argument("--report-json", type=str, default=None, help="Path to write JSON report")
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip confirmation prompt in apply mode (for non-interactive use)",
    )
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be > 0")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be > 0")
    if args.question_ids and args.limit:
        parser.error("--question-id and --limit are mutually exclusive")
    if args.import_ids and args.limit:
        parser.error("--import-id and --limit are mutually exclusive")

    if args.apply:
        print("=" * 70)
        print("APPLY mode: will write changes to database.")
        print("Recommendation: take a backup before running.")
        print("=" * 70)
        print()
        if not args.yes:
            response = input("Type 'yes' to continue: ")
            if response.strip().lower() != "yes":
                print("Aborted.")
                return
            print()
    else:
        print("=" * 70)
        print("DRY RUN mode: scan only, no database writes.")
        print("=" * 70)

    asyncio.run(
        scan_and_backfill(
            apply=args.apply,
            batch_size=args.batch_size,
            limit=args.limit,
            import_ids=args.import_ids,
            question_ids=args.question_ids,
            report_json=args.report_json,
        )
    )

    if args.apply:
        print()
        print("=" * 70)
        print("REMINDER: Run --dry-run again to verify idempotency.")
        print("=  (no new candidates should be found on second pass)")
        print("=" * 70)
