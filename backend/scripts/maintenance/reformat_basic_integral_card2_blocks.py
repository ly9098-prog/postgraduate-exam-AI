#!/usr/bin/env python3
"""把「基本积分公式-2」卡片由单 block（6 条公式以分号+空格连接）重排为 3 个 block。

背景：单 block 内 6 条公式连成一行，小程序里 `;` 分隔不触发分组渲染
（splitFormulaGroup 只按 \\quad 分隔且需 3-6 部分），导致整行超长需要横向滑动。
改为 3 个 block，每个 block 两条公式用 `\\\\` 换行（gathered 多行渲染），
消除横向滚动。该结构已用前端 prepareFormulaBlocks 逻辑验证：全部
isScrollable=false、isMultiline=true。

幂等：第二次执行为 no-op。用法：
    python reformat_basic_integral_card2_blocks.py \
        --database /absolute/path/postgraduate.db [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

TITLE = "基本积分公式-2"
EXPECTED_CATEGORY_PATH = "高等数学 / 一元函数积分学 / 不定积分与定积分公式"
EDIT_REASON = "「基本积分公式-2」单 block 过长需横向滑动，拆分为 3 个多行 block"
ADMIN_USERNAME = "admin"

BR = r"\\"

TARGET_BLOCKS = [
    {
        "label": "tan 与 cot",
        "latex": (
            r"\int\tan x\,dx=-\ln|\cos x|+C"
            + BR
            + r"\int\cot x\,dx=\ln|\sin x|+C"
        ),
    },
    {
        "label": "sec 与 csc",
        "latex": (
            r"\int\sec x\,dx=\ln|\sec x+\tan x|+C"
            + BR
            + r"\int\csc x\,dx=\ln|\csc x-\cot x|+C"
        ),
    },
    {
        "label": "乘积型",
        "latex": (
            r"\int\sec x\tan x\,dx=\sec x+C"
            + BR
            + r"\int\csc x\cot x\,dx=-\csc x+C"
        ),
    },
]


def _compute_content_hash(blocks: list[dict]) -> str:
    raw = json.dumps(blocks, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _category_path(conn: sqlite3.Connection, category_id: int) -> str:
    names: list[str] = []
    cur_id = category_id
    seen: set[int] = set()
    while cur_id and cur_id not in seen:
        seen.add(cur_id)
        row = conn.execute(
            "SELECT id, name, parent_id FROM formula_categories WHERE id = ?",
            (cur_id,),
        ).fetchone()
        if row is None:
            break
        names.append(row["name"])
        cur_id = row["parent_id"]
    return " / ".join(reversed(names))


def _find_admin_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT id FROM admin_users WHERE username = ? AND is_active = 1 "
        "ORDER BY id LIMIT 1",
        (ADMIN_USERNAME,),
    ).fetchone()
    return row["id"] if row else None


def _backup(db_path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(
        os.path.dirname(os.path.abspath(db_path)),
        f"postgraduate.before_card2_reformat_{ts}.db",
    )
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_path = args.database
    if not os.path.isabs(db_path) or not os.path.exists(db_path):
        print(f"FATAL: --database 必须是存在的绝对路径: {db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM formula_cards WHERE title = ? AND deleted_at IS NULL",
            (TITLE,),
        ).fetchall()
        if len(rows) != 1:
            print(f"FATAL: 「{TITLE}」匹配 {len(rows)} 条（期望 1），中止", file=sys.stderr)
            return 2
        card = rows[0]
        cat_path = _category_path(conn, card["category_id"])
        if cat_path != EXPECTED_CATEGORY_PATH:
            print(f"FATAL: 分类路径不符: {cat_path}", file=sys.stderr)
            return 2

        cur_blocks = json.loads(card["formula_blocks"]) if isinstance(card["formula_blocks"], str) else card["formula_blocks"]
        new_hash = _compute_content_hash(TARGET_BLOCKS)

        if new_hash == card["content_hash"]:
            print("已为重排后的多 block 结构，无需更新")
            return 0

        print("=" * 60)
        print("写入前差异")
        print("=" * 60)
        print(f"目标数据库 : {os.path.abspath(db_path)}")
        print(f"卡片       : 「{TITLE}」 id={card['id']} 版本 {card['version']} 分类 {cat_path}")
        print(f"原 blocks  : {len(cur_blocks)} 个")
        for b in cur_blocks:
            print(f"  [{b['label']}] {str(b['latex'])[:70]}...")
        print(f"新 blocks  : {len(TARGET_BLOCKS)} 个（每个 2 条公式，\\\\ 换行多行渲染）")
        for b in TARGET_BLOCKS:
            print(f"  [{b['label']}]")
            for line in b["latex"].split(BR):
                print(f"      {line}")
        print(f"hash: {card['content_hash'][:12]} → {new_hash[:12]}")
        print("=" * 60)

        if args.dry_run:
            print("\n[dry-run] 未写入。加 --database 正式执行（将自动备份）。")
            return 0

        backup_path = _backup(db_path)
        print(f"\n[backup] {backup_path}")

        admin_id = _find_admin_id(conn)
        new_version = card["version"] + 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        snapshot = {
            "id": card["id"], "title": card["title"], "category_id": card["category_id"],
            "card_type": card["card_type"], "formula_blocks": TARGET_BLOCKS,
            "conditions": card["conditions"], "status": card["status"], "version": new_version,
        }
        cur = conn.cursor()
        cur.execute(
            "UPDATE formula_cards SET formula_blocks = ?, content_hash = ?, version = ?, "
            "updated_by = ?, updated_at = ? WHERE id = ?",
            (json.dumps(TARGET_BLOCKS, ensure_ascii=False), new_hash, new_version,
             admin_id, now, card["id"]),
        )
        cur.execute(
            "INSERT INTO formula_card_versions (formula_card_id, version, snapshot, action, edited_by, edit_reason) "
            "VALUES (?, ?, ?, 'update', ?, ?)",
            (card["id"], new_version, json.dumps(snapshot, ensure_ascii=False), admin_id, EDIT_REASON),
        )
        conn.commit()
        print(f"[apply] 卡片{card['id']}「{TITLE}」 version {card['version']} → {new_version} hash {card['content_hash'][:12]} → {new_hash[:12]}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
