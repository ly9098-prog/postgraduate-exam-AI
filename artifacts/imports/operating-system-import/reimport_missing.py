#!/usr/bin/env python3
"""Re-import missing pages from OS question bank PDF.

Identifies pages (1-497) that have no question_imports entry,
extracts them from the PDF, OCRs via the local pipeline OCR executor,
parses the text into question structure, and inserts into question_imports.

Usage:
    cd backend && python3 ../artifacts/operating-system-import/reimport_missing.py
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import fitz  # PyMuPDF

_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_script_dir, "..", "..", "backend"))
os.environ["APP_ENV"] = "development"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reimport")
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

PDF_PATH = "/home/lmh/projects/postgraduate-ai/ocr_test/import/os_sc.pdf"
DB_PATH = os.path.join(_script_dir, "..", "..", "backend", "postgraduate.db")
SUBJECT_ID = 9
BATCH_SIZE = 25  # OCR batch size


def get_missing_pages() -> list[int]:
    """Return sorted list of page numbers (1-497) with no question_imports entry."""
    import sqlite3
    db = sqlite3.connect(DB_PATH)
    present = set(r[0] for r in db.execute(
        "SELECT DISTINCT source_page_start FROM question_imports WHERE source_page_start IS NOT NULL"
    ).fetchall())
    db.close()
    missing = [p for p in range(1, 498) if p not in present]
    log.info("Missing pages (1-497): %d pages: %s", len(missing), missing)
    return missing


def extract_page_images(missing_pages: list[int]) -> dict[int, bytes]:
    """Extract missing pages from PDF as PNG images.

    Returns dict of {page_number: image_bytes}.
    """
    doc = fitz.open(PDF_PATH)
    images: dict[int, bytes] = {}
    for pg in missing_pages:
        page = doc[pg - 1]  # 0-indexed
        pix = page.get_pixmap(dpi=200)
        images[pg] = pix.tobytes("png")
    doc.close()
    log.info("Extracted %d page images from PDF", len(images))
    return images


def parse_ocr_text(text: str, page_num: int) -> dict | None:
    """Parse OCR text into question structure.

    Expected format:
        风中易小生·24考研计算机WD操作系统做题本【选择题】
        N.question_stem(  ).
        A.option_text
        B.option_text
        C.option_text
        D.option_text
        X.Y section_name  (optional)

    Returns dict with keys: stem, options, question_type, source_question_no
    or None if parsing fails.
    """
    if not text or not text.strip():
        return None

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    # Remove header line if present
    # Strip header lines
    while lines and re.search(r"风中易小生|做题本|微信|公众号", lines[0]):
        lines.pop(0)

    if not lines:
        return None

    # Find question line: starts with a number followed by "."
    question_line_idx = None
    qno = None
    stem = None

    for idx, line in enumerate(lines):
        m = re.match(r"^(\d+)[.、．]\s*(.*)", line)
        if m:
            qno = m.group(1)
            stem = m.group(2)
            question_line_idx = idx
            break

    if qno is None:
        log.debug("Page %d: no question number found. Lines: %s", page_num, lines)
        return None

    # Build full stem: collect all lines between question and first option
    stem_parts = [stem]  # Start with the first line after question number
    for idx in range(question_line_idx + 1, len(lines)):
        line = lines[idx]
        # Stop if we hit an option line (A.-D.) or section reference (X.Y)
        if re.match(r"^[A-Da-d][.、．]\s", line):
            break
        if re.match(r"^\d+\.\d+\s", line):
            break
        if re.match(r"^\d+[.、．]\s", line):
            break
        stem_parts.append(line)
    stem = "".join(stem_parts).strip()
    # Clean up any stray parentheses or spaces from line breaks
    stem = re.sub(r"\s+", " ", stem)

    # Extract options - scan ALL remaining lines after question
    options: dict[str, str] = {}
    opt_pattern = re.compile(r"^([A-Da-d])[.、．]\s*(.*)")

    for idx in range(question_line_idx + 1, len(lines)):
        line = lines[idx]
        # Skip continuation lines (already part of stem, or section refs)
        if re.match(r"^\d+\.\d+\s", line):
            continue
        m = opt_pattern.match(line)
        if m:
            key = m.group(1).upper()
            # Only set if shorter than existing (some OCR runs output the
            # same option key multiple times; take the longest text)
            existing = options.get(key, "")
            val = m.group(2).strip()
            if len(val) > len(existing):
                options[key] = val

    if not options:
        log.debug("Page %d: no options found for q%s", page_num, qno)
        # Some questions might not have standard A/B/C/D
        # Return what we have
        pass

    return {
        "stem": stem,
        "options": options,
        "question_type": "single_choice" if len(options) >= 2 else "subjective",
        "source_question_no": qno,
    }


def build_import_record(parsed: dict, page_num: int, raw_text: str) -> dict:
    """Build a question_imports row dict from parsed data."""
    import hashlib

    stem = parsed["stem"]
    options = parsed["options"]
    qtype = parsed["question_type"]
    qno = parsed["source_question_no"]

    # Normalize stem: add question number prefix
    normalized_stem = f"{qno}.{stem}" if not stem.startswith(qno + ".") else stem

    # Build JSON structures matching existing import format
    parsed_content = {"text": normalized_stem}
    parsed_options = {k: v for k, v in sorted(options.items())}

    # Build raw_data matching pipeline format
    raw_data = {
        "stem": normalized_stem,
        "code_blocks": [],
        "options": [{"key": k, "text": v} for k, v in sorted(options.items())],
        "answer": "",
        "analysis": "",
        "subject": "",
        "subject_id": SUBJECT_ID,
        "question_type": qtype,
        "raw_text": raw_text,
        "knowledge_points": [],
        "difficulty": 3,
        "source": {"file": "os_sc.pdf", "page": page_num, "type": "pdf"},
        "is_valid": False,
        "errors": ["missing_answer"] if qtype != "subjective" else [],
        "warnings": ["missing_answer_for_objective_question"] if qtype != "subjective" else [],
        "stem_hash": hashlib.md5(normalized_stem.encode()).hexdigest()[:8],
        "confidence_score": 0.7,
        "validation_status": "passed",
        "failure_reason": ["missing_answer_for_objective_question"] if qtype != "subjective" else [],
        "retry_recommended": False,
        "ocr_quality_flags": [],
        "risk_flags": ["reimported_missing_page"],
        "decision_trace": [
            {"stage": "reimport", "result": "pass", "reason": "direct_import_from_ocr"},
            {"stage": "validation", "result": "pass", "reason": "missing_answer"},
            {"stage": "review", "result": "pending", "reason": "written_to_review_queue"},
        ],
        "is_frozen": True,
        "options_classified": True,
        "options_classify_reason": "direct_parsed",
        "schema_version": "v1",
        "quality_status": "needs_manual_review",
        "quality_blockers": ["missing_answer_for_objective_question"] if qtype != "subjective" else [],
        "page_start": page_num,
        "page_end": page_num,
        "source_question_no": str(qno),
        "source_question_label": f"{qno}.",
        "ai_validation": {"is_valid": True, "issues": [], "severity": "none"},
    }

    # Compute a consistent question_hash
    qhash_input = f"{normalized_stem}|{json.dumps(parsed_options, sort_keys=True)}"
    question_hash = hashlib.md5(qhash_input.encode()).hexdigest()[:16]

    return {
        "batch_id": f"REIMPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "source_type": "pdf",
        "source_file": "os_sc.pdf",
        "question_type": qtype,
        "raw_data": raw_data,
        "parsed_content": parsed_content,
        "parsed_options": parsed_options,
        "parsed_answer": None,
        "parsed_analysis": None,
        "status": "pending",
        "review_note": None,
        "subject_id": SUBJECT_ID,
        "source_question_no": str(qno),
        "source_page_start": page_num,
        "source_page_end": page_num,
        "source_order_index": page_num,
        "raw_text_preview": raw_text[:200],
        "answer_status": "missing",
        "question_hash": question_hash,
    }


def insert_imports(records: list[dict]) -> int:
    """Insert question_imports records into the database.

    Returns number of inserted rows.
    """
    import sqlite3
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()

    # First check which pages already have data (dedup)
    existing_pages = set(r[0] for r in db.execute(
        "SELECT DISTINCT source_page_start FROM question_imports WHERE source_page_start IS NOT NULL"
    ).fetchall())

    inserted = 0
    skipped = 0
    for rec in records:
        page = rec["source_page_start"]
        if page in existing_pages:
            skipped += 1
            continue

        try:
            cursor.execute("""
                INSERT INTO question_imports (
                    batch_id, source_type, source_file, question_type,
                    raw_data, parsed_content, parsed_options,
                    parsed_answer, parsed_analysis,
                    status, review_note,
                    subject_id,
                    source_question_no, source_page_start, source_page_end,
                    source_order_index, raw_text_preview,
                    answer_status, question_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec["batch_id"],
                rec["source_type"],
                rec["source_file"],
                rec["question_type"],
                json.dumps(rec["raw_data"], ensure_ascii=False),
                json.dumps(rec["parsed_content"], ensure_ascii=False),
                json.dumps(rec["parsed_options"], ensure_ascii=False),
                rec["parsed_answer"],
                rec["parsed_analysis"],
                rec["status"],
                rec["review_note"],
                rec["subject_id"],
                rec["source_question_no"],
                rec["source_page_start"],
                rec["source_page_end"],
                rec["source_order_index"],
                rec["raw_text_preview"],
                rec["answer_status"],
                rec["question_hash"],
            ))
            existing_pages.add(page)
            inserted += 1
        except sqlite3.IntegrityError as e:
            log.warning("Page %d: integrity error: %s", page, e)
            skipped += 1

    db.commit()
    db.close()
    return inserted, skipped


async def main():
    log.info("=" * 60)
    log.info("OS Question Bank: Re-import missing pages")
    log.info("=" * 60)

    # Step 1: Identify missing pages
    missing_pages = get_missing_pages()
    if not missing_pages:
        log.info("No missing pages found. Nothing to do.")
        return

    # Step 2: Extract page images
    log.info("Extracting %d page images...", len(missing_pages))
    images = extract_page_images(missing_pages)

    # Step 3: Run OCR in batches
    from app.services import import_pipeline_service as svc

    ocr = svc.ocr_executor
    ocr_start = time.monotonic()

    all_parsed: list[dict] = []
    total_inserted = 0
    total_skipped = 0
    parse_failures: list[int] = []

    for batch_start in range(0, len(missing_pages), BATCH_SIZE):
        batch_pages = missing_pages[batch_start:batch_start + BATCH_SIZE]
        batch_images = [(p, images[p]) for p in batch_pages]

        log.info("OCR batch: pages %s ...", batch_pages[:3])
        ocr_results = await ocr.run_ocr_pages_with_boxes(batch_images)

        for page_num in batch_pages:
            raw_text = ""
            if page_num in ocr_results:
                result = ocr_results[page_num]
                if isinstance(result, dict):
                    raw_text = result.get("text", "")
                elif isinstance(result, str):
                    raw_text = result
            else:
                log.warning("Page %d: no OCR result", page_num)

            parsed = parse_ocr_text(raw_text, page_num)
            if parsed:
                record = build_import_record(parsed, page_num, raw_text)
                all_parsed.append(record)
                log.debug("Page %d: q%s parsed OK (%d options)",
                          page_num, parsed["source_question_no"], len(parsed["options"]))
            else:
                parse_failures.append(page_num)
                log.warning("Page %d: failed to parse OCR text: %.80s",
                            page_num, raw_text[:80])

        # Insert this batch
        if all_parsed:
            inserted, skipped = insert_imports(all_parsed)
            total_inserted += inserted
            total_skipped += skipped
            log.info("Batch inserted: %d new, %d skipped (total: %d)",
                     inserted, skipped, total_inserted)
            all_parsed = []  # Clear for next batch

    # Final summary
    ocr_elapsed = time.monotonic() - ocr_start
    log.info("=" * 60)
    log.info("RE-IMPORT COMPLETE")
    log.info("Total pages processed: %d", len(missing_pages))
    log.info("Total inserted: %d", total_inserted)
    log.info("Skipped (already existed): %d", total_skipped)
    log.info("Parse failures: %d pages: %s", len(parse_failures), parse_failures)
    log.info("OCR+processing time: %.1fs", ocr_elapsed)

    # Verify final count
    import sqlite3
    db = sqlite3.connect(DB_PATH)
    final_count = db.execute("SELECT COUNT(*) FROM question_imports").fetchone()[0]
    log.info("Final question_imports count: %d", final_count)
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
