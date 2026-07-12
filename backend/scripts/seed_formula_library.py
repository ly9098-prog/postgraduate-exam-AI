"""
seed_formula_library — Idempotent seed for the formula library.

Reads math2_core_v1.json and populates the database with category tree,
formula cards, tag associations, and version snapshots.

Usage:
    python scripts/seed_formula_library.py              # published (dev default)
    SEED_ENV=production python scripts/seed_formula_library.py  # pending_review

Idempotent: safe to run multiple times — existing cards are skipped.
"""
import asyncio
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import init_db, async_session
from app.core.time_utils import utcnow
from app.models.formula import (
    FormulaCard,
    FormulaCardTag,
    FormulaCardVersion,
    FormulaCategory,
    FormulaTag,
)

DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app",
    "data",
    "formula_library",
    "math2_core_v1.json",
)


def compute_content_hash(formula_blocks: list[dict]) -> str:
    raw = json.dumps(formula_blocks, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def load_data() -> dict:
    """Parse the Python-ish seed file and return the MATH2_CORE dict."""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove docstring ("""...""")
    content = re.sub(r'^""".*?"""', "", content, flags=re.DOTALL).strip()
    # Remove Python assignment prefix (MATH2_CORE =)
    content = re.sub(r"^\w+\s*=\s*", "", content)
    return json.loads(content)


async def load_tags(db) -> dict[str, FormulaTag]:
    result = await db.execute(select(FormulaTag))
    return {t.code: t for t in result.scalars().all()}


async def find_or_create_category(
    db,
    parent_id: int | None,
    code: str,
    name: str,
    node_type: str,
    exam_scope: str = "math2",
    sort_order: int = 0,
) -> FormulaCategory:
    result = await db.execute(
        select(FormulaCategory).where(
            FormulaCategory.parent_id == parent_id,
            FormulaCategory.code == code,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    cat = FormulaCategory(
        parent_id=parent_id,
        exam_scope=exam_scope,
        node_type=node_type,
        code=code,
        name=name,
        sort_order=sort_order,
        is_active=True,
    )
    db.add(cat)
    await db.flush()
    return cat


def build_snapshot(card: FormulaCard, tag_ids: list[int], tag_map: dict) -> dict:
    tags = []
    for tid in tag_ids:
        tag = next((t for t in tag_map.values() if t.id == tid), None)
        if tag:
            tags.append(
                {
                    "id": tag.id,
                    "code": tag.code,
                    "name": tag.name,
                    "sort_order": tag.sort_order,
                }
            )
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
        "tags": tags,
        "version": card.version,
    }


async def main():
    print("=" * 60)
    print("2240AI — Formula Library Seed Script")
    print("=" * 60)

    # Determine target status from environment
    seed_env = os.environ.get("SEED_ENV", "") or os.environ.get("APP_ENV", "development")
    target_status = "published" if seed_env == "development" else "pending_review"
    print(f"\nEnvironment: {seed_env} → seeding status='{target_status}'")

    # Load data file
    if not os.path.exists(DATA_FILE):
        print(f"ERROR: Data file not found: {DATA_FILE}")
        sys.exit(1)

    raw = load_data()
    subjects_data = raw.get("subjects", [])
    print(f"Loaded {len(subjects_data)} subjects from {DATA_FILE}")

    # Init DB
    await init_db()
    async with async_session() as db:
        tag_map = await load_tags(db)
        print(f"Loaded {len(tag_map)} tags: {list(tag_map.keys())}")

        stats = {
            "subjects": 0,
            "chapters": 0,
            "groups": 0,
            "cards_created": 0,
            "cards_skipped": 0,
        }

        for si, subject in enumerate(subjects_data):
            subj_code = subject["code"]
            subj_name = subject["name"]

            subj_cat = await find_or_create_category(
                db, None, subj_code, subj_name, "subject", sort_order=si,
            )
            stats["subjects"] += 1
            print(f"\n  [{subj_code}] {subj_name}")

            for ci, chapter in enumerate(subject.get("chapters", [])):
                chap_code = chapter["code"]
                chap_name = chapter["name"]

                chap_cat = await find_or_create_category(
                    db, subj_cat.id, chap_code, chap_name, "chapter", sort_order=ci,
                )
                stats["chapters"] += 1
                print(f"    └─ [{chap_code}] {chap_name}")

                for gi, group in enumerate(chapter.get("groups", [])):
                    group_code = group["code"]
                    group_name = group["name"]

                    group_cat = await find_or_create_category(
                        db, chap_cat.id, group_code, group_name, "group", sort_order=gi,
                    )
                    stats["groups"] += 1

                    for card_data in group.get("cards", []):
                        title = card_data["title"]
                        formula_blocks = card_data.get("formula_blocks", [])
                        content_hash = compute_content_hash(formula_blocks)

                        # Check existing — idempotent guard
                        existing = await db.execute(
                            select(FormulaCard).where(
                                FormulaCard.category_id == group_cat.id,
                                FormulaCard.title == title,
                                FormulaCard.deleted_at.is_(None),
                            )
                        )
                        if existing.scalar_one_or_none():
                            stats["cards_skipped"] += 1
                            continue

                        # Resolve tag IDs
                        tag_ids = []
                        for tag_code in card_data.get("tags", []):
                            tag = tag_map.get(tag_code)
                            if tag:
                                tag_ids.append(tag.id)
                            else:
                                print(f"      ⚠ Tag '{tag_code}' not found for '{title}'")

                        # Create card
                        now = utcnow()
                        card = FormulaCard(
                            exam_scope="math2",
                            category_id=group_cat.id,
                            title=title,
                            aliases=card_data.get("aliases"),
                            search_text=card_data.get("search_text"),
                            card_type=card_data.get("card_type", "pure_formula"),
                            summary=card_data.get("summary"),
                            formula_blocks=formula_blocks,
                            conditions=card_data.get("conditions"),
                            symbol_notes=card_data.get("symbol_notes"),
                            secondary_conclusions=card_data.get("secondary_conclusions"),
                            error_tips=card_data.get("error_tips"),
                            examples=card_data.get("examples"),
                            function_properties=card_data.get("function_properties"),
                            sort_order=card_data.get("sort_order", 0),
                            status=target_status,
                            source_type="manual",
                            source_title="数学二核心公式 v1",
                            content_hash=content_hash,
                            version=1,
                            created_at=now,
                            updated_at=now,
                            published_at=now if target_status == "published" else None,
                        )
                        db.add(card)
                        await db.flush()

                        # Tag associations
                        for tag_id in tag_ids:
                            db.add(
                                FormulaCardTag(
                                    formula_card_id=card.id, tag_id=tag_id,
                                )
                            )

                        # Version snapshot
                        snapshot = build_snapshot(card, tag_ids, tag_map)
                        db.add(
                            FormulaCardVersion(
                                formula_card_id=card.id,
                                version=1,
                                snapshot=snapshot,
                                action="create",
                                edited_by=None,
                            )
                        )

                        stats["cards_created"] += 1

                await db.commit()

    print(f"\n{'=' * 60}")
    print("Seed complete!")
    print(f"  Subjects: {stats['subjects']}")
    print(f"  Chapters: {stats['chapters']}")
    print(f"  Groups:   {stats['groups']}")
    print(f"  Cards created: {stats['cards_created']}")
    print(f"  Cards skipped: {stats['cards_skipped']}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
