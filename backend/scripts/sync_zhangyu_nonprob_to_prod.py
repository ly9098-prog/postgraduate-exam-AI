#!/usr/bin/env python3
"""Targeted sync of zhangyu nonprob formula extensions to production PostgreSQL.

Syncs ONLY the cards whose source_ref starts with
``zhangyu_formula_manual:nonprob:`` plus the category chain they live under
(subject/chapter/group). Unlike the full ``sync_formulas_to_prod.py`` this does
NOT touch graph assets, graph specs, existing cards, or existing versions —
those were intentionally left untouched to avoid inserting image asset rows
without the corresponding files.

Identity matching mirrors the established cross-env convention:
  - categories matched by (mapped_parent_id, code)
  - cards matched by source_ref (primary), then (title, mapped_category_id)
  - tags matched by code
Production numeric ids are NOT used to match anything.

Usage:
    # Dry run (default) — read-only
    python scripts/sync_zhangyu_nonprob_to_prod.py \
        --source sqlite+aiosqlite:///./postgraduate.db \
        --target "postgresql+asyncpg://user:pass@host:5432/db"

    # Apply
    ... --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

NONPROB_PREFIX = "zhangyu_formula_manual:nonprob:"


def _coerce_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    if isinstance(val, str):
        return val.lower() in ("1", "true", "t", "yes")
    return False


def _coerce_datetime(val):
    if val is None or isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None


class NonprobSyncer:
    def __init__(self, source_url: str, target_url: str, dry_run: bool = True):
        self.source_url = source_url
        self.target_url = target_url
        self.dry_run = dry_run
        self.stats = {
            "categories_created": 0, "categories_skipped": 0,
            "cards_created": 0, "cards_skipped": 0,
            "card_tags_created": 0, "card_tags_skipped": 0,
            "versions_created": 0, "versions_skipped": 0, "warnings": [],
        }
        self._category_map: dict[int, int] = {}
        self._tag_by_code: dict[str, int] = {}
        self._card_map: dict[int, int] = {}
        self._category_by_key: dict[tuple, int] = {}
        self._card_by_source_ref: dict[str, int] = {}

    def _init_engines(self):
        self.source_engine = create_async_engine(self.source_url, echo=False)
        self.target_engine = create_async_engine(self.target_url, echo=False)
        self.SourceSession = sessionmaker(
            self.source_engine, class_=AsyncSession, expire_on_commit=False
        )
        self.TargetSession = sessionmaker(
            self.target_engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self):
        await self.source_engine.dispose()
        await self.target_engine.dispose()

    async def _load_source_rows(self, table, order_by=None):
        async with self.SourceSession() as s:
            q = f"SELECT * FROM {table}"
            if order_by:
                q += f" ORDER BY {order_by}"
            r = await s.execute(text(q))
            cols = r.keys()
            return [dict(zip(cols, row)) for row in r.fetchall()]

    async def _insert(self, session, table, data):
        cols = ", ".join(data.keys())
        ph = ", ".join(f":{k}" for k in data)
        r = await session.execute(
            text(f"INSERT INTO {table} ({cols}) VALUES ({ph}) RETURNING id"), data
        )
        return r.scalar()

    async def _load_target_indexes(self):
        async with self.TargetSession() as t:
            r = await t.execute(
                text("SELECT id, parent_id, code FROM formula_categories")
            )
            for row in r.fetchall():
                self._category_by_key[(row.parent_id, row.code)] = row.id
            r = await t.execute(text("SELECT id, code FROM formula_tags"))
            for row in r.fetchall():
                self._tag_by_code[row.code] = row.id
            r = await t.execute(
                text("SELECT id, source_ref FROM formula_cards WHERE source_ref IS NOT NULL")
            )
            for row in r.fetchall():
                self._card_by_source_ref[row.source_ref] = row.id

    # ── categories ──

    async def sync_categories(self, source_cats, needed_ids):
        """Create the category chain for the needed categories (deepest-first
        parents resolved by code through the source parent tree)."""
        cat_by_id = {c["id"]: c for c in source_cats}

        def depth(cat, seen=None):
            seen = seen or set()
            d, p = 0, cat.get("parent_id")
            while p is not None:
                if p in seen or p not in cat_by_id:
                    break
                seen.add(p)
                d += 1
                p = cat_by_id[p].get("parent_id")
            return d

        ordered = sorted(needed_ids, key=lambda i: (depth(cat_by_id[i]), i))
        for cid in ordered:
            cat = cat_by_id[cid]
            parent = self._category_map.get(cat["parent_id"]) if cat["parent_id"] else None
            key = (parent, cat["code"])
            if key in self._category_by_key:
                self._category_map[cid] = self._category_by_key[key]
                self.stats["categories_skipped"] += 1
                continue
            if not self.dry_run:
                async with self.TargetSession() as t:
                    async with t.begin():
                        new_id = await self._insert(t, "formula_categories", {
                            "parent_id": parent,
                            "exam_scope": cat["exam_scope"],
                            "node_type": cat["node_type"],
                            "code": cat["code"],
                            "name": cat["name"],
                            "description": cat.get("description"),
                            "sort_order": cat["sort_order"],
                            "is_active": _coerce_bool(cat["is_active"]),
                        })
                self._category_map[cid] = new_id
                self._category_by_key[key] = new_id
            else:
                # dry-run: reserve a synthetic map entry so cards resolve
                self._category_map[cid] = -cid
            self.stats["categories_created"] += 1

    # ── cards ──

    async def sync_cards(self, source_cards, needed_ids):
        for cid in needed_ids:
            card = next(c for c in source_cards if c["id"] == cid)
            mapped_cat = self._category_map.get(card["category_id"])
            if mapped_cat is None:
                self.stats["warnings"].append(
                    f"Card '{card['title']}' (id={card['id']}): category not mapped"
                )
                self.stats["cards_skipped"] += 1
                continue
            src_ref = card.get("source_ref")
            if mapped_cat > 0 and src_ref and src_ref in self._card_by_source_ref:
                self.stats["cards_skipped"] += 1
                continue
            if mapped_cat > 0 and not self.dry_run:
                data = {
                    "exam_scope": card["exam_scope"],
                    "category_id": mapped_cat,
                    "title": card["title"],
                    "aliases": card.get("aliases"),
                    "search_text": card.get("search_text"),
                    "card_type": card["card_type"],
                    "summary": card.get("summary"),
                    "formula_blocks": card["formula_blocks"],
                    "conditions": card.get("conditions"),
                    "symbol_notes": card.get("symbol_notes"),
                    "secondary_conclusions": card.get("secondary_conclusions"),
                    "error_tips": card.get("error_tips"),
                    "examples": card.get("examples"),
                    "function_properties": card.get("function_properties"),
                    "sort_order": card["sort_order"],
                    "status": card["status"],
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "rejection_reason": None,
                    "published_at": _coerce_datetime(card.get("published_at")),
                    "created_by": None,
                    "updated_by": None,
                    "source_type": card.get("source_type"),
                    "source_title": card.get("source_title"),
                    "source_ref": src_ref,
                    "content_hash": card.get("content_hash"),
                    "graph_spec": card.get("graph_spec"),
                    "draft_graph_spec": card.get("draft_graph_spec"),
                    "graph_status": card["graph_status"],
                    "graph_last_error": card.get("graph_last_error"),
                    "graph_generated_at": _coerce_datetime(card.get("graph_generated_at")),
                    "graph_confirmed_at": _coerce_datetime(card.get("graph_confirmed_at")),
                    "version": card["version"],
                }
                async with self.TargetSession() as t:
                    async with t.begin():
                        new_id = await self._insert(t, "formula_cards", data)
                self._card_map[cid] = new_id
                self._card_by_source_ref[src_ref] = new_id
            else:
                # dry-run (or would-create): keep a synthetic marker for downstream
                self._card_map[cid] = -cid
            self.stats["cards_created"] += 1

    # ── card tags ──

    async def sync_card_tags(self, source_cts, card_ids):
        for ct in source_cts:
            if ct["formula_card_id"] not in card_ids:
                continue
            mapped_card = self._card_map.get(ct["formula_card_id"])
            if mapped_card is None:
                self.stats["card_tags_skipped"] += 1
                continue
            tag_row = next(
                (t for t in self._source_tags if t["id"] == ct["tag_id"]), None
            )
            if tag_row is None:
                self.stats["card_tags_skipped"] += 1
                continue
            mapped_tag = self._tag_by_code.get(tag_row["code"])
            if mapped_tag is None:
                self.stats["warnings"].append(
                    f"tag '{tag_row['code']}' missing on target"
                )
                self.stats["card_tags_skipped"] += 1
                continue
            if mapped_card > 0 and not self.dry_run:
                async with self.TargetSession() as t:
                    async with t.begin():
                        await self._insert(t, "formula_card_tags", {
                            "formula_card_id": mapped_card,
                            "tag_id": mapped_tag,
                        })
            self.stats["card_tags_created"] += 1

    # ── versions ──

    async def sync_versions(self, source_versions, card_ids):
        for v in source_versions:
            if v["formula_card_id"] not in card_ids:
                continue
            mapped_card = self._card_map.get(v["formula_card_id"])
            if mapped_card is None:
                # card was skipped this run (already on target) — versions
                # already synced on the run that created it; nothing to do
                self.stats["versions_skipped"] += 1
                continue
            if mapped_card > 0 and not self.dry_run:
                async with self.TargetSession() as t:
                    async with t.begin():
                        await self._insert(t, "formula_card_versions", {
                            "formula_card_id": mapped_card,
                            "version": v["version"],
                            "snapshot": v["snapshot"],
                            "action": v["action"],
                            "edited_by": v.get("edited_by"),
                            "edit_reason": v.get("edit_reason"),
                            "created_at": _coerce_datetime(v.get("created_at")),
                        })
            self.stats["versions_created"] += 1

    async def sync_all(self):
        self._init_engines()
        print(f"Source: {self.source_url}")
        print(f"Target: {self.target_url}")
        print(f"Dry-run: {self.dry_run}")
        print()
        await self._load_target_indexes()

        source_cats = await self._load_source_rows("formula_categories", "id")
        source_cards = await self._load_source_rows("formula_cards", "id")
        self._source_tags = await self._load_source_rows("formula_tags", "id")
        source_cts = await self._load_source_rows("formula_card_tags", "id")
        source_versions = await self._load_source_rows("formula_card_versions", "id")

        card_ids = [c["id"] for c in source_cards
                    if (c.get("source_ref") or "").startswith(NONPROB_PREFIX)]
        needed_cat_ids = set()
        cat_by_id = {c["id"]: c for c in source_cats}
        for cid in card_ids:
            card = next(c for c in source_cards if c["id"] == cid)
            p = card["category_id"]
            while p is not None and p in cat_by_id:
                needed_cat_ids.add(p)
                p = cat_by_id[p].get("parent_id")

        print(f"Scoped to {len(card_ids)} nonprob cards and "
              f"{len(needed_cat_ids)} categories in their chain")

        await self.sync_categories(source_cats, needed_cat_ids)
        print(f"  Categories: {self.stats['categories_created']} created, "
              f"{self.stats['categories_skipped']} skipped")

        await self.sync_cards(source_cards, card_ids)
        print(f"  Cards: {self.stats['cards_created']} created, "
              f"{self.stats['cards_skipped']} skipped")

        await self.sync_card_tags(source_cts, set(card_ids))
        print(f"  Card-Tags: {self.stats['card_tags_created']} created, "
              f"{self.stats['card_tags_skipped']} skipped")

        await self.sync_versions(source_versions, set(card_ids))
        print(f"  Versions: {self.stats['versions_created']} created, "
              f"{self.stats['versions_skipped']} skipped")

        print()
        if self.stats["warnings"]:
            print("Warnings:")
            for w in self.stats["warnings"]:
                print(f"  - {w}")
        print("Done.")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="sqlite+aiosqlite:///./postgraduate.db")
    p.add_argument("--target", default=None)
    p.add_argument("--apply", action="store_true", help="Perform writes (default dry-run)")
    p.add_argument("--allow-production", action="store_true")
    return p.parse_args()


async def main():
    args = parse_args()
    target_url = args.target or os.environ.get("DATABASE_URL", "")
    if not target_url:
        print("ERROR: --target or DATABASE_URL env var required")
        sys.exit(1)
    app_env = os.environ.get("APP_ENV", "development")
    if target_url.startswith("postgresql") and app_env == "production":
        if not args.target and not args.allow_production and args.apply:
            print("ERROR: Refusing to write to production database. "
                  "Pass --target explicitly or --allow-production.")
            sys.exit(1)
    syncer = NonprobSyncer(args.source, target_url, dry_run=not args.apply)
    try:
        await syncer.sync_all()
    finally:
        await syncer.close()


if __name__ == "__main__":
    asyncio.run(main())
