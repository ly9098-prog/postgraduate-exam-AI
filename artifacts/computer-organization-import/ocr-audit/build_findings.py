#!/usr/bin/env python3
"""Build consolidated findings CSV + final check report for cs_ds OCR audit.

Consolidates manually-verified findings across checks 1-6 into:
  ocr-audit/findings.csv          (machine-readable, one row per finding)
  ocr-audit/check_report.md       (narrative report)
"""
import csv
import json
import os
import re
import sqlite3

BASE = "/home/lmh/projects/postgraduate-ai"
OUT = os.path.join(BASE, "artifacts/computer-organization-import/ocr-audit")
OCR = os.path.join(BASE, "artifacts/computer-organization-import/backend-ocr/remote")

c = sqlite3.connect(BASE + "/backend/postgraduate.db")
c.row_factory = sqlite3.Row

id_to_page = {}
with open(os.path.join(OUT, "questions.jsonl"), encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rec = json.loads(line)
            id_to_page[rec["id"]] = rec["page"]

# ------------------------------------------------------------------ helpers
def db_stem(qid):
    r = c.execute("SELECT parsed_content FROM question_imports WHERE id=?", (qid,)).fetchone()
    return json.loads(r["parsed_content"])["text"]

def db_opts(qid):
    r = c.execute("SELECT parsed_options FROM question_imports WHERE id=?", (qid,)).fetchone()
    return json.loads(r["parsed_options"])

def ocr_text(page):
    p = os.path.join(OCR, "p-%04d.txt" % page)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

findings = []  # list of dicts

def add(qid, page, check, rule, severity, detail, status):
    findings.append({
        "id": qid, "page": page, "check": check, "rule": rule,
        "severity": severity, "detail": detail, "status": status,
    })

# ------------------------------------------------------------------ Check 1: watermark / stem noise
watermark_rows = []
all_rows = c.execute(
    "SELECT id, source_page_start, parsed_content FROM question_imports WHERE subject_id=8 ORDER BY source_page_start"
).fetchall()
for r in all_rows:
    st = json.loads(r["parsed_content"])["text"]
    if "公众号" in st or "风中易小生" in st:
        add(r["id"], r["source_page_start"], "C1", "watermark_in_stem", "high",
            "题干含页脚水印【公众号:风中易小生】", "confirmed")
# trailing roman-answer garbage
garb = {48: "I、/III、IV", 154: "I、/III、IV", 382: "II、/III、IV", 450: "I、/II、III"}
garb_id = {48: 636, 154: 725, 382: 977, 450: 1047}
for pg, g in garb.items():
    add(garb_id[pg], pg, "C1", "trailing_roman_garbage", "high",
        "题干尾部残留答案线索 %s" % g, "confirmed")
add(663, 76, "C1", "stray_token", "low",
    "题干 IV 项后混入提问尾巴且多出孤立')'", "confirmed")
add(739, 118, "C1", "stray_token", "low", "题干尾部残留孤立'C.'", "confirmed")
add(712, 141, "C1", "stray_token", "low", "题干出现重复空括号'(\\n()'", "confirmed")
add(797, 205, "C1", "stray_token", "low", "题干尾部残留'(). [公众号…'", "confirmed")

# ------------------------------------------------------------------ Check 2: paren balance (observation, not defect)
# computed inline below

# ------------------------------------------------------------------ Check 3: figure/table references
add(633, 45, "C3", "table_missing", "critical",
    "引用'如下表'(CPI表)，表格数据丢失，仅剩表头，无法求解", "confirmed")
add(801, 209, "C3", "figure_missing", "critical",
    "引用'如下图'的译码电路图，未截取图片，仅'译码输出'泄漏入题干", "confirmed")
add(851, 255, "C3", "table_garbled", "high",
    "引用'如下表'(TLB快表)，表格数据乱码(有效位/标记/页框号丢失)", "confirmed")
add(856, 260, "C3", "table_missing", "critical",
    "引用'如下表'(页表)，表格数据缺失，无法求解", "confirmed")

# ------------------------------------------------------------------ Check 4: roman-list seq broken
broken_seq = {
    604: [1, 2, 1, 4], 612: [1, 2, 1], 618: [1, 2, 1, 4], 636: [1, 1, 3, 4, 1, 3],
    666: [1, 1], 711: [1, 2, 1, 4], 718: [1, 2, 2, 4, 5], 725: [1, 1, 2, 4, 1, 3],
    781: [1, 1, 2, 4], 816: [1, 2, 1, 4], 967: [1, 2, 2, 4], 977: [1, 2, 3, 4, 2, 3],
    1032: [1, 2, 1], 1047: [1, 2, 1, 4, 1, 2], 1110: [1, 1, 2, 4, 5, 6],
}
for qid, seq in broken_seq.items():
    add(qid, id_to_page[qid], "C4", "roman_seq_broken", "high",
        "题干罗马序号序列错乱: %s" % seq, "confirmed")
add(904, 307, "C4", "circle_seq_broken", "high",
    "①-⑥列表第⑤项编号丢失(④⑤内容合并)", "confirmed")
add(663, 76, "C4", "item_merged", "low",
    "IV 项后提问语尾被合并进该项文本", "confirmed")

# ------------------------------------------------------------------ Check 5: options
# confirmed duplicates / empties
dup = {
    636: ("B=A", "仅I、II；C=仅 I、I；D=仅"), 666: ("B=A", "仅I、II；C=仅II、II；D=I、I和III"),
    678: ("C=B,D=A", "寄存器值列重复，进位标志列丢失"), 767: ("D=A", "仅I；B=仅I和I；C=I、I和II"),
    885: ("C=B", "2002H, 截断"), 977: ("D=C", "仅/仅，罗马列表丢失"),
    1009: ("B=A", "仅I、II 重复"),
}
for qid, (why, det) in dup.items():
    add(qid, id_to_page[qid], "C5", "option_dup_or_empty", "high",
        "选项重复/为空(%s): %s" % (why, det), "confirmed")
# truncation
add(879, 283, "C5", "option_truncated", "high", "A='(P'、C='+' (应含(PC)+A 等)", "confirmed")
add(885, 289, "C5", "option_truncated", "high", "B/C/D 截断: 2002H, /2000H, (丢第二值)", "confirmed")
add(1037, 440, "C5", "option_truncated", "high", "D='IS' (应为 ISA、EISA、PCI、PCI-Express)", "confirmed")
add(904, 307, "C5", "arrow_dropped", "medium", "选项 ②→③ 序列箭头→丢失", "confirmed")

# roman option mismatches (DB vs OCR differ) — needs manual review
roman_manual = {  # page: (qid, option letters)
    16: (603, "A"), 48: (636, "B,C,D"), 79: (666, "B,C,D"), 98: (684, "A"),
    108: (694, "C"), 147: (718, "A"), 154: (725, "A,B,C"), 171: (767, "B,C,D"),
    186: (781, "D"), 220: (816, "A,B,C,D"), 252: (848, "A,C"), 372: (967, "A"),
    382: (977, "B,C,D"), 383: (978, "A,D"), 408: (1005, "B,C,D"), 412: (1009, "B,C"),
    420: (1017, "B,C,D"), 472: (1069, "B"), 485: (1082, "D"), 486: (1083, "A,C,D"),
    488: (1085, "B,D"), 524: (1120, "C,D"),
}
for pg, (qid, letters) in roman_manual.items():
    add(qid, pg, "C5", "roman_option_mismatch", "review",
        "选项罗马数字与OCR读数不一致(需人工核对) 选项%s" % letters, "manual_review")

# ------------------------------------------------------------------ Check 6: contamination
add(747, 126, "C6", "stem_contamination", "critical",
    "题干尾部混入本页选项+下一页(p127)完整题目内容; source_page_end 误为127", "confirmed")

# ------------------------------------------------------------------ write CSV
csv_path = os.path.join(OUT, "findings.csv")
with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["id", "page", "check", "rule", "severity", "detail", "status"])
    w.writeheader()
    for x in sorted(findings, key=lambda x: (x["page"], x["check"])):
        w.writerow(x)
print("Wrote", len(findings), "findings ->", csv_path)

# ------------------------------------------------------------------ counts for report
from collections import Counter
sev = Counter(x["severity"] for x in findings)
print("severity:", dict(sev))
