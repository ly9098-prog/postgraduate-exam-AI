#!/usr/bin/env python3
"""把「基本积分公式」卡片（id=19）的"三角函数"block 拆分，提升小程序阅读体验。

拆分方案：
    1. 卡片19「基本积分公式」：三角函数 block 只保留 4 条基础三角
       （sin/cos/sec²/csc²），移除 tan/cot/sec/csc/sec·tan/csc·cot 6 条进阶三角。
       version+1、重算 content_hash、写 formula_card_versions(update) 快照。
    2. 新建卡片「基本积分公式-2」（同分类"不定积分与定积分公式"，card_type=pure_formula），
       公式块为上述 6 条进阶三角，status=published。写 formula_card_versions(create) 快照。

幂等：第二次执行为 no-op。用法：
    python split_basic_integral_trig_to_card2.py \
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

TITLE_MAIN = "基本积分公式"
TITLE_NEW = "基本积分公式-2"
EXPECTED_CATEGORY_PATH = "高等数学 / 一元函数积分学 / 不定积分与定积分公式"
EDIT_REASON_UPDATE = "拆分三角函数 block：进阶三角公式移至「基本积分公式-2」，提升可读性"
EDIT_REASON_CREATE = "从「基本积分公式」拆分三角函数进阶公式，提升可读性"
ADMIN_USERNAME = "admin"

BASIC_TRIG = [
    r"\int\sin x\,dx=-\cos x+C",
    r"\int\cos x\,dx=\sin x+C",
    r"\int\sec^2x\,dx=\tan x+C",
    r"\int\csc^2x\,dx=-\cot x+C",
]
ADVANCED_TRIG = [
    r"\int\tan x\,dx=-\ln|\cos x|+C",
    r"\int\cot x\,dx=\ln|\sin x|+C",
    r"\int\sec x\,dx=\ln|\sec x+\tan x|+C",
    r"\int\csc x\,dx=\ln|\csc x-\cot x|+C",
    r"\int\sec x\tan x\,dx=\sec x+C",
    r"\int\csc x\cot x\,dx=-\csc x+C",
]

NEW_CARD_BLOCKS = [{"label": "三角函数", "latex": r";\ ".join(ADVANCED_TRIG)}]


def _norm(s: str) -> str:
    s = re.sub(r"\\[ ,!;]", "", s)
    s = s.replace("\\quad", "").replace("\\qquad", "")
    s = s.replace("\\left", "").replace("\\right", "")
    s = re.sub(r"\\operatorname\{(\w+)\}", r"\\\1", s)
    s = s.replace("\\vert", "|").replace("\\lvert", "|").replace("\\rvert", "|")
    s = s.replace("a^2+x^2", "x^2+a^2")
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"^\{|\}$", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def _split_formulas(latex: str) -> list[str]:
    units = [u.strip() for u in latex.split(";")]
    units = [re.sub(r"^\\(?:\s|quad|qquad)\s*", "", u) for u in units]
    return [u for u in units if u]


def _join_formulas(units: list[str]) -> str:
    return r";\ ".join(units)


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
        f"postgraduate.before_integral_split_{ts}.db",
    )
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


def _trig_block(blocks: list[dict]) -> dict | None:
    for b in blocks:
        if b.get("label") == "三角函数":
            return b
    return None


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
            (TITLE_MAIN,),
        ).fetchall()
        if len(rows) != 1:
            print(f"FATAL: 「{TITLE_MAIN}」匹配 {len(rows)} 条（期望 1），中止", file=sys.stderr)
            return 2
        card = rows[0]
        cat_path = _category_path(conn, card["category_id"])
        if cat_path != EXPECTED_CATEGORY_PATH:
            print(f"FATAL: 分类路径不符: {cat_path}", file=sys.stderr)
            return 2

        blocks = json.loads(card["formula_blocks"]) if isinstance(card["formula_blocks"], str) else card["formula_blocks"]
        trig = _trig_block(blocks)
        if trig is None:
            print(f"FATAL: 卡片缺少「三角函数」block", file=sys.stderr)
            return 2

        # 当前三角函数单元
        cur_units = _split_formulas(trig["latex"])
        cur_norm = {_norm(u) for u in cur_units}
        adv_present = [f for f in ADVANCED_TRIG if _norm(f) in cur_norm]

        # 卡片19 是否需要更新
        need_update_main = bool(adv_present)
        new_trig_latex = _join_formulas(BASIC_TRIG)
        new_blocks_main = None
        if need_update_main:
            new_blocks_main = [
                ({"label": b["label"], "latex": new_trig_latex} if b is trig else dict(b))
                for b in blocks
            ]

        # 新卡片是否存在 / 是否一致
        new_rows = conn.execute(
            "SELECT * FROM formula_cards WHERE title = ? AND category_id = ? AND deleted_at IS NULL",
            (TITLE_NEW, card["category_id"]),
        ).fetchall()
        new_card = new_rows[0] if len(new_rows) == 1 else None
        new_card_same = False
        if new_card is not None:
            nb = json.loads(new_card["formula_blocks"]) if isinstance(new_card["formula_blocks"], str) else new_card["formula_blocks"]
            new_card_same = _compute_content_hash(nb) == _compute_content_hash(NEW_CARD_BLOCKS)

        changes = []
        if need_update_main:
            changes.append(f"更新卡片{card['id']}「{TITLE_MAIN}」: 三角函数 block {len(cur_units)}条 → {len(BASIC_TRIG)}条 (移除 {len(adv_present)} 条进阶三角)")
        if new_card is None:
            changes.append(f"新建卡片「{TITLE_NEW}」: {len(ADVANCED_TRIG)} 条进阶三角公式，status=published")
        elif not new_card_same:
            changes.append(f"警告: 「{TITLE_NEW}」已存在但内容不同，跳过（不覆盖）")

        work_needed = need_update_main or new_card is None
        if not work_needed:
            if new_card is not None and not new_card_same:
                print("警告: 「基本积分公式-2」已存在但内容与预期不一致（跳过，不覆盖）")
            print("未发现需要拆分的变更，无需更新")
            return 0

        print("=" * 60)
        print("写入前差异")
        print("=" * 60)
        print(f"目标数据库   : {os.path.abspath(db_path)}")
        print(f"卡片19 id    : {card['id']} 版本 {card['version']} 分类 {cat_path}")
        print(f"卡片19 三角函数 block: {len(cur_units)} 条 → {len(BASIC_TRIG)} 条")
        print(f"  移除进阶三角: {[f[:40] for f in adv_present]}")
        print(f"  保留基础三角: {[f[:30] for f in BASIC_TRIG]}")
        print(f"新卡片       : 「{TITLE_NEW}」 category_id={card['category_id']}")
        for f in ADVANCED_TRIG:
            print(f"    {f}")
        if new_card is not None:
            print(f"「{TITLE_NEW}」已存在 id={new_card['id']} 内容{'一致' if new_card_same else '不一致'}")
        for c in changes:
            print(f"  → {c}")
        print("=" * 60)

        if args.dry_run:
            print("\n[dry-run] 未写入。加 --database 正式执行（将自动备份）。")
            return 0

        backup_path = _backup(db_path)
        print(f"\n[backup] {backup_path}")

        admin_id = _find_admin_id(conn)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        cur = conn.cursor()

        # 1) 更新卡片19
        if need_update_main:
            new_version = card["version"] + 1
            new_hash = _compute_content_hash(new_blocks_main)
            snapshot = {
                "id": card["id"], "title": card["title"], "category_id": card["category_id"],
                "card_type": card["card_type"], "formula_blocks": new_blocks_main,
                "conditions": card["conditions"], "status": card["status"], "version": new_version,
            }
            cur.execute(
                "UPDATE formula_cards SET formula_blocks = ?, content_hash = ?, version = ?, "
                "updated_by = ?, updated_at = ? WHERE id = ?",
                (json.dumps(new_blocks_main, ensure_ascii=False), new_hash, new_version,
                 admin_id, now, card["id"]),
            )
            cur.execute(
                "INSERT INTO formula_card_versions (formula_card_id, version, snapshot, action, edited_by, edit_reason) "
                "VALUES (?, ?, ?, 'update', ?, ?)",
                (card["id"], new_version, json.dumps(snapshot, ensure_ascii=False), admin_id, EDIT_REASON_UPDATE),
            )
            print(f"[apply] 卡片{card['id']} version {card['version']} → {new_version} hash {card['content_hash'][:12]} → {new_hash[:12]}")

        # 2) 新建「基本积分公式-2」
        if new_card is None:
            new_hash2 = _compute_content_hash(NEW_CARD_BLOCKS)
            cur.execute(
                "INSERT INTO formula_cards (exam_scope, category_id, title, aliases, search_text, card_type, summary, "
                "formula_blocks, conditions, symbol_notes, secondary_conclusions, error_tips, examples, function_properties, "
                "sort_order, status, reviewed_by, reviewed_at, rejection_reason, published_at, created_by, updated_by, "
                "source_type, source_title, source_ref, content_hash, version, graph_status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "math2", card["category_id"], TITLE_NEW,
                    json.dumps(["三角函数积分公式"], ensure_ascii=False), "", "pure_formula",
                    "基本积分公式的补充：三角函数的不定积分。",
                    json.dumps(NEW_CARD_BLOCKS, ensure_ascii=False),
                    "", "", "", "", None, None,
                    0, "published", None, None, None, now, admin_id, admin_id,
                    "manual", "数学二核心公式 v1", "", new_hash2, 1, "not_applicable", now, now,
                ),
            )
            new_id = cur.lastrowid
            snapshot2 = {
                "id": new_id, "exam_scope": "math2", "category_id": card["category_id"],
                "title": TITLE_NEW, "aliases": ["三角函数积分公式"], "search_text": None,
                "card_type": "pure_formula", "summary": "基本积分公式的补充：三角函数的不定积分。",
                "formula_blocks": NEW_CARD_BLOCKS, "conditions": None, "symbol_notes": None,
                "secondary_conclusions": None, "error_tips": None, "examples": None,
                "function_properties": None, "sort_order": 0, "status": "published",
                "tags": [], "version": 1,
            }
            cur.execute(
                "INSERT INTO formula_card_versions (formula_card_id, version, snapshot, action, edited_by, edit_reason) "
                "VALUES (?, ?, ?, 'create', ?, ?)",
                (new_id, 1, json.dumps(snapshot2, ensure_ascii=False), admin_id, EDIT_REASON_CREATE),
            )
            print(f"[apply] 新建卡片「{TITLE_NEW}」 id={new_id} version=1 hash {new_hash2[:12]}")

        conn.commit()
        print("\n[apply] 拆分完成。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
