#!/usr/bin/env python3
"""publish_all_questions.py

Batch-publish all 510 pending question_imports to the questions table.
Idempotent: skips already-published records.

Usage:
    python scripts/publish_all_questions.py
    python scripts/publish_all_questions.py --dry-run

Safe guards:
    - Duplicate detection by question_hash
    - Stem-similarity fallback (exact stem text)
    - Preserves segments, image_url, source_snapshot_url
    - No force-overwrite of existing questions
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("publish_all")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "postgraduate.db")

from app.features.question_pipeline import process_question_pipeline
from app.utils.question_content import extract_image_urls_from_content


def build_question_record(q_fields, qi, normalized, result):
    """Build a Question record dict from pipeline output and import data."""
    fields = dict(q_fields)

    # Ensure subject_id from the import record
    fields["subject_id"] = qi.get("subject_id")

    # Preserve segments/render_mode from parsed_content
    qi_content = qi.get("parsed_content") or {}
    if isinstance(qi_content, dict) and qi_content.get("render_mode") == "segments":
        content = dict(fields.get("content") or {})
        content["render_mode"] = "segments"
        content["segments"] = qi_content.get("segments")
        fields["content"] = content

    # Extract image URLs from segments
    image_urls = extract_image_urls_from_content(qi_content)
    if image_urls:
        fields["image_url"] = image_urls

    # Preserve source snapshot for admin
    if isinstance(qi_content, dict):
        for key in ("source_snapshot_url", "source_snapshot_full_page"):
            if key in qi_content:
                content = dict(fields.get("content") or {})
                content[key] = qi_content[key]
                fields["content"] = content

    # Add metadata fields
    fields["source"] = qi.get("source_file")
    fields["source_file"] = qi.get("source_file")
    fields["import_batch_id"] = qi.get("batch_id")
    fields["review_status"] = "approved"
    fields["is_active"] = True

    return fields


def publish(args):
    dry_run = args.dry_run
    logger.info("Dry-run mode: %s", dry_run)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")

    # Get all unpublished records
    rows = db.execute("""
        SELECT * FROM question_imports
        WHERE subject_id=7 AND question_id IS NULL
        ORDER BY id
    """).fetchall()

    logger.info("Found %d unpublished records", len(rows))

    # Pre-load existing question_hashes for duplicate detection
    existing_hashes = set()
    for r in db.execute("SELECT question_hash FROM questions WHERE question_hash IS NOT NULL"):
        existing_hashes.add(r[0])

    stats = {"created": 0, "duplicate": 0, "failed": 0, "already_published": 0, "skipped_dry_run": 0}
    errors = []

    for row in rows:
        import_id = row["id"]
        qi = dict(row)

        # Parse JSON fields
        try:
            def _safe_json(val, default=None):
                if val is None or (isinstance(val, str) and not val.strip()):
                    return default or {}
                if isinstance(val, (dict, list)):
                    return val
                return json.loads(val)
            pc = _safe_json(qi["parsed_content"], {})
            po = _safe_json(qi["parsed_options"], {})
            pa = _safe_json(qi["parsed_analysis"], {})
        except (json.JSONDecodeError, TypeError) as e:
            errors.append(f"import {import_id}: JSON parse error: {e}")
            stats["failed"] += 1
            continue

        # Run pipeline
        try:
            result = process_question_pipeline(
                {
                    "subject": "ds",
                    "question_type": qi["question_type"],
                    "parsed_content": pc,
                    "parsed_options": po,
                    "parsed_answer": qi["parsed_answer"],
                    "parsed_analysis": pa,
                },
                "manual",
                {"file": qi.get("source_file") or "", "page": 0},
            )
        except Exception as e:
            errors.append(f"import {import_id}: pipeline exception: {e}")
            stats["failed"] += 1
            continue

        if not result["is_valid"]:
            errors.append(f"import {import_id}: pipeline invalid: {result.get('errors', [])}")
            stats["failed"] += 1
            continue

        q_fields = result.get("question_fields", {}) or {}
        question_hash = q_fields.get("question_hash", "")
        normalized = result.get("normalized", {})

        # Duplicate detection
        question_id = None
        if question_hash and question_hash in existing_hashes:
            existing_id = db.execute(
                "SELECT id FROM questions WHERE question_hash=?", (question_hash,)
            ).fetchone()
            if existing_id:
                question_id = existing_id[0]
                stats["duplicate"] += 1
                logger.debug("  import %d: duplicate (question_id=%d)", import_id, question_id)

        # Stem similarity fallback
        if not question_id:
            stem = normalized.get("stem", "")
            if stem:
                similar = db.execute(
                    "SELECT id FROM questions WHERE subject_id=? AND content LIKE ?",
                    (qi.get("subject_id"), f"%{stem[:100]}%"),
                ).fetchone()
                if similar:
                    question_id = similar[0]
                    stats["duplicate"] += 1
                    logger.debug("  import %d: stem-similar duplicate (question_id=%d)", import_id, question_id)

        if dry_run:
            if question_id:
                logger.info("  import %d → duplicate of question %d [DRY-RUN]", import_id, question_id)
            else:
                logger.info("  import %d → would create new question [DRY-RUN]", import_id)
            stats["skipped_dry_run"] += 1
            continue

        # Actually publish
        try:
            if question_id:
                # Link to existing question
                db.execute(
                    "UPDATE question_imports SET status=?, question_id=? WHERE id=?",
                    ("published", question_id, import_id),
                )
            else:
                # Create new Question
                q_record = build_question_record(q_fields, {"parsed_content": pc, "subject_id": qi.get("subject_id"),
                    "source_file": qi.get("source_file"), "batch_id": qi.get("batch_id")}, normalized, result)
                q_record["raw_content"] = str(qi.get("raw_data", ""))

                columns = ", ".join(q_record.keys())
                placeholders = ", ".join(["?"] * len(q_record))
                values = []
                for v in q_record.values():
                    if isinstance(v, (dict, list)):
                        values.append(json.dumps(v, ensure_ascii=False))
                    elif v is None:
                        values.append(None)
                    else:
                        values.append(v)

                cursor = db.execute(
                    f"INSERT INTO questions ({columns}) VALUES ({placeholders})",
                    values,
                )
                question_id = cursor.lastrowid

                db.execute(
                    "UPDATE question_imports SET status=?, question_id=? WHERE id=?",
                    ("published", question_id, import_id),
                )

                # Track hash
                if question_hash:
                    existing_hashes.add(question_hash)

                stats["created"] += 1

            if (stats["created"] + stats["duplicate"]) % 50 == 0:
                db.commit()
                logger.info("  Progress: %d published...", stats["created"] + stats["duplicate"])

        except Exception as e:
            errors.append(f"import {import_id}: publish failed: {e}")
            stats["failed"] += 1

    db.commit()
    db.close()

    # Report
    logger.info("=" * 50)
    logger.info("Publish complete")
    logger.info("  Created:    %d", stats["created"])
    logger.info("  Duplicate:  %d", stats["duplicate"])
    logger.info("  Failed:     %d", stats["failed"])
    logger.info("  Dry-run:    %d", stats["skipped_dry_run"])
    if errors:
        logger.info("  Errors:     %d", len(errors))
        for e in errors[:20]:
            logger.warning("  %s", e)
        if len(errors) > 20:
            logger.warning("  ... and %d more", len(errors) - 20)

    return stats


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Publish all pending questions")
    p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = p.parse_args()
    publish(args)
