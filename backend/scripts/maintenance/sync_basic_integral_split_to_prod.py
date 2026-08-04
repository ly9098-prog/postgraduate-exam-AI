#!/usr/bin/env python3
"""把本地「基本积分公式」拆分结果同步到生产 PostgreSQL。

同步两张卡：
    1. 更新生产「基本积分公式」：三角函数 block 4 条基础三角，version+1，重算 hash。
    2. 新建生产「基本积分公式-2」：6 条进阶三角公式，status=published。

身份匹配：title + 分类路径（绝不使用 numeric id，本地/生产 category_id 可分叉）。
用法（目标库需在容器内解析 DATABASE_URL）：
    python sync_basic_integral_split_to_prod.py \
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

TITLE_MAIN = "基本积分公式"
TITLE_NEW = "基本积分公式-2"
EXPECTED_CATEGORY_PATH = "高等数学 / 一元函数积分学 / 不定积分与定积分公式"
EDIT_REASON_UPDATE = "拆分三角函数 block：进阶三角公式移至「基本积分公式-2」，提升可读性"
EDIT_REASON_CREATE = "从「基本积分公式」拆分三角函数进阶公式，提升可读性"
ADMIN_PREFERRED = ("admin", "lmh_admin_01")

CARD_FIELDS = (
    "exam_scope, category_id, title, aliases, search_text, card_type, summary, "
    "formula_blocks, conditions, symbol_notes, secondary_conclusions, error_tips, "
    "examples, function_properties, sort_order, status, published_at, "
    "source_type, source_title, source_ref, content_hash, version, graph_status, updated_at"
)


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


async def _category_id_by_path(session: AsyncSession) -> int:
    rows = (await session.execute(text("SELECT id, name, parent_id FROM formula_categories"))).fetchall()
    by_id = {r.id: r for r in rows}
    for r in rows:
        chain = []
        cur = r.id
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            chain.append(by_id[cur].name)
            cur = by_id[cur].parent_id
        if " / ".join(reversed(chain)) == EXPECTED_CATEGORY_PATH:
            return r.id
    raise RuntimeError(f"生产分类路径未找到: {EXPECTED_CATEGORY_PATH}")


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


async def _find_card_by_title(session: AsyncSession, title: str):
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
            lmain = await _find_card_by_title(s, TITLE_MAIN)
            lnew = await _find_card_by_title(s, TITLE_NEW)
            if lmain is None or lnew is None:
                print("FATAL: 本地缺少目标卡片", file=sys.stderr)
                return
            lmain_blocks = _as_list(lmain.formula_blocks)
            lnew_blocks = _as_list(lnew.formula_blocks)
            print(f"本地 {TITLE_MAIN} id={lmain.id} ver={lmain.version} blocks={len(lmain_blocks)} hash={lmain.content_hash[:12]}")
            print(f"本地 {TITLE_NEW} id={lnew.id} ver={lnew.version} blocks={len(lnew_blocks)} hash={lnew.content_hash[:12]}")

        async with TS() as t:
            pcat = await _category_id_by_path(t)
            padmin = await _find_admin_id(t)
            pmain = await _find_card_by_title(t, TITLE_MAIN)
            pnew = await _find_card_by_title(t, TITLE_NEW)
            print(f"生产分类 id={pcat} admin={padmin}")

            if pmain is None:
                print("FATAL: 生产缺少「基本积分公式」", file=sys.stderr)
                return
            pmain_blocks = _as_list(pmain.formula_blocks)
            print(f"生产 {TITLE_MAIN} id={pmain.id} ver={pmain.version} blocks={len(pmain_blocks)} hash={(pmain.content_hash or '')[:12]}")
            if pnew is not None:
                pnew_blocks = _as_list(pnew.formula_blocks)
                print(f"生产 {TITLE_NEW} id={pnew.id} ver={pnew.version} blocks={len(pnew_blocks)} hash={(pnew.content_hash or '')[:12]}")
            else:
                print(f"生产 {TITLE_NEW}: 不存在（将创建）")

            # 一致性守卫：生产主卡片应为拆分前基线
            if pmain.version != lmain.version - 1 or len(pmain_blocks) != 8:
                print(f"FATAL: 生产主卡片非预期基线 (ver={pmain.version} blocks={len(pmain_blocks)}，期望 ver={lmain.version - 1} blocks=8)，中止", file=sys.stderr)
                return

            print("\n写入前差异:")
            print(f"  更新 {TITLE_MAIN}: ver {pmain.version}→{lmain.version}, blocks {len(pmain_blocks)}→{len(lmain_blocks)}, hash {(pmain.content_hash or '')[:12]}→{lmain.content_hash[:12]}")
            if pnew is None:
                print(f"  新建 {TITLE_NEW}: {len(lnew_blocks)} blocks, hash {lnew.content_hash[:12]}, status=published")

            if not args.apply:
                print("\n[dry-run] 未写入。加 --apply 生效。")
                return

            now = datetime.now(timezone.utc).replace(tzinfo=None)

            # ── 备份受影响生产行 ──
            backup = {
                "main_before": {
                    "id": pmain.id, "title": pmain.title, "category_id": pmain.category_id,
                    "formula_blocks": pmain_blocks, "content_hash": pmain.content_hash,
                    "version": pmain.version, "status": pmain.status, "updated_by": pmain.updated_by,
                },
                "main_versions_before": [],
            }
            for v in (await t.execute(text("SELECT id, version, action, edited_by, edit_reason FROM formula_card_versions WHERE formula_card_id = :i ORDER BY version"), {"i": pmain.id})).fetchall():
                backup["main_versions_before"].append({"id": v.id, "version": v.version, "action": v.action, "edited_by": v.edited_by, "edit_reason": v.edit_reason})
            if pnew is not None:
                backup["new_before"] = {"id": pnew.id, "title": pnew.title, "formula_blocks": pnew_blocks, "content_hash": pnew.content_hash, "version": pnew.version, "status": pnew.status}
            with open("/tmp/prod_integral_split_backup.json", "w", encoding="utf-8") as f:
                json.dump(backup, f, ensure_ascii=False, indent=2, default=str)
            print("\n[backup] 生产受影响行已备份到容器内 /tmp/prod_integral_split_backup.json")

            # ── 1) 更新生产主卡片 ──
            snapshot = {
                "id": pmain.id, "title": pmain.title, "category_id": pmain.category_id,
                "card_type": pmain.card_type, "formula_blocks": lmain_blocks,
                "conditions": pmain.conditions, "status": pmain.status, "version": lmain.version,
            }
            await t.execute(
                text("UPDATE formula_cards SET formula_blocks = :b, content_hash = :h, version = :v, updated_by = :u, updated_at = :now WHERE id = :i"),
                {"b": json.dumps(lmain_blocks, ensure_ascii=False), "h": lmain.content_hash, "v": lmain.version, "u": padmin, "now": now, "i": pmain.id},
            )
            await t.execute(
                text("INSERT INTO formula_card_versions (formula_card_id, version, snapshot, action, edited_by, edit_reason) VALUES (:c, :v, :s, 'update', :e, :r)"),
                {"c": pmain.id, "v": lmain.version, "s": json.dumps(snapshot, ensure_ascii=False), "e": padmin, "r": EDIT_REASON_UPDATE},
            )
            print(f"[apply] 生产 {TITLE_MAIN} id={pmain.id}: ver {pmain.version}→{lmain.version}")

            # ── 2) 新建生产「基本积分公式-2」 ──
            if pnew is None:
                def _j(v):
                    return json.dumps(v, ensure_ascii=False) if v is not None else None
                insert_data = {
                    "exam_scope": lnew.exam_scope,
                    "category_id": pcat,
                    "title": TITLE_NEW,
                    "aliases": _j(lnew.aliases),
                    "search_text": lnew.search_text,
                    "card_type": lnew.card_type,
                    "summary": lnew.summary,
                    "formula_blocks": _j(lnew_blocks),
                    "conditions": lnew.conditions,
                    "symbol_notes": lnew.symbol_notes,
                    "secondary_conclusions": lnew.secondary_conclusions,
                    "error_tips": lnew.error_tips,
                    "examples": _j(lnew.examples),
                    "function_properties": _j(lnew.function_properties),
                    "sort_order": lnew.sort_order,
                    "status": "published",
                    "published_at": now,
                    "source_type": lnew.source_type,
                    "source_title": lnew.source_title,
                    "source_ref": lnew.source_ref,
                    "content_hash": lnew.content_hash,
                    "version": 1,
                    "graph_status": "not_applicable",
                    "updated_at": now,
                }
                new_id = (
                    await t.execute(
                        text(
                            f"INSERT INTO formula_cards ({CARD_FIELDS}) VALUES "
                            f"(:exam_scope, :category_id, :title, :aliases, :search_text, :card_type, :summary, "
                            f":formula_blocks, :conditions, :symbol_notes, :secondary_conclusions, :error_tips, "
                            f":examples, :function_properties, :sort_order, :status, :published_at, "
                            f":source_type, :source_title, :source_ref, :content_hash, :version, :graph_status, :updated_at) "
                            f"RETURNING id"
                        ),
                        insert_data,
                    )
                ).scalar()
                snap_new = {
                    "id": new_id, "exam_scope": lnew.exam_scope, "category_id": pcat,
                    "title": TITLE_NEW, "aliases": lnew.aliases, "search_text": lnew.search_text,
                    "card_type": lnew.card_type, "summary": lnew.summary,
                    "formula_blocks": lnew_blocks, "conditions": lnew.conditions,
                    "symbol_notes": lnew.symbol_notes, "secondary_conclusions": lnew.secondary_conclusions,
                    "error_tips": lnew.error_tips, "examples": lnew.examples,
                    "function_properties": lnew.function_properties, "sort_order": lnew.sort_order,
                    "status": "published", "tags": [], "version": 1,
                }
                await t.execute(
                    text("INSERT INTO formula_card_versions (formula_card_id, version, snapshot, action, edited_by, edit_reason) VALUES (:c, 1, :s, 'create', :e, :r)"),
                    {"c": new_id, "s": json.dumps(snap_new, ensure_ascii=False), "e": padmin, "r": EDIT_REASON_CREATE},
                )
                print(f"[apply] 新建生产 {TITLE_NEW} id={new_id} ver=1")
            elif lnew.content_hash != pnew.content_hash:
                print(f"[warn] 生产 {TITLE_NEW} 已存在且内容不一致（跳过，不覆盖）")

            await t.commit()
            print("\n[apply] 生产同步完成。")
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
