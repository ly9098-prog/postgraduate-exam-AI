"""Sync formula data from local SQLite to production PostgreSQL.

Syncs only formula-related tables, using stable identity matching
(source_ref, code, slug) rather than numeric DB IDs.

Usage:
    # Dry run (default) — read-only, no writes
    python scripts/sync_formulas_to_prod.py --dry-run

    # Apply sync
    python scripts/sync_formulas_to_prod.py --apply

    # Apply with image file copy
    python scripts/sync_formulas_to_prod.py --apply --sync-images

    # Custom source/target URLs (e.g. on production server)
    python scripts/sync_formulas_to_prod.py \
        --source "sqlite+aiosqlite:////tmp/source.db" \
        --target "postgresql+asyncpg://user:pass@localhost:5432/db" \
        --apply

Production safety:
    - Detects APP_ENV=production when no --target given and refuses writes
      unless --allow-production is set
    - Dry-run by default (no writes unless --apply)
    - Only touches tables: formula_tags, formula_categories, formula_cards,
      formula_card_tags, formula_graph_assets, formula_graph_specs,
      formula_card_versions
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


# ── Type coercion for SQLite → PostgreSQL ──


def _coerce(val: object) -> object:
    """Convert SQLite raw values to PostgreSQL-compatible Python types.

    SQLite has no native booleans or datetimes — cursor returns int/str.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int) and val in (0, 1):
        # Could be a boolean stored as integer — check column name in caller
        return val
    if isinstance(val, str):
        # Try datetime parsing
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
    return val


def _coerce_bool(val: object) -> bool:
    """Coerce a value to bool (handles SQLite 0/1)."""
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    if isinstance(val, str):
        return val.lower() in ("1", "true", "t", "yes")
    return False


def _coerce_datetime(val: object) -> object:
    """Coerce a value to datetime or None."""
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


SYNC_TABLES = [
    "formula_tags",
    "formula_categories",
    "formula_cards",
    "formula_card_tags",
    "formula_graph_assets",
    "formula_graph_specs",
    "formula_card_versions",
]


@dataclass
class SyncStats:
    tags_created: int = 0
    tags_skipped: int = 0
    categories_created: int = 0
    categories_skipped: int = 0
    cards_created: int = 0
    cards_skipped: int = 0
    card_tags_created: int = 0
    card_tags_skipped: int = 0
    assets_created: int = 0
    assets_skipped: int = 0
    specs_created: int = 0
    specs_skipped: int = 0
    versions_created: int = 0
    versions_skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    def total(self) -> int:
        return (
            self.tags_created
            + self.categories_created
            + self.cards_created
            + self.card_tags_created
            + self.assets_created
            + self.specs_created
            + self.versions_created
        )

    def report(self) -> str:
        lines = [
            "=== Sync Report ===",
            "",
            f"  Tags:              {self.tags_created} created, {self.tags_skipped} skipped",
            f"  Categories:        {self.categories_created} created, {self.categories_skipped} skipped",
            f"  Cards:             {self.cards_created} created, {self.cards_skipped} skipped",
            f"  Card-Tags:         {self.card_tags_created} created, {self.card_tags_skipped} skipped",
            f"  Graph Assets:      {self.assets_created} created, {self.assets_skipped} skipped",
            f"  Graph Specs:       {self.specs_created} created, {self.specs_skipped} skipped",
            f"  Card Versions:     {self.versions_created} created, {self.versions_skipped} skipped",
            f"  ---",
            f"  Total mutations:   {self.total()}",
        ]
        if self.warnings:
            lines.extend(["", "Warnings:"] + [f"  - {w}" for w in self.warnings])
        return "\n".join(lines)


async def table_exists(session: AsyncSession, table_name: str) -> bool:
    dialect = session.bind.dialect.name if session.bind else "postgresql"
    if dialect == "sqlite":
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table_name},
        )
        return result.scalar() is not None
    else:
        result = await session.execute(
            text(
                "SELECT tablename FROM pg_catalog.pg_tables WHERE tablename=:t"
            ),
            {"t": table_name},
        )
        return result.scalar() is not None


class FormulaSyncer:
    """Sync formula data from source SQLite to target PostgreSQL."""

    def __init__(self, source_url: str, target_url: str, dry_run: bool = True):
        self.source_url = source_url
        self.target_url = target_url
        self.dry_run = dry_run
        self.stats = SyncStats()

        # ID mappings: source_id -> target_id
        self._tag_map: dict[int, int] = {}
        self._category_map: dict[int, int] = {}
        self._card_map: dict[int, int] = {}
        self._asset_map: dict[int, int] = {}
        self._spec_map: dict[int, int] = {}

        # Helper maps for matching
        self._tag_by_code: dict[str, int] = {}
        self._category_by_key: dict[tuple, int] = {}
        self._card_by_source_ref: dict[str, int] = {}
        self._card_by_title: dict[tuple, int] = {}

    def _init_engines(self) -> None:
        self.source_engine = create_async_engine(self.source_url, echo=False)
        self.target_engine = create_async_engine(self.target_url, echo=False)
        self.SourceSession = sessionmaker(
            self.source_engine, class_=AsyncSession, expire_on_commit=False
        )
        self.TargetSession = sessionmaker(
            self.target_engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self) -> None:
        await self.source_engine.dispose()
        await self.target_engine.dispose()

    async def sync_all(self) -> SyncStats:
        self._init_engines()
        print(f"Source: {self.source_url}")
        print(f"Target: {self.target_url}")
        print(f"Dry-run: {self.dry_run}")
        print()

        async with self.TargetSession() as target_session:
            for tbl in SYNC_TABLES:
                if not await table_exists(target_session, tbl):
                    self.stats.warnings.append(
                        f"Target table '{tbl}' not found — "
                        f"run alembic migration first"
                    )

        await self._sync_tags()
        await self._sync_categories()
        await self._sync_cards()
        await self._sync_card_tags()
        await self._sync_graph_assets()
        await self._sync_graph_specs()
        await self._sync_card_versions()

        return self.stats

    # ── Load helpers ──

    async def _load_source_rows(
        self, table: str, order_by: str | None = None
    ) -> list[dict]:
        async with self.SourceSession() as s:
            q = f"SELECT * FROM {table}"
            if order_by:
                q += f" ORDER BY {order_by}"
            result = await s.execute(text(q))
            cols = result.keys()
            return [dict(zip(cols, row)) for row in result.fetchall()]

    async def _insert_target(
        self, session: AsyncSession, table: str, data: dict
    ) -> int:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data)
        result = await session.execute(
            text(
                f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
                f"RETURNING id"
            ),
            data,
        )
        return result.scalar()

    # ── Tags ──

    async def _sync_tags(self) -> None:
        print("--- Syncing formula_tags ---")
        source_tags = await self._load_source_rows("formula_tags", "id")

        async with self.TargetSession() as t:
            result = await t.execute(
                text("SELECT id, code FROM formula_tags")
            )
            for row in result.fetchall():
                self._tag_by_code[row.code] = row.id

        for tag in source_tags:
            existing_id = self._tag_by_code.get(tag["code"])
            if existing_id is not None:
                self._tag_map[tag["id"]] = existing_id
                self.stats.tags_skipped += 1
                continue

            if not self.dry_run:
                async with self.TargetSession() as t:
                    async with t.begin():
                        new_id = await self._insert_target(t, "formula_tags", {
                            "code": tag["code"],
                            "name": tag["name"],
                            "sort_order": tag["sort_order"],
                        })
                self._tag_map[tag["id"]] = new_id
            self.stats.tags_created += 1

        print(
            f"  Tags: {self.stats.tags_created} created, "
            f"{self.stats.tags_skipped} skipped"
        )

    # ── Categories ──

    async def _sync_categories(self) -> None:
        print("--- Syncing formula_categories ---")
        source_cats = await self._load_source_rows(
            "formula_categories", "id"
        )

        def _depth(cat: dict, cmap: dict) -> int:
            d, p, seen = 0, cat.get("parent_id"), set()
            while p is not None:
                if p in seen or p not in cmap:
                    break
                seen.add(p)
                d += 1
                p = cmap[p].get("parent_id")
            return d

        cat_by_id = {c["id"]: c for c in source_cats}
        for c in source_cats:
            c["_depth"] = _depth(c, cat_by_id)
        source_cats.sort(key=lambda c: (c["_depth"], c["id"]))

        async with self.TargetSession() as t:
            result = await t.execute(
                text("SELECT id, parent_id, code FROM formula_categories")
            )
            for row in result.fetchall():
                self._category_by_key[(row.parent_id, row.code)] = row.id

        for cat in source_cats:
            mapped_parent = (
                self._category_map.get(cat["parent_id"])
                if cat["parent_id"]
                else None
            )
            key = (mapped_parent, cat["code"])

            existing_id = self._category_by_key.get(key)
            if existing_id is not None:
                self._category_map[cat["id"]] = existing_id
                self.stats.categories_skipped += 1
                continue

            if not self.dry_run:
                insert_data = {
                    "parent_id": mapped_parent,
                    "exam_scope": cat["exam_scope"],
                    "node_type": cat["node_type"],
                    "code": cat["code"],
                    "name": cat["name"],
                    "description": cat.get("description"),
                    "sort_order": cat["sort_order"],
                    "is_active": _coerce_bool(cat["is_active"]),
                }
                async with self.TargetSession() as t:
                    async with t.begin():
                        new_id = await self._insert_target(
                            t, "formula_categories", insert_data
                        )
                self._category_map[cat["id"]] = new_id
            self.stats.categories_created += 1

        print(
            f"  Categories: {self.stats.categories_created} created, "
            f"{self.stats.categories_skipped} skipped "
            f"(over {len(source_cats)} source rows)"
        )

    # ── Cards ──

    async def _sync_cards(self) -> None:
        print("--- Syncing formula_cards ---")
        source_cards = await self._load_source_rows("formula_cards", "id")

        async with self.TargetSession() as t:
            result = await t.execute(
                text(
                    "SELECT id, source_ref, title, category_id "
                    "FROM formula_cards"
                )
            )
            for row in result.fetchall():
                if row.source_ref:
                    self._card_by_source_ref[row.source_ref] = row.id
                self._card_by_title[(row.title, row.category_id)] = row.id

        for card in source_cards:
            mapped_cat = self._category_map.get(card["category_id"])
            if mapped_cat is None:
                self.stats.warnings.append(
                    f"Card '{card['title']}' (id={card['id']}): "
                    f"category_id={card['category_id']} not mapped, skipping"
                )
                continue

            existing_id = None
            if card.get("source_ref"):
                existing_id = self._card_by_source_ref.get(card["source_ref"])

            if existing_id is None:
                existing_id = self._card_by_title.get(
                    (card["title"], mapped_cat)
                )

            if existing_id is not None:
                self._card_map[card["id"]] = existing_id
                self.stats.cards_skipped += 1
                continue

            if not self.dry_run:
                insert_data = {
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
                    "source_ref": card.get("source_ref"),
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
                        new_id = await self._insert_target(
                            t, "formula_cards", insert_data
                        )
                self._card_map[card["id"]] = new_id
            self.stats.cards_created += 1

        print(
            f"  Cards: {self.stats.cards_created} created, "
            f"{self.stats.cards_skipped} skipped"
        )

    # ── Card-Tags ──

    async def _sync_card_tags(self) -> None:
        print("--- Syncing formula_card_tags ---")
        source_cts = await self._load_source_rows(
            "formula_card_tags", "id"
        )

        existing: set[tuple[int, int]] = set()
        async with self.TargetSession() as t:
            result = await t.execute(
                text(
                    "SELECT formula_card_id, tag_id "
                    "FROM formula_card_tags"
                )
            )
            for row in result.fetchall():
                existing.add((row.formula_card_id, row.tag_id))

        for ct in source_cts:
            mapped_card = self._card_map.get(ct["formula_card_id"])
            mapped_tag = self._tag_map.get(ct["tag_id"])
            if mapped_card is None or mapped_tag is None:
                continue
            key = (mapped_card, mapped_tag)
            if key in existing:
                self.stats.card_tags_skipped += 1
                continue

            if not self.dry_run:
                async with self.TargetSession() as t:
                    async with t.begin():
                        await self._insert_target(t, "formula_card_tags", {
                            "formula_card_id": mapped_card,
                            "tag_id": mapped_tag,
                        })
            self.stats.card_tags_created += 1
            existing.add(key)

        print(
            f"  Card-Tags: {self.stats.card_tags_created} created, "
            f"{self.stats.card_tags_skipped} skipped"
        )

    # ── Graph Assets ──

    async def _sync_graph_assets(self) -> None:
        print("--- Syncing formula_graph_assets ---")
        source_assets = await self._load_source_rows(
            "formula_graph_assets", "id"
        )

        existing: set[tuple[int, str]] = set()
        async with self.TargetSession() as t:
            result = await t.execute(
                text(
                    "SELECT formula_card_id, source_type, id "
                    "FROM formula_graph_assets"
                )
            )
            for row in result.fetchall():
                existing.add((row.formula_card_id, row.source_type))

        for asset in source_assets:
            mapped_card = self._card_map.get(asset["formula_card_id"])
            if mapped_card is None:
                self.stats.warnings.append(
                    f"Graph asset id={asset['id']}: "
                    f"card_id={asset['formula_card_id']} not mapped, skipping"
                )
                continue
            key = (mapped_card, asset["source_type"])
            if key in existing:
                self._asset_map[asset["id"]] = -1  # placeholder, not a real FK
                self.stats.assets_skipped += 1
                continue

            if not self.dry_run:
                insert_data = {
                    "formula_card_id": mapped_card,
                    "source_type": asset["source_type"],
                    "template_type": asset.get("template_type"),
                    "template_parameters": asset.get("template_parameters"),
                    "viewport": asset.get("viewport"),
                    "image_url": asset.get("image_url"),
                    "thumbnail_url": asset.get("thumbnail_url"),
                    "original_svg_url": asset.get("original_svg_url"),
                    "mime_type": asset.get("mime_type"),
                    "width": asset.get("width"),
                    "height": asset.get("height"),
                    "file_size": asset.get("file_size"),
                    "checksum": asset.get("checksum"),
                    "renderer_version": asset.get("renderer_version"),
                    "alt_text": asset.get("alt_text"),
                    "description": asset.get("description"),
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "review_note": None,
                    "published_version": asset.get("published_version"),
                }
                async with self.TargetSession() as t:
                    async with t.begin():
                        new_id = await self._insert_target(
                            t, "formula_graph_assets", insert_data
                        )
                self._asset_map[asset["id"]] = new_id
            self.stats.assets_created += 1

        print(
            f"  Graph Assets: {self.stats.assets_created} created, "
            f"{self.stats.assets_skipped} skipped"
        )

    # ── Graph Specs ──

    async def _sync_graph_specs(self) -> None:
        print("--- Syncing formula_graph_specs ---")
        source_specs = await self._load_source_rows(
            "formula_graph_specs", "id"
        )

        existing: set[tuple[int, str]] = set()
        async with self.TargetSession() as t:
            result = await t.execute(
                text(
                    "SELECT formula_card_id, slug, id "
                    "FROM formula_graph_specs"
                )
            )
            for row in result.fetchall():
                existing.add((row.formula_card_id, row.slug))

        for spec in source_specs:
            mapped_card = self._card_map.get(spec["formula_card_id"])
            if mapped_card is None:
                self.stats.warnings.append(
                    f"Graph spec id={spec['id']} (slug={spec['slug']}): "
                    f"card_id={spec['formula_card_id']} not mapped, skipping"
                )
                continue
            key = (mapped_card, spec["slug"])
            if key in existing:
                self.stats.specs_skipped += 1
                continue

            mapped_asset = (
                self._asset_map.get(spec["confirmed_asset_id"])
                if spec.get("confirmed_asset_id")
                else None
            )
            if mapped_asset == -1:
                mapped_asset = None  # placeholder, not a real FK

            if not self.dry_run:
                insert_data = {
                    "formula_card_id": mapped_card,
                    "slug": spec["slug"],
                    "source_ref": spec["source_ref"],
                    "title": spec["title"],
                    "description": spec.get("description"),
                    "alt_text": spec.get("alt_text"),
                    "spec_json": spec["spec_json"],
                    "spec_hash": spec["spec_hash"],
                    "schema_version": spec["schema_version"],
                    "renderer_version": spec["renderer_version"],
                    "status": spec["status"],
                    "sort_order": spec["sort_order"],
                    "confirmed_asset_id": mapped_asset,
                    "reviewed_by": None,
                    "reviewed_at": None,
                }
                async with self.TargetSession() as t:
                    async with t.begin():
                        new_id = await self._insert_target(
                            t, "formula_graph_specs", insert_data
                        )
                self._spec_map[spec["id"]] = new_id
            self.stats.specs_created += 1

        print(
            f"  Graph Specs: {self.stats.specs_created} created, "
            f"{self.stats.specs_skipped} skipped"
        )

    # ── Card Versions ──

    async def _sync_card_versions(self) -> None:
        print("--- Syncing formula_card_versions ---")
        source_versions = await self._load_source_rows(
            "formula_card_versions", "id"
        )

        existing: set[tuple[int, int]] = set()
        async with self.TargetSession() as t:
            result = await t.execute(
                text(
                    "SELECT formula_card_id, version "
                    "FROM formula_card_versions"
                )
            )
            for row in result.fetchall():
                existing.add((row.formula_card_id, row.version))

        for ver in source_versions:
            mapped_card = self._card_map.get(ver["formula_card_id"])
            if mapped_card is None:
                continue
            key = (mapped_card, ver["version"])
            if key in existing:
                self.stats.versions_skipped += 1
                continue

            if not self.dry_run:
                insert_data = {
                    "formula_card_id": mapped_card,
                    "version": ver["version"],
                    "snapshot": ver["snapshot"],
                    "action": ver["action"],
                    "edited_by": None,
                    "edit_reason": ver.get("edit_reason"),
                }
                async with self.TargetSession() as t:
                    async with t.begin():
                        await self._insert_target(
                            t, "formula_card_versions", insert_data
                        )
            self.stats.versions_created += 1

        print(
            f"  Card Versions: {self.stats.versions_created} created, "
            f"{self.stats.versions_skipped} skipped"
        )


# ── Image sync ──


def sync_images(
    ssh_host: str,
    ssh_key: str,
    local_static_dir: str,
    docker_workdir: str,
) -> None:
    graphs_rel = "static/formulas/graphs"
    local_path = os.path.join(local_static_dir, graphs_rel)
    server_path = f"{ssh_host}:{docker_workdir}/{graphs_rel}"

    print("--- Syncing images to production server ---")
    rsync_cmd = [
        "rsync", "-az",
        "-e", f"ssh -i {ssh_key} -o BatchMode=yes",
        f"{local_path}/",
        f"{server_path}/",
    ]
    print(f"  Running: {' '.join(rsync_cmd)}")
    r = subprocess.run(rsync_cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ERROR: rsync failed: {r.stderr}")
        return
    print("  rsync completed")

    docker_cmd = (
        f"cd {docker_workdir} && "
        f"container=$(docker compose -f deploy/docker-compose.prod.yml "
        f"--env-file backend/.env ps -q app) && "
        f"docker cp {graphs_rel}/. $container:/app/{graphs_rel}/"
    )
    print("  Copying into Docker container...")
    r = subprocess.run(
        ["ssh", "-i", ssh_key, "-o", "BatchMode=yes", ssh_host, docker_cmd],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  WARNING: docker cp may have failed: {r.stderr}")
    else:
        print("  Images copied into Docker container")


# ── CLI ──


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sync formula data from local SQLite to production PostgreSQL"
    )
    p.add_argument(
        "--source",
        default="sqlite+aiosqlite:///./postgraduate.db",
        help="Source database URL (default: local SQLite)",
    )
    p.add_argument(
        "--target",
        default=None,
        help=(
            "Target database URL (default: DATABASE_URL env var). "
            "When DATABASE_URL starts with postgresql, "
            "auto-detects production."
        ),
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Perform writes (default is dry-run)",
    )
    p.add_argument(
        "--allow-production",
        action="store_true",
        help="Allow writes when APP_ENV=production and --target not set",
    )
    p.add_argument(
        "--sync-images",
        action="store_true",
        help="Also rsync image files to production server",
    )
    p.add_argument(
        "--ssh-host",
        default="user@your-production-domain.example",
        help="Production SSH host",
    )
    p.add_argument(
        "--ssh-key",
        default=os.path.expanduser("~/loginkey.pem"),
        help="SSH private key path",
    )
    p.add_argument(
        "--docker-workdir",
        default="/opt/22408-ai",
        help="Production docker-compose directory",
    )
    p.add_argument(
        "--local-static-dir",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".."
        ),
        help="Local backend directory",
    )
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    target_url = args.target or os.environ.get("DATABASE_URL", "")
    if not target_url:
        print("ERROR: --target or DATABASE_URL env var required")
        sys.exit(1)

    app_env = os.environ.get("APP_ENV", "development")
    is_prod_target = target_url.startswith("postgresql")
    if is_prod_target and app_env == "production" and not args.target:
        if not args.allow_production and args.apply:
            print(
                "ERROR: Refusing to write to production database.\n"
                "  APP_ENV=production and --target not explicitly set.\n"
                "  Use --allow-production to override, "
                "or pass --target explicitly."
            )
            sys.exit(1)

    print(f"APP_ENV: {app_env}")
    print(f"Apply writes: {args.apply}")
    print()

    syncer = FormulaSyncer(
        source_url=args.source,
        target_url=target_url,
        dry_run=not args.apply,
    )

    try:
        stats = await syncer.sync_all()
        print()
        print(stats.report())
    finally:
        await syncer.close()

    if args.sync_images and args.apply:
        sync_images(
            ssh_host=args.ssh_host,
            ssh_key=args.ssh_key,
            local_static_dir=args.local_static_dir,
            docker_workdir=args.docker_workdir,
        )
    elif args.sync_images and not args.apply:
        print(
            "\n--sync-images requires --apply. Skipping image sync."
        )


if __name__ == "__main__":
    asyncio.run(main())
