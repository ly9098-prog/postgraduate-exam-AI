"""从 question_imports 重新生成 ocr-audit/questions.csv。

相比上一版（id,stem,A,B,C,D），新增两列：
  - question_type：题型（526 行为 single_choice，889/1098 为 multi_blank_choice）
  - answer：解析答案
    * single_choice：选项字母（如 B）
    * multi_blank_choice：规范序列化（如 1:D;2:C）

选项列 A/B/C/D：
  - single_choice：取 parsed_options
  - multi_blank_choice：各空共享同一组选项，取 blank_option_groups[0].options

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。
"""
import csv
import json
import os
import sqlite3

REPO = "/home/lmh/projects/postgraduate-ai"
OUT = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/questions.csv")
DB = "postgraduate.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute(
    "SELECT id, question_type, parsed_content, parsed_options, parsed_answer "
    "FROM question_imports WHERE source_file='cs_ds.pdf' ORDER BY id"
)
rows = cur.fetchall()
assert len(rows) == 524, f"expected 524 rows (was 526; 916/1092 六次审计去重删除), got {len(rows)}"


def get_options(pc, po, qtype):
    if qtype == "multi_blank_choice":
        groups = pc.get("blank_option_groups") or []
        if groups:
            opts = groups[0].get("options") or []
            return {str(o.get("key") or "").upper(): str(o.get("text") or "") for o in opts}
        return {}
    if po:
        return {str(k).upper(): str(v) for k, v in po.items()}
    return {}


with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["id", "question_type", "stem", "A", "B", "C", "D", "answer"])
    for r in rows:
        pc = json.loads(r["parsed_content"]) if r["parsed_content"] else {}
        po = json.loads(r["parsed_options"]) if r["parsed_options"] else None
        stem = pc.get("text") or pc.get("stem") or ""
        opts = get_options(pc, po, r["question_type"])
        writer.writerow([
            r["id"],
            r["question_type"],
            stem,
            opts.get("A", ""), opts.get("B", ""), opts.get("C", ""), opts.get("D", ""),
            r["parsed_answer"] or "",
        ])

print(f"written: {OUT} ({len(rows)} rows)")
conn.close()
