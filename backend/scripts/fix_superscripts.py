#!/usr/bin/env python3
"""上标化修复脚本：把 questions.options 中未加花括号的幂次写法转为标准 LaTeX。

目标格式（前端 formatInlineMathText 只识别 ^{...} 与单字符 ^X）：
    2^32      → 2^{32}
    2^n       → 2^{n}
    2^(n-1)   → 2^{n-1}
    2^-126    → 2^{-126}
    2^+1023   → 2^{+1023}

保守规则（避免误吞）：
    - 2^n+1  → 2^{n}+1   （+1 不属于指数）
    - 已存在 ^{...} 不重复处理
    - 内容字段（题干）不含幂次，不处理

修改后重算 question_hash，并 bump updated_at / sync_version 以便同步。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, "")

# 目标行：本地扫描确认的 17 道题（幂次全部在 options）
AFFECTED_IDS = [
    598, 615, 625, 626, 627, 628, 646, 683, 684,
    692, 693, 696, 697, 725, 727, 765, 969,
]


def superscriptize(s: str) -> str:
    """把未加花括号的幂次转为 ^{...}。仅处理 options 字符串值。"""
    # 1) 括号分组指数：^(...) → ^{...}
    s = re.sub(r"\^\(([^()]*)\)", lambda m: "^{" + m.group(1) + "}", s)
    # 2) 单字符/数字串/带符号指数：^X → ^{X}（不含 +1/-1 这种后续符号）
    s = re.sub(r"\^([+-]?[0-9A-Za-z]+)", lambda m: "^{" + m.group(1) + "}", s)
    return s


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="postgraduate.db")
    parser.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    ph = ",".join("?" * len(AFFECTED_IDS))
    cur.execute(
        f"SELECT id, sync_uuid, options, question_hash FROM questions WHERE id IN ({ph})",
        AFFECTED_IDS,
    )
    rows = cur.fetchall()
    if len(rows) != len(AFFECTED_IDS):
        missing = set(AFFECTED_IDS) - {r["id"] for r in rows}
        print(f"WARN: 本地缺少 {len(missing)} 行: {sorted(missing)}")

    changed = []
    for r in rows:
        raw_opts = r["options"]
        old_opts = json.loads(raw_opts) if isinstance(raw_opts, str) else raw_opts
        if not isinstance(old_opts, dict):
            print(f"id={r['id']}: options 非 dict，跳过")
            continue
        new_opts = {}
        for k, v in old_opts.items():
            new_opts[k] = superscriptize(str(v)) if isinstance(v, str) else v
        if new_opts != old_opts:
            changed.append((r["id"], r["sync_uuid"], old_opts, new_opts, r["question_hash"]))

    print(f"扫描 {len(rows)} 行，其中 {len(changed)} 行 options 需要上标化：\n")
    for qid, suuid, old, new, old_hash in changed:
        print(f"--- id={qid} uuid={suuid} ---")
        for k in new:
            if str(old.get(k)) != str(new[k]):
                print(f"  {k}: {old.get(k)!r}")
                print(f"       → {new[k]!r}")

    if not args.apply:
        print(f"\n[dry-run] 共 {len(changed)} 行待修改，未写入。加 --apply 生效。")
        conn.close()
        return

    # 重算 question_hash 并写入
    from app.features.question_pipeline import normalizer

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    updated = 0
    for qid, suuid, old, new, old_hash in changed:
        cur.execute("SELECT content, answer FROM questions WHERE id = ?", (qid,))
        qrow = cur.fetchone()
        raw_content = qrow["content"]
        content = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
        stem = content.get("text", "")
        new_hash = normalizer.build_question_hash(stem, new, qrow["answer"])
        cur.execute(
            "UPDATE questions SET options = ?, question_hash = ?, sync_version = sync_version + 1, updated_at = ? WHERE id = ?",
            (json.dumps(new, ensure_ascii=False), new_hash, now, qid),
        )
        updated += 1
        print(f"id={qid}: hash {old_hash[:12]} → {new_hash[:12]}")

    conn.commit()
    conn.close()
    print(f"\n[apply] 已更新 {updated} 行。")


if __name__ == "__main__":
    main()
