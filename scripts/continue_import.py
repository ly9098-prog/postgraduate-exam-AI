"""Continue import: pages 311-513 of ds_sc.pdf, 50 pages per batch."""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time

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
BATCH_SIZE = 50
LOG_DIR = os.path.join(ARTIFACTS, "logs")

async def wait_for_pipeline(pipeline_id, timeout=1800):
    start_ts = time.time()
    last_status = None
    while time.time() - start_ts < timeout:
        async with async_session() as db:
            try:
                status_resp = await get_pipeline_status(pipeline_id, db)
                status = status_resp.status
            except ValueError:
                status = "unknown"
        if status != last_status:
            print(f"    Status: {status} ({time.time() - start_ts:.0f}s)")
            last_status = status
        terminal = {"completed", "failed", "cancelled"}
        if status in terminal:
            return status
        await asyncio.sleep(5)
    return "timeout"

async def main():
    # Count starting questions
    async with async_session() as db:
        start_count = len((await db.execute(select(QuestionImport))).scalars().all())
    print(f"Starting question_imports count: {start_count}")

    # Build batches: 311-513
    batches = []
    for start in range(311, 514, BATCH_SIZE):
        end = min(start + BATCH_SIZE - 1, 513)
        batches.append((start, end))
    print(f"Total batches: {len(batches)} (pages 311-513)")

    # Start worker
    worker_task = asyncio.create_task(
        run_pipeline_worker(poll_interval=3.0),
        name="pipeline-worker",
    )
    await asyncio.sleep(2)

    all_results = []
    for i, (page_start, page_end) in enumerate(batches):
        print(f"\n[Batch {i+1}/{len(batches)}] Pages {page_start}-{page_end}")

        # Copy PDF to temp
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_path = tmp.name
        tmp.close()
        shutil.copy2(SAFE_PDF, tmp_path)

        # Start pipeline
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
            created_by=f"script:continue-import-batch-{i+1}",
        )

        pipeline_id = result.pipeline_id
        print(f"    Pipeline: {pipeline_id}")

        # Wait for completion
        final_status = await wait_for_pipeline(pipeline_id)
        print(f"    Final status: {final_status}")

        # Count questions after
        async with async_session() as db:
            current_count = len((await db.execute(select(QuestionImport))).scalars().all())
        new_count = current_count - start_count - sum(r.get("new_q", 0) for r in all_results)
        print(f"    New questions in this batch: {new_count}")

        batch_result = {
            "batch_num": i + 1,
            "page_start": page_start,
            "page_end": page_end,
            "pipeline_id": pipeline_id,
            "status": final_status,
            "new_questions": new_count,
        }
        all_results.append(batch_result)

        # Save per-batch result
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, f"continue_batch_{i+1:02d}_result.json"), "w") as f:
            json.dump(batch_result, f, indent=2, ensure_ascii=False)

        if final_status != "completed":
            print(f"\n*** Batch {i+1} FAILED, stopping ***")
            break

    worker_task.cancel()

    # Summary
    async with async_session() as db:
        final_count = len((await db.execute(select(QuestionImport))).scalars().all())

    print("\n" + "=" * 60)
    print("CONTINUE IMPORT SUMMARY")
    print("=" * 60)
    for r in all_results:
        print(f"Batch {r['batch_num']}: pages {r['page_start']}-{r['page_end']} | {r['status']} | {r['new_questions']} new questions")
    print(f"\nBefore: {start_count} questions")
    print(f"After:  {final_count} questions")
    print(f"Added:  {final_count - start_count} questions")

    # Save summary
    summary = {
        "total_batches": len(all_results),
        "start_questions": start_count,
        "final_questions": final_count,
        "added_questions": final_count - start_count,
        "batches": all_results,
    }
    with open(os.path.join(LOG_DIR, "continue_import_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return all(r["status"] == "completed" for r in all_results)

if __name__ == "__main__":
    success = asyncio.run(main())
    print(f"\nContinue import: {'SUCCESS' if success else 'PARTIAL'}")
    sys.exit(0 if success else 1)
