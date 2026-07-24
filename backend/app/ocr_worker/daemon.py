"""OCR Worker daemon — main entry point for the local GPU OCR worker.

Runs as a long-lived process that:
1. Polls production server for OCR jobs
2. Downloads input, runs PaddleOCR via isolated subprocess
3. Uploads results
4. Sends heartbeats
5. Handles graceful shutdown

Usage:
    PYTHONPATH=. python -m app.ocr_worker.daemon \\
      --server https://production.example.com \\
      --worker-id local-ocr-01
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.ocr_worker.client import WorkerAPIClient, WorkerClientError
from app.ocr_worker.config import OCRWorkerConfig
from app.ocr_worker.executor import ExecutorError, OcrExecutorProcess
from app.ocr_worker.workspace import JobWorkspace

logger = logging.getLogger("postgraduate-ai.ocr-worker.daemon")

_SHUTTING_DOWN = False


def _signal_handler(signum: int, frame) -> None:
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        logger.warning("Forced exit")
        sys.exit(1)
    _SHUTTING_DOWN = True
    logger.info("Shutdown requested (signal %d)", signum)


class OcrWorkerDaemon:
    """Main OCR worker daemon — polls, executes, and reports."""

    def __init__(self, config: OCRWorkerConfig) -> None:
        self._config = config
        self._client = WorkerAPIClient(config)
        self._executor = OcrExecutorProcess(
            gpu_memory_limit_mb=config.GPU_MEMORY_LIMIT_MB,
            ocr_timeout_seconds=config.OCR_TIMEOUT_SECONDS,
            max_tasks=config.MAX_TASKS_PER_CHILD,
        )
        self._current_job_id: str | None = None
        self._current_lease_token: str | None = None
        self._last_heartbeat: float = 0.0
        self._completed_jobs = 0
        self._failed_jobs = 0

    @property
    def worker_id(self) -> str:
        return self._config.WORKER_ID

    def run(self) -> None:
        """Main loop — polls for jobs, processes them, repeats."""
        logger.info(
            "Worker starting: id=%s server=%s interval=%ds lease=%ds",
            self._config.WORKER_ID,
            self._config.SERVER_URL,
            self._config.POLL_INTERVAL_SECONDS,
            self._config.LEASE_SECONDS,
        )

        # Resume incomplete workspaces from previous run
        self._resume_incomplete()

        # Start the OCR executor subprocess
        self._executor.start()
        atexit.register(self._shutdown)

        while not _SHUTTING_DOWN:
            try:
                self._tick()
            except Exception:
                logger.exception("Unhandled error in tick cycle")

            # Poll interval
            for _ in range(self._config.POLL_INTERVAL_SECONDS):
                if _SHUTTING_DOWN:
                    break
                time.sleep(1)

        self._shutdown()

    def _tick(self) -> None:
        """One tick of the main loop."""

        # 1. Heartbeat if currently working
        if self._current_job_id and self._current_lease_token:
            now = time.time()
            if now - self._last_heartbeat >= self._config.HEARTBEAT_SECONDS:
                try:
                    self._client.heartbeat(self._current_job_id, self._current_lease_token)
                    self._last_heartbeat = now
                    logger.debug("Heartbeat sent for job %s", self._current_job_id)
                except WorkerClientError as e:
                    logger.warning("Heartbeat failed: %s", e)

        # 2. If no current job, try to claim one
        if not self._current_job_id:
            self._claim_and_process()

    def _claim_and_process(self) -> None:
        """Claim a job and process it synchronously."""
        try:
            claimed = self._client.claim()
        except WorkerClientError as e:
            logger.warning("Claim failed: %s", e)
            return

        if claimed is None:
            return

        self._current_job_id = claimed.job_id
        self._current_lease_token = claimed.lease_token
        self._last_heartbeat = time.time()

        logger.info(
            "Claimed job %s (input=%s, mime=%s, pages=%s)",
            claimed.job_id,
            claimed.input_artifact_key,
            claimed.input_mime_type,
            claimed.input_page_count,
        )

        try:
            self._process_job(claimed)
            self._completed_jobs += 1
        except Exception as e:
            logger.exception("Job %s failed", claimed.job_id)
            self._failed_jobs += 1
            self._report_failure(claimed.job_id, claimed.lease_token, e)
        finally:
            self._current_job_id = None
            self._current_lease_token = None

        # Gracefully recycle executor if max tasks reached
        if self._executor.task_count >= self._config.MAX_TASKS_PER_CHILD:
            logger.info(
                "Recycling executor after %d tasks", self._executor.task_count
            )
            self._executor.stop()
            self._executor.start()

    def _process_job(self, claimed: Any) -> None:
        """Process a claimed job: download, OCR, upload result."""
        ws = JobWorkspace(self._config.WORKSPACE_ROOT, claimed.job_id)

        # Ensure workspace exists for resume
        import asyncio
        asyncio.run(ws.create())

        # Write initial manifest
        ws.write_manifest({
            "job_id": claimed.job_id,
            "pipeline_fingerprint": claimed.pipeline_fingerprint,
            "status": "downloading",
            "completed_pages": [],
            "input_artifact_key": claimed.input_artifact_key,
            "created_at": datetime.now(UTC).isoformat(),
        })

        # Download input
        logger.info("Downloading input for job %s", claimed.job_id)
        input_path = ws.input_path
        _download_file(claimed.input_artifact_key, str(input_path))
        logger.info("Downloaded %d bytes for job %s", input_path.stat().st_size, claimed.job_id)

        ws.update_manifest(status="downloaded")

        # Start job on server
        self._client.start(
            claimed.job_id,
            claimed.lease_token,
            worker_fingerprint=f"worker-{self._config.WORKER_ID}",
        )

        # Run OCR (delegates to subprocess)
        logger.info("Running OCR for job %s", claimed.job_id)
        ws.update_manifest(status="running")

        # For now, load the file and wrap as a single-page job
        # (full PDF rendering would happen here in production)
        input_bytes = input_path.read_bytes()
        mime = claimed.input_mime_type

        if mime.startswith("image/"):
            pages = [(0, input_bytes)]
        else:
            # PDF — would render to images here
            # For now, treat as single-image fallback
            pages = [(0, input_bytes)]

        result = self._executor.run_ocr(pages)

        # Mark pages completed
        for page in result.get("pages", []):
            ws.mark_page_completed(page["page_index"])

        ws.update_manifest(status="uploading")

        # Save result to workspace
        result_path = ws.result_path
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

        # Upload result (in production, this would upload to artifact storage)
        import hashlib
        result_bytes = result_path.read_bytes()
        output_sha256 = hashlib.sha256(result_bytes).hexdigest()
        output_key = f"ocr-results/{claimed.job_id}/document.ir.json"

        # Upload artifact (in production, upload to COS / streaming endpoint)
        _upload_artifact(
            self._config.SERVER_URL,
            self._config.API_KEY,
            claimed.job_id,
            output_key,
            result_bytes,
        )

        # Complete job on server
        self._client.complete(
            claimed.job_id,
            claimed.lease_token,
            output_artifact_key=output_key,
            output_sha256=output_sha256,
            worker_fingerprint=f"worker-{self._config.WORKER_ID}",
        )

        ws.update_manifest(status="completed", completed_at=datetime.now(UTC).isoformat())
        logger.info("Job %s completed successfully", claimed.job_id)

    def _report_failure(self, job_id: str, lease_token: str, error: Exception) -> None:
        """Report job failure to server."""
        error_code = "WORKER_PROCESS_CRASH"
        error_message = str(error)[:500]
        is_retryable = True

        if isinstance(error, ExecutorError):
            if "timeout" in str(error).lower():
                error_code = "OCR_TIMEOUT"
            elif "OOM" in str(error) or "memory" in str(error).lower():
                error_code = "GPU_OOM_RECOVERABLE"
        elif isinstance(error, WorkerClientError):
            error_code = "NETWORK_ERROR"

        try:
            self._client.fail(
                job_id, lease_token,
                error_code=error_code,
                error_message=error_message,
                is_retryable=is_retryable,
            )
        except WorkerClientError:
            logger.exception("Failed to report failure for job %s", job_id)

    def _resume_incomplete(self) -> None:
        """Scan workspace for incomplete jobs from previous run."""
        incomplete = JobWorkspace.list_incomplete(self._config.WORKSPACE_ROOT)
        if not incomplete:
            return
        logger.info("Found %d incomplete workspaces from previous run", len(incomplete))
        for manifest in incomplete:
            logger.warning(
                "Incomplete job: %s (status=%s, pages=%s)",
                manifest.get("job_id"),
                manifest.get("status"),
                manifest.get("completed_pages"),
            )
            # In production, these would be resumed. For now, log and skip.
            # The server-side lease will eventually expire, making these claimable again.

    def _shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down worker")
        if self._current_job_id and self._current_lease_token:
            try:
                self._client.release(self._current_job_id, self._current_lease_token)
                logger.info("Released job %s", self._current_job_id)
            except WorkerClientError:
                logger.exception("Failed to release job during shutdown")
        self._executor.stop()
        logger.info(
            "Worker stopped: completed=%d failed=%d",
            self._completed_jobs,
            self._failed_jobs,
        )


# ── Helpers ───────────────────────────────────────────────

def _download_file(url: str, dest: str) -> None:
    """Download a file from URL to local path."""
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        resp = client.get(url)
        resp.raise_for_status()
        tmp = dest + ".tmp"
        Path(tmp).write_bytes(resp.content)
        Path(tmp).rename(dest)


def _upload_artifact(server_url: str, api_key: str, job_id: str,
                     key: str, data: bytes) -> None:
    """Upload a result artifact to the production server.

    In production, this should use a signed URL or streaming upload endpoint.
    For now, uses a simple PUT-like POST to an internal endpoint.
    """
    import hashlib
    sha256 = hashlib.sha256(data).hexdigest()
    payload = {
        "job_id": job_id,
        "key": key,
        "sha256": sha256,
        "data": data.hex(),  # hex-encoded for JSON transport
    }
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        resp = client.post(
            f"{server_url.rstrip('/')}/api/internal/ocr-worker/artifacts/upload",
            json=payload,
            headers={
                "Worker-API-Key": f"{job_id}/{api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()


# ── CLI entry point ───────────────────────────────────────

def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Local GPU OCR Worker")
    parser.add_argument("--server", help="Production server URL (overrides env)")
    parser.add_argument("--worker-id", help="Worker ID (overrides env)")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # Override config from CLI args
    if args.server:
        os.environ["OCR_WORKER_SERVER_URL"] = args.server
    if args.worker_id:
        os.environ["OCR_WORKER_ID"] = args.worker_id

    config = OCRWorkerConfig()
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("Config error: %s", err)
        sys.exit(1)

    # Set up signal handling
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    daemon = OcrWorkerDaemon(config)
    daemon.run()


if __name__ == "__main__":
    main()
