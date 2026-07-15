"""Direct import: OCR all 513 pages and create question_imports via submit_to_review.

Each page has exactly one question. Pipeline's complex multi-stage processing
loses too many questions (~70% drop rate). This script skips the unnecessary
stages (structure_analysis, freeze, classify, repair, etc.) and directly
creates QuestionImport records using the ORM's submit_to_review service.
"""
import asyncio
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import async_session
from app.features.review_service import submit_to_review
from app.services.ocr_service import ocr_pages_with_boxes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("direct-import")

SAFE_PDF = "/home/lmh/projects/postgraduate-ai/artifacts/data-structure-import/source/ds_sc.pdf"
SUBJECT_ID = 7
BATCH_SIZE = 50  # submit_to_review batch size

QUESTION_RE = re.compile(r'(?:第\s*)?(\d+)\s*[.．、)）]\s*(.*)')
OPTION_RE = re.compile(r'^\s*([A-Da-d])\s*[.．、:：)）\s]\s*(.*)')
WATERMARK_RE = re.compile(r'风中易小生|做题本|微信公众号|选择题】')

def parse_question_text(text: str) -> dict | None:
    """Parse OCR text from a single page into question dict.

    Expected format:
        风中易小生...【选择题】
        N. Question text...
        A. Option A
        B. Option B
        C. Option C
        D. Option D
    """
    if not text or not text.strip():
        return None

    lines = text.strip().split('\n')

    # Find the first line with a question number
    stem_lines = []
    options = []
    in_stem = False
    question_num = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Skip watermark lines
        if WATERMARK_RE.search(stripped) and not OPTION_RE.match(stripped):
            continue

        # Check if this is an option line
        opt_match = OPTION_RE.match(stripped)
        if opt_match:
            key = opt_match.group(1).upper()
            val = opt_match.group(2).strip()
            options.append({"key": key, "text": val})
            in_stem = False
            continue

        # Check if this is a question number line
        q_match = QUESTION_RE.match(stripped)
        if q_match and not in_stem:
            qnum = int(q_match.group(1))
            qtext = q_match.group(2).strip()
            if 1 <= qnum <= 500:  # reasonable question number
                question_num = qnum
                stem_lines.append(qtext)
                in_stem = True
                continue

        if in_stem:
            stem_lines.append(stripped)

    if not stem_lines:
        # Fallback: use all non-watermark text
        stem_lines = [l for l in lines if not WATERMARK_RE.search(l)]

    stem = ' '.join(s for s in stem_lines if s).strip()
    if not stem:
        return None

    # Clean up the stem
    stem = re.sub(r'\s+', ' ', stem)

    qtype = "single_choice" if len(options) >= 2 else "unknown"

    return {
        "stem": stem,
        "options": options,
        "question_type": qtype,
        "source": {"source_page_start": None},
        "answer": None,
        "answer_source": "unknown",
    }

async def main():
    import fitz

    # Render all pages
    logger.info("Opening PDF...")
    doc = fitz.open(SAFE_PDF)
    total_pages = len(doc)
    logger.info(f"PDF has {total_pages} pages")

    # Process in batches to avoid OOM
    all_questions = []
    ocr_batch_size = 50  # pages per OCR batch

    for batch_start in range(1, total_pages + 1, ocr_batch_size):
        batch_end = min(batch_start + ocr_batch_size - 1, total_pages)
        logger.info(f"Rendering pages {batch_start}-{batch_end}...")

        images = []
        for p in range(batch_start, batch_end + 1):
            pix = doc[p-1].get_pixmap(dpi=150)
            png = pix.tobytes('png')
            images.append((p, png))
            del pix

        logger.info(f"  OCR {len(images)} pages...")
        results = ocr_pages_with_boxes(images, skip_rotation=True)

        for page_idx in sorted(results.keys()):
            r = results[page_idx]
            if r.text and r.text.strip():
                q = parse_question_text(r.text)
                if q:
                    q["source"]["source_page_start"] = page_idx
                    all_questions.append(q)
                else:
                    logger.warning(f"  Page {page_idx}: could not parse question from text ({len(r.text)} chars)")
            else:
                logger.warning(f"  Page {page_idx}: empty OCR result")

        logger.info(f"  Parsed {len(all_questions)} questions so far")

    doc.close()
    logger.info(f"\nTotal questions parsed: {len(all_questions)} from {total_pages} pages")

    # Submit to review in batches
    logger.info("\nSubmitting to review queue...")
    total_written = 0
    total_skipped = 0

    for i in range(0, len(all_questions), BATCH_SIZE):
        batch = all_questions[i:i + BATCH_SIZE]
        logger.info(f"  Submitting batch {i//BATCH_SIZE + 1}/{(len(all_questions)-1)//BATCH_SIZE + 1} ({len(batch)} questions)...")

        async with async_session() as db:
            result = await submit_to_review(
                db,
                batch,
                {
                    "source_type": "pdf",
                    "source_file": "ds_sc.pdf",
                    "subject_id": SUBJECT_ID,
                },
                skip_existing=True,
            )
            await db.commit()

            total_written += result["written"]
            total_skipped += result["skipped"]

            logger.info(f"    Written: {result['written']}, Skipped: {result['skipped']}, Batch: {result['batch_id']}")

    logger.info(f"\n=== SUMMARY ===")
    logger.info(f"Total pages: {total_pages}")
    logger.info(f"Questions parsed: {len(all_questions)}")
    logger.info(f"Written to question_imports: {total_written}")
    logger.info(f"Skipped (duplicates): {total_skipped}")

    # Final count
    import sqlite3
    sdb = sqlite3.connect('postgraduate.db')
    qi_count = sdb.execute('SELECT COUNT(*) FROM question_imports').fetchone()[0]
    q_count = sdb.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
    sdb.close()
    logger.info(f"Final question_imports count: {qi_count}")
    logger.info(f"Questions table count: {q_count}")

    return total_written > 0

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
