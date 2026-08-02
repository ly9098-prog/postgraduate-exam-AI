#!/usr/bin/env python3
"""Drive the existing import pipeline for a page range of cs_ds.pdf.

Calls the orchestrator's ``run_pipeline_background`` directly (the exact
function the worker dispatcher invokes after dequeue). This runs the REAL
pipeline (extract → OCR → split → normalize → validate → dedup → review →
question_imports) with its checkpoint/chunk machinery, but avoids the
Redis-queue/fencing wrapper — which is only needed for multi-worker
concurrency safety and requires pre-created import_pipelines rows that the
enqueue path doesn't create.

Usage (run from backend/ with the venv):
    .venv/bin/python /abs/path/run_pipeline_batch.py --start 1 --end 10
"""
import argparse
import asyncio
import os
import sys
import time
import uuid
from datetime import datetime

sys.path.insert(0, "/home/lmh/projects/postgraduate-ai/backend")
# Local dev: backend/.env has no REDIS_URL, but a local Redis runs on 6379.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
# pdf_renderer_service caps input at PDF_MAX_FILE_BYTES (5MB cloud default);
# the local 54MB scanned PDF needs the 200MB dev limit.
os.environ.setdefault("PDF_MAX_FILE_BYTES", str(200 * 1024 * 1024))
# cs_ds.pdf has one self-contained question per page — cross-page merging is
# wrong and falsely merges whole chapters (see batch 111-135). Disable it.
os.environ.setdefault("DISABLE_CROSS_PAGE_MERGING", "1")

PDF_PATH = "/home/lmh/projects/postgraduate-ai/ocr_test/import/cs_ds.pdf"
FILENAME = "cs_ds.pdf"
SUBJECT_ID = 8  # 计算机组成原理


async def _init_runtime() -> None:
    """Replicate the dev ``all``-role startup: executors + OCR gateway."""
    import threading

    from app.core.executor_registry import init_executor_registry
    from app.core.executors import init_executors_for_role
    from app.core.ocr_runtime_config import get_runtime_config

    executors = init_executors_for_role("all", is_production=False)
    init_executor_registry(executors)

    # WSL /tmp reports total-free as ~84GB "used" on the virtual fs even though
    # ~992GB is free — the default 512MB temp-disk guard trips falsely. Relax the
    # threshold in-process only (no file/config change) so the pipeline can run.
    from app.core.resource_guard import resource_guard
    resource_guard._thresholds.max_temp_disk_mb = 200_000

    # The pipeline runs stage functions via asyncio.to_thread, so the legacy
    # sync OCR bridge (ocr_service._run_async) calls asyncio.run() — a fresh
    # event loop per call. Shared httpx/Redis clients break across loops.
    # Route all OCR through one dedicated persistent loop instead.
    import app.services.ocr_service as ocr_svc_mod
    _ocr_loop = asyncio.new_event_loop()
    def _loop_runner():
        asyncio.set_event_loop(_ocr_loop)
        _ocr_loop.run_forever()
    threading.Thread(target=_loop_runner, daemon=True).start()

    def _run_async_persistent(coro):
        fut = asyncio.run_coroutine_threadsafe(coro, _ocr_loop)
        return fut.result(timeout=600)
    ocr_svc_mod._run_async = _run_async_persistent
    print("[driver] OCR routed through persistent event loop", flush=True)

    cfg = get_runtime_config()
    if cfg.enabled:
        import httpx

        from app.core.deployment_profile import detect_deployment_profile
        from app.features.ocr_gateway import OCRGateway
        from app.services.ocr_service import set_gateway
        from app.services.ocr_worker_client import create_ocr_worker_client

        _http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=cfg.remote_connect_timeout_sec,
                read=cfg.remote_read_timeout_sec,
                write=cfg.remote_connect_timeout_sec,
                pool=cfg.remote_connect_timeout_sec,
            ),
            limits=httpx.Limits(
                max_keepalive_connections=cfg.remote_max_concurrency,
                max_connections=cfg.remote_max_concurrency,
            ),
        )
        worker_client = create_ocr_worker_client(cfg, http_client=_http)
        gateway = OCRGateway(
            mode="gateway",
            profile=detect_deployment_profile(),
            worker_client=worker_client,
        )
        set_gateway(gateway)
        print(f"[driver] OCR gateway initialized backend={cfg.execution_backend} "
              f"url={cfg.remote_url}", flush=True)
    else:
        print("[driver] OCR disabled per runtime config", flush=True)


def _query_pipeline(pipeline_id: str) -> dict | None:
    import sqlite3

    db = sqlite3.connect("/home/lmh/projects/postgraduate-ai/backend/postgraduate.db")
    db.row_factory = sqlite3.Row
    try:
        row = db.execute(
            "SELECT * FROM import_pipelines WHERE pipeline_id=?", (pipeline_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def _query_chunks(pipeline_id: str) -> list[dict]:
    import sqlite3

    db = sqlite3.connect("/home/lmh/projects/postgraduate-ai/backend/postgraduate.db")
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            "SELECT * FROM import_pipeline_chunks WHERE pipeline_id=? ORDER BY chunk_index",
            (pipeline_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--ai-repair", dest="ai_repair", action="store_true",
                        help="enable_ai_repair=True (default: False)")
    parser.add_argument("--created-by", default="local-auto-import")
    args = parser.parse_args()

    from app.core.logging_config import setup_logging
    setup_logging()

    await _init_runtime()

    from app.core.database import async_session
    from app.features.pipeline_orchestrator import run_pipeline_background

    pipeline_id = (
        f"pl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )
    options = {
        "enable_ai_repair": args.ai_repair,
        "confidence_threshold": 0.6,
        "import_mode": "auto",
        "page_start": args.start,
        "page_end": args.end,
    }
    print(f"[driver] running pipeline {pipeline_id} pages {args.start}-{args.end} "
          f"ai_repair={args.ai_repair}", flush=True)

    t0 = time.time()
    async with async_session() as db:
        await run_pipeline_background(
            pipeline_id=pipeline_id,
            source_type="pdf",
            source_file=FILENAME,
            file_path=PDF_PATH,
            subject_id=SUBJECT_ID,
            options=options,
            db=db,
            created_by=args.created_by,
        )
    elapsed = time.time() - t0
    print(f"[driver] pipeline returned after {elapsed:.1f}s", flush=True)

    row = _query_pipeline(pipeline_id)
    chunks = _query_chunks(pipeline_id)
    print("[driver] === pipeline row ===")
    if row:
        for k in ("pipeline_id", "status", "total_pages", "chunk_size",
                  "error_message", "started_at", "finished_at"):
            print(f"  {k}: {row.get(k)}")
        if row.get("quality_report"):
            print("  quality_report:", str(row["quality_report"])[:600])
    print("[driver] === chunks ===")
    for c in chunks:
        print(f"  chunk {c['chunk_index']} pages {c['page_start']}-{c['page_end']} "
              f"status={c['status']} batch={c.get('batch_id')} qcount={c.get('question_count')} "
              f"err={(c.get('error_message') or '')[:120]}")
    print(f"[driver] DONE pipeline={pipeline_id} status={(row or {}).get('status')} "
          f"chunks={len(chunks)}")


if __name__ == "__main__":
    asyncio.run(main())
