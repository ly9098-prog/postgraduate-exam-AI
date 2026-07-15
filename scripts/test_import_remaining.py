"""Test import: pages 286-310 to verify pipeline produces new questions."""
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
SUBJECT_ID = 7

async def wait_for_pipeline(pipeline_id, timeout=1200):
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
    # Count existing questions first
    async with async_session() as db:
        before = (await db.execute(select(QuestionImport))).scalars().all()
        before_count = len(before)
        before_batch_ids = set(q.batch_id for q in before)
        print(f"Existing questions: {before_count}")
        print(f"Existing batch_ids: {len(before_batch_ids)}")

    # Copy PDF to temp
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_path = tmp.name
    tmp.close()
    shutil.copy2(SAFE_PDF, tmp_path)
    print(f"Temp PDF: {tmp_path}")

    # Start worker
    worker_task = asyncio.create_task(
        run_pipeline_worker(poll_interval=3.0),
        name="pipeline-worker",
    )
    await asyncio.sleep(2)  # Let worker start

    # Start pipeline for pages 286-310
    print("\nStarting pipeline for pages 286-310...")
    result = await start_import_pipeline(
        file_path=tmp_path,
        filename="ds_sc.pdf",
        content_type="application/pdf",
        subject_id=SUBJECT_ID,
        import_mode="auto",
        enable_ai_repair=True,
        confidence_threshold=0.6,
        page_start=286,
        page_end=310,
        created_by="script:test-continue-import",
    )

    pipeline_id = result.pipeline_id
    print(f"Pipeline: {pipeline_id}")

    # Wait
    final_status = await wait_for_pipeline(pipeline_id)
    print(f"Final status: {final_status}")

    # Count new questions
    async with async_session() as db:
        after = (await db.execute(select(QuestionImport))).scalars().all()
        after_count = len(after)
        new_batch_ids = set(q.batch_id for q in after) - before_batch_ids
        print(f"\nQuestions before: {before_count}, after: {after_count}")
        print(f"New questions: {after_count - before_count}")
        print(f"New batch_ids: {new_batch_ids}")

        # Show new questions
        for q in after:
            if q.batch_id not in before_batch_ids:
                c = q.parsed_content
                text = c.get('text', '')[:80] if isinstance(c, dict) else str(c)[:80]
                print(f"  New ID={q.id}: batch={q.batch_id}, type={q.question_type}, text={text!r}")

    worker_task.cancel()

    # Cleanup temp
    try:
        os.unlink(tmp_path)
    except OSError:
        pass

    success = final_status == "completed"
    print(f"\nTest import: {'SUCCESS' if success else 'FAILED'}")
    return success

if __name__ == "__main__":
    asyncio.run(main())
