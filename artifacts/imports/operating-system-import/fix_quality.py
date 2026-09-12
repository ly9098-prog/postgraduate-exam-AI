#!/usr/bin/env python3
"""Fix quality issues in OS question bank (subject_id=9).

Fixes:
1. ①②③ ordering issues (ID=457 corrupted option D)
2. Stem cleanup — remove appended enumeration text, options, chapter refs
3. Roman numeral corruption (ⅡI→III, IⅢI→III, ⅡⅡ→II, etc.)
4. Missing closing parens on stems
5. Options-in-stem corruption (ID=522)
"""
import sqlite3, json, hashlib, os, re

DB = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "postgraduate.db")
SUBJECT_ID = 9
db = sqlite3.connect(DB)

def get_question(id_):
    row = db.execute(
        "SELECT id, source_page_start, parsed_content, parsed_options, raw_data, batch_id, source_question_no "
        "FROM question_imports WHERE id=?", (id_,)).fetchone()
    if not row:
        return None
    id_, page, pc_json, po_json, rd_json, batch, qno = row
    return {
        'id': id_, 'page': page,
        'pc': json.loads(pc_json) if pc_json else {},
        'po': json.loads(po_json) if po_json else {},
        'rd': json.loads(rd_json) if rd_json else {},
        'batch': batch, 'qno': qno,
    }

def update_stem(id_, new_stem, new_options=None):
    """Update parsed_content (stem) and optionally parsed_options for a question."""
    q = get_question(id_)
    if not q:
        print(f"  ID={id_}: NOT FOUND")
        return

    # Update stem
    q['pc']['text'] = new_stem

    # Update options
    if new_options is not None:
        q['po'] = new_options

    # Rebuild raw_data stem/options
    q['rd']['stem'] = new_stem
    if new_options is not None:
        q['rd']['options'] = [{"key": k, "text": v} for k, v in sorted(new_options.items())]

    # Update question_hash
    qhash_input = f"{new_stem}|{json.dumps(q['po'], sort_keys=True)}"
    new_qhash = hashlib.md5(qhash_input.encode()).hexdigest()[:16]

    db.execute("""UPDATE question_imports SET
        parsed_content=?, parsed_options=?, raw_data=?, question_hash=?
        WHERE id=?""",
        (json.dumps(q['pc'], ensure_ascii=False),
         json.dumps(q['po'], ensure_ascii=False),
         json.dumps(q['rd'], ensure_ascii=False),
         new_qhash, id_))
    print(f"  OK   ID={id_:>4}: stem={new_stem[:60]}...")

def strip_appended_noise(stem):
    """Remove chapter refs, header text, and trailing options from stem."""
    # Remove chapter references: "3.2 虚拟内存管理" at end
    stem = re.sub(r'\n\d+\.\d+\s*.*$', '', stem, flags=re.DOTALL)
    # Also same pattern without leading newline (directly at end)
    stem = re.sub(r'\d+\.\d+\s*.*$', '', stem)
    # Remove 风中易小生 header
    stem = re.sub(r'\n风中易小生.*$', '', stem, flags=re.DOTALL)
    # Remove 【微信公众号:风中易小生】
    stem = re.sub(r'【微信公众号:风中易小生】', '', stem)
    # Remove trailing options (A. B. C. D. patterns with roman numerals)
    stem = re.sub(r'[A-D][.、．]\s*.*$', '', stem)
    # Remove trailing enumeration (I. II. III.) that's not part of the stem
    stem = re.sub(r'[ⅠⅡⅢⅣⅤⅥIV]+[.、．]\s*\S.*$', '', stem)
    # Clean up multiple newlines
    stem = re.sub(r'\n{3,}', '\n\n', stem)
    # Clean trailing whitespace
    stem = stem.strip()
    # Remove trailing commas/periods/spaces
    stem = re.sub(r'[，,。\s]+$', '', stem)
    return stem

def ensure_closing_paren(stem):
    """Ensure stem ends with proper closing paren if it looks like it should."""
    stripped = stem.strip()
    if stripped.endswith('(') and not stripped.endswith('()'):
        return stripped + ')'
    # Check if stem ends with Chinese that suggests a question
    if re.search(r'[是为啥指别]\s*$', stripped) and not stripped.endswith(')'):
        return stripped + '()'
    return stripped

print("=" * 60)
print("FIX 1: ID=457 — corrupted option D (@→④→②→① → ③→④→②→①)")
print("=" * 60)
q457 = get_question(457)
if q457:
    new_options = q457['po'].copy()
    new_options['D'] = '③→④→②→①'
    # Also clean stem (remove options text)
    stem = q457['pc']['text']
    # The stem should NOT include the options text
    stem_clean = re.sub(r'[A-D][.、．].*$', '', stem).strip()
    # Remove trailing text after the correct paren
    update_stem(457, stem_clean, new_options)

print("\n" + "=" * 60)
print("FIX 2: ID=447 — garbled stem")
print("=" * 60)
new_stem_447 = "8.下列( )应用工作最好采用实时操作系统平台。"
new_opts_447 = {
    "A": "I、II和III",
    "B": "I、III和IV",
    "C": "I、V和IV",
    "D": "I、III和VI",
}
update_stem(447, new_stem_447, new_opts_447)

print("\n" + "=" * 60)
print("FIX 3: ID=449 — stem has appended text & corrupted ⅡI→II")
print("=" * 60)
new_stem_449 = "14.【2016 统考真题】下列关于批处理系统的叙述中，正确的是()。"
new_opts_449 = {
    "A": "仅II、III",
    "B": "仅II",
    "C": "仅I、II",
    "D": "仅I、III",
}
update_stem(449, new_stem_449, new_opts_449)

print("\n" + "=" * 60)
print("FIX 4: ID=470 — stem has appended text, option B 仅IⅡI→仅II")
print("=" * 60)
new_stem_470 = "53.【2018 统考真题】下列选项中，可能导致当前进程P阻塞的事件是()。"
new_opts_470 = {
    "A": "仅I",
    "B": "仅II",
    "C": "仅I、II",
    "D": "I、II、III",
}
update_stem(470, new_stem_470, new_opts_470)

print("\n" + "=" * 60)
print("FIX 5: ID=471 — stem has corrupted roman numerals (ⅡⅡ→II, ⅡI→III)")
print("=" * 60)
new_stem_471 = "54.【2019 统考真题】下列选项中，可能会将进程唤醒的事件是()。"
new_opts_471 = {
    "A": "仅I",
    "B": "仅II",
    "C": "仅I、II",
    "D": "I、II、III",
}
update_stem(471, new_stem_471, new_opts_471)

print("\n" + "=" * 60)
print("FIX 6: ID=492 — stem has appended text, option A I、ⅡI→I、II")
print("=" * 60)
new_stem_492 = "32.下列关于临界区和临界资源的说法中，正确的是()。"
new_opts_492 = {
    "A": "I、II",
    "B": "I、IV",
    "C": "仅III",
    "D": "以上答案都错误",
}
update_stem(492, new_stem_492, new_opts_492)

print("\n" + "=" * 60)
print("FIX 7: ID=501 — stem/article ⅠⅡⅠ→III in enumeration & option B")
print("=" * 60)
new_stem_501 = "31.【2015 统考真题】若系统S1采用死锁避免方法，S2采用死锁检测方法。下列叙述中，正确的是()。【微信公众号:风中易小生】"
new_opts_501 = {
    "A": "仅I、II",
    "B": "仅II、III",
    "C": "仅I、II",
    "D": "I、II、III",
}
update_stem(501, new_stem_501, new_opts_501)

print("\n" + "=" * 60)
print("FIX 8: ID=511 — stem has appended text, ⅡI→III")
print("=" * 60)
new_stem_511 = "43.下列关于页式存储的论述中，正确的是()。"
new_opts_511 = {
    "A": "I、II、IV",
    "B": "I、IV",
    "C": "仅I",
    "D": "全都正确",
}
update_stem(511, new_stem_511, new_opts_511)

print("\n" + "=" * 60)
print("FIX 9: ID=522 — stem has appended text, option A corrupted")
print("=" * 60)
new_stem_522 = "28.假定有一个请求分页存储管理系统，测得系统各相关设备的利用率为:CPU的利用率为10%，磁盘交换区的利用率为99.7%，其他IO设备的利用率为5%。下面()措施将可能改进CPU的利用率。"
new_opts_522 = {
    "A": "I、II、III、IV",
    "B": "I、III",
    "C": "II、III、V",
    "D": "II、VI",
}
update_stem(522, new_stem_522, new_opts_522)

print("\n" + "=" * 60)
print("FIX 10: ID=530 — stem ⅡI→III")
print("=" * 60)
# Current stem is OK except ⅡI→III. Options are already correct.
q530 = get_question(530)
if q530:
    new_stem_530 = q530['pc']['text']
    # Fix roman numerals in stem: ⅡI → III
    new_stem_530 = new_stem_530.replace('ⅡI', 'III')
    # Also clean up the appended Chapter info and options text
    new_stem_530 = re.sub(r'\n*D\.\S+.*$', '', new_stem_530)
    new_stem_530 = re.sub(r'\n*4\.2\s+目录.*$', '', new_stem_530)
    new_stem_530 = strip_appended_noise(new_stem_530)
    if not new_stem_530.endswith(')'):
        new_stem_530 += '()'
    update_stem(530, new_stem_530)

print("\n" + "=" * 60)
print("FIX 11: ID=531 — stem IⅢI→III, option A/D corrupted")
print("=" * 60)
new_stem_531 = "9.【2017 统考真题】若文件f1的硬链接为f2，两个进程分别打开f1和f2，获得对应的文件描述符为fd1和fd2，则下列叙述中正确的是()。"
new_opts_531 = {
    "A": "仅III",
    "B": "仅II、III",
    "C": "仅I、II",
    "D": "I、II和III",
}
update_stem(531, new_stem_531, new_opts_531)

print("\n" + "=" * 60)
print("FIX 12: ID=576 — stem ⅡI→III, option A 仅ⅡI→仅II")
print("=" * 60)
new_stem_576 = "20.【2017 统考真题】下列选项中，磁盘逻辑格式化程序所做的工作是()。"
new_opts_576 = {
    "A": "仅II",
    "B": "仅II、IV",
    "C": "仅III、IV",
    "D": "仅I、II、IV",
}
update_stem(576, new_stem_576, new_opts_576)

print("\n" + "=" * 60)
print("FIX 13: ID=163 — missing closing paren")
print("=" * 60)
q163 = get_question(163)
if q163:
    new_stem_163 = q163['pc']['text']
    if not new_stem_163.endswith('()'):
        new_stem_163 = new_stem_163.rstrip('，。 ') + '()'
    update_stem(163, new_stem_163)

print("\n" + "=" * 60)
print("FIX 14: ID=333 — missing paren + chapter ref appended")
print("=" * 60)
q333 = get_question(333)
if q333:
    new_stem_333 = q333['pc']['text']
    # Remove chapter ref
    new_stem_333 = strip_appended_noise(new_stem_333)
    if not new_stem_333.endswith('()'):
        new_stem_333 = new_stem_333.rstrip('，。 ') + '()'
    update_stem(333, new_stem_333)

# Commit
db.commit()

# Verify results
print("\n" + "=" * 60)
print("VERIFICATION — count by type")
print("=" * 60)
cnt = dict(db.execute(
    "SELECT question_type, COUNT(*) FROM question_imports WHERE subject_id=? GROUP BY question_type",
    (SUBJECT_ID,)).fetchall())
for k, v in sorted(cnt.items()):
    print(f"  {k}: {v}")
print(f"  total: {sum(cnt.values())}")

# Count still-corrupted roman numerals in stems
still_bad = db.execute("""
    SELECT id, source_page_start, parsed_content
    FROM question_imports
    WHERE subject_id=9 AND question_type='single_choice'
    AND (parsed_content LIKE '%ⅡI%' OR parsed_content LIKE '%IⅢI%' OR parsed_content LIKE '%ⅡⅡ%')
""").fetchall()
print(f"\nRemaining roman numeral corruption: {len(still_bad)}")
for row in still_bad:
    pc = json.loads(row[2])
    print(f"  ID={row[0]} p{row[1]}: {pc.get('text','')[:80]}")

# Check still-missing closing paren
print("\n" + "=" * 60)
print("REMAINING ISSUES CHECK")
result = db.execute("""
    SELECT id, json_extract(parsed_content, '$.text') AS stem
    FROM question_imports WHERE subject_id=9 AND question_type='single_choice'
""").fetchall()
still_missing = []
for id_, stem in result:
    if stem and stem.strip() and not stem.strip().endswith(')') and not stem.strip().endswith('）'):
        still_missing.append((id_, stem[:80]))
print(f"Stems still missing closing paren: {len(still_missing)}")
for id_, s in still_missing:
    print(f"  ID={id_:>4}: {s}")

db.close()
print("\nDone!")
