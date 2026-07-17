#!/usr/bin/env python3
"""Validate visual-v2.1 migration for import_id 407/302/320.

Usage:
    python scripts/validate_visual_v21_migration.py [--db <db>]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("v21_validate")

BACKEND_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_ROOT)

TARGETS = [
    {"import_id": 407, "qno": 326, "qid": 1, "type": "stem_diagram"},
    {"import_id": 302, "qno": 201, "qid": 148, "type": "option_group"},
    {"import_id": 320, "qno": 229, "qid": 166, "type": "option_group"},
]


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_file(url: str) -> str | None:
    """Resolve an asset URL to a filesystem path."""
    if "/static/" not in url:
        return None
    rel = url.split("/static/", 1)[1]
    candidate = os.path.join(BACKEND_ROOT, "static", rel)
    if os.path.isfile(candidate):
        return os.path.realpath(candidate)
    candidate2 = os.path.join(BACKEND_ROOT, "..", "static", rel)
    if os.path.isfile(candidate2):
        return os.path.realpath(candidate2)
    return None


async def main():
    parser = argparse.ArgumentParser(description="Validate visual-v2.1 migration")
    parser.add_argument("--db", default=None)
    parser.add_argument("--output-dir", default="reports/sprint3h/visual-v21-validation")
    args = parser.parse_args()
    output_dir = os.path.join(BACKEND_ROOT, args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    if args.db:
        os.environ["DATABASE_URL"] = args.db

    import aiosqlite
    import re

    db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")
    db_path = re.sub(r"^sqlite\+aiosqlite:///", "", db_url)
    if not os.path.isabs(db_path):
        db_path = os.path.join(BACKEND_ROOT, db_path)
    db_path = os.path.realpath(db_path)

    results = {}
    all_pass = True
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row

    for target in TARGETS:
        import_id = target["import_id"]
        qid = target["qid"]
        qno = target["qno"]
        itype = target["type"]
        case = {"import_id": import_id, "qno": qno, "question_id": qid,
                "type": itype, "checks": [], "pass": True}

        def check(name: str, ok: bool, detail: str = ""):
            case["checks"].append({"name": name, "pass": ok, "detail": detail})
            if not ok:
                case["pass"] = False

        # 1. Question record exists
        cur = await conn.execute("SELECT id, content, options, image_url FROM questions WHERE id = ?", (qid,))
        row = await cur.fetchone()
        check("question_record_exists", row is not None, f"question_id={qid}")

        if row:
            content = json.loads(row["content"]) if isinstance(row["content"], str) else (row["content"] or {})
            segments = content.get("segments", []) if isinstance(content, dict) else []
            text_segs = [s for s in segments if isinstance(s, dict) and s.get("type") == "text"]
            image_segs = [s for s in segments if isinstance(s, dict) and s.get("type") == "image"]

            check("content_parseable", bool(content), f"keys={list(content.keys()) if isinstance(content, dict) else 'N/A'}")

            if itype == "stem_diagram":
                check("text_segment_exists", len(text_segs) >= 1, f"count={len(text_segs)}")

            urls = [s.get("url", "") for s in image_segs]
            check("no_duplicate_images", len(urls) == len(set(urls)), f"urls={urls}")

            cv = [s.get("crop_version", "") for s in image_segs]
            all_v21 = all(v == "visual-v2.1" for v in cv) if cv else True
            check("crop_version_visual_v21", all_v21, f"versions={cv}")

            for i, seg in enumerate(image_segs):
                url = seg.get("url", "")
                fpath = resolve_file(url)
                exists = fpath and os.path.isfile(fpath)
                check(f"image_{i}_exists", bool(exists), f"url={url[-60:]}")
                if exists and fpath:
                    try:
                        fh = file_hash(fpath)
                        sz = os.path.getsize(fpath)
                        check(f"image_{i}_readable", True, f"hash={fh[:16]} size={sz}")
                    except Exception as e:
                        check(f"image_{i}_readable", False, str(e))

            snap = content.get("source_snapshot_url", "") if isinstance(content, dict) else ""
            if itype == "stem_diagram":
                check("source_snapshot", bool(snap), f"url={snap[-60:]}" if snap else "MISSING")
                if snap:
                    sp = resolve_file(snap)
                    check("snapshot_exists", sp and os.path.isfile(sp), f"path={sp}")

        logger.info("import=%-4d qno=%-4d qid=%-4d %s checks=%d/%d",
                    import_id, qno, qid,
                    "✅" if case["pass"] else "❌",
                    sum(1 for c in case["checks"] if c["pass"]),
                    len(case["checks"]))
        results[import_id] = case
        if not case["pass"]:
            all_pass = False

    await conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "all_pass": all_pass,
        "results": results,
        "summary": {"total": len(TARGETS),
                     "passed": sum(1 for r in results.values() if r["pass"]),
                     "failed": sum(1 for r in results.values() if not r["pass"])},
    }
    rpath = os.path.join(output_dir, "visual_v21_validation.json")
    with open(rpath, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info("Summary: %d/%d passed", report["summary"]["passed"], report["summary"]["total"])


if __name__ == "__main__":
    asyncio.run(main())
