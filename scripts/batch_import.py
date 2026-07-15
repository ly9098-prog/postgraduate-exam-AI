"""Full batch import: pages 11-513, 25 pages per batch.

Each batch copies the safe PDF to a temp file (pipeline deletes it after).
"""
import asyncio
import json
import os
import shutil
import sys
import time
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import async_session
from app.services.import_pipeline_service import start_import_pipeline, get_pipeline_status
from app.services.task_queue_worker import run_pipeline_worker
from app.models.question_import import QuestionImport
from sqlalchemy import select

SAFE_PDF = "/home/lmh/projects/postgraduate-ai/artifacts/data-structure-import/source/ds_sc.pdf"
ARTIFACTS = "/home/lmh/projects/postgraduate-ai/artifacts/data-structure-import"
SUBJECT_ID = 7
BATCH_SIZE = 25
TOTAL_PAGES = 513
LOG_DIR = os.path.join(ARTIFACTS, "logs")

async def wait_for_pipeline(pipeline_id, timeout=900):
    start_ts = time.time()
    last_status = None
    while time.time() - start_ts < timeout:
        async with async_session() as db:
            status_resp = await get_pipeline_status(pipeline_id, db)
        status = status_resp.status
        if status != last_status:
            print("    Status: %s (%.0fs)" % (status, time.time() - start_ts))
            last_status = status
        terminal = {"completed", "failed", "cancelled"}
        if status in terminal:
            return status
        await asyncio.sleep(5)
    return "timeout"

async def run_batch(page_start, page_end, batch_num, total_batches):
    """Run one batch with a temp copy of the PDF."""
    print("\n[Batch %d/%d] Pages %d-%d" % (batch_num, total_batches, page_start, page_end))

    # Copy safe PDF to temp (pipeline will delete this copy)
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_path = tmp.name
    tmp.close()
    shutil.copy2(SAFE_PDF, tmp_path)

    # Start pipeline with temp copy
    result = await start_import_pipeline(
        file_path=tmp_path,
        filename="ds_sc.pdf",
        content_type="application/pdf",
        subject_id=SUBJECT_ID,
        import_mode="auto",
        enable_ai_repair=True,
        confidence_threshold=0.6,
        page_start=page_start,
        page_end=page_end,
        created_by="script:batch-import-%d" % batch_num,
    )

    pipeline_id = result.pipeline_id
    print("    Pipeline: %s" % pipeline_id)

    # Wait for completion
    final_status = await wait_for_pipeline(pipeline_id)
    print("    Final status: %s" % final_status)

    # Count questions
    async with async_session() as db:
        cnt = await db.execute(
            select(QuestionImport).where(
                QuestionImport.batch_id == result.model_dump().get("page_range", {}).get("batch_id", "")
            )
        )
        q_count = len(cnt.scalars().all())

    return {
        "batch_num": batch_num,
        "page_start": page_start,
        "page_end": page_end,
        "pipeline_id": pipeline_id,
        "status": final_status,
        "question_count": q_count,
    }

async def main():
    # Generate batches
    batches = []
    for start in range(11, TOTAL_PAGES + 1, BATCH_SIZE):
        end = min(start + BATCH_SIZE - 1, TOTAL_PAGES)
        batches.append((start, end))

    total = len(batches)
    print("Total batches: %d (pages 11-%d, %d per batch)" % (total, TOTAL_PAGES, BATCH_SIZE))

    # Start worker
    worker_task = asyncio.create_task(
        run_pipeline_worker(poll_interval=3.0),
        name="pipeline-worker",
    )

    results = []
    for i, (page_start, page_end) in enumerate(batches):
        r = await run_batch(page_start, page_end, i + 1, total)
        results.append(r)

        # Save per-batch result
        with open(os.path.join(LOG_DIR, "batch_%02d_result.json" % (i + 1)), "w") as f:
            json.dump(r, f, indent=2, ensure_ascii=False)

        if r["status"] != "completed":
            print("\n*** Batch %d FAILED, stopping ***" % (i + 1))
            break

    worker_task.cancel()

    # Summary
    print("\n" + "=" * 60)
    print("BATCH IMPORT SUMMARY")
    print("=" * 60)

    total_questions = 0
    for r in results:
        print("Batch %d: pages %d-%d | %s | %d questions" % (
            r["batch_num"], r["page_start"], r["page_end"],
            r["status"], r["question_count"]))
        total_questions += r["question_count"]

    print("\nTotal questions imported: %d" % total_questions)

    # Save summary
    summary = {
        "total_batches": len(results),
        "total_questions": total_questions,
        "batches": results,
    }
    with open(os.path.join(LOG_DIR, "full_import_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return all(r["status"] == "completed" for r in results)

if __name__ == "__main__":
    success = asyncio.run(main())
    print("\nFull import: %s" % ("SUCCESS" if success else "FAILED"))
    sys.exit(0 if success else 1)
