#!/usr/bin/env python3
"""generate_batch1_dryrun.py

Generate Batch 1 dry-run report for import_ids 407 and 480.
Read-only — no DB or storage modifications.

Output: See --output-dir (default: /tmp/batch-1-dry-run)
  manifest.json, targets.json, before.json, after-proposed.json,
  db-diff.json, file-plan.json, rollback-plan.json, previews/, review.html, approval.json

Usage:
    python scripts/generate_batch1_dryrun.py
    python scripts/generate_batch1_dryrun.py --output-dir artifacts/.../batch-1-dry-run
"""

import hashlib
import html
import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("batch1_dryrun")

# ── Paths ──
IMPORT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(IMPORT_DIR, "backend", "postgraduate.db")
PDF_PATH = os.path.join(IMPORT_DIR, "artifacts", "data-structure-import", "source", "ds_sc.pdf")
PREVIEWS_SRC = os.path.join(
    IMPORT_DIR,
    "artifacts", "backfill", "ds_sc", "visual-v2.1", "run_20260717_0030", "previews",
)

BATCH_IDS = [407, 480]
CROP_VERSION = "visual-v2.1"
STORAGE_PREFIX = "/static/question-assets/202607/ds_sc/"


def _sha256(path):
    if not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json_field(val):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            pass
    return val


def generate(output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    previews_dir = os.path.join(output_dir, "previews")
    os.makedirs(previews_dir, exist_ok=True)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db_sha = _sha256(DB_PATH)
    pdf_sha = _sha256(PDF_PATH)

    targets, before_state, proposed_state = [], {}, {}
    db_diff = {"changes": []}
    file_plan = {"new_files": [], "archive_files": []}

    for import_id in BATCH_IDS:
        logger.info("Processing import_id=%d", import_id)
        row = db.execute("SELECT * FROM question_imports WHERE id=?", (import_id,)).fetchone()
        if not row:
            logger.error("Not found: %d", import_id)
            continue
        qi = dict(row)
        qi["parsed_content"] = _load_json_field(qi.get("parsed_content"))
        qi["parsed_options"] = _load_json_field(qi.get("parsed_options"))

        q, is_published = None, False
        if qi.get("question_id"):
            qr = db.execute("SELECT * FROM questions WHERE id=?", (qi["question_id"],)).fetchone()
            if qr:
                q = dict(qr)
                q["content"] = _load_json_field(q.get("content"))
                q["options"] = _load_json_field(q.get("options"))
                is_published = True

        q_no = str(qi.get("source_question_no", "?"))
        page_num = int(q_no) if q_no.isdigit() else 0

        # ── Build proposed parsed_content ──
        pc = qi.get("parsed_content") or {}
        segments = list(pc.get("segments", []))
        new_seg = {
            "type": "image",
            "semantic_role": "content_image",
            "crop_version": CROP_VERSION,
            "url": f"{STORAGE_PREFIX}q_{import_id}_p{q_no}_{CROP_VERSION}.png",
            "region_type": "diagram",
            "region_id": f"auto_q{import_id}",
            "coordinate_space": "pdf_points",
            "source_page": page_num,
        }
        snapshot_url = f"{STORAGE_PREFIX}snapshot_q{import_id}_p{q_no}_{CROP_VERSION}.png"

        old_url = ""
        for i, seg in enumerate(segments):
            if seg.get("type") == "image":
                new_seg["_replaces"] = {"index": i, "old_url": seg.get("url", "")}
                old_url = seg.get("url", "")
                segments[i] = new_seg
                break
        else:
            segments.append(new_seg)

        proposed_content = dict(pc)
        proposed_content["segments"] = segments
        proposed_content["source_snapshot_url"] = snapshot_url

        # ── Build proposed Question content ──
        proposed_q_content = None
        proposed_q_image_url = None
        if is_published and q:
            qc = q.get("content") or {}
            q_segments = list(qc.get("segments", []))
            for i, seg in enumerate(q_segments):
                if seg.get("type") == "image":
                    q_segments[i] = {"type": "image", "url": new_seg["url"], "semantic_role": "content_image"}
                    break
            proposed_q_content = dict(qc)
            proposed_q_content["segments"] = q_segments
            proposed_q_image_url = [new_seg["url"]]

        # ── Capture state ──
        targets.append({
            "import_id": import_id, "source_question_no": q_no,
            "question_id": qi.get("question_id"), "is_published": is_published,
            "crop_version": CROP_VERSION, "page": page_num,
        })
        before_state[str(import_id)] = {
            "question_imports": {
                "parsed_content": qi.get("parsed_content"),
                "parsed_options": qi.get("parsed_options"),
            },
            "questions": {
                "content": q.get("content") if q else None,
                "image_url": q.get("image_url") if q else None,
                "options": q.get("options") if q else None,
            } if q else None,
        }
        proposed_state[str(import_id)] = {
            "question_imports": {
                "parsed_content": proposed_content,
                "parsed_options": qi.get("parsed_options"),
            },
            "questions": {
                "content": proposed_q_content,
                "image_url": proposed_q_image_url,
                "options": q.get("options") if q else None,
            } if is_published else None,
        }

        db_diff["changes"].extend([
            {"import_id": import_id, "table": "question_imports", "field": "parsed_content.segments[1].url",
             "before": old_url, "after": new_seg["url"]},
            {"import_id": import_id, "table": "question_imports", "field": "parsed_content.source_snapshot_url",
             "before": pc.get("source_snapshot_url"), "after": snapshot_url},
        ])
        if is_published:
            prev_img_url = q.get("image_url") if q else None
            db_diff["changes"].append({
                "import_id": import_id, "table": "questions", "field": "image_url",
                "before": prev_img_url, "after": proposed_q_image_url,
            })

        file_plan["new_files"].extend([
            {"import_id": import_id, "purpose": "content_image", "storage_key": new_seg["url"],
             "source": "PDF page crop (visual-v2.1)", "old_url_to_archive": old_url},
            {"import_id": import_id, "purpose": "source_snapshot", "storage_key": snapshot_url,
             "source": "PDF page crop (visual-v2.1)", "back_office_only": True},
        ])

        # ── Copy previews ──
        src = os.path.join(PREVIEWS_SRC, str(import_id))
        dst = os.path.join(previews_dir, str(import_id))
        if os.path.isdir(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    db.close()

    # ── Rollback and approval ──
    rollback_plan = {
        "strategy": "restore_from_before + archive_cleanup",
        "steps": [
            "1. Restore question_imports.parsed_content to pre-migration state",
            "2. Restore question_imports.parsed_options to pre-migration state",
            "3. Restore questions.content to pre-migration state (if published)",
            "4. Restore questions.image_url to pre-migration state (if published)",
            "5. Delete newly created storage files (zero refcount check)",
            "6. Do NOT delete archived old files (may be referenced elsewhere)",
        ],
        "per_import": before_state,
    }
    approval = {
        "schema": "batch-approval-v1", "batch": "1",
        "target_import_ids": BATCH_IDS,
        "run_metadata": {"db_sha256": db_sha, "pdf_sha256": pdf_sha},
        "approvals": {
            str(iid): {
                "import_id": iid,
                "requires_content_image_approval": "pending",
                "content_bbox_approval": "pending",
                "content_image_approval": "pending",
                "source_snapshot_approval": "pending",
                "segment_placement_approval": "pending",
                "published_sync_approval": "pending",
                "final_approval": "pending",
            } for iid in BATCH_IDS
        },
    }

    # ── Write outputs ──
    data_files = {
        "manifest.json": {
            "schema": "batch-dry-run-v1", "batch": "1",
            "description": "Batch 1: Published broken assets — 407 (q326, Q1) and 480 (q399, Q3)",
            "generated_at": datetime.now().isoformat(),
            "db_sha256": db_sha, "pdf_sha256": pdf_sha,
            "dry_run": True, "no_db_modifications": True, "no_storage_uploads": True,
        },
        "targets.json": {"targets": targets, "total": len(targets)},
        "before.json": before_state,
        "after-proposed.json": proposed_state,
        "db-diff.json": db_diff,
        "file-plan.json": file_plan,
        "rollback-plan.json": rollback_plan,
        "approval.json": approval,
    }
    for name, data in data_files.items():
        with open(os.path.join(output_dir, name), "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Wrote %s", os.path.join(output_dir, name))

    # ── Review HTML ──
    _write_review_html(output_dir, targets, before_state, proposed_state, file_plan, db_diff, approval)
    logger.info("Batch 1 dry-run complete: %s", output_dir)


def _write_review_html(output_dir, targets, before_state, proposed_state, file_plan, db_diff, approval):
    rows = []
    for t in targets:
        iid = str(t["import_id"])
        bef = before_state.get(iid, {})
        aft = proposed_state.get(iid, {})
        bef_str = json.dumps(bef.get("question_imports", {}).get("parsed_content", {}), indent=2, ensure_ascii=False)[:500]
        aft_str = json.dumps(aft.get("question_imports", {}).get("parsed_content", {}), indent=2, ensure_ascii=False)[:500]
        pv = "".join(
            f'<div class=cell><div class=label>{lb}</div><a href="previews/{iid}/{fn}" target=_blank><img src="previews/{iid}/{fn}" loading=lazy></a></div>'
            for lb, fn in [("Full", "full-page.png"), ("Overlay", "overlay.png"), ("Crop", "proposed-content.png")]
            if os.path.isfile(os.path.join(output_dir, "previews", iid, fn))
        )
        fp = "".join(f"<li><b>{x['purpose']}</b>: <code>{x['storage_key'][:50]}…</code></li>" for x in file_plan.get("new_files", []) if str(x.get("import_id")) == iid)
        rows.append(f"<tr><td>{iid}</td><td>q{t['source_question_no']}</td><td>{'✓' if t['is_published'] else ''}</td><td>{pv}</td><td><pre class=d>{html.escape(bef_str)}</pre></td><td><pre class=d>{html.escape(aft_str)}</pre></td><td><ul>{fp}</ul></td></tr>")

    diff_rows = "".join(
        f"<tr><td>{c.get('import_id','')}</td><td><code>{html.escape(c.get('field',''))}</code></td>"
        f"<td><pre class=d>{html.escape(json.dumps(c.get('before'),indent=1,ensure_ascii=False)[:200])}</pre></td>"
        f"<td><pre class=d>{html.escape(json.dumps(c.get('after'),indent=1,ensure_ascii=False)[:200])}</pre></td></tr>"
        for c in db_diff.get("changes", [])
    )

    ap_headers = "".join(f"<th>{h}</th>" for h in ["Import ID"] + list(next(iter(approval.get("approvals", {}).values())).keys()))
    ap_rows = "".join(
        f"<tr><td>{k}</td>{''.join(f'<td><span class=ap-{v}>{v}</span></td>' for v in vv.values())}</tr>"
        for k, vv in approval.get("approvals", {}).items()
    )

    html_content = f"""<!DOCTYPE html>
<html lang=zh-CN><head><meta charset=utf-8><title>Batch 1 Dry-Run</title>
<style>
body{{font-family:-apple-system,sans-serif;margin:20px;background:#111;color:#e0e0e0}}
h1,h2{{color:#ddd}}table{{border-collapse:collapse;width:100%;margin-bottom:20px;font-size:13px}}
th,td{{border:1px solid #333;padding:8px;text-align:left;vertical-align:top}}th{{background:#222}}
pre.d{{font-size:11px;max-height:150px;overflow:auto;background:#1a1a1a;padding:6px;border-radius:4px;white-space:pre-wrap;word-break:break-all}}
code{{background:#2a2a2a;padding:1px 4px;border-radius:3px;font-size:12px}}
.cell{{display:inline-block;margin:4px}}.cell img{{max-width:150px;max-height:100px;border-radius:4px}}
.label{{font-size:10px;color:#999}}.ap-pending{{color:#f0ad4e}}ul{{margin:0;padding-left:16px}}li{{font-size:12px}}
.tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;background:#f0ad4e;color:#000}}
</style></head><body>
<span class=tag>DRY RUN — No modifications made</span>
<h1>Batch 1 Dry-Run: Published Broken Assets</h1>
<p>Targets: <b>407</b> (q326 → Q1) and <b>480</b> (q399 → Q3) &nbsp;|&nbsp; Crop: visual-v2.1</p>
<h2>Target Preview</h2>
<table><thead><tr><th>ID</th><th>Q</th><th>Pub</th><th>Previews</th><th>Before</th><th>After</th><th>File Plan</th></tr></thead><tbody>{rows}</tbody></table>
<h2>DB Diff</h2>
<table><thead><tr><th>ID</th><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>{diff_rows}</tbody></table>
<h2>Approval Status</h2>
<table><thead><tr>{ap_headers}</tr></thead><tbody>{ap_rows}</tbody></table>
<h2>Rollback Plan</h2>
<pre>{html.escape(json.dumps({"strategy":"restore_from_before + archive_cleanup","steps":["Restore question_imports","Restore questions","Delete new storage files (zero refcount)","Do NOT delete archived files"]},indent=2,ensure_ascii=False))}</pre>
</body></html>"""
    with open(os.path.join(output_dir, "review.html"), "w") as f:
        f.write(html_content)
    logger.info("Wrote review.html")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", default="/tmp/batch-1-dry-run")
    args = p.parse_args()
    generate(args.output_dir)
