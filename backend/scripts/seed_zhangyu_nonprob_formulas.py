#!/usr/bin/env python3
"""
seed_zhangyu_nonprob_formulas — Idempotent seed for non-probability formula
extensions from the 27张宇数学公式手册.

Reads zhangyu_nonprob_extensions_v1.json and populates categories and formula
cards for sections that the earlier "math2-only" audit excluded but the PDF's
full table of contents covers:
  - 向量代数和空间解析几何
  - 偏导数在几何中的应用
  - 三重积分、重积分的应用、曲线积分与曲面积分
  - 数项级数、幂级数、傅里叶级数
  - 差分方程
  - n维向量空间

Scope: the PDF is the coverage boundary. 概率论与数理统计 is the ONLY
excluded part (not covered by this data file).

Idempotent: safe to run multiple times — deduplicates by source_ref first,
then category_id + normalized title.

Usage:
    python scripts/seed_zhangyu_nonprob_formulas.py --dry-run   # preview only
    python scripts/seed_zhangyu_nonprob_formulas.py --apply     # create as draft
    python scripts/seed_zhangyu_nonprob_formulas.py --apply --allow-production
"""
import argparse
import asyncio
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

DATA_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "formula_library" / "zhangyu_nonprob_extensions_v1.json"


# ── helpers ──────────────────────────────────────────────────────────


def compute_content_hash(formula_blocks: list[dict]) -> str:
    import hashlib
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
    import re
    return re.sub(r'\s+', '', title.strip()).lower()


# ── core logic ───────────────────────────────────────────────────────


async def find_category(db: AsyncSession, parent_id: int | None, code: str) -> FormulaCategory | None:
    r = await db.execute(
        select(FormulaCategory).where(
            FormulaCategory.parent_id == parent_id,
            FormulaCategory.code == code,
        )
    )
    return r.scalar_one_or_none()


async def resolve_category_chain(
    db: AsyncSession,
    subject_data: dict,
    chapter_data: dict,
    group_data: dict,
    stats: dict,
) -> FormulaCategory:
    # Subject (existing roots are found by code; new ones inherit math2 scope)
    subj = await find_category(db, None, subject_data["code"])
    if not subj:
        subj = FormulaCategory(
            parent_id=None, exam_scope="math2", node_type="subject",
            code=subject_data["code"], name=subject_data["name"], is_active=True,
        )
        db.add(subj)
        await db.flush()
        stats["categories_created"].append(f"subject:{subject_data['code']}")

    # Chapter — reuse existing chapter (by code) if present
    chap = await find_category(db, subj.id, chapter_data["code"])
    if not chap:
        chap = FormulaCategory(
            parent_id=subj.id, exam_scope="math2", node_type="chapter",
            code=chapter_data["code"], name=chapter_data["name"], is_active=True,
        )
        db.add(chap)
        await db.flush()
        stats["categories_created"].append(f"chapter:{chapter_data['code']}")

    # Group
    grp = await find_category(db, chap.id, group_data["code"])
    if not grp:
        grp = FormulaCategory(
            parent_id=chap.id, exam_scope="math2", node_type="group",
            code=group_data["code"], name=group_data["name"], is_active=True,
        )
        db.add(grp)
        await db.flush()
        stats["categories_created"].append(f"group:{group_data['code']}")

    return grp


async def resolve_tags(db: AsyncSession, tag_codes: list[str], stats: dict) -> list[FormulaTag]:
    result = []
    for code in tag_codes:
        r = await db.execute(select(FormulaTag).where(FormulaTag.code == code))
        tag = r.scalar_one_or_none()
        if not tag:
            name_map = {
                "syllabus_required": "大纲必备", "common_inference": "常用推论",
                "basic": "基础", "high_frequency": "高频",
                "error_prone": "易错", "must_memorize": "必背",
            }
            tag = FormulaTag(code=code, name=name_map.get(code, code))
            db.add(tag)
            await db.flush()
            stats["tags_created"] += 1
        result.append(tag)
    return result


async def process_card(
    db: AsyncSession,
    card_data: dict,
    group_cat: FormulaCategory,
    tag_objs: list[FormulaTag],
    target_status: str,
    stats: dict,
) -> None:
    title = card_data["title"]
    source_ref = card_data.get("source_ref", "")

    # 1. source_ref is the primary identity
    if source_ref:
        r = await db.execute(
            select(FormulaCard).where(
                FormulaCard.source_ref == source_ref,
                FormulaCard.deleted_at.is_(None),
            )
        )
        if r.scalar_one_or_none():
            stats["skipped"].append(title)
            return

    # 2. category_id + normalized title
    norm = normalize_title(title)
    r = await db.execute(
        select(FormulaCard).where(
            FormulaCard.category_id == group_cat.id,
            FormulaCard.deleted_at.is_(None),
        )
    )
    for c in r.scalars().all():
        if normalize_title(c.title) == norm:
            stats["skipped"].append(title)
            return

    # Create
    formula_blocks = card_data.get("formula_blocks", [])
    content_hash = compute_content_hash(formula_blocks)
    now = utcnow()

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

    for tag in tag_objs:
        db.add(FormulaCardTag(formula_card_id=card.id, tag_id=tag.id))

    snapshot = build_snapshot(card, tag_objs)
    db.add(
        FormulaCardVersion(
            formula_card_id=card.id, version=1, snapshot=snapshot, action="create", edited_by=None,
        )
    )

    stats["created"].append(title)


async def main():
    parser = argparse.ArgumentParser(
        description="Seed non-probability Zhangyu formula extensions from v1 data file"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--apply", action="store_true", help="Apply changes")
    parser.add_argument("--allow-production", action="store_true")
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        parser.print_help()
        sys.exit(1)

    with open(DATA_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    subjects_data = raw.get("subjects", [])

    app_env = os.environ.get("APP_ENV", "development")
    db_url = os.environ.get("DATABASE_URL", "unknown")
    db_scheme = db_url.split("://")[0] if "://" in db_url else db_url
    print(f"APP_ENV: {app_env}  |  Database: {db_scheme}://...")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")

    if app_env == "production" and args.apply and not args.dry_run:
        if not args.allow_production:
            print("ERROR: Refusing to write to production. Use --allow-production to override.")
            sys.exit(1)

    target_status = "draft"
    stats = {
        "created": [], "skipped": [],
        "categories_created": [], "tags_created": 0,
    }

    await init_db()
    async with async_session() as db:
        transaction = await db.begin()
        try:
            for subject in subjects_data:
                for chapter in subject.get("chapters", []):
                    for group in chapter.get("groups", []):
                        group_cat = await resolve_category_chain(db, subject, chapter, group, stats)
                        for card_data in group.get("cards", []):
                            tag_objs = await resolve_tags(db, card_data.get("tags", []), stats)
                            if args.dry_run:
                                exists = False
                                src_ref = card_data.get("source_ref", "")
                                if src_ref:
                                    r = await db.execute(
                                        select(FormulaCard).where(
                                            FormulaCard.source_ref == src_ref,
                                            FormulaCard.deleted_at.is_(None),
                                        )
                                    )
                                    if r.scalar_one_or_none():
                                        exists = True
                                if not exists:
                                    norm = normalize_title(card_data["title"])
                                    r = await db.execute(
                                        select(FormulaCard).where(
                                            FormulaCard.category_id == group_cat.id,
                                            FormulaCard.deleted_at.is_(None),
                                        )
                                    )
                                    if any(
                                        normalize_title(c.title) == norm
                                        for c in r.scalars().all()
                                    ):
                                        exists = True
                                if exists:
                                    stats["skipped"].append(card_data["title"])
                                else:
                                    stats["created"].append(card_data["title"])
                                continue
                            await process_card(db, card_data, group_cat, tag_objs, target_status, stats)

            if args.dry_run:
                await transaction.rollback()
            else:
                await transaction.commit()
        except Exception:
            await transaction.rollback()
            raise

    print(f"\n{'=' * 60}")
    print("Seed complete!")
    print(f"  Created:   {len(stats['created'])}")
    print(f"  Skipped:   {len(stats['skipped'])}")
    print(f"  Categories created: {len(stats['categories_created'])}")
    print(f"  Tags created:       {stats['tags_created']}")
    if stats['categories_created']:
        print("  New categories:")
        for c in stats['categories_created']:
            print(f"    └ {c}")
    if stats['created']:
        print("  Cards:")
        for t in stats['created']:
            print(f"    └ {t}")
    if stats['skipped']:
        print("  Skipped (existing):")
        for t in stats['skipped']:
            print(f"    └ {t}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
