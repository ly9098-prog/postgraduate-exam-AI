#!/usr/bin/env python3
"""Clean inline chapter refs and trailing options text from OS question stems."""
import sqlite3, json, hashlib, re, os

DB = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "postgraduate.db")
db = sqlite3.connect(DB)

rows = db.execute("""
    SELECT id, parsed_content, parsed_options, raw_data, question_hash
    FROM question_imports WHERE subject_id=9 AND question_type='single_choice'
""").fetchall()

# Section-number pattern at very end: \d+.\d+ followed by text
CHAPTER_REF = re.compile(r'(\d+\.\d+\s*\S[^\n]*)$')

stats = {'total': 0, 'ch_ref': 0, 'opts': 0, 'cleaned': 0}

for id_, pc_json, po_json, rd_json, old_qhash in rows:
    pc = json.loads(pc_json) if pc_json else {}
    po = json.loads(po_json) if po_json else {}
    rd = json.loads(rd_json) if rd_json else {}
    stem = pc.get('text', '')

    if not stem:
        continue

    stats['total'] += 1
    original = stem

    # Clean chapter ref at end
    m = CHAPTER_REF.search(stem)
    if m:
        ref_text = m.group(1)
        # Only remove if it's truly at the end (nothing after but whitespace)
        if stem.endswith(ref_text):
            stem = stem[:m.start()].rstrip()
            stats['ch_ref'] += 1

    # Clean trailing options text — iterate to remove multiple inline options
    if po:
        opt_list = sorted(po.values(), key=len, reverse=True)
        changed = True
        while changed:
            changed = False
            for opt_text in opt_list:
                if opt_text and stem.endswith(opt_text):
                    stem = stem[:-len(opt_text)].rstrip()
                    # Clean up option marker (e.g. "A.", "D.")
                    stem = re.sub(r'[A-D][.、．]\s*$', '', stem.rstrip()).rstrip()
                    stats['opts'] += 1
                    changed = True
                    break  # restart with fresh opt_list after each removal

    if stem != original:
        stats['cleaned'] += 1
        pc['text'] = stem
        rd['stem'] = stem
        qhash_input = f"{stem}|{json.dumps(po, sort_keys=True)}"
        new_qhash = hashlib.md5(qhash_input.encode()).hexdigest()[:16]
        if 'old_question_hash' not in rd:
            rd['old_question_hash'] = old_qhash
        db.execute("""UPDATE question_imports SET
            parsed_content=?, raw_data=?, question_hash=?
            WHERE id=?""",
            (json.dumps(pc, ensure_ascii=False),
             json.dumps(rd, ensure_ascii=False),
             new_qhash, id_))

db.commit()

print(f"Total stems: {stats['total']}")
print(f"Chapter refs cleaned: {stats['ch_ref']}")
print(f"Inline options cleaned: {stats['opts']}")
print(f"Total modified: {stats['cleaned']}")

# Verify: show any remaining stems with \d+.\d+章节 ref at end
print("\n=== Remaining stems with trailing chapter ref ===")
remaining = db.execute("""
    SELECT id, json_extract(parsed_content, '$.text')
    FROM question_imports
    WHERE subject_id=9 AND question_type='single_choice'
""").fetchall()
still_noisy = 0
for id_, stem in remaining:
    if CHAPTER_REF.search(stem):
        m = CHAPTER_REF.search(stem)
        if stem.endswith(m.group(1)):
            still_noisy += 1
            print(f"  ID={id_}: ...{stem[-60:]}")
if still_noisy == 0:
    print("  NONE — all clean!")

db.close()
