#!/usr/bin/env python3
"""把本地「基本积分公式」卡片（id=19）的多行/分组重排同步到生产 PostgreSQL。

身份匹配：title + 分类路径（绝不使用 numeric id）。仅更新该卡片的
formula_blocks / content_hash / version+1 / updated_by / updated_at，
并插入 formula_card_versions(action='update') 快照。

用法（目标库需在容器内解析 DATABASE_URL）：
    python sync_basic_integral_card_reformat_to_prod.py \
        --source sqlite+aiosqlite:////tmp/formula_sync_source.db \
        --target "$DATABASE_URL" [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

TITLE = "基本积分公式"
EXPECTED_CATEGORY_PATH = "高等数学 / 一元函数积分学 / 不定积分与定积分公式"
EDIT_REASON = "「基本积分公式」block 横向滚动，重排为分组/多行渲染提升可读性"
ADMIN_PREFERRED = ("admin", "lmh_admin_01")


def _as_list(v) -> list:
    return v if isinstance(v, list) else json.loads(v)


async def _category_path(session: AsyncSession, category_id: int) -> str:
    names: list[str] = []
    cur_id = category_id
    seen: set[int] = set()
    while cur_id and cur_id not in seen:
        seen.add(cur_id)
        row = (
            await session.execute(
                text("SELECT id, name, parent_id FROM formula_categories WHERE id = :i"),
                {"i": cur_id},
            )
        ).fetchone()
        if row is None:
            break
        names.append(row.name)
        cur_id = row.parent_id
    return " / ".join(reversed(names))


async def _find_admin_id(session: AsyncSession) -> int | None:
    rows = (
        await session.execute(
            text("SELECT id, username FROM admin_users WHERE is_active = true ORDER BY id")
        )
    ).fetchall()
    for pref in ADMIN_PREFERRED:
        for r in rows:
            if r.username == pref:
                return r.id
    return rows[0].id if rows else None


async def _find_card(session: AsyncSession, title: str):
    rows = (
        await session.execute(
            text("SELECT * FROM formula_cards WHERE title = :t AND deleted_at IS NULL"),
            {"t": title},
        )
    ).fetchall()
    return rows[0] if len(rows) == 1 else None


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_engine = create_async_engine(args.source, echo=False)
    target_engine = create_async_engine(args.target, echo=False)
    SS = sessionmaker(source_engine, class_=AsyncSession, expire_on_commit=False)
    TS = sessionmaker(target_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with SS() as s:
            lcard = await _find_card(s, TITLE)
            if lcard is None:
                print("FATAL: 本地缺少「基本积分公式」", file=sys.stderr)
                return
            lpath = await _category_path(s, lcard.category_id)
            if lpath != EXPECTED_CATEGORY_PATH:
                print(f"FATAL: 本地分类路径不符: {lpath}", file=sys.stderr)
                return
            lblocks = _as_list(lcard.formula_blocks)
            print(f"本地 {TITLE} id={lcard.id} ver={lcard.version} blocks={len(lblocks)} hash={lcard.content_hash[:12]}")
            for b in lblocks:
                print(f"  [{b['label']}] {b['latex'][:55]}")

        async with TS() as t:
            pcard = await _find_card(t, TITLE)
            if pcard is None:
                print("FATAL: 生产缺少「基本积分公式」", file=sys.stderr)
                return
            ppath = await _category_path(t, pcard.category_id)
            if ppath != EXPECTED_CATEGORY_PATH:
                print(f"FATAL: 生产分类路径不符: {ppath}", file=sys.stderr)
                return
            pblocks = _as_list(pcard.formula_blocks)
            admin_id = await _find_admin_id(t)
            print(f"生产 {TITLE} id={pcard.id} ver={pcard.version} blocks={len(pblocks)} hash={(pcard.content_hash or '')[:12]} admin={admin_id}")

            # 一致性守卫：生产应为重排前基线
            if pcard.version != lcard.version - 1 or len(pblocks) != 8:
                print(f"FATAL: 生产非预期基线 (ver={pcard.version} blocks={len(pblocks)}，期望 ver={lcard.version - 1} blocks=8)，中止", file=sys.stderr)
                return

            print("\n写入前差异:")
            print(f"  version: {pcard.version} → {lcard.version}")
            print(f"  blocks: {len(pblocks)} → {len(lblocks)}")
            print(f"  hash: {(pcard.content_hash or '')[:12]} → {lcard.content_hash[:12]}")

            if not args.apply:
                print("\n[dry-run] 未写入。加 --apply 生效。")
                return

            backup = {
                "card_before": {
                    "id": pcard.id, "title": pcard.title, "category_id": pcard.category_id,
                    "formula_blocks": pblocks, "content_hash": pcard.content_hash,
                    "version": pcard.version, "status": pcard.status, "updated_by": pcard.updated_by,
                },
                "versions_before": [],
            }
            for v in (await t.execute(text("SELECT id, version, action, edited_by, edit_reason FROM formula_card_versions WHERE formula_card_id = :i ORDER BY version"), {"i": pcard.id})).fetchall():
                backup["versions_before"].append({"id": v.id, "version": v.version, "action": v.action, "edited_by": v.edited_by, "edit_reason": v.edit_reason})
            with open("/tmp/prod_card_reformat_backup.json", "w", encoding="utf-8") as f:
                json.dump(backup, f, ensure_ascii=False, indent=2, default=str)
            print("\n[backup] 生产受影响行已备份到容器内 /tmp/prod_card_reformat_backup.json")

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            snapshot = {
                "id": pcard.id, "title": pcard.title, "category_id": pcard.category_id,
                "card_type": pcard.card_type, "formula_blocks": lblocks,
                "conditions": pcard.conditions, "status": pcard.status, "version": lcard.version,
            }
            await t.execute(
                text("UPDATE formula_cards SET formula_blocks = :b, content_hash = :h, version = :v, updated_by = :u, updated_at = :now WHERE id = :i"),
                {"b": json.dumps(lblocks, ensure_ascii=False), "h": lcard.content_hash, "v": lcard.version, "u": admin_id, "now": now, "i": pcard.id},
            )
            await t.execute(
                text("INSERT INTO formula_card_versions (formula_card_id, version, snapshot, action, edited_by, edit_reason) VALUES (:c, :v, :s, 'update', :e, :r)"),
                {"c": pcard.id, "v": lcard.version, "s": json.dumps(snapshot, ensure_ascii=False), "e": admin_id, "r": EDIT_REASON},
            )
            await t.commit()
            print(f"[apply] 生产 {TITLE} id={pcard.id}: ver {pcard.version} → {lcard.version}")
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
