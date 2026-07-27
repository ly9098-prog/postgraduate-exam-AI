#!/usr/bin/env python3
"""Fix corrupted formula_blocks JSON in existing cards (v1 seed data)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3

# Load v1 JSON data (file has a docstring prefix before the JSON object)
v1_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "app", "data", "formula_library", "math2_core_v1.json")
with open(v1_path, encoding="utf-8") as f:
    content = f.read()
start = content.index("{")
v1_data = json.loads(content[start:])

# Build card title -> formula_blocks map
v1_cards = {}
for subject in v1_data["subjects"]:
    for chapter in subject.get("chapters", []):
        for group in chapter.get("groups", []):
            for card in group.get("cards", []):
                key = card["title"]
                if key not in v1_cards:
                    v1_cards[key] = json.dumps(card["formula_blocks"], ensure_ascii=False)

conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "postgraduate.db"))
cur = conn.cursor()

fixed = 0
cur.execute("SELECT id, title, formula_blocks FROM formula_cards ORDER BY id")
for row in cur.fetchall():
    cid, title, blocks_str = row
    if not blocks_str:
        continue
    try:
        json.loads(blocks_str)
    except Exception:
        if title in v1_cards:
            cur.execute("UPDATE formula_cards SET formula_blocks = ? WHERE id = ?",
                       (v1_cards[title], cid))
            print(f"Fixed #{cid}: {title}")
            fixed += 1
        else:
            print(f"SKIP #{cid}: {title} — not found in v1 source")
            print(f"  Data: {blocks_str[:100]}")

conn.commit()
conn.close()
print(f"\nFixed {fixed} cards total")
