#!/usr/bin/env python3
"""Reconstruct missing questions for a page range using the project's own
OCR->normalize->split->submit_to_review chain (the pipeline's splitter works
correctly on clean blocks; the full orchestrator drops some for this book).

Usage:
    .venv/bin/python /abs/reconstruct_pages.py --start 111 --end 127
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import urllib.request

sys.path.insert(0, "/home/lmh/projects/postgraduate-ai/backend")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

PDF = "/home/lmh/projects/postgraduate-ai/ocr_test/import/cs_ds.pdf"


def ocr_page(png_bytes):
    body = json.dumps({"file": base64.b64encode(png_bytes).decode(), "fileType": 1}).encode()
    req = urllib.request.Request("http://172.27.64.1:8080/ocr", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    pr = data["result"]["ocrResults"][0]["prunedResult"]
    lines = sorted([(int(b[0][1]), int(b[0][0]), t)
                    for t, b in zip(pr["rec_texts"], pr["rec_polys"])], key=lambda x: (x[0], x[1]))
    return "\n".join(t for _, _, t in lines)


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    args = p.parse_args()

    import fitz
    from app.core.database import async_session
    from app.features.question_splitter import split_questions
    from app.features.review_service import submit_to_review
    from app.features.text_normalizer import normalize_ocr_text

    doc = fitz.open(PDF)
    blocks = []
    for pi in range(args.start - 1, args.end):
        pix = doc[pi].get_pixmap(dpi=200)
        full = ocr_page(pix.tobytes("png"))
        blocks.append({"page": pi + 1, "block_index": 0,
                       "normalized_text": normalize_ocr_text(full), "text": full})
    doc.close()

    qs = split_questions(blocks, structure=None, import_mode="auto", split_mode="standard")
    print(f"split produced {len(qs)} questions for pages {args.start}-{args.end}")

    # build submit payloads
    payloads = []
    for q in qs:
        opts = q.get("option_lines") or {}
        opt_list = [{"key": k, "text": v} for k, v in opts.items()]
        payloads.append({
            "stem": (q.get("raw_question_text") or "").strip(),
            "options": opt_list,
            "question_type": "single_choice",
            "page_start": q.get("page_start"),
            "page_end": q.get("page_end"),
            "source_question_no": str(q.get("number")) if q.get("number") else None,
            "raw_question_text": q.get("raw_question_text"),
            "confidence_score": q.get("confidence", 0.8),
            "is_valid": True,
        })

    # drop any payloads that already exist (page already has a question)
    import sqlite3
    conn = sqlite3.connect("/home/lmh/projects/postgraduate-ai/backend/postgraduate.db")
    existing = set()
    for pg in range(args.start, args.end + 1):
        rows = conn.execute("SELECT source_page_start FROM question_imports WHERE source_file='cs_ds.pdf' AND source_page_start=?", (pg,)).fetchall()
        if rows:
            existing.add(pg)
    conn.close()
    payloads = [pl for pl in payloads if pl["page_start"] not in existing]
    print(f"after excluding existing pages: {len(payloads)} to create")

    async with async_session() as db:
        for pl in payloads:
            result = await submit_to_review(
                db, [pl],
                {"source_type": "pdf", "source_file": "cs_ds.pdf", "subject_id": 8},
                skip_existing=True,
            )
            item = (result.get("items") or [{}])[0]
            print(f"  created page={pl['page_start']} id={item.get('id')} stem={pl['stem'][:30]!r} "
                  f"options={len(pl['options'])}")
        await db.commit()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
