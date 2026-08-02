#!/usr/bin/env python3
"""OCR error-correction checks on cs_ds question_imports (subject_id=8).

Checks (DB-text based):
  1. stem trailing noise: digit-string / page-ref / repeated-punct at stem end
  2. paren balance: missing closing ')' / '）'
  4. roman-numeral & ①-type sequence ordering within stem/options
  5. options A/B/C/D completeness & order

Outputs ocr-audit/checks_text.jsonl + a readable findings report.
"""
import json
import os
import re

BASE = "/home/lmh/projects/postgraduate-ai"
OUT = os.path.join(BASE, "artifacts/computer-organization-import/ocr-audit")
DATA = os.path.join(OUT, "questions.jsonl")

ROMAN_UNI = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5, "Ⅵ": 6, "Ⅶ": 7, "Ⅷ": 8, "Ⅸ": 9, "Ⅹ": 10}
CIRCLE = {c: i + 1 for i, c in enumerate("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳")}
PUNCT = set("，,。.、；;！!？?：:")


def load():
    recs = []
    with open(DATA, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


# ------------------------------------------------------------------ check 1
# trailing noise patterns (applied to the stem after rstrip)
C1_PATTERNS = [
    ("paren_page_ref", r"[（(]\s*第\s*\d+\s*页\s*[）)]\s*$"),
    ("paren_p_ref",    r"[（(]\s*见?\s*[Pp]\s*\d+\s*[）)]?\s*$"),
    ("trailing_page_ref", r"第\s*\d+\s*页\s*$"),
    ("trailing_p_ref", r"(?<![（(])\b[Pp]\s*\d+\s*$"),
    ("paren_num",      r"[（(]\s*\d+\s*[）)]\s*$"),
    ("trailing_digits", r"(?<![位年个级号页^A-Za-z0-9一-龥()（）])\d{2,}\s*$"),
    ("repeated_punct", r"([，,。.、；;！!？?：:])\1{1,}\s*$"),
    ("repeated_char",  r"(?P<c>[一-龥A-Za-z])(?P=c){2,}\s*$"),
]

# repeated-char runs anywhere in the stem (consecutive identical CJK/letters)
C1_ANYWHERE = re.compile(r"([一-龥A-Za-z])\1{2,}")


def check1(rec):
    issues = []
    stem = rec["stem"].strip()
    if not stem:
        return issues
    for name, pat in C1_PATTERNS:
        m = re.search(pat, stem)
        if m:
            issues.append({"rule": name, "found": m.group(0)})
    for m in C1_ANYWHERE.finditer(stem):
        issues.append({"rule": "repeated_run_anywhere", "found": m.group(0)})
    return issues


# ------------------------------------------------------------------ check 2
def check2(rec):
    issues = []
    stem = rec["stem"].strip()
    # half-width
    ho = stem.count("(")
    hc = stem.count(")")
    # full-width
    fo = stem.count("（")
    fc = stem.count("）")
    if ho > hc:
        issues.append({"rule": "halfwidth_unbalanced", "open": ho, "close": hc})
    if fo > fc:
        issues.append({"rule": "fullwidth_unbalanced", "open": fo, "close": fc})
    if stem.endswith("(") or stem.endswith("（"):
        issues.append({"rule": "trailing_open_paren", "found": stem[-1]})
    # an odd single unpaired closing (more closes than opens) is also noise
    if hc > ho:
        issues.append({"rule": "halfwidth_extra_close", "open": ho, "close": hc})
    if fc > fo:
        issues.append({"rule": "fullwidth_extra_close", "open": fo, "close": fc})
    return issues


# ------------------------------------------------------------------ check 4
def extract_markers(text):
    """Return ordered list of (value, token) for roman/circle/（n）/bare-digit markers."""
    out = []
    # circle numbers ①②③...
    for ch in text:
        if ch in CIRCLE:
            out.append((CIRCLE[ch], ch))
    # unicode roman ⅠⅡⅢ...
    for ch in text:
        if ch in ROMAN_UNI:
            out.append((ROMAN_UNI[ch], ch))
    # parenthesized numbers （3）(2)
    for m in re.finditer(r"[（(]\s*(\d{1,3})\s*[）)]", text):
        out.append((int(m.group(1)), m.group(0)))
    # bare arabic digits in list context: preceded by 、，,；;/space and followed by 、，.。 etc.
    for m in re.finditer(r"(?<=[、，,；;/ ])(\d{1,3})(?=[、，.。:：)）])", text):
        out.append((int(m.group(1)), m.group(0)))
    return out


def check4(rec):
    issues = []
    for field in ["stem", "A", "B", "C", "D"]:
        text = rec.get(field) or ""
        markers = extract_markers(text)
        if len(markers) >= 2:
            vals = [v for v, _ in markers]
            # only meaningful if the run looks like an ordered list (span <= 5 and first is small)
            if vals[-1] - vals[0] <= 5 and vals[0] <= 5:
                # check strictly increasing by 1
                bad = []
                for i in range(1, len(vals)):
                    if vals[i] != vals[i - 1] + 1:
                        bad.append((i, vals[i - 1], vals[i]))
                if bad:
                    issues.append({
                        "rule": "out_of_order",
                        "field": field,
                        "sequence": [(v, t) for v, t in markers],
                        "bad_idx": bad,
                    })
        # single unicode-roman token that is NOT a common legit standalone (Ⅳ/Ⅴ/Ⅵ)
        # e.g. garbled roman in place of option letter — leave to check5/manual
    return issues


# ------------------------------------------------------------------ check 5
def check5(rec):
    issues = []
    keys = [k for k in "ABCD" if rec.get(k) is not None]
    missing = [k for k in "ABCD" if (rec.get(k) or "").strip() == ""]
    if missing:
        issues.append({"rule": "missing_option", "missing": missing})
    if set(keys) != {"A", "B", "C", "D"}:
        issues.append({"rule": "wrong_keys", "keys": keys})
    # duplicate option values
    vals = {k: (rec.get(k) or "").strip() for k in "ABCD"}
    seen = {}
    for k, v in vals.items():
        if v and v in seen and not re.search(r"以上|都对|皆|均|上述", v):
            issues.append({"rule": "duplicate_option", "k": k, "dup_of": seen[v], "value": v[:40]})
        seen[v] = k
    # empty option value
    for k in "ABCD":
        if (rec.get(k) or "").strip() == "":
            issues.append({"rule": "empty_option", "k": k})
    # embedded letter-dot pattern inside an option value => merged/leaked
    for k in "ABCD":
        v = rec.get(k) or ""
        # pattern like "B. " or "B、" or "B．" appearing after some content
        for m in re.finditer(r"[A-D]\s*[.、．]", v):
            pos = m.start()
            if pos > 0:
                issues.append({"rule": "embedded_letter_dot", "k": k, "found": m.group(0),
                               "pos": pos, "context": v[max(0, pos - 12):pos + 12]})
                break
    # very short option value (likely truncated noise)
    for k in "ABCD":
        v = (rec.get(k) or "").strip()
        if v and len(v) < 2:
            issues.append({"rule": "short_option", "k": k, "value": v})
    return issues


def main():
    recs = load()
    findings = []
    for rec in recs:
        for c in (check1, check2, check4, check5):
            for iss in c(rec):
                findings.append({
                    "id": rec["id"],
                    "page": rec["page"],
                    "check": c.__name__.replace("check", "C"),
                    **iss,
                    "stem_preview": rec["stem"][:60],
                })
    # de-dup: some rules may double-report same thing
    uniq = []
    seen_k = set()
    for f in findings:
        key = (f["id"], f["check"], f["rule"], str(f.get("found", "")),
               json.dumps(f.get("sequence", ""), ensure_ascii=False),
               json.dumps(f.get("missing", "")))
        if key in seen_k:
            continue
        seen_k.add(key)
        uniq.append(f)

    with open(os.path.join(OUT, "checks_text.jsonl"), "w", encoding="utf-8") as f:
        for u in uniq:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")

    # readable report grouped by check
    from collections import Counter, defaultdict
    by_check = defaultdict(list)
    for u in uniq:
        by_check[u["check"]].append(u)
    lines = []
    for c in ["C1", "C2", "C4", "C5"]:
        items = by_check.get(c, [])
        lines.append(f"\n===== Check {c} : {len(items)} findings =====")
        for it in items:
            lines.append(f"  id={it['id']} p{it['page']} [{it['rule']}] {it.get('found') or it.get('sequence') or it.get('missing')}  stem: {it['stem_preview']}")
    report = "\n".join(lines)
    print(report)
    with open(os.path.join(OUT, "checks_text_report.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    ctr = Counter((u["check"], u["rule"]) for u in uniq)
    print("\n=== rule counters ===")
    for k, v in sorted(ctr.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
