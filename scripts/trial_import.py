"""Trial import: Data Structures PDF pages 1-10 via pipeline service.

Run from backend directory: python3 ../scripts/trial_import.py
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import async_session
from app.models.admin import Subject
from app.services.import_pipeline_service import start_import_pipeline, get_pipeline_status
from app.services.task_queue_worker import run_pipeline_worker
from app.models.question_import import QuestionImport
from sqlalchemy import select

PDF_PATH = "/home/lmh/projects/postgraduate-ai/ocr_test/import/ds_sc.pdf"
ARTIFACTS = "/home/lmh/projects/postgraduate-ai/artifacts/data-structure-import"

async def ensure_subject():
    async with async_session() as db:
        result = await db.execute(select(Subject).where(Subject.code == "ds"))
        subj = result.scalar_one_or_none()
        if subj:
            print(f"Found subject: id={subj.id}, name={subj.name}, code={subj.code}")
            return subj.id
        else:
            print("ERROR: No 'ds' subject found!")
            sys.exit(1)

async def main():
    subject_id = await ensure_subject()

    print(f"\n{'='*60}")
    print(f"Starting trial import: pages 1-10, subject_id={subject_id}")
    print(f"PDF: {PDF_PATH}")
    print(f"{'='*60}\n")

    # Start pipeline worker in background task
    worker_task = asyncio.create_task(
        run_pipeline_worker(poll_interval=3.0),
        name="pipeline-worker",
    )

    result = await start_import_pipeline(
        file_path=PDF_PATH,
        filename="ds_sc.pdf",
        content_type="application/pdf",
        subject_id=subject_id,
        import_mode="auto",
        enable_ai_repair=True,
        confidence_threshold=0.6,
        page_start=1,
        page_end=10,
        created_by="script:trial-import",
    )

    pipeline_id = result.pipeline_id
    print(f"\nPipeline created: id={pipeline_id}, status={result.status}")

    # Save results
    out = os.path.join(ARTIFACTS, "logs", "trial_pipeline_result.json")
    with open(out, "w") as f:
        f.write(result.model_dump_json(indent=2))

    if not pipeline_id:
        print("ERROR: No pipeline_id returned!")
        worker_task.cancel()
        sys.exit(1)

    # Monitor pipeline status
    max_wait = 600
    start_ts = time.time()
    last_status = None

    while time.time() - start_ts < max_wait:
        async with async_session() as db:
            status_resp = await get_pipeline_status(pipeline_id, db)

        status = status_resp.status
        progress = status_resp.model_dump()

        if status != last_status:
            print(f"  [{int(time.time()-start_ts)}s] Pipeline: {status}")
            if status_resp.errors:
                for e in status_resp.errors:
                    print(f"    ERROR: {e}")
            if status_resp.question_count:
                print(f"    Questions: {status_resp.question_count}")
            last_status = status

        terminal = {"completed", "failed", "cancelled"}
        if status in terminal:
            print(f"\nPipeline reached terminal state: {status}")

            out2 = os.path.join(ARTIFACTS, "logs", "trial_pipeline_final.json")
            with open(out2, "w") as f:
                json.dump(progress, f, indent=2, ensure_ascii=False)

            # Get batch_id from pipeline status
            batch_id = status_resp.batch_id
            print(f"\nImported questions (batch_id={batch_id}):")

            # Count imported questions
            if batch_id:
                async with async_session() as db:
                    result = await db.execute(
                        select(QuestionImport).where(
                            QuestionImport.batch_id == batch_id
                        )
                    )
                    items = result.scalars().all()
                    print(f"  Total: {len(items)}")
                    for item in items:
                        print(f"  ID={item.id} | page={item.source_page_start} | type={item.question_type} | status={item.status}")
            else:
                print("  No batch_id found in pipeline status")

            worker_task.cancel()
            return status == "completed"

        await asyncio.sleep(5)

    print("ERROR: Timed out waiting for pipeline completion")
    worker_task.cancel()
    return False

if __name__ == "__main__":
    success = asyncio.run(main())
    print(f"\nTrial import {'SUCCESS' if success else 'FAILED'}")
    sys.exit(0 if success else 1)
