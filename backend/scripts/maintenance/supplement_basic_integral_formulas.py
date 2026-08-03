#!/usr/bin/env python3
"""补充「基本积分公式」卡片中图片缺失的公式（数据内容修复，非 schema 迁移）。

可重复执行、幂等；第二次执行为 no-op。用法：
    python supplement_basic_integral_formulas.py \
        --database /absolute/path/postgraduate.db [--dry-run]

遵循 backend/app/api/v1/admin_formulas.py update_formula_card 的既有约定：
    - content_hash = sha256(json.dumps(formula_blocks, sort_keys=True, ensure_ascii=False))
    - version += 1；updated_by / edited_by 优先取用户名 admin 的 active 管理员
    - formula_card_versions 插入 action='update' 的快照
    - published 状态保持不变（项目更新逻辑只把 approved/rejected 转回 draft）
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

EDIT_REASON = "补充图片中的缺失基本积分公式，执行数学等价去重"
TITLE = "基本积分公式"
EXPECTED_CATEGORY_PATH = "高等数学 / 一元函数积分学 / 不定积分与定积分公式"
MAX_BLOCKS = 8
ADMIN_USERNAME = "admin"

# 目标 block 顺序：现有 block 保持相对顺序，新增 block 按此位置插入。
FINAL_ORDER = [
    "幂函数",
    "指数函数",
    "三角函数",
    "三角函数平方",
    "常见有理积分",
    "常见有理积分2",
    "根式积分",
    "换元积分",
]

# 目标公式（label -> 公式列表）。与图片 4.1-4.4 一一对应；幂函数特例由通用公式覆盖，不加入。
TARGET_FORMULAS: dict[str, list[str]] = {
    "幂函数": [
        r"\int x^\mu dx = \frac{x^{\mu+1}}{\mu+1}+C\ (\mu\neq-1)",
        r"\int\frac{dx}{x}=\ln|x|+C",
    ],
    "指数函数": [
        r"\int a^x dx = \frac{a^x}{\ln a}+C\ (a>0,\ a\neq1)",
        r"\int e^x dx = e^x+C",
    ],
    "三角函数": [
        r"\int\sin x\,dx=-\cos x+C",
        r"\int\cos x\,dx=\sin x+C",
        r"\int\sec^2x\,dx=\tan x+C",
        r"\int\csc^2x\,dx=-\cot x+C",
        r"\int\tan x\,dx=-\ln|\cos x|+C",
        r"\int\cot x\,dx=\ln|\sin x|+C",
        r"\int\sec x\,dx=\ln|\sec x+\tan x|+C",
        r"\int\csc x\,dx=\ln|\csc x-\cot x|+C",
        r"\int\sec x\tan x\,dx=\sec x+C",
        r"\int\csc x\cot x\,dx=-\csc x+C",
    ],
    "常见有理积分": [
        r"\int\frac{dx}{1+x^2}=\arctan x+C",
        r"\int\frac{dx}{\sqrt{1-x^2}}=\arcsin x+C",
        r"\int\frac{dx}{a^2+x^2}=\frac{1}{a}\arctan\frac{x}{a}+C\ (a>0)",
    ],
    "常见有理积分2": [
        r"\int\frac{dx}{x^2-a^2}=\frac{1}{2a}\ln\left|\frac{x-a}{x+a}\right|+C",
        r"\int\frac{dx}{\sqrt{a^2-x^2}}=\arcsin\frac{x}{a}+C\ (a>0)",
        r"\int\frac{dx}{a^2-x^2}=\frac{1}{2a}\ln\left|\frac{x+a}{x-a}\right|+C\ (a>0)",
    ],
    "根式积分": [
        r"\int\frac{dx}{\sqrt{x^2+a^2}}=\ln\left(x+\sqrt{x^2+a^2}\right)+C\ (a>0)",
        r"\int\frac{dx}{\sqrt{x^2-a^2}}=\ln\left|x+\sqrt{x^2-a^2}\right|+C\ (a>0,\ |x|>a)",
        r"\int\sqrt{a^2-x^2}\,dx=\frac{a^2}{2}\arcsin\frac{x}{a}+\frac{x}{2}\sqrt{a^2-x^2}+C\ (a>0,\ |x|\le a)",
    ],
    "三角函数平方": [
        r"\int\sin^2 x\,dx=\frac{x}{2}-\frac{\sin 2x}{4}+C",
        r"\int\cos^2 x\,dx=\frac{x}{2}+\frac{\sin 2x}{4}+C",
        r"\int\tan^2 x\,dx=\tan x-x+C",
        r"\int\cot^2 x\,dx=-\cot x-x+C",
    ],
    "换元积分": [
        r"\int f(g(x))g'(x)dx = \int f(u)du\quad(u=g(x))",
    ],
}

# 只补适用条件、不新增重复公式：base -> 带条件的完整公式。
CONDITION_RULES: dict[str, list[tuple[str, str]]] = {
    "指数函数": [(
        r"\int a^x dx = \frac{a^x}{\ln a}+C",
        r"\int a^x dx = \frac{a^x}{\ln a}+C\ (a>0,\ a\neq1)",
    )],
    "常见有理积分": [(
        r"\int\frac{dx}{a^2+x^2}=\frac{1}{a}\arctan\frac{x}{a}+C",
        r"\int\frac{dx}{a^2+x^2}=\frac{1}{a}\arctan\frac{x}{a}+C\ (a>0)",
    )],
}

# 由通用幂函数公式 \int x^\mu dx 覆盖、特意不重复添加的特殊形式。
COVERED_SPECIALS = [
    r"\int\frac{1}{x^2}\,dx=-\frac{1}{x}+C",
    r"\int\frac{1}{\sqrt{x}}\,dx=2\sqrt{x}+C",
]


def _norm(s: str) -> str:
    """数学等价规范化，用于单条公式去重比较。"""
    s = re.sub(r"\\[ ,!;]", "", s)  # \, \! \; \ 等间距命令
    s = s.replace("\\quad", "").replace("\\qquad", "")
    s = s.replace("\\left", "").replace("\\right", "")
    s = re.sub(r"\\operatorname\{(\w+)\}", r"\\\1", s)
    s = s.replace("\\vert", "|").replace("\\lvert", "|").replace("\\rvert", "|")
    s = s.replace(r"\frac{1}{\cos x}", r"\sec x").replace(r"\frac{1}{\sin x}", r"\csc x")
    s = s.replace("a^2+x^2", "x^2+a^2")  # 加法交换：a^2+x^2 与 x^2+a^2 相同
    s = re.sub(r"\\frac\s*([^{}\\s])(\s*)([^{}\\s])", r"\\frac{\1}{\3}", s)  # \frac1a → \frac{1}{a}
    prev = None
    while prev != s:  # 去掉外层无意义花括号
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


def _apply_condition_rules(
    label: str, units: list[str]
) -> tuple[list[str], bool, list[tuple[str, str]]]:
    changed = False
    upgraded: list[tuple[str, str]] = []
    for base, conditioned in CONDITION_RULES.get(label, []):
        nb = _norm(base)
        for i, u in enumerate(units):
            nu = _norm(u)
            if nu == nb:
                units[i] = conditioned
                changed = True
                upgraded.append((base, conditioned))
                break
            if nu.startswith(nb):
                break  # 已带条件，跳过
    return units, changed, upgraded


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
        f"postgraduate.before_basic_integral_formula_{ts}.db",
    )
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


def build_target_blocks(
    current_blocks: list[dict],
) -> tuple[list[dict], dict[str, list]]:
    stats: dict[str, list] = {
        "added": [],             # (label, formula)
        "condition_upgraded": [],  # (label, base)
        "skipped_existing": [],    # (label, formula)
        "new_blocks": [],
    }
    current_by_label = {b["label"]: b for b in current_blocks}
    new_blocks: list[dict] = []
    for label in FINAL_ORDER:
        existing = current_by_label.get(label)
        target = TARGET_FORMULAS[label]
        if existing is None:
            units = list(target)
            new_blocks.append({"label": label, "latex": _join_formulas(units)})
            stats["added"].extend((label, f) for f in target)
            stats["new_blocks"].append(label)
            continue

        units_orig = _split_formulas(existing["latex"])
        units = list(units_orig)
        units, cond_changed, upgraded = _apply_condition_rules(label, units)
        if upgraded:
            stats["condition_upgraded"].extend((label, base) for base, _ in upgraded)

        missing = [f for f in target if not any(_norm(u) == _norm(f) for u in units)]
        # 已存在/新增按条件升级前的原公式判断，避免把"补条件"误算成已存在
        for f in target:
            nf = _norm(f)
            if any(_norm(u) == nf for u in units_orig):
                stats["skipped_existing"].append((label, f))
            elif any(_norm(u) == nf for u in units):
                pass  # 被条件升级覆盖，仅在"只补充适用条件"中计数
            else:
                stats["added"].append((label, f))

        if missing:
            units = units + missing
            latex = _join_formulas(units)
        elif cond_changed:
            latex = _join_formulas(units)
        else:
            latex = existing["latex"]  # 原样保留
        new_blocks.append({"label": label, "latex": latex})

    # 目标清单之外的既有 block 一律保留（不删除任何现有公式）
    for label, b in current_by_label.items():
        if label not in FINAL_ORDER:
            new_blocks.append(b)

    return new_blocks, stats


def _print_diff(args, db_path, card, cat_path, current_blocks, new_blocks, stats):
    lines = []
    lines.append("=" * 60)
    lines.append("写入前差异输出")
    lines.append("=" * 60)
    lines.append(f"目标数据库绝对路径 : {os.path.abspath(db_path)}")
    if args.dry_run:
        lines.append("备份路径           : （dry-run 不备份）")
    else:
        lines.append("备份路径           : _backup()（apply 时创建）")
    lines.append(f"目标 formula_card ID: {card['id']}")
    lines.append(f"目标分类完整路径     : {cat_path}")
    lines.append(f"原版本号            : {card['version']}")
    lines.append(f"原 formula_blocks 数量: {len(current_blocks)}")
    lines.append("")
    lines.append("现有公式 canonical keys:")
    for b in current_blocks:
        keys = ", ".join(_norm(u) for u in _split_formulas(b["latex"]))
        lines.append(f"  [{b['label']}] {keys}")
    lines.append("")
    lines.append("准备新增的公式:")
    for label, f in stats["added"]:
        lines.append(f"  [{label}] {f}")
    lines.append("")
    lines.append("已存在而跳过的公式:")
    for label, f in stats["skipped_existing"]:
        lines.append(f"  [{label}] {f}")
    lines.append("")
    lines.append("由通用幂函数公式覆盖而跳过的特殊公式:")
    for f in COVERED_SPECIALS:
        lines.append(f"  {f}")
    lines.append("")
    lines.append("只补充适用条件的公式:")
    for label, base in stats["condition_upgraded"]:
        lines.append(f"  [{label}] {base} → 追加适用条件")
    if not stats["condition_upgraded"]:
        lines.append("  （无）")
    lines.append("")
    lines.append(f"修改后 formula_blocks 数量: {len(new_blocks)}")
    lines.append("=" * 60)
    print("\n".join(lines))


def apply_changes(
    conn: sqlite3.Connection, card: sqlite3.Row, new_blocks: list[dict], admin_id: int | None
) -> None:
    new_version = card["version"] + 1
    content_hash = _compute_content_hash(new_blocks)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    snapshot = {
        "id": card["id"],
        "title": card["title"],
        "category_id": card["category_id"],
        "card_type": card["card_type"],
        "formula_blocks": new_blocks,
        "conditions": card["conditions"],
        "status": card["status"],
        "version": new_version,
    }
    cur = conn.cursor()
    cur.execute(
        "UPDATE formula_cards SET formula_blocks = ?, content_hash = ?, version = ?, "
        "updated_by = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
        (
            json.dumps(new_blocks, ensure_ascii=False),
            content_hash,
            new_version,
            admin_id,
            now,
            card["id"],
        ),
    )
    cur.execute(
        "INSERT INTO formula_card_versions "
        "(formula_card_id, version, snapshot, action, edited_by, edit_reason) "
        "VALUES (?, ?, ?, 'update', ?, ?)",
        (
            card["id"],
            new_version,
            json.dumps(snapshot, ensure_ascii=False),
            admin_id,
            EDIT_REASON,
        ),
    )
    conn.commit()
    print(f"[apply] 已更新 formula_card id={card['id']} version {card['version']} → {new_version}")
    print(f"[apply] content_hash: {card['content_hash'][:12]} → {content_hash[:12]}")
    print(f"[apply] formula_card_versions 新增 version={new_version} (action=update)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="SQLite 数据库绝对路径")
    parser.add_argument("--dry-run", action="store_true", help="只输出差异，不写入")
    args = parser.parse_args()

    db_path = args.database
    if not os.path.isabs(db_path):
        print(f"FATAL: --database 必须是绝对路径: {db_path}", file=sys.stderr)
        return 2
    if not os.path.exists(db_path):
        print(f"FATAL: 数据库不存在: {db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, title, category_id, formula_blocks, version, content_hash, "
            "status, published_at, conditions, card_type, updated_at, updated_by "
            "FROM formula_cards WHERE title = ? AND deleted_at IS NULL",
            (TITLE,),
        ).fetchall()
        if len(rows) != 1:
            print(f"FATAL: 匹配卡片 {len(rows)} 条（期望恰好 1 条），中止且不修改任何数据。", file=sys.stderr)
            return 2
        card = rows[0]

        cat_path = _category_path(conn, card["category_id"])
        if cat_path != EXPECTED_CATEGORY_PATH:
            print(
                f"FATAL: 分类路径不符合预期\n  expected: {EXPECTED_CATEGORY_PATH}\n  actual:   {cat_path}",
                file=sys.stderr,
            )
            return 2

        raw_blocks = card["formula_blocks"]
        current_blocks = json.loads(raw_blocks) if isinstance(raw_blocks, str) else raw_blocks
        if not isinstance(current_blocks, list):
            print(f"FATAL: formula_blocks 不是数组", file=sys.stderr)
            return 2

        new_blocks, stats = build_target_blocks(current_blocks)

        unchanged = (
            not stats["added"]
            and not stats["condition_upgraded"]
            and len(new_blocks) == len(current_blocks)
        )
        if unchanged:
            print("未发现缺失公式，无需更新")
            return 0

        if len(new_blocks) > MAX_BLOCKS:
            print(f"FATAL: 修改后 block 数 {len(new_blocks)} 超过上限 {MAX_BLOCKS}，中止。", file=sys.stderr)
            return 2

        _print_diff(args, db_path, card, cat_path, current_blocks, new_blocks, stats)

        if args.dry_run:
            print("\n[dry-run] 未写入数据库。加 --database 正式执行（将自动备份）。")
            return 0

        backup_path = _backup(db_path)
        print(f"\n[backup] {backup_path}")

        admin_id = _find_admin_id(conn)
        if admin_id is None:
            print("[warn] 未找到 active 管理员，updated_by / edited_by 使用 NULL")
        else:
            print(f"[admin] 使用管理员 id={admin_id} (username=admin)")

        apply_changes(conn, card, new_blocks, admin_id)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
