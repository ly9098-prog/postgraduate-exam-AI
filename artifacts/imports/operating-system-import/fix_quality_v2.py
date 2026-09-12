#!/usr/bin/env python3
"""Fix remaining quality issues in OS question bank (subject_id=9).

Source of truth: page image OCR (PP-OCRv6) + raw_data for each question.

Fixes:
1. Stems with inline options text — strip appended A/B/C/D text
2. Missing/corrupted options — restore from raw_text / page OCR
3. Flag questions too corrupted to auto-repair
"""
import sqlite3, json, hashlib, re, os

DB = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "postgraduate.db")
db = sqlite3.connect(DB)

SUBJECT_ID = 9
QUESTION_TYPE = "single_choice"

# ---- helpers ----------------------------------------------------------------

def get_q(id_):
    row = db.execute(
        "SELECT id, source_page_start, parsed_content, parsed_options, raw_data, batch_id, source_question_no "
        "FROM question_imports WHERE id=?", (id_,)).fetchone()
    if not row:
        return None
    return {
        'id': row[0], 'page': row[1],
        'pc': json.loads(row[2]) if row[2] else {},
        'po': json.loads(row[3]) if row[3] else {},
        'rd': json.loads(row[4]) if row[4] else {},
        'batch': row[5], 'qno': row[6],
    }

def update_question(id_, new_stem, new_options=None):
    q = get_q(id_)
    if not q:
        print(f"  ID={id_}: NOT FOUND")
        return
    q['pc']['text'] = new_stem
    if new_options is not None:
        q['po'] = new_options
    q['rd']['stem'] = new_stem
    if new_options is not None:
        q['rd']['options'] = [{"key": k, "text": v} for k, v in sorted(new_options.items())]
    qhash_input = f"{new_stem}|{json.dumps(q['po'], sort_keys=True)}"
    new_qhash = hashlib.md5(qhash_input.encode()).hexdigest()[:16]
    db.execute("""UPDATE question_imports SET
        parsed_content=?, parsed_options=?, raw_data=?, question_hash=?
        WHERE id=?""",
        (json.dumps(q['pc'], ensure_ascii=False),
         json.dumps(q['po'], ensure_ascii=False),
         json.dumps(q['rd'], ensure_ascii=False),
         new_qhash, id_))
    print(f"  OK   ID={id_:>4}: stem={new_stem[:60]}... opts={sorted(q['po'].keys())}")

def strip_inline_options(stem, options):
    """Remove inline option texts from the end of a stem."""
    result = stem
    for key in ['D', 'C', 'B', 'A']:  # longest first (reverse order helps)
        opt = options.get(key, '')
        if opt and result.endswith(opt):
            result = result[:-len(opt)].rstrip()
            result = re.sub(rf'{key}[.、．]\s*$', '', result.rstrip()).rstrip()
    return result

# ---- Fixes ------------------------------------------------------------------

print("=" * 60)
print("GROUP 1: Stems with inline options text stripped")
print("=" * 60)

# ID=494: stem ends with option D text (the code listing inline)
q494 = get_q(494)
if q494:
    stem = q494['pc']['text']
    # The inline D text is at the very end: "D.能保证进程互斥进入临界区，不会出现"饥饿"现象"
    # Strip it cleanly by matching the last "D." in stem
    m = re.search(r'D\.能保证进程互斥进入临界区，不会出现[""」]?饥饿[""」]?现象\s*$', stem)
    if m:
        stem_clean = stem[:m.start()].rstrip()
        update_question(494, stem_clean)
    else:
        print(f"  SKIP ID=494: could not locate inline D pattern")

# ID=510: stem has all four options inline
q510 = get_q(510)
if q510:
    stem = q510['pc']['text']
    stem_clean = strip_inline_options(stem, q510['po'])
    # Also fix truncated D option — from page OCR: should end with "有限的内存空间"
    full_d = "所有进程共享一张页表，只有页表中当前使用的页面必须驻留在内存中，以最大限度地节省有限的内存空间"
    po = q510['po'].copy()
    po['D'] = full_d
    update_question(510, stem_clean, po)

# ID=580: stem has A/B/C options inline, plus missing D
q580 = get_q(580)
if q580:
    stem = q580['pc']['text']
    stem_clean = strip_inline_options(stem, q580['po'])
    # Remove any remaining "A." / "B." / "C." that might be left after text removal
    stem_clean = re.sub(r'[A-D][.、．]\s*$', '', stem_clean.rstrip()).rstrip()
    # Fix truncated C option
    full_c = "当输入设备忙时，SPOOLing系统中的用户程序暂停执行，待I/O空闲时再被唤醒执行输出操作"
    # Add D option (from page OCR)
    full_d = "SPOOLing系统中的用户程序可以随时将输出数据送到输出井中，待输出设备空闲时再由SPOOLing系统完成数据的输出操作"
    new_opts = q580['po'].copy()
    new_opts['C'] = full_c
    new_opts['D'] = full_d
    update_question(580, stem_clean, new_opts)

print()
print("=" * 60)
print("GROUP 2: Missing / corrupted option restoration")
print("=" * 60)

# ID=284: stem and options completely wrong (question 42 from page 303)
new_stem_284 = (
    "42.以下存储管理方式中，会产生内部碎片的是()。\n"
    "I.分段虚拟存储管理\n"
    "Ⅱ.分页虚拟存储管理\n"
    "Ⅲ.段页式分区管理\n"
    "IV.固定式分区管理"
)
new_opts_284 = {
    "A": "I、II、III",
    "B": "III、IV",
    "C": "仅Ⅱ",
    "D": "II、III、IV",
}
update_question(284, new_stem_284, new_opts_284)

# ID=285: missing A
new_opts_285 = {
    "A": "I、II",
    "B": "I、IV",
    "C": "仅 I",
    "D": "全都正确",
}
q285 = get_q(285)
if q285:
    update_question(285, q285['pc']['text'], new_opts_285)

# ID=420: options from wrong question (formulas instead of text)
new_opts_420 = {
    "A": "最有效",
    "B": "几乎无效",
    "C": "均衡",
    "D": "以上答案都不对",
}
q420 = get_q(420)
if q420:
    update_question(420, q420['pc']['text'], new_opts_420)

# ID=424: wrong options
new_opts_424 = {
    "A": "PCB",
    "B": "DCT",
    "C": "COCT",
    "D": "CHCT",
}
q424 = get_q(424)
if q424:
    update_question(424, q424['pc']['text'], new_opts_424)

# ID=425: wrong options
new_opts_425 = {
    "A": "独享分配",
    "B": "共享分配",
    "C": "虚拟分配",
    "D": "分区分配",
}
q425 = get_q(425)
if q425:
    update_question(425, q425['pc']['text'], new_opts_425)

# ID=504: compound question with two blanks — pair sub-options
new_opts_504 = {
    "A": "1、绝对",
    "B": "0、名义",
    "C": "IP、逻辑",
    "D": "CS、实",
}
q504 = get_q(504)
if q504:
    update_question(504, q504['pc']['text'], new_opts_504)

# ---- Commit ----------------------------------------------------------------
db.commit()

# ---- Verification ----------------------------------------------------------
print()
print("=" * 60)
print("VERIFICATION")
print("=" * 60)

# Check remaining option count issues
remaining = db.execute("""
    SELECT id, json_extract(parsed_content, '$.text')
    FROM question_imports
    WHERE subject_id=? AND question_type=?
    ORDER BY id
""", (SUBJECT_ID, QUESTION_TYPE)).fetchall()

opt_issues = 0
stem_issues = 0
for id_, stem in remaining:
    po_data = db.execute("SELECT parsed_options FROM question_imports WHERE id=?", (id_,)).fetchone()
    if po_data and po_data[0]:
        po = json.loads(po_data[0])
        keys = set(po.keys())
        if keys != {'A','B','C','D'}:
            opt_issues += 1
            missing = {'A','B','C','D'} - keys
            print(f"  ID={id_:>4}: still missing options {sorted(missing)} (have {sorted(keys)})")
    # Check stem still has inline options
    if stem:
        for k in ['D','C','B','A']:
            pat = f'{k}[.、．]'
            if pat in stem[-30:]:
                stem_issues += 1
                print(f"  ID={id_:>4}: stem still has inline key: ...{stem[-60:]}")
                break

print(f"\nRemaining option issues: {opt_issues}")
print(f"Remaining inline-key issues: {stem_issues}")

# Check roman numeral corruption (regression check)
bad_roman = db.execute("""
    SELECT id FROM question_imports
    WHERE subject_id=? AND question_type=?
    AND (parsed_content LIKE '%ⅡI%' OR parsed_content LIKE '%IⅢI%' OR parsed_content LIKE '%ⅡⅡ%')
""", (SUBJECT_ID, QUESTION_TYPE)).fetchall()
print(f"Roman numeral corruption (regression): {len(bad_roman)}")

db.close()

print("\nDone! Flagged for manual review: ID=194 (p211), ID=262 (p280) — content too corrupted to auto-repair.")
