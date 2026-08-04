#!/usr/bin/env python3
"""把「基本积分公式」卡片（id=19）的 7 个横向滚动 block 重排为多行/分组渲染。

根因：block 内多条公式以 `;` 连接，小程序 splitFormulaGroup 只按 \\quad 分隔且需
3-6 部分、每部分 complexity≤108 才触发"纵向堆叠"；否则整行超长 → 横向滑动。

重排规则（已用前端 prepareFormulaBlocks 逻辑验证）：
    - 2 条公式 → `\\\\` 换行（gathered 多行渲染，isMultiline=true）
    - 3-4 条公式且每条 complexity≤108 → `\\quad` 连接（触发分组堆叠，isGrouped=true）
    - 公式过长（complexity>108，如常见有理积分2、根式积分）→ `\\\\` 多行最优
      （多行让短公式免滚动，长公式仍会横向滑动，这是前端阈值所致）

幂等：第二次执行为 no-op。用法：
    python reformat_basic_integral_card_blocks.py \
        --database /absolute/path/postgraduate.db [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime

TITLE = "基本积分公式"
EXPECTED_CATEGORY_PATH = "高等数学 / 一元函数积分学 / 不定积分与定积分公式"
EDIT_REASON = "「基本积分公式」block 横向滚动，重排为分组/多行渲染提升可读性"
ADMIN_USERNAME = "admin"

BR = r"\\"      # LaTeX 行内换行（多行渲染）
Q = r"\quad"    # LaTeX 分隔（触发分组堆叠）

TARGET_BLOCKS = [
    {"label": "幂函数", "latex": (
        r"\int x^\mu dx = \frac{x^{\mu+1}}{\mu+1}+C\ (\mu\neq-1)"
        + BR
        + r"\int\frac{dx}{x}=\ln|x|+C"
    )},
    {"label": "指数函数", "latex": (
        r"\int a^x dx = \frac{a^x}{\ln a}+C\ (a>0,\ a\neq1)"
        + BR
        + r"\int e^x dx = e^x+C"
    )},
    {"label": "三角函数", "latex": (
        r"\int\sin x\,dx=-\cos x+C"
        + Q + r"\int\cos x\,dx=\sin x+C"
        + Q + r"\int\sec^2x\,dx=\tan x+C"
        + Q + r"\int\csc^2x\,dx=-\cot x+C"
    )},
    {"label": "三角函数平方", "latex": (
        r"\int\sin^2 x\,dx=\frac{x}{2}-\frac{\sin 2x}{4}+C"
        + Q + r"\int\cos^2 x\,dx=\frac{x}{2}+\frac{\sin 2x}{4}+C"
        + Q + r"\int\tan^2 x\,dx=\tan x-x+C"
        + Q + r"\int\cot^2 x\,dx=-\cot x-x+C"
    )},
    {"label": "常见有理积分", "latex": (
        r"\int\frac{dx}{1+x^2}=\arctan x+C"
        + Q + r"\int\frac{dx}{\sqrt{1-x^2}}=\arcsin x+C"
        + Q + r"\int\frac{dx}{a^2+x^2}=\frac{1}{a}\arctan\frac{x}{a}+C\ (a>0)"
    )},
    {"label": "常见有理积分2", "latex": (
        r"\int\frac{dx}{x^2-a^2}=\frac{1}{2a}\ln\left|\frac{x-a}{x+a}\right|+C"
        + BR
        + r"\int\frac{dx}{\sqrt{a^2-x^2}}=\arcsin\frac{x}{a}+C\ (a>0)"
        + BR
        + r"\int\frac{dx}{a^2-x^2}=\frac{1}{2a}\ln\left|\frac{x+a}{x-a}\right|+C\ (a>0)"
    )},
    {"label": "根式积分", "latex": (
        r"\int\frac{dx}{\sqrt{x^2+a^2}}=\ln\left(x+\sqrt{x^2+a^2}\right)+C\ (a>0)"
        + BR
        + r"\int\frac{dx}{\sqrt{x^2-a^2}}=\ln\left|x+\sqrt{x^2-a^2}\right|+C\ (a>0,\ |x|>a)"
        + BR
        + r"\int\sqrt{a^2-x^2}\,dx=\frac{a^2}{2}\arcsin\frac{x}{a}+\frac{x}{2}\sqrt{a^2-x^2}+C\ (a>0,\ |x|\le a)"
    )},
    {"label": "换元积分", "latex": r"\int f(g(x))g'(x)dx = \int f(u)du\quad(u=g(x))"},
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
        f"postgraduate.before_card_reformat_{ts}.db",
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
            print("已为重排后的多行/分组结构，无需更新")
            return 0

        print("=" * 60)
        print("写入前差异")
        print("=" * 60)
        print(f"目标数据库 : {os.path.abspath(db_path)}")
        print(f"卡片       : 「{TITLE}」 id={card['id']} 版本 {card['version']} 分类 {cat_path}")
        print(f"原 blocks  : {len(cur_blocks)} 个")
        for b in cur_blocks:
            print(f"  [{b['label']}] {str(b['latex'])[:65]}...")
        print(f"新 blocks  : {len(TARGET_BLOCKS)} 个")
        for b in TARGET_BLOCKS:
            print(f"  [{b['label']}]")
            for part in str(b['latex']).split(BR):
                print(f"      {part[:80]}")
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
