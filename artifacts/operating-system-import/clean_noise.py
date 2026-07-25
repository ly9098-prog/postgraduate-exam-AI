#!/usr/bin/env python3
"""Detect and remove OCR noise from OS question stems.

Noise patterns detected (appearing in 2+ stems at the tail):
1. \n风中易小生24考研计算机WD操作系统做题本【选择题】 — header watermark
2. \nN.N 章节名称 — chapter/section references
3. 【微信公众号:风中易小生】 — WeChat watermark
"""
import sqlite3, json, hashlib, re, os

DB = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "postgraduate.db")
db = sqlite3.connect(DB)

rows = db.execute("""
    SELECT id, parsed_content, parsed_options, raw_data, question_hash
    FROM question_imports WHERE subject_id=9 AND question_type='single_choice'
""").fetchall()

# Comprehensive noise removal: match trailing noise segments in any order
# Components:
#   \n风中易小生...【选择题】 — page header
#   【微信公众号:风中易小生】 — WeChat watermark
#   \n?\d+\.\d+\s+\S[^\n]* — chapter reference (e.g. \n1.1操作系统的基本概念)
# Use non-capturing groups and + quantifier to eat all contiguous noise segments
TRAILING_NOISE = re.compile(
    r'(?:'
    r'\n\s*风中易小生24考研计算机WD操作系统做题本\s*【选择题】'
    r'|'
    r'【微信公众号:风中易小生】'
    r'|'
    r'\n\s*\d+\.\d+\s*\S[^\n]*'
    r')+\s*$'
)

def clean_stem(stem):
    return TRAILING_NOISE.sub('', stem)

stats = {'total': 0, 'cleaned': 0}

for row in rows:
    id_, pc_json, po_json, rd_json, old_qhash = row
    pc = json.loads(pc_json) if pc_json else {}
    po = json.loads(po_json) if po_json else {}
    rd = json.loads(rd_json) if rd_json else {}
    stem = pc.get('text', '')

    if not stem:
        continue

    stats['total'] += 1
    new_stem = clean_stem(stem)

    if new_stem != stem:
        stats['cleaned'] += 1

        # Update parsed_content
        pc['text'] = new_stem

        # Update raw_data stem
        rd['stem'] = new_stem

        # Recompute hash
        qhash_input = f"{new_stem}|{json.dumps(po, sort_keys=True)}"
        new_qhash = hashlib.md5(qhash_input.encode()).hexdigest()[:16]

        # Preserve old qhash in raw_data for audit
        if 'old_question_hash' not in rd:
            rd['old_question_hash'] = old_qhash

        db.execute("""UPDATE question_imports SET
            parsed_content=?, raw_data=?, question_hash=?
            WHERE id=?""",
            (json.dumps(pc, ensure_ascii=False),
             json.dumps(rd, ensure_ascii=False),
             new_qhash, id_))
        stats['cleaned'] += 1

db.commit()

print(f"Total stems examined: {stats['total']}")
print(f"Stems cleaned: {stats['cleaned']}")
print(f"Remaining with noise (%): ~{stats['total'] - stats['cleaned']} stems unchanged")

# Sample verification: show before/after for first few
print(f"\n--- Sample stems after cleaning ---")
samples = db.execute("""
    SELECT id, json_extract(parsed_content, '$.text')
    FROM question_imports
    WHERE subject_id=9 AND question_type='single_choice'
    LIMIT 10
""").fetchall()
for id_, stem in samples:
    print(f"  ID={id_:>4}: {stem[:80]}")

db.close()
