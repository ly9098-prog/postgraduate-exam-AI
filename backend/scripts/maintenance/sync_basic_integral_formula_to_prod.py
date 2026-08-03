#!/usr/bin/env python3
"""把本地「基本积分公式」卡片的内容更新（补充缺失公式）同步到生产 PostgreSQL。

生产卡片身份匹配：title='基本积分公式' + 分类路径一致（绝不使用 numeric id，
本地/生产 id 与分类 id 均可分叉）。仅更新该卡片的
formula_blocks / content_hash / version+1 / updated_by / updated_at，
并插入一条 formula_card_versions(action='update') 快照。

用法（目标库需在容器内解析 DATABASE_URL）：
    # Dry run（默认）
    python sync_basic_integral_formula_to_prod.py \
        --source sqlite+aiosqlite:////tmp/formula_sync_source.db \
        --target "$DATABASE_URL"

    # Apply
    python sync_basic_integral_formula_to_prod.py \
        --source sqlite+aiosqlite:////tmp/formula_sync_source.db \
        --target "$DATABASE_URL" --apply
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
EDIT_REASON = "补充图片中的缺失基本积分公式，执行数学等价去重"
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
                text(
                    "SELECT id, name, parent_id FROM formula_categories WHERE id = :i"
                ),
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
            text(
                "SELECT id, username FROM admin_users WHERE is_active = true "
                "ORDER BY id"
            )
        )
    ).fetchall()
    for pref in ADMIN_PREFERRED:
        for r in rows:
            if r.username == pref:
                return r.id
    return rows[0].id if rows else None


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
        # ── 读取本地卡片 ──
        async with SS() as s:
            lrows = (
                await s.execute(
                    text(
                        "SELECT id, title, category_id, formula_blocks, content_hash, "
                        "version, status, conditions, card_type, published_at "
                        "FROM formula_cards WHERE title = :t AND deleted_at IS NULL"
                    ),
                    {"t": TITLE},
                )
            ).fetchall()
            if len(lrows) != 1:
                print(f"FATAL: 本地匹配卡片 {len(lrows)} 条（期望 1），中止")
                return
            lcard = lrows[0]
            lpath = await _category_path(s, lcard.category_id)
            if lpath != EXPECTED_CATEGORY_PATH:
                print(f"FATAL: 本地分类路径不符: {lpath}")
                return
            lblocks = _as_list(lcard.formula_blocks)
            lhash = lcard.content_hash
            lversion = lcard.version
            print(f"本地 card id={lcard.id} 分类={lpath}")
            print(f"  本地 version={lversion} hash={lhash[:16]} blocks={len(lblocks)}")

        # ── 读取生产卡片 ──
        async with TS() as t:
            prows = (
                await t.execute(
                    text(
                        "SELECT id, title, category_id, formula_blocks, content_hash, "
                        "version, status, conditions, card_type, published_at, "
                        "updated_by "
                        "FROM formula_cards WHERE title = :t AND deleted_at IS NULL"
                    ),
                    {"t": TITLE},
                )
            ).fetchall()
            if len(prows) != 1:
                print(f"FATAL: 生产匹配卡片 {len(prows)} 条（期望 1），中止")
                return
            pcard = prows[0]
            ppath = await _category_path(t, pcard.category_id)
            if ppath != EXPECTED_CATEGORY_PATH:
                print(f"FATAL: 生产分类路径不符: {ppath}")
                return
            pblocks = _as_list(pcard.formula_blocks)
            admin_id = await _find_admin_id(t)
            vcount = (
                await t.execute(
                    text(
                        "SELECT count(*) FROM formula_card_versions "
                        "WHERE formula_card_id = :i"
                    ),
                    {"i": pcard.id},
                )
            ).scalar()
            print(f"生产 card id={pcard.id} 分类={ppath}")
            print(
                f"  生产 version={pcard.version} hash={(pcard.content_hash or '')[:16]} "
                f"blocks={len(pblocks)} updated_by={pcard.updated_by} "
                f"versions={vcount} admin_id={admin_id}"
            )

            # ── 一致性检查：生产旧内容应为本地修改前基线（6 blocks、version=1） ──
            if pcard.version != 1 or len(pblocks) != 6:
                print(f"FATAL: 生产卡片非预期基线 (version={pcard.version} blocks={len(pblocks)})，中止")
                return
            if lversion != pcard.version + 1:
                print(
                    f"FATAL: 本地 version({lversion}) 应等于 生产 version+1({pcard.version + 1})，中止"
                )
                return

            # ── 写入前差异 ──
            print("\n写入前差异:")
            print(f"  version: {pcard.version} → {lversion}")
            print(f"  content_hash: {(pcard.content_hash or '')[:12]} → {lhash[:12]}")
            print(f"  blocks: {len(pblocks)} → {len(lblocks)}")
            print(f"  updated_by: {pcard.updated_by} → {admin_id}")
            new_labels = [b.get('label') for b in lblocks if b.get('label') not in {x.get('label') for x in pblocks}]
            print(f"  新增 block: {new_labels}")
            for nb in lblocks:
                if nb.get('label') not in {x.get('label') for x in pblocks}:
                    print(f"    [{nb['label']}] {nb['latex'][:80]}...")

            if not args.apply:
                print("\n[dry-run] 未写入。加 --apply 生效。")
                return

            # ── 备份受影响的生产行 ──
            backup = {
                "card_before": {
                    "id": pcard.id,
                    "title": pcard.title,
                    "category_id": pcard.category_id,
                    "formula_blocks": pblocks,
                    "content_hash": pcard.content_hash,
                    "version": pcard.version,
                    "status": pcard.status,
                    "updated_by": pcard.updated_by,
                    "updated_at": None,
                },
                "versions_before": [],
            }
            vrows = (
                await t.execute(
                    text(
                        "SELECT id, version, action, snapshot, edited_by, edit_reason "
                        "FROM formula_card_versions WHERE formula_card_id = :i "
                        "ORDER BY version"
                    ),
                    {"i": pcard.id},
                )
            ).fetchall()
            for v in vrows:
                backup["versions_before"].append({
                    "id": v.id, "version": v.version, "action": v.action,
                    "snapshot": v.snapshot, "edited_by": v.edited_by,
                    "edit_reason": v.edit_reason,
                })
            backup_path = "/tmp/prod_basic_integral_formula_backup.json"
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(backup, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n[backup] 生产受影响行已备份到容器内 {backup_path}")

            # ── 写入 ──
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            new_version = lversion
            snapshot = {
                "id": pcard.id,
                "title": pcard.title,
                "category_id": pcard.category_id,
                "card_type": pcard.card_type,
                "formula_blocks": lblocks,
                "conditions": pcard.conditions,
                "status": pcard.status,
                "version": new_version,
            }
            await t.execute(
                text(
                    "UPDATE formula_cards SET formula_blocks = :b, content_hash = :h, "
                    "version = :v, updated_by = :u, updated_at = :now "
                    "WHERE id = :i AND deleted_at IS NULL"
                ),
                {
                    "b": json.dumps(lblocks, ensure_ascii=False),
                    "h": lhash,
                    "v": new_version,
                    "u": admin_id,
                    "now": now,
                    "i": pcard.id,
                },
            )
            await t.execute(
                text(
                    "INSERT INTO formula_card_versions "
                    "(formula_card_id, version, snapshot, action, edited_by, edit_reason) "
                    "VALUES (:card, :ver, :snap, 'update', :edited, :reason)"
                ),
                {
                    "card": pcard.id,
                    "ver": new_version,
                    "snap": json.dumps(snapshot, ensure_ascii=False),
                    "edited": admin_id,
                    "reason": EDIT_REASON,
                },
            )
            await t.commit()
            print(f"[apply] 生产 card id={pcard.id}: version {pcard.version} → {new_version}")
            print(f"[apply] formula_card_versions 新增 version={new_version} (action=update)")
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
