#!/usr/bin/env python3
"""Quality check OS question bank — targeted issues."""
import sqlite3, json, re, os

DB = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "postgraduate.db")
db = sqlite3.connect(DB)

rows = db.execute("""
  SELECT id, source_page_start, parsed_content, parsed_options, raw_data, batch_id
  FROM question_imports WHERE subject_id=9 AND question_type='single_choice'
""").fetchall()

issues = []

for row in rows:
    id_, page, pc_json, po_json, rd_json, batch = row
    page = page or 0
    pc = json.loads(pc_json) if pc_json else {}
    stem = pc.get('text', '')
    po = json.loads(po_json) if po_json else {}
    rd = json.loads(rd_json) if rd_json else {}

    # -- Check 1: ①②③ ordering issues --
    if '①' in stem or '②' in stem:
        # Find all ① ② ③ ④ positions
        nums = re.findall(r'[①②③④⑤⑥]', stem)
        expected = {'①': 0, '②': 1, '③': 2, '④': 3, '⑤': 4}
        positions = [expected.get(n, 99) for n in nums]
        if positions != sorted(positions):
            issues.append(('CIRCLE_ORDER', id_, page, f"Order {''.join(nums)}: {stem[:200]}"))

    # -- Check 2: ⅠⅡⅢ corruption --
    if 'Ⅰ' in stem or 'Ⅱ' in stem or 'Ⅲ' in stem:
        # Check for corruption: consecutive identical (ⅡⅡ), mixed (ⅡI, IⅢI)
        if 'ⅡⅡ' in stem:
            issues.append(('ROMAN_REPEAT', id_, page, f"Double Ⅱ in: {stem[:200]}"))
        if 'ⅡI' in stem or 'IⅢ' in stem or 'ⅡI' in stem:
            issues.append(('ROMAN_CORRUPT', id_, page, f"Suspicious roman: {stem[:200]}"))
        # Check if roman numerals have blank newlines between them
        lines = stem.split('\n')
        roman_lines = [l for l in lines if re.match(r'\s*[ⅠⅡⅢⅣⅤⅥ]\s*\.', l)]
        if len(roman_lines) > 1:
            # Check gaps
            pass  # just note

    # -- Check 3: Missing close paren in raw stem (before noise removal) --
    stem_clean = stem.split('\n')[0]  # Take first line only (before any appended noise)
    # Only flag if the first line clearly ends with a "()" pattern
    paren_match = re.search(r'[\(（][\)）]?$', stem_clean.strip())
    if not paren_match:
        # Check if the first line genuinely looks like a question needing paren
        if re.search(r'[是啥为指]\s*$', stem_clean.strip()):
            issues.append(('MISSING_PAREN', id_, page, f"First line: {stem_clean.strip()[:80]}"))

    # -- Check 4: Duplicate/repeated content at end of stem --
    # Strip known suffix patterns (chapter refs)
    stripped = re.sub(r'\n1\.\d+\s.*$', '', stem, flags=re.DOTALL).strip()
    stripped = re.sub(r'\n风中易小生.*$', '', stripped, flags=re.DOTALL).strip()
    stripped = re.sub(r'\n风中易小生24考研.*$', '', stripped, flags=re.DOTALL).strip()
    stripped = re.sub(r'【微信公众号:风中易小生】', '', stripped).strip()

    # Check for trailing repeated digit/letter patterns
    m = re.search(r'([A-Z][.、．]\s*[ⅠⅡⅢ]?[A-Z]?[.、．]?[ⅠⅡⅢ]?[.、．]?\s*)+$', stripped)
    if m:
        issues.append(('OPTIONS_IN_STEM', id_, page, f"Options appended: ...{stripped[-80:]}"))

    # Check if options text got appended to stem
    opt_keys = ''.join(sorted(po.keys()))
    for opt_text in po.values():
        if opt_text and opt_text in stripped:
            # Option text embedded in stem is unusual
            pass

    # -- Check 5: Stray characters in parsed_options --
    for k, v in po.items():
        if '@' in v or re.search(r'[①②③④]', v):
            issues.append(('STRAY_IN_OPTION', id_, page, f"Option {k}: {v[:60]}"))

# Deduplicate
seen = set()
unique_issues = []
for iss in issues:
    key = (iss[0], iss[1])
    if key not in seen:
        unique_issues.append(iss)
        seen.add(key)

# Group by type
by_type = {}
for iss in unique_issues:
    by_type.setdefault(iss[0], []).append(iss)

for t, items in sorted(by_type.items()):
    print(f"\n{'='*60}")
    print(f"  {t} ({len(items)} items)")
    print('='*60)
    for _, id_, page, desc in sorted(items, key=lambda x: x[2]):
        print(f"  ID={id_:>4} p{page:>3}: {desc}\n")

# -- Check 6: Count orphan split stems (already done previously) --
# Check for stems that are just option letters like "A.I、II 和 III"
orphan_count = 0
for row in rows:
    id_, page, pc_json, _, _, _ = row
    page = page or 0
    pc = json.loads(pc_json) if pc_json else {}
    stem = pc.get('text', '')
    # If stem starts with A. or B. or only contains option refs
    if re.match(r'^[A-D][.、．]\s*[ⅠII]', stem.strip()):
        orphan_count += 1
        issues.append(('ORPHAN_OPTION_STEM', id_, page, stem[:80]))

# Also check raw_text in raw_data
raw_text_issues = []
for row in rows:
    id_, page, _, _, rd_json, _ = row
    page = page or 0
    rd = json.loads(rd_json) if rd_json else {}
    rt = rd.get('raw_text', '')
    # Check if raw_text has remnants that explain the corruption
    if rt and ('①②' not in rt and '①' in rt):
        pass  # raw_text has ① too

print(f"\n{'='*60}")
print(f"  ORPHAN_OPTION_STEM ({orphan_count} items)")
print('='*60)

db.close()
