#!/usr/bin/env python3
"""OCR cross-validation of cs_ds question_imports (subject_id=8) against page OCR ground truth.

Checks:
  3. image-reference keywords (下图/如图/如下表/...) — confirm reference exists in OCR, no image captured
  4. stem roman-item sequence order + option roman-set decode correctness
  5. options A/B/C/D: keys, per-letter roman-set decode vs OCR, truncation (multi-line join)
  6. stem-option relevance vs own-page OCR + cross-question contamination (leak of prev/next page)

Reads questions.jsonl (DB) + backend-ocr/remote/p-NNNN.txt (ground truth).
"""
import json
import os
import re
import glob

BASE = "/home/lmh/projects/postgraduate-ai"
OUT = os.path.join(BASE, "artifacts/computer-organization-import/ocr-audit")
OCR = os.path.join(BASE, "artifacts/computer-organization-import/backend-ocr/remote")
DATA = os.path.join(OUT, "questions.jsonl")

IMG_KW = re.compile(r"如下图|如右图|如左图|如图|见下图|下表|如表|上表|见下表|如下表|图示|示意图|电路图|时序图|波形|数据通路|连接图|框图|结构图|逻辑图|原理图|流程图|真值表|引脚图|芯片|逻辑门电路图|存储器扩展|译码|接线图")


def load_db():
    recs = []
    with open(DATA, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def load_ocr(page):
    p = os.path.join(OCR, f"p-{page:04d}.txt")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()


def extract_options_joined(text):
    """Extract options from OCR text, joining continuation lines.
    Returns dict letter->value, plus the raw lines.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    opts = {}
    cur = None
    opt_re = re.compile(r"^([A-D])\s*[.、．:]\s*(.*)$")
    for l in lines:
        m = opt_re.match(l)
        if m:
            cur = m.group(1)
            opts[cur] = m.group(2).strip()
        elif cur:
            opts[cur] += "" + l
    return opts


def extract_stem(text, opts):
    """Extract stem as the OCR lines before the first option line."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    opt_re = re.compile(r"^([A-D])\s*[.、．:]")
    parts = []
    for l in lines:
        if opt_re.match(l):
            break
        if re.match(r"^风中易小生|^0$|^第\s*\d+\s*章|^\d+\.\d+\s*\S", l):
            continue
        parts.append(l)
    return "".join(parts)


ROMAN_REPL = [
    ("IⅢI", "3"), ("IⅡI", "3"), ("ⅢI", "3"), ("ⅡI", "2"),
    ("IⅡ", "2"), ("IⅢ", "3"), ("ⅠI", "1"),
    ("Ⅰ", "1"), ("Ⅱ", "2"), ("Ⅲ", "3"), ("Ⅳ", "4"), ("Ⅴ", "5"),
    ("IV", "4"), ("III", "3"), ("II", "2"),
    ("VI", "6"), ("V", "5"), ("X", "10"),
]


def decode_romans(text):
    """Decode roman-numeral values (I=1..) present in a text, as a sorted set."""
    t = text
    for a, b in ROMAN_REPL:
        t = t.replace(a, b)
    # remaining standalone ASCII I -> 1 (but not 'I' inside a word)
    t = re.sub(r"\bI\b", "1", t)
    vals = set()
    for tok in re.findall(r"\d+", t):
        v = int(tok)
        if 1 <= v <= 20:
            vals.add(v)
    return vals


def roman_sequence(text):
    """Ordered list of roman values as they appear in text (for stems)."""
    t = text
    for a, b in ROMAN_REPL:
        t = t.replace(a, b)
    t = re.sub(r"\bI\b", "1", t)
    out = []
    for tok in re.findall(r"\d+", t):
        v = int(tok)
        if 1 <= v <= 10:
            out.append(v)
    return out


def norm_sim(a, b):
    import difflib
    na = re.sub(r"\s+", "", a or "")
    nb = re.sub(r"\s+", "", b or "")
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.9
    return difflib.SequenceMatcher(None, na, nb).ratio()


def main():
    recs = load_db()
    findings = []

    for rec in recs:
        page = rec["page"]
        qid = rec["id"]
        stem = rec["stem"].strip()
        db_opts = {k: (rec.get(k) or "").strip() for k in "ABCD"}
        ocr = load_ocr(page)
        if ocr is None:
            findings.append({"id": qid, "page": page, "check": "OCR_MISSING", "detail": "no ground truth"})
            continue
        ocr_opts = extract_options_joined(ocr)
        ocr_stem = extract_stem(ocr, ocr_opts)

        # ---- check 3: image-reference keywords ----
        kws = sorted(set(IMG_KW.findall(stem)))
        if kws:
            # cross-confirm the keyword appears in the page OCR too
            in_ocr = any(k in ocr for k in kws)
            findings.append({
                "id": qid, "page": page, "check": "C3",
                "rule": "image_ref",
                "keywords": kws,
                "kw_in_page_ocr": in_ocr,
                "image_captured": False,
            })

        # ---- check 4: stem roman sequence order ----
        seq = roman_sequence(stem)
        if len(seq) >= 2:
            # expect 1,2,3,4... strictly increasing without gaps
            bad = False
            for i in range(1, len(seq)):
                if seq[i] != seq[i - 1] + 1:
                    bad = True
                    break
            if bad:
                findings.append({
                    "id": qid, "page": page, "check": "C4",
                    "rule": "stem_roman_seq", "seq": seq,
                    "stem_preview": stem[:80],
                })

        # ---- check 5: options roman decode vs OCR ----
        for k in "ABCD":
            dbv = db_opts.get(k)
            ocrv = ocr_opts.get(k)
            if not ocrv:
                continue
            db_set = decode_romans(dbv)
            ocr_set = decode_romans(ocrv)
            # only meaningful when OCR option contains roman numerals (>=2 distinct values or contains Ⅰ..Ⅳ/I、)
            ocr_has_roman = bool(re.search(r"[ⅠⅡⅢⅣⅤ]|I、|II、|III、|IV、|\bI\b|、I|和I", ocrv))
            if ocr_has_roman and db_set != ocr_set:
                findings.append({
                    "id": qid, "page": page, "check": "C5",
                    "rule": "roman_option_mismatch", "k": k,
                    "db": dbv, "db_set": sorted(db_set),
                    "ocr": ocrv, "ocr_set": sorted(ocr_set),
                })

        # ---- check 5b: option truncation (DB option much shorter than OCR option) ----
        for k in "ABCD":
            dbv = db_opts.get(k)
            ocrv = ocr_opts.get(k)
            if dbv and ocrv and not dbv.endswith("。") and len(ocrv) - len(dbv) >= 4:
                # OCR longer by 4+ chars and DB isn't just a punctuation-trimmed variant
                findings.append({
                    "id": qid, "page": page, "check": "C5",
                    "rule": "option_truncated", "k": k,
                    "db": dbv, "ocr": ocrv,
                })

        # ---- check 6: stem-option relevance vs own page ----
        stem_sim = norm_sim(stem, ocr_stem)
        opt_relevance = {}
        for k in "ABCD":
            dbv = db_opts.get(k)
            ocrv = ocr_opts.get(k)
            if dbv and ocrv:
                opt_relevance[k] = norm_sim(dbv, ocrv)
            else:
                opt_relevance[k] = 0.0
        low = [k for k, v in opt_relevance.items() if v < 0.5]
        if stem_sim < 0.5 or low:
            findings.append({
                "id": qid, "page": page, "check": "C6",
                "rule": "low_relevance",
                "stem_sim": round(stem_sim, 3),
                "opt_sim": {k: round(v, 3) for k, v in opt_relevance.items()},
                "low_opt_keys": low,
                "db_stem": stem[:80], "ocr_stem": ocr_stem[:80],
            })

        # ---- check 6b: cross-question contamination (leak from adjacent pages) ----
        for dpage, dname in ((page - 1, "prev"), (page + 1, "next")):
            if dpage < 1:
                continue
            docr = load_ocr(dpage)
            if not docr:
                continue
            dstem = extract_stem(docr, extract_options_joined(docr))
            dplain = re.sub(r"\s+", "", docr)
            # does DB stem contain a long chunk of the neighbor's stem?
            # use the neighbor's OCR lines (excluding own page)
            for probe, pname in ((stem, "db_stem"),):
                # check if a significant phrase of neighbor stem appears in db stem
                nb_clean = re.sub(r"\s+", "", dstem)
                if len(nb_clean) >= 12:
                    # find longest common contiguous substring
                    a, b = re.sub(r"\s+", "", probe), nb_clean
                    longest = 0
                    # rough: if db stem contains a 10+ char substring of neighbor stem
                    for j in range(len(b) - 9):
                        if b[j:j + 10] in a:
                            longest = 10
                            break
                    if longest >= 10:
                        findings.append({
                            "id": qid, "page": page, "check": "C6",
                            "rule": "contamination", "from_page": dpage, "dir": dname,
                            "shared_snippet": b[max(0, j):j + 24],
                        })
                        break

    with open(os.path.join(OUT, "checks_ocr.jsonl"), "w", encoding="utf-8") as f:
        for x in findings:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    from collections import Counter
    ctr = Counter((x["check"], x["rule"]) for x in findings)
    print("=== OCR cross-check counters ===")
    for k, v in sorted(ctr.items()):
        print(f"  {k}: {v}")
    print("total", len(findings))
    # dump C3 list and C5 roman mismatches + truncations
    print("\n=== C3 image-ref questions ===")
    for x in findings:
        if x["check"] == "C3":
            print(f"  p{x['page']} id={x['id']} kw={x['keywords']} in_ocr={x['kw_in_page_ocr']} captured={x['image_captured']}")
    print("\n=== C5 roman option mismatches ===")
    for x in findings:
        if x["check"] == "C5" and x["rule"] == "roman_option_mismatch":
            print(f"  p{x['page']} id={x['id']} {x['k']}: db={x['db']!r} db_set={x['db_set']} | ocr={x['ocr']!r} ocr_set={x['ocr_set']}")
    print("\n=== C5 option truncations ===")
    for x in findings:
        if x["check"] == "C5" and x["rule"] == "option_truncated":
            print(f"  p{x['page']} id={x['id']} {x['k']}: db={x['db']!r} | ocr={x['ocr']!r}")
    print("\n=== C4 stem roman seq anomalies ===")
    for x in findings:
        if x["check"] == "C4":
            print(f"  p{x['page']} id={x['id']} seq={x['seq']} | {x['stem_preview'][:70]}")
    print("\n=== C6 relevance/contamination ===")
    for x in findings:
        if x["check"] == "C6":
            print(f"  p{x['page']} id={x['id']} [{x['rule']}] {json.dumps(x, ensure_ascii=False)[:180]}")


if __name__ == "__main__":
    main()
