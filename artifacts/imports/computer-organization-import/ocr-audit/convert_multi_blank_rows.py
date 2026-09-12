"""将 cs_ds.pdf 批次中 2 道多空题（id 889、1098）转换为 multi_blank_choice。

背景：批次答案补充时识别出这 2 道实际各有 2 个填空（每题从同一组 A-D 选项各选一），
但库内类型为 single_choice。此脚本按 multi_blank_choice 数据契约拆分：

  - question_type -> "multi_blank_choice"
  - parsed_options -> None（选项移入 blank_option_groups）
  - parsed_content.blank_option_groups = build_blank_option_groups(slots, old_options)
  - parsed_answer -> 规范序列化 "1:D;2:C"（slot:value; 分隔）
  - question_hash -> build_question_hash(stem, [], answer, blank_option_groups=groups)

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。幂等（已是 multi_blank_choice 则跳过）。
"""
import json
import os
import sqlite3

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.features.multi_blank_choice import (  # noqa: E402
    build_blank_option_groups,
    extract_blank_slots,
    serialize_multi_blank_answer,
)
from app.features.question_pipeline import QuestionNormalizer  # noqa: E402

REPO = "/home/lmh/projects/postgraduate-ai"
OUT_LOG = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/multi-blank-convert.jsonl")
BACKUP = os.path.join(REPO, "artifacts/computer-organization-import/backups/backup_multi_blank_pre_convert_20260802.jsonl")
DB = "postgraduate.db"

# (id, 答案空序映射 {slot: letter})
TARGETS = {
    889: {"1": "D", "2": "C"},
    1098: {"1": "B", "2": "D"},
}

normalizer = QuestionNormalizer()


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = []
    for rid in TARGETS:
        cur.execute(
            "SELECT id, parsed_content, parsed_options, parsed_answer, question_type, question_hash "
            "FROM question_imports WHERE id=?",
            (rid,),
        )
        row = cur.fetchone()
        assert row, f"id {rid} 不存在"
        rows.append(row)

    # 备份
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    print(f"backup written: {BACKUP} ({len(rows)} rows)")

    changes = []
    for row in rows:
        rid = row["id"]
        if row["question_type"] == "multi_blank_choice":
            print(f"id {rid}: already multi_blank_choice, skip")
            continue

        pc = json.loads(row["parsed_content"]) if row["parsed_content"] else {}
        po = json.loads(row["parsed_options"]) if row["parsed_options"] else {}
        stem = pc.get("text") or pc.get("stem") or ""
        slots = extract_blank_slots(stem)
        assert len(slots) == 2, f"id {rid}: expected 2 slots, got {slots}"
        assert set(TARGETS[rid].keys()) == set(slots), (
            f"id {rid}: answer slots {TARGETS[rid].keys()} != stem slots {slots}"
        )

        groups = build_blank_option_groups(slots, po)
        assert len(groups) == 2, f"id {rid}: blank groups build failed"
        serialized = serialize_multi_blank_answer(TARGETS[rid], slots)
        new_hash = normalizer.build_question_hash(
            stem, [], serialized, blank_option_groups=groups
        )

        new_pc = dict(pc)
        new_pc["blank_option_groups"] = groups
        old_hash = row["question_hash"]

        cur.execute(
            "UPDATE question_imports SET question_type='multi_blank_choice', "
            "parsed_content=?, parsed_options=NULL, parsed_answer=?, question_hash=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                json.dumps(new_pc, ensure_ascii=False),
                serialized,
                new_hash,
                rid,
            ),
        )
        changes.append({
            "id": rid,
            "old_type": row["question_type"], "new_type": "multi_blank_choice",
            "old_parsed_options": po, "new_parsed_options": None,
            "old_answer": row["parsed_answer"], "new_answer": serialized,
            "old_hash": old_hash, "new_hash": new_hash,
            "blank_slots": slots,
        })
        print(f"id {rid}: converted -> {serialized} (hash {old_hash} -> {new_hash})")

    conn.commit()

    with open(OUT_LOG, "w", encoding="utf-8") as f:
        for ch in changes:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")
    print(f"changes logged: {len(changes)} -> {OUT_LOG}")
    conn.close()


if __name__ == "__main__":
    main()
