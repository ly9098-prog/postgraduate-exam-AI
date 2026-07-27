#!/usr/bin/env python3
"""Export all function_graph cards' graph_specs + default specs to a deployment JSON.
Run this locally — output file goes into the repo and gets synced to production."""
import json, sqlite3, os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "postgraduate.db")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "app", "data", "formula_library", "deploy_formula_specs.json")

CARD_IDS = list(range(58, 93)) + [201]  # 58-92 + 201

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

specs = {}
missing = []

for cid in CARD_IDS:
    cur.execute(
        "SELECT id, title, graph_spec, graph_status, source_ref FROM formula_cards WHERE id=? AND deleted_at IS NULL",
        (cid,),
    )
    row = cur.fetchone()
    if not row:
        missing.append(cid)
        continue

    cid, title, spec_json, status, source_ref = row
    if not spec_json:
        missing.append((cid, title))
        continue

    spec = json.loads(spec_json) if isinstance(spec_json, str) else spec_json

    # Ensure cross-axis is set
    for p in spec.get("panels", []):
        if p.get("axis_style") != "cross":
            p["axis_style"] = "cross"
            p["x_label"] = ""
            p["y_label"] = ""

    specs[str(cid)] = {
        "title": title,
        "source_ref": source_ref,
        "graph_spec": spec,
    }

conn.close()

deploy = {
    "version": 1,
    "description": "Formula graph_specs for production deployment — export from local DB",
    "cards": specs,
}

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(deploy, f, ensure_ascii=False, indent=2)

print(f"✅ Exported {len(specs)} cards' specs → {OUTPUT_PATH}")
if missing:
    print(f"⚠ Missing {len(missing)} cards: {[m for m in missing]}")
print(f"   Cards: {sorted(int(k) for k in specs.keys())}")
