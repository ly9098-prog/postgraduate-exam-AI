"""第五次审计重复组：硬删除重复项（不允许同题跨章节重复）。

范围：
  - 硬删除 947（与 610 EXACT-1 完全重复，2009 统考真题：CPU 区分指令与数据依据）
  - 硬删除 866（与 757 NEAR-1 近似重复，16MB 半字寻址可寻址单元数）
  - 保留 610、757（先出现者），并追加 review_note 记录去重动作

背景：
  4 行均 status=pending（未确认入正式 questions 表），question_imports 无外键引用，
  硬删除安全。已按用户确认：硬删除 + 保留先出现者。

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。幂等（已删则跳过）。
"""
import json
import os
import sqlite3

REPO = "/home/lmh/projects/postgraduate-ai"
OUT_LOG = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/reaudit5-dedup-delete.jsonl")
BACKUP = os.path.join(REPO, "artifacts/computer-organization-import/backups/backup_cs_ds_dedup_pre_delete_20260802.jsonl")
DB = "postgraduate.db"

DELETE_IDS = [947, 866]      # 被删（重复的后者）
KEEP_NOTES = {               # 保留行追加 note
    610: "五次审计：与 id 947 完全重复（2009 统考真题：CPU 区分指令与数据存放依据，题干仅空格差异），已按业务规则硬删除 947，本行保留（2026-08-02）",
    757: "五次审计：与 id 866 近似重复（16MB 半字寻址可寻址单元数，题意/选项/答案相同，仅“可寻址的/寻址”及句末标点差异），已按业务规则硬删除 866，本行保留（2026-08-02）",
}


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    ids = DELETE_IDS + list(KEEP_NOTES.keys())
    q = ",".join("?" * len(ids))
    cur.execute(
        f"SELECT id, status, question_hash, review_note FROM question_imports WHERE id IN ({q}) ORDER BY id",
        tuple(ids),
    )
    rows = cur.fetchall()
    by_id = {r["id"]: r for r in rows}

    # 前置校验：被删行存在、保留行存在
    for rid in ids:
        assert rid in by_id, f"id {rid} 不存在"

    # ── 备份 ──
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    print(f"backup written: {BACKUP} ({len(rows)} rows)")

    changes = []
    # ── 保留行追加 note ──
    for rid, note in KEEP_NOTES.items():
        r = by_id[rid]
        existing = r["review_note"] or ""
        if "硬删除" in existing:
            print(f"id {rid}: 已有硬删除 note，跳过")
            continue
        new_note = f"{existing}\n{note}" if existing else note
        cur.execute(
            "UPDATE question_imports SET review_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_note, rid),
        )
        changes.append({"id": rid, "field": "review_note_append_keep", "note": note})
        print(f"id {rid}: keeper note appended")

    # ── 硬删除 ──
    for rid in DELETE_IDS:
        r = by_id[rid]
        cur.execute("DELETE FROM question_imports WHERE id=?", (rid,))
        if cur.rowcount != 1:
            raise RuntimeError(f"id {rid}: DELETE rowcount={cur.rowcount}")
        changes.append({"id": rid, "field": "hard_delete", "status": r["status"], "hash": r["question_hash"]})
        print(f"id {rid}: hard deleted (was {r['status']})")

    conn.commit()

    with open(OUT_LOG, "w", encoding="utf-8") as f:
        for ch in changes:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    cur.execute("SELECT COUNT(*) AS n FROM question_imports WHERE source_file='cs_ds.pdf'")
    n = cur.fetchone()["n"]
    print(f"cs_ds.pdf remaining rows: {n} (was 528 -> expected 526)")
    print(f"changes logged: {len(changes)} -> {OUT_LOG}")
    conn.close()


if __name__ == "__main__":
    main()
