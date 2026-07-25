#!/usr/bin/env python3
"""Direct pipeline runner — bypasses HTTP layer, processes tasks in-process."""
import asyncio, json, logging, os, sys, time

_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_script_dir, "..", "..", "backend"))
os.environ["APP_ENV"] = "development"

import shutil
import tempfile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("direct-runner")
# Suppress noisy loggers
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

ARTIFACTS = _script_dir
PDF_PATH = "/home/lmh/projects/postgraduate-ai/ocr_test/import/os_sc.pdf"


async def main():
    # ── 1. Import all needed modules ──
    from app.core.config import settings
    from app.services.import_pipeline_service import start_import_pipeline
    from app.services.task_queue_worker import run_pipeline_worker, stop_worker
    from app.features.pipeline_orchestrator import get_pipeline_status, _pipeline_store

    logger.info("Environment: APP_ENV=%s OCR=%s DB=%s",
                settings.APP_ENV, settings.OCR_ENABLED, settings.DATABASE_URL)

    # ── 2. Copy PDF to temp location (pipeline worker deletes source!) ──
    logger.info("Copying PDF to temp location for pipeline safety...")
    tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    shutil.copy2(PDF_PATH, tmp_pdf.name)
    tmp_path = tmp_pdf.name
    tmp_pdf.close()

    logger.info("Starting trial import: pages 1-10, subject_id=9 (操作系统)...")
    result = await start_import_pipeline(
        file_path=tmp_path,
        filename="os_sc.pdf",
        content_type="application/pdf",
        subject_id=9,
        import_mode="auto",
        enable_ai_repair=True,
        confidence_threshold=0.6,
        page_start=1,
        page_end=10,
        created_by="admin:1",
    )

    pipeline_id = result.pipeline_id
    logger.info("Pipeline created: id=%s status=%s", pipeline_id, result.status)
    if result.page_range:
        logger.info("Page range: requested=(%s, %s) effective=(%s, %s) total=%s",
                    result.page_range.requested_start, result.page_range.requested_end,
                    result.page_range.effective_start, result.page_range.effective_end,
                    result.page_range.total_pages)

    # Save pipeline metadata
    os.makedirs(os.path.join(ARTIFACTS, "logs"), exist_ok=True)
    with open(os.path.join(ARTIFACTS, "logs", "trial_pipeline.json"), "w") as f:
        json.dump({
            "pipeline_id": pipeline_id,
            "status": result.status,
            "source_type": result.source_type,
            "page_range": {
                "requested_start": result.page_range.requested_start if result.page_range else None,
                "requested_end": result.page_range.requested_end if result.page_range else None,
                "start": result.page_range.effective_start if result.page_range else None,
                "end": result.page_range.effective_end if result.page_range else None,
            } if result.page_range else None,
        }, f, indent=2)

    # ── 3. Start the pipeline worker ──
    logger.info("Starting pipeline worker...")
    worker_task = asyncio.create_task(run_pipeline_worker(poll_interval=2.0))

    # ── 4. Monitor progress ──
    max_wait = 900  # 15 minutes
    poll_interval = 10
    waited = 0

    while waited < max_wait:
        await asyncio.sleep(poll_interval)
        waited += poll_interval

        try:
            status_data = await get_pipeline_status(pipeline_id)
        except Exception as exc:
            logger.warning("Status query failed: %s", exc)
            continue

        s = status_data.get("status", "unknown")
        stage = status_data.get("current_stage", "")
        err_count = len(status_data.get("errors", []))
        batch_id = status_data.get("batch_id", "")

        # Try to get chunk progress
        chunk_progress = status_data.get("chunk_progress") or {}
        chunks_done = chunk_progress.get("completed", 0)
        chunks_total = chunk_progress.get("total", 0)

        qc = status_data.get("stats", {}).get("question_count", 0)

        logger.info("Status: %s | stage: %s | chunks: %d/%d | questions: %d | errors: %d | batch: %s",
                     s, stage, chunks_done, chunks_total, qc, err_count,
                     batch_id[:16] if batch_id else "-")

        if s in ("completed", "failed", "paused", "interrupted"):
            logger.info("Pipeline reached terminal state: %s", s)
            if status_data.get("errors"):
                for e in status_data["errors"][:5]:
                    logger.error("  Error: %s", e)
            break

    if waited >= max_wait:
        logger.warning("TIMEOUT: pipeline did not complete within %ds", max_wait)

    # ── 5. Final status ──
    final = await get_pipeline_status(pipeline_id)
    final["_pipeline_store_keys"] = list(_pipeline_store.keys()) if hasattr(_pipeline_store, 'keys') else []
    with open(os.path.join(ARTIFACTS, "logs", "trial_result.json"), "w") as f:
        json.dump(final, f, indent=2, default=str)

    logger.info("=== FINAL PIPELINE STATUS ===")
    logger.info(json.dumps(final, indent=2, default=str)[:3000])

    # ── 6. Check database results ──
    try:
        import sqlite3
        db_path = os.path.join(_script_dir, "..", "..", "backend", "postgraduate.db")
        db = sqlite3.connect(db_path)
        cur = db.execute("SELECT pipeline_id, status, total_pages, chunk_size FROM import_pipelines")
        for row in cur.fetchall():
            logger.info("DB Pipeline: id=%s status=%s pages=%s chunk_size=%s", *row)
        cur = db.execute("SELECT COUNT(*) FROM import_pipeline_chunks")
        logger.info("DB Chunks: %d", cur.fetchone()[0])
        cur = db.execute("SELECT status, COUNT(*) FROM import_pipeline_chunks GROUP BY status")
        for row in cur.fetchall():
            logger.info("  Chunk status %s: %d", row[0], row[1])
        cur = db.execute("SELECT COUNT(*) FROM question_imports")
        logger.info("DB Question Imports: %d", cur.fetchone()[0])
        cur = db.execute("SELECT COUNT(*) FROM questions")
        logger.info("DB Questions: %d", cur.fetchone()[0])
        db.close()
    except Exception as exc:
        logger.warning("DB check failed: %s", exc)

    # ── 7. Stop worker ──
    await stop_worker()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    logger.info("Worker stopped. Done.")


if __name__ == "__main__":
    asyncio.run(main())
