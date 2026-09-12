#!/usr/bin/env python3
"""Batch import runner for OS question bank — processes pages in chunks, audits after each."""
import asyncio, json, logging, os, shutil, sys, tempfile, time

_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_script_dir, "..", "..", "backend"))
os.environ["APP_ENV"] = "development"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("batch-import")
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

ARTIFACTS = _script_dir
PDF_PATH = "/home/lmh/projects/postgraduate-ai/ocr_test/import/os_sc.pdf"
BATCH_SIZE = 25
MAX_RETRIES = 2
TOTAL_PAGES = 500

async def run_batch(page_start: int, page_end: int, attempt: int = 1) -> dict:
    """Run a single batch import and return pipeline results."""
    from app.services.import_pipeline_service import start_import_pipeline
    from app.features.pipeline_orchestrator import get_pipeline_status

    # Copy PDF to temp
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    shutil.copy2(PDF_PATH, tmp.name)
    tmp_path = tmp.name
    tmp.close()

    log.info("=== Batch pages %d-%d (attempt %d) ===", page_start, page_end, attempt)
    result = await start_import_pipeline(
        file_path=tmp_path,
        filename="os_sc.pdf",
        content_type="application/pdf",
        subject_id=9,
        import_mode="auto",
        enable_ai_repair=True,
        confidence_threshold=0.6,
        page_start=page_start,
        page_end=page_end,
        created_by="admin:1",
    )
    pipeline_id = result.pipeline_id
    log.info("Pipeline: %s (pages %d-%d)", pipeline_id, page_start, page_end)

    # Monitor
    max_wait = 600
    poll = 10
    waited = 0
    while waited < max_wait:
        await asyncio.sleep(poll)
        waited += poll
        try:
            status = await get_pipeline_status(pipeline_id)
        except Exception:
            continue
        s = status.get("status", "unknown")
        stage = status.get("current_stage", "")
        errs = len(status.get("errors", []))
        log.info("  [%s] %s stage=%s errors=%d", pipeline_id[:12], s, stage, errs)
        if s in ("completed", "failed", "paused"):
            break

    if waited >= max_wait:
        log.warning("TIMEOUT: pipeline %s", pipeline_id)

    final = await get_pipeline_status(pipeline_id)
    final["page_start"] = page_start
    final["page_end"] = page_end
    return final

async def main():
    # Find the next unprocessed page range
    import sqlite3
    db_path = os.path.join(_script_dir, "..", "..", "backend", "postgraduate.db")

    db = sqlite3.connect(db_path)
    cur = db.execute("SELECT COALESCE(MAX(source_page_end), 10) FROM question_imports WHERE source_page_end >= 1")
    last_page = cur.fetchone()[0] or 10
    db.close()

    start_page = max(last_page + 1, 11)
    if start_page > TOTAL_PAGES:
        log.info("All pages already imported. Last page = %d", last_page)
        return

    log.info("Starting from page %d (last imported: page %d)", start_page, last_page)

    # Start the pipeline worker
    from app.services.task_queue_worker import run_pipeline_worker, stop_worker

    worker = asyncio.create_task(run_pipeline_worker(poll_interval=2.0))

    results = []
    for ps in range(start_page, TOTAL_PAGES + 1, BATCH_SIZE):
        pe = min(ps + BATCH_SIZE - 1, TOTAL_PAGES)
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                final = await run_batch(ps, pe, attempt)
                results.append(final)
                if final.get("status") == "completed":
                    qc = 0
                    try:
                        db2 = sqlite3.connect(db_path)
                        cur = db2.execute(
                            "SELECT COUNT(*) FROM question_imports WHERE source_page_start >= ? AND source_page_start <= ?",
                            (ps, pe))
                        qc = cur.fetchone()[0]
                        db2.close()
                    except Exception:
                        pass
                    log.info("Batch %d-%d COMPLETED: %d questions imported", ps, pe, qc)
                    break
                elif attempt <= MAX_RETRIES:
                    log.warning("Batch %d-%d failed (attempt %d), retrying...", ps, pe, attempt)
                    await asyncio.sleep(5)
                else:
                    log.error("Batch %d-%d FAILED after %d attempts", ps, pe, attempt)
            except Exception as e:
                log.error("Batch %d-%d exception: %s", ps, pe, e)
                if attempt <= MAX_RETRIES:
                    await asyncio.sleep(5)
                else:
                    log.error("Giving up on batch %d-%d", ps, pe)

    # Save results
    with open(os.path.join(ARTIFACTS, "logs", "full_import_results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Summary
    db3 = sqlite3.connect(db_path)
    qi = db3.execute("SELECT COUNT(*) FROM question_imports").fetchone()[0]
    qs = db3.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    pl = db3.execute("SELECT COUNT(*) FROM import_pipelines").fetchone()[0]
    log.info("=== IMPORT SUMMARY ===")
    log.info("Question imports: %d | Questions: %d | Pipelines: %d", qi, qs, pl)
    db3.close()

    # Stop worker
    await stop_worker()
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    asyncio.run(main())
