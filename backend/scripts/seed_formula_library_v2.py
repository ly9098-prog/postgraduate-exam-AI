#!/usr/bin/env python3
"""
seed_formula_library_v2 — Idempotent seed for math2_core_v2 extensions.

Reads math2_core_v2_extensions.json and populates the database with new
categories, formula cards, tag associations, and version snapshots.

Identity lookup (in order):
  1. Exact `source_ref` match → linked to existing (skip, no seed_hash field)
  2. Normalized title + compatible category → skipped (already exists)
  3. Otherwise → create new

Usage:
    python scripts/seed_formula_library_v2.py --dry-run       # preview only
    python scripts/seed_formula_library_v2.py --apply         # create as draft
    python scripts/seed_formula_library_v2.py --apply --allow-production  # force

Idempotent: safe to run multiple times.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import init_db, async_session
from app.core.time_utils import utcnow
from app.models.formula import (
    FormulaCard,
    FormulaCardTag,
    FormulaCardVersion,
    FormulaCategory,
    FormulaTag,
)

DATA_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "formula_library" / "math2_core_v2_extensions.json"


# ── helpers ──────────────────────────────────────────────────────────


def compute_content_hash(formula_blocks: list[dict]) -> str:
    raw = json.dumps(formula_blocks, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def build_snapshot(card: FormulaCard, tag_objs: list[FormulaTag]) -> dict:
    return {
        "id": card.id,
        "exam_scope": card.exam_scope,
        "category_id": card.category_id,
        "title": card.title,
        "aliases": card.aliases,
        "search_text": card.search_text,
        "card_type": card.card_type,
        "summary": card.summary,
        "formula_blocks": card.formula_blocks,
        "conditions": card.conditions,
        "symbol_notes": card.symbol_notes,
        "secondary_conclusions": card.secondary_conclusions,
        "error_tips": card.error_tips,
        "examples": card.examples,
        "function_properties": card.function_properties,
        "sort_order": card.sort_order,
        "status": card.status,
        "tags": [{"id": t.id, "code": t.code, "name": t.name, "sort_order": t.sort_order}
                 for t in tag_objs],
        "version": card.version,
    }


def normalize_title(title: str) -> str:
    """Normalize formula card title for loose comparison."""
    import re
    t = title.strip()
    t = re.sub(r'\s+', '', t)  # Remove all whitespace
    t = t.lower()
    return t


# ── core logic ───────────────────────────────────────────────────────


async def resolve_category(
    db: AsyncSession,
    subject_data: dict,
    chapter_data: dict,
    group_data: dict,
    stats: dict,
) -> FormulaCategory:
    """Find or create the subject→chapter→group category chain by code.

    Returns the group-level FormulaCategory.
    """
    # Subject (parent=None)
    subj_code = subject_data["code"]
    subj = await _find_category(db, None, subj_code)
    if not subj:
        subj = FormulaCategory(
            parent_id=None,
            exam_scope="math2",
            node_type="subject",
            code=subj_code,
            name=subject_data["name"],
            is_active=True,
        )
        db.add(subj)
        await db.flush()
        stats["categories_created"] += 1

    # Chapter (parent=subject)
    chap_code = chapter_data["code"]
    chap = await _find_category(db, subj.id, chap_code)
    if not chap:
        chap = FormulaCategory(
            parent_id=subj.id,
            exam_scope="math2",
            node_type="chapter",
            code=chap_code,
            name=chapter_data["name"],
            is_active=True,
        )
        db.add(chap)
        await db.flush()
        stats["categories_created"] += 1

    # Group (parent=chapter)
    group_code = group_data["code"]
    group = await _find_category(db, chap.id, group_code)
    if not group:
        group = FormulaCategory(
            parent_id=chap.id,
            exam_scope="math2",
            node_type="group",
            code=group_code,
            name=group_data["name"],
            is_active=True,
        )
        db.add(group)
        await db.flush()
        stats["categories_created"] += 1
    else:
        stats.get("categories_reused", 0)
        stats.setdefault("categories_reused", 0)

    # Count reuse (if not newly created)
    if subj.id and chap.id and group.id:
        pass  # Already counted created above

    return group


async def _find_category(db: AsyncSession, parent_id: int | None, code: str) -> FormulaCategory | None:
    r = await db.execute(
        select(FormulaCategory).where(
            FormulaCategory.parent_id == parent_id,
            FormulaCategory.code == code,
        )
    )
    return r.scalar_one_or_none()


async def resolve_tags(db: AsyncSession, tag_codes: list[str], stats: dict) -> list[FormulaTag]:
    """Resolve tag codes to FormulaTag objects, creating new tags if needed."""
    result = []
    for code in tag_codes:
        r = await db.execute(select(FormulaTag).where(FormulaTag.code == code))
        tag = r.scalar_one_or_none()
        if not tag:
            # Create name from code
            name_map = {
                "syllabus_required": "大纲必备",
                "common_inference": "常用推论",
                "basic": "基础",
                "high_frequency": "高频",
                "error_prone": "易错",
                "must_memorize": "必背",
            }
            name = name_map.get(code, code)
            tag = FormulaTag(code=code, name=name)
            db.add(tag)
            await db.flush()
            stats["tags_created"] += 1
        result.append(tag)
    return result


async def resolve_card_action(
    db: AsyncSession,
    card_data: dict,
    group_cat: FormulaCategory,
    tag_objs: list[FormulaTag],
    stats: dict,
) -> str:
    """Determine action for a card: 'create', 'skip', or 'conflict'.

    Returns the action string and updates stats accordingly.
    Does NOT create/update the card — that's handled by the caller.
    """
    source_ref = card_data.get("source_ref", "")
    title = card_data["title"]

    # Lookup 1: exact source_ref match
    if source_ref:
        r = await db.execute(
            select(FormulaCard).where(
                FormulaCard.source_ref == source_ref,
                FormulaCard.deleted_at.is_(None),
            )
        )
        existing = r.scalar_one_or_none()
        if existing:
            # Without seed_hash field, we can't detect manual edits reliably.
            # Report as "linked to existing" for manual review.
            stats.setdefault("linked_to_existing", []).append(title)
            return "skip"

    # Lookup 2: normalized title + compatible category
    norm = normalize_title(title)
    r = await db.execute(
        select(FormulaCard).where(
            FormulaCard.category_id == group_cat.id,
            FormulaCard.deleted_at.is_(None),
        )
    )
    same_group_cards = list(r.scalars().all())
    for c in same_group_cards:
        if normalize_title(c.title) == norm:
            stats.setdefault("skipped", []).append(title)
            return "skip"

    # Also check wider: any card with same title under parent chapter
    parent_cat = await db.get(FormulaCategory, group_cat.parent_id)
    if parent_cat:
        # Find all group IDs under this chapter
        r2 = await db.execute(
            select(FormulaCategory.id).where(
                FormulaCategory.parent_id == parent_cat.id,
                FormulaCategory.node_type == "group",
            )
        )
        sibling_group_ids = [row[0] for row in r2.all()]
        if sibling_group_ids:
            r3 = await db.execute(
                select(FormulaCard).where(
                    FormulaCard.category_id.in_(sibling_group_ids),
                    FormulaCard.deleted_at.is_(None),
                )
            )
            for c in r3.scalars().all():
                if normalize_title(c.title) == norm:
                    # Same title exists in a sibling group — treat as conflict
                    stats.setdefault("conflicts", []).append(
                        f"{title} (exists in category_id={c.category_id})"
                    )
                    return "conflict"

    return "create"


async def process_card(
    db: AsyncSession,
    card_data: dict,
    group_cat: FormulaCategory,
    tag_objs: list[FormulaTag],
    target_status: str,
    stats: dict,
    dry_run: bool,
) -> None:
    """Process a single card."""
    title = card_data["title"]
    action = await resolve_card_action(db, card_data, group_cat, tag_objs, stats)

    if action == "skip":
        return
    if action == "conflict":
        return

    # Create
    formula_blocks = card_data.get("formula_blocks", [])
    content_hash = compute_content_hash(formula_blocks)
    source_ref = card_data.get("source_ref", "")
    now = utcnow()

    if not dry_run:
        card = FormulaCard(
            exam_scope="math2",
            category_id=group_cat.id,
            title=title,
            aliases=card_data.get("aliases"),
            search_text=card_data.get("search_text", ""),
            card_type=card_data.get("card_type", "pure_formula"),
            summary=card_data.get("summary"),
            formula_blocks=formula_blocks,
            conditions=card_data.get("conditions"),
            symbol_notes=card_data.get("symbol_notes"),
            secondary_conclusions=card_data.get("secondary_conclusions"),
            error_tips=card_data.get("error_tips"),
            examples=card_data.get("examples"),
            sort_order=card_data.get("sort_order", 0),
            status=target_status,
            source_type="manual",
            source_title=card_data.get("source_title"),
            source_ref=source_ref,
            content_hash=content_hash,
            version=1,
            created_at=now,
            updated_at=now,
        )
        db.add(card)
        await db.flush()

        # Tag associations
        for tag in tag_objs:
            db.add(FormulaCardTag(formula_card_id=card.id, tag_id=tag.id))

        # Version snapshot
        snapshot = build_snapshot(card, tag_objs)
        db.add(
            FormulaCardVersion(
                formula_card_id=card.id,
                version=1,
                snapshot=snapshot,
                action="create",
                edited_by=None,
            )
        )

    stats["created"] += 1
    stats["created_titles"].append(title)


# ── main ─────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description="Seed math2_core_v2 formula card extensions")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--apply", action="store_true", help="Actually apply changes")
    parser.add_argument("--allow-production", action="store_true", help="Override production guard")
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        parser.print_help()
        sys.exit(1)

    is_dry_run = args.dry_run
    is_apply = args.apply
    allow_prod = args.allow_production

    # Load data
    if not DATA_FILE.exists():
        print(f"ERROR: Data file not found: {DATA_FILE}")
        sys.exit(1)

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    subjects_data = raw.get("subjects", [])

    # Environment check
    app_env = os.environ.get("APP_ENV", "development")
    db_url = os.environ.get("DATABASE_URL", "unknown")
    db_scheme = db_url.split("://")[0] if "://" in db_url else db_url
    print(f"APP_ENV: {app_env}")
    print(f"Database: {db_scheme}://...")

    if is_apply:
        print(f"Mode: APPLY {'(DRY RUN — no changes)' if is_dry_run else ''}")
    else:
        print("Mode: DRY RUN — no changes will be made")

    if app_env == "production" and is_apply and not is_dry_run:
        if not allow_prod:
            print("ERROR: Refusing to write to production database.")
            print("  Set --allow-production to override (resulting cards will still be draft).")
            sys.exit(1)
        print("  WARNING: Production override enabled.")

    # Determine target status
    target_status = "draft"  # Always draft by default for v2
    print(f"Target status: {target_status}")

    if not is_apply:
        print("\n=== DRY RUN: Would process ===")
    else:
        print("\n=== Processing ===")

    # Stats
    stats = {
        "created": 0,
        "updated": 0,
        "skipped": [],
        "conflicts": [],
        "linked_to_existing": [],
        "created_titles": [],
        "categories_created": 0,
        "categories_reused": 0,
        "tags_created": 0,
    }

    # Init DB
    await init_db()

    async with async_session() as db:
        # All work in a single transaction
        transaction = await db.begin()
        try:
            for subject in subjects_data:
                for chapter in subject.get("chapters", []):
                    for group in chapter.get("groups", []):
                        group_cat = await resolve_category(
                            db, subject, chapter, group, stats
                        )

                        for card_data in group.get("cards", []):
                            tag_codes = card_data.get("tags", [])
                            tag_objs = await resolve_tags(db, tag_codes, stats)

                            if is_dry_run:
                                action = await resolve_card_action(
                                    db, card_data, group_cat, tag_objs, stats
                                )
                                if action == "create":
                                    stats["created"] += 1
                                    stats["created_titles"].append(card_data["title"])
                                continue

                            await process_card(
                                db, card_data, group_cat, tag_objs,
                                target_status, stats, dry_run=False,
                            )

            if is_dry_run:
                await transaction.rollback()
                from app.core.database import async_session as _  # noqa: keep import
            else:
                await transaction.commit()
        except Exception:
            await transaction.rollback()
            raise

    # ── report ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Seed complete!")
    print("=" * 60)
    print(f"Created:   {stats['created']}")
    print(f"Updated:   {stats['updated']}")
    print(f"Skipped:   {len(stats['skipped'])}")
    for t in stats['skipped']:
        print(f"  └ {t}")
    print(f"Conflicts: {len(stats['conflicts'])}")
    for t in stats['conflicts']:
        print(f"  └ {t}")
    print(f"Linked to existing: {len(stats['linked_to_existing'])}")
    for t in stats['linked_to_existing']:
        print(f"  └ {t}")
    print("---")
    print(f"Categories created: {stats['categories_created']}")
    print(f"Categories reused:  {stats.get('categories_reused', 0)}")
    print(f"Tags created:       {stats['tags_created']}")

    print(f"\n  Dry run: {'yes' if is_dry_run else 'no'}")
    print(f"  Applied: {'yes' if is_apply and not is_dry_run else 'no'}")

    if stats['conflicts']:
        print(f"\n  ⚠ {len(stats['conflicts'])} conflict(s) require manual review.")
    if stats['linked_to_existing']:
        print(f"  ℹ {len(stats['linked_to_existing'])} card(s) linked to existing records (manual review needed).")

    # Verify target accounting
    total_targets = 22
    accounted = (
        stats['created']
        + stats['updated']
        + len(stats['skipped'])
        + len(stats['conflicts'])
        + len(stats['linked_to_existing'])
    )
    if accounted != total_targets:
        print(f"\n  ⚠ Target accounting mismatch: {accounted} != {total_targets}")


if __name__ == "__main__":
    asyncio.run(main())
