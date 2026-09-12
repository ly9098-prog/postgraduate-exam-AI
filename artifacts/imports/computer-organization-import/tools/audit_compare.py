#!/usr/bin/env python3
"""Compare question_imports rows against per-page OCR ground truth for a page range.

For each page in [start, end]:
  - finds the page's OCR text (backend-ocr/remote/p-NNNN.txt)
  - extracts the expected stem + options from OCR text (A./B./C./D. lines)
  - finds the question_imports row(s) mapped to this page
  - reports per-page status: correct | wrong_options | missing | extra | span

Usage:
    .venv/bin/python /abs/audit_compare.py --start 1 --end 10
"""
import argparse
import json
import os
import re
import sys

BASE = "/home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import"


def _norm_roman(s: str) -> str:
    # map unicode Roman numerals and common OCR-garbled variants to ASCII
    s = s.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III")
    s = s.replace("Ⅳ", "IV").replace("Ⅴ", "V")
    s = s.replace("ⅡI", "III").replace("IⅡ", "III").replace("ⅡⅡ", "IV")
    s = s.replace("IⅢI", "III").replace("ⅡI", "III").replace("IⅡI", "III")
    # collapse stray single I's that are noise around a value (e.g. "I、I" -> "I")
    return s


def norm(s: str) -> str:
    s = str(s or "")
    s = s.replace(" ", "").replace("\n", "").replace("　", "").replace("·", "")
    s = s.replace("．", ".").replace(",", "").replace("，", "")
    # common OCR glyph confusions
    s = s.replace("於", "于").replace("買", "买")
    s = re.sub(r"([A-Za-z])o([0-9])", r"\g<1>0\g<2>", s)  # Ao1 -> A01
    # strip punctuation for fuzzy option/stem comparison (OCR noise like "MDR .")
    s = re.sub(r"[.。、：:；;！!？?（）()\[\]【】\"'\"'\-—_→←⇒↔×÷=~]", "", s)
    return _norm_roman(s)


def load_page_ocr(page: int) -> str:
    p = f"{BASE}/backend-ocr/remote/p-{page:04d}.txt"
    if not os.path.exists(p):
        return ""
    with open(p) as f:
        return f.read()


def extract_expected(text: str):
    """Extract stem (before first A./B./C./D.) and option values from OCR text."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    opt_re = re.compile(r"^([A-D])\s*[.、．:：]\s*(.+)$")
    opts = {}
    stem_parts = []
    seen_stem = False
    for l in lines:
        m = opt_re.match(l)
        if m:
            opts[m.group(1)] = m.group(2).strip()
            seen_stem = True
            continue
        # skip watermark / page-number / chapter-header / section-header lines
        if re.match(r"^风中易小生|^0$|^第\s*\d+\s*章|^\d+\.\d+\s*\S|^O$|^o$|^-$", l):
            continue
        stem_parts.append(l)
    stem = "".join(stem_parts)
    return stem, opts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    args = p.parse_args()

    import sqlite3
    conn = sqlite3.connect("/home/lmh/projects/postgraduate-ai/backend/postgraduate.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, source_page_start, source_page_end, parsed_content, parsed_options
           FROM question_imports WHERE source_file='cs_ds.pdf'
           AND ((source_page_start BETWEEN ? AND ?) OR (source_page_end BETWEEN ? AND ?))
           ORDER BY source_page_start""",
        (args.start, args.end, args.start, args.end),
    ).fetchall()
    qis = []
    for r in rows:
        stem = json.loads(r["parsed_content"])["text"] if r["parsed_content"] else ""
        opts = json.loads(r["parsed_options"]) if r["parsed_options"] else {}
        qis.append({"id": r["id"], "p0": r["source_page_start"], "p1": r["source_page_end"], "stem": stem, "opts": opts})
    conn.close()

    qis_by_page = {}
    for q in qis:
        # a question "owns" only its starting page; a span means the continuation
        # page has no dedicated question (1 question/page in this book)
        qis_by_page.setdefault(q["p0"], []).append(q)

    report = []
    for page in range(args.start, args.end + 1):
        text = load_page_ocr(page)
        if not text.strip():
            report.append({"page": page, "status": "no_ocr", "qids": [q["id"] for q in qis_by_page.get(page, [])]})
            continue
        exp_stem, exp_opts = extract_expected(text)
        qlist = qis_by_page.get(page, [])
        if not qlist:
            report.append({"page": page, "status": "missing", "exp_stem": exp_stem, "exp_opts": exp_opts, "qids": []})
            continue
        # find the best-matching question (by stem similarity)
        best = None
        for q in qlist:
            stem_sim = _sim(q["stem"], exp_stem)
            opts_sim = _opts_match(q["opts"], exp_opts)
            if best is None or (opts_sim, stem_sim) > (best[2], best[1]):
                best = (q, stem_sim, opts_sim)
        q, stem_sim, opts_ok = best
        if opts_ok and stem_sim >= 0.7:
            report.append({"page": page, "status": "correct", "qid": q["id"], "qids": [x["id"] for x in qlist]})
        elif opts_ok:
            report.append({"page": page, "status": "stem_minor", "qid": q["id"], "qids": [x["id"] for x in qlist],
                           "db_stem": q["stem"], "exp_stem": exp_stem})
        else:
            report.append({"page": page, "status": "wrong_options", "qid": q["id"], "qids": [x["id"] for x in qlist],
                           "db_stem": q["stem"], "exp_stem": exp_stem,
                           "db_opts": q["opts"], "exp_opts": exp_opts})

    # output
    summary = {}
    for r in report:
        summary.setdefault(r["status"], []).append(r["page"])
    print("=== SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: pages {v}")
    print("=== DETAIL ===")
    for r in report:
        if r["status"] == "correct":
            print(f"p{r['page']:>4}  OK qid={r['qid']}")
        else:
            print(f"p{r['page']:>4}  {r['status'].upper()} qids={r.get('qids')}")
            if r.get("exp_stem"): print(f"        exp_stem: {r['exp_stem'][:60]}")
            if r.get("db_stem"):  print(f"        db_stem:  {r['db_stem'][:60]}")
            if r.get("exp_opts"): print(f"        exp_opts: {json.dumps(r['exp_opts'], ensure_ascii=False)[:120]}")
            if r.get("db_opts"):  print(f"        db_opts:  {json.dumps(r['db_opts'], ensure_ascii=False)[:120]}")
    # write items.jsonl
    with open(f"{BASE}/audit/items.jsonl", "a") as f:
        for r in report:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _sim(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # containment
    if a in b or b in a:
        return 0.9
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def _opts_match(db_opts, exp_opts: dict) -> bool:
    if not exp_opts or not db_opts:
        return False
    if set(db_opts.keys()) != set(exp_opts.keys()):
        return False
    for k in exp_opts:
        a, b = norm(db_opts.get(k)), norm(exp_opts.get(k))
        if a == b:
            continue
        # lenient: OCR truncation / Roman glyph variants
        if a and b and (a in b or b in a):
            continue
        if a and b and _sim(a, b) >= 0.8:
            continue
        return False
    return True


if __name__ == "__main__":
    main()
