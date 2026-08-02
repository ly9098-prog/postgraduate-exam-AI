#!/usr/bin/env python3
import json, os, re, sqlite3

BASE = '/home/lmh/projects/postgraduate-ai'
c = sqlite3.connect(BASE + '/backend/postgraduate.db')
c.row_factory = sqlite3.Row
OCR = BASE + '/artifacts/computer-organization-import/backend-ocr/remote'

id_to_page = {}
with open(BASE + '/artifacts/computer-organization-import/ocr-audit/questions.jsonl', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            rec = json.loads(line)
            id_to_page[rec['id']] = rec['page']

def opts_joined(page):
    p = os.path.join(OCR, 'p-%04d.txt' % page)
    if not os.path.exists(p):
        return {}
    lines = [l.strip() for l in open(p, encoding='utf-8').read().split('\n') if l.strip()]
    o = {}
    cur = None
    for l in lines:
        m = re.match(r'^([A-D])\s*[.、．:]\s*(.*)$', l)
        if m:
            cur = m.group(1)
            o[cur] = m.group(2).strip()
        elif cur:
            o[cur] += ' ' + l
    return o

targets = [(718, 'C'), (772, 'B'), (792, 'A'), (799, 'A'), (809, 'A'), (811, 'A'),
           (830, 'A'), (835, 'A'), (836, 'A'), (852, 'A'), (867, 'A'), (872, 'A'),
           (918, 'A'), (936, 'A'), (974, 'A'), (997, 'A'), (1017, 'A')]
for qid, k in targets:
    pg = id_to_page.get(qid)
    r = c.execute('SELECT parsed_options FROM question_imports WHERE id=?', (qid,)).fetchone()
    po = json.loads(r['parsed_options'])
    db = po.get(k)
    oo = opts_joined(pg)
    ocr = oo.get(k, '')
    print('p%d id=%d %s: db=%-18r ocr=%-34r' % (pg, qid, k, db, ocr))
