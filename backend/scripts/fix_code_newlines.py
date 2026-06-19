"""Targeted fix for code-newline corruption in specific questions from display audit.

Matches questions by exact content fingerprints (from pending_display_issue_fix_task.md)
and applies _normalize_code_newlines to rejoin operator-operand splits.

Case 2: [2011] while (x < n/2)  →  split into  (x < n  / 2)
Case 3: [2012] if (n <= 1)       →  split into  (n <=  1)

Case 4 cannot be auto-fixed — it has content duplication and cross-question
pollution that require manual review.

MUST be run against the server PostgreSQL database (not local SQLite).

Usage (run on server after deploy):
    ssh xzshub.top
    docker exec deploy-app-1 python -m scripts.fix_code_newlines --dry-run
    docker exec deploy-app-1 python -m scripts.fix_code_newlines
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.features.question_pipeline import QuestionNormalizer  # noqa: E402

# ── Fingerprints from pending_display_issue_fix_task.md ─────────────────────

FINGERPRINTS: list[tuple[str, re.Pattern]] = [
    # Case 2: [2011 统考真题] time complexity — while (x < n/2)
    (
        "case_2_2011_while",
        re.compile(r"【2011\s*统考真题】.*下列程序段的时间复杂度"),
    ),
    # Case 3: [2012 统考真题] factorial — int fact(int n) { if (n <=
    (
        "case_3_2012_factorial",
        re.compile(r"【2012\s*统考真题】.*阶乘"),
    ),
]


async def run(dry_run: bool = False) -> None:
    normalizer = QuestionNormalizer()

    async with async_session() as db:
        result = await db.execute(
            select(Question).where(Question.is_active.is_(True))
        )
        questions = result.scalars().all()

    # ── Match against fingerprints ──────────────────────────────────────
    matched: dict[str, list[Question]] = {key: [] for key, _ in FINGERPRINTS}
    unmatched_ids: set[int] = set()

    for q in questions:
        content = q.content
        if not isinstance(content, dict):
            continue
        text = content.get("text", "")
        if not text:
            continue

        found = False
        for key, pattern in FINGERPRINTS:
            if pattern.search(text):
                matched[key].append(q)
                found = True
                break
        if not found:
            unmatched_ids.add(q.id)

    # ── Report matches ──────────────────────────────────────────────────
    total = sum(len(v) for v in matched.values())
    if total == 0:
        print("No questions matched the display-issue fingerprints.")
        print(
            "They may not be imported yet, or the content has changed "
            "since the audit."
        )
        return

    print(f"Matched {total} question(s) across {len(matched)} case(s):\n")
    for key, qs in matched.items():
        if qs:
            print(f"  {key}: {len(qs)} question(s) (IDs: {[q.id for q in qs]})")

    # ── Apply _normalize_code_newlines ──────────────────────────────────
    changes: list[tuple[str, int, str, str]] = []

    for key, qs in matched.items():
        for q in qs:
            text = q.content.get("text", "")
            normalized = normalizer._normalize_code_newlines(text)
            if normalized != text:
                changes.append((key, q.id, text, normalized))

    if not changes:
        print("\nAll matched questions already have clean code newlines.")
        return

    print(f"\n{len(changes)} row(s) need repair:\n")
    for key, qid, before, after in changes:
        # Show only the changed portion
        for i, (b_line, a_line) in enumerate(
            zip(before.split("\n"), after.split("\n"))
        ):
            if b_line != a_line:
                print(f"  [{key}] #{qid} line {i}:")
                print(f"    BEFORE: {repr(b_line[:120])}")
                print(f"    AFTER:  {repr(a_line[:120])}")
                break
        print()

    if dry_run:
        print(f"Dry-run — {len(changes)} row(s) would be updated.")
        return

    # ── Write back (same session kept open via re-attach) ───────────────
    async with async_session() as db:
        for key, qid, _before, after in changes:
            q = await db.get(Question, qid)
            if q is None:
                print(f"  WARNING: question #{qid} not found, skipped")
                continue
            if not isinstance(q.content, dict):
                continue
            q.content = {**q.content, "text": after}
            flag_modified(q, "content")
        await db.commit()

    print(f"Updated {len(changes)} question(s).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix code-newline corruption in display-audit questions"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
