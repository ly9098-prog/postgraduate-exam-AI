"""Apply audit-report-package corrections to local question_imports (cs_ds.pdf batch).

Write-back source (authoritative):
  artifacts/computer-organization-import/audit-report-package/
    question_imports_corrected.csv   -> stem + A/B/C/D for all 528 rows
    question_imports_with_media.csv  -> media_file/media_kind for 13 media records
    question_imports_audit_flagged.csv -> issue_types for audit reason

Changes:
  - parsed_content: set text + stem (preserving any other keys), add media_files for media records
  - parsed_options: set A/B/C/D
  - question_hash: recompute via QuestionNormalizer.build_question_hash (fixes stale hashes
    left by earlier watermark-strip fixes that never recomputed them)

Usage: run from backend/ with backend/.venv python. Idempotent.
"""
import csv
import json
import os
import sqlite3
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.features.question_pipeline import QuestionNormalizer  # noqa: E402

BASE = "/home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import/audit-report-package"
OUT_LOG = "/home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import/ocr-audit/audit-report-writeback.jsonl"
DB = "postgraduate.db"

normalizer = QuestionNormalizer()


def read_csv(name):
    with open(os.path.join(BASE, name), encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    corrected = read_csv("question_imports_corrected.csv")
    with_media = read_csv("question_imports_with_media.csv")
    flagged = read_csv("question_imports_audit_flagged.csv")

    corr = {int(r["id"]): r for r in corrected}
    media = {int(r["id"]): r for r in with_media if r["needs_media"] != "否"}
    flagged_by_id = {int(r["id"]): r for r in flagged}

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id, parsed_content, parsed_options, parsed_answer, question_hash "
        "FROM question_imports WHERE source_file='cs_ds.pdf' ORDER BY id"
    )
    rows = cur.fetchall()
    assert len(rows) == 528, f"expected 528 rows, got {len(rows)}"

    changes = []
    stem_changed = 0
    opt_changed = 0
    media_added = 0
    hash_changed = 0

    for row in rows:
        rid = row["id"]
        c = corr[rid]
        new_stem = c["stem"]
        new_options = {"A": c["A"], "B": c["B"], "C": c["C"], "D": c["D"]}

        old_pc = json.loads(row["parsed_content"]) if row["parsed_content"] else {}
        old_po = json.loads(row["parsed_options"]) if row["parsed_options"] else {}
        old_hash = row["question_hash"]
        old_stem = old_pc.get("text") or old_pc.get("stem") or ""
        answer = row["parsed_answer"] or ""

        new_pc = dict(old_pc)
        if old_pc.get("text") != new_stem or old_pc.get("stem") != new_stem:
            new_pc["text"] = new_stem
            new_pc["stem"] = new_stem
        # ensure stem key present even when value unchanged
        new_pc.setdefault("stem", new_stem)

        if rid in media:
            m = media[rid]
            media_files = new_pc.get("media_files") or []
            entry = {"file": m["media_file"], "kind": m["media_kind"], "page": int(m["source_page"])}
            if entry not in media_files:
                media_files = [*media_files, entry]
                new_pc["media_files"] = media_files
                media_added += 1
                changes.append({
                    "id": rid, "field": "media_files",
                    "old": None, "new": entry, "reason": "需关联源页截图",
                })

        opt_diff_keys = [k for k in new_options if (old_po.get(k) or "") != new_options[k]]
        new_hash = normalizer.build_question_hash(new_stem, new_options, answer)

        # Log stem change
        if old_stem != new_stem:
            stem_changed += 1
            fl = flagged_by_id.get(rid, {})
            changes.append({
                "id": rid, "field": "stem",
                "old": old_stem, "new": new_stem,
                "reason": fl.get("issue_types") or "内容修正",
            })
        for k in opt_diff_keys:
            opt_changed += 1
            fl = flagged_by_id.get(rid, {})
            changes.append({
                "id": rid, "field": f"option_{k}",
                "old": old_po.get(k), "new": new_options[k],
                "reason": fl.get("issue_types") or "选项修正",
            })
        if new_hash != old_hash:
            hash_changed += 1
            changes.append({
                "id": rid, "field": "question_hash",
                "old": old_hash, "new": new_hash,
                "reason": "内容修正后重算hash",
            })

        # Apply
        cur.execute(
            "UPDATE question_imports SET parsed_content=?, parsed_options=?, question_hash=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                json.dumps(new_pc, ensure_ascii=False),
                json.dumps(new_options, ensure_ascii=False),
                new_hash,
                rid,
            ),
        )

    conn.commit()

    with open(OUT_LOG, "w", encoding="utf-8") as f:
        for ch in changes:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    print(f"rows updated: {len(rows)}")
    print(f"stem changed: {stem_changed}, options changed: {opt_changed}, "
          f"media added: {media_added}, hash changed: {hash_changed}")
    print(f"changes logged: {len(changes)} -> {OUT_LOG}")
    conn.close()


if __name__ == "__main__":
    main()
