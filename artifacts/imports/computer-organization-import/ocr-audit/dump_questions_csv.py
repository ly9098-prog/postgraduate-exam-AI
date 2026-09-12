#!/usr/bin/env python3
"""Dump cs_ds question_imports (subject_id=8) to a CSV: id, page, no, type, stem, A-D, answer_status.

Also emits an all-text JSONL for the OCR-based checks.
"""
import csv
import json
import os

BASE = "/home/lmh/projects/postgraduate-ai"
OUT = os.path.join(BASE, "artifacts/computer-organization-import/ocr-audit")

import sqlite3

conn = sqlite3.connect(os.path.join(BASE, "backend/postgraduate.db"))
conn.row_factory = sqlite3.Row

rows = conn.execute(
    """SELECT id, source_page_start, source_page_end, source_question_no, source_question_label,
              question_type, parsed_content, parsed_options, answer_status, question_hash
       FROM question_imports WHERE subject_id=8
       ORDER BY source_page_start, source_order_index, id"""
).fetchall()

records = []
for r in rows:
    pc = json.loads(r["parsed_content"]) if r["parsed_content"] else {}
    po = json.loads(r["parsed_options"]) if r["parsed_options"] else {}
    stem = pc.get("text") or pc.get("stem") or "" if isinstance(pc, dict) else ""
    records.append({
        "id": r["id"],
        "page": r["source_page_start"],
        "page_end": r["source_page_end"],
        "q_no": r["source_question_no"],
        "q_label": r["source_question_label"],
        "q_type": r["question_type"],
        "stem": stem,
        "A": po.get("A", ""), "B": po.get("B", ""), "C": po.get("C", ""), "D": po.get("D", ""),
        "answer_status": r["answer_status"],
        "hash": r["question_hash"],
    })

csv_path = os.path.join(OUT, "questions.csv")
with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["id", "page", "page_end", "q_no", "q_label", "q_type",
                                      "stem", "A", "B", "C", "D", "answer_status", "hash"])
    w.writeheader()
    for rec in records:
        w.writerow(rec)

with open(os.path.join(OUT, "questions.jsonl"), "w", encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Wrote {len(records)} rows -> {csv_path}")
print(f"Wrote {len(records)} rows -> {os.path.join(OUT, 'questions.jsonl')}")
