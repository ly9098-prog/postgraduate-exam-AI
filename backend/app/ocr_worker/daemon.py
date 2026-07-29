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
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.ocr_worker.client import (
    WorkerAPIClient,
    WorkerClientError,
    parse_iso_timestamp,
)
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
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._lease_lost = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_done = False
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

        # Resume incomplete workspaces from previous run and prune terminal
        # workspaces before accepting more input.
        self._resume_incomplete()
        self._prune_workspaces()

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
        """Claim work when idle; active jobs heartbeat on a dedicated thread."""
        if not self._current_job_id:
            self._claim_and_process()

    def _claim_and_process(self) -> None:
        """Claim a job and process it synchronously with lease heartbeats."""
        try:
            claimed = self._client.claim()
        except WorkerClientError as exc:
            logger.warning("Claim failed: %s", exc)
            return

        if claimed is None:
            return

        self._current_job_id = claimed.job_id
        self._current_lease_token = claimed.lease_token
        self._lease_lost.clear()
        self._start_heartbeat(
            claimed.job_id,
            claimed.lease_token,
            claimed.lease_expires_at,
        )

        logger.info(
            "Claimed job %s (input=%s, mime=%s, pages=%s)",
            claimed.job_id, claimed.input_artifact_key,
            claimed.input_mime_type, claimed.input_page_count,
        )

        try:
            self._ensure_workspace_capacity(claimed.input_size_bytes)
            self._process_job(claimed)
            self._completed_jobs += 1
        except Exception as exc:
            self._stop_heartbeat()
            logger.exception("Job %s failed", claimed.job_id)
            self._failed_jobs += 1
            try:
                JobWorkspace(
                    self._config.WORKSPACE_ROOT, claimed.job_id
                ).update_manifest(
                    status="failed",
                    error=str(exc)[:1000],
                    completed_at=datetime.now(UTC).isoformat(),
                )
            except Exception:
                pass
            self._report_failure(claimed.job_id, claimed.lease_token, exc)
        finally:
            self._stop_heartbeat()
            self._current_job_id = None
            self._current_lease_token = None
            self._prune_workspaces()

        # Recover automatically after timeout/crash.  Previously a stopped
        # executor made every later claimed job fail until daemon restart.
        if not _SHUTTING_DOWN and not self._executor.is_running:
            self._executor.start()
        elif self._executor.task_count >= self._config.MAX_TASKS_PER_CHILD:
            logger.info(
                "Recycling executor after %d pages", self._executor.task_count
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
        used_bytes = JobWorkspace.total_disk_usage(self._config.WORKSPACE_ROOT)
        remaining_bytes = max(0, self._workspace_limit_bytes() - used_bytes)
        _download_file(
            claimed.input_artifact_key,
            str(input_path),
            max_bytes=remaining_bytes,
            expected_size=claimed.input_size_bytes,
        )
        logger.info("Downloaded %d bytes for job %s", input_path.stat().st_size, claimed.job_id)

        ws.update_manifest(status="downloaded")
        self._ensure_lease_active()

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
        self._ensure_lease_active()

        # Mark pages completed
        for page in result.get("pages", []):
            ws.mark_page_completed(page["page_index"])

        ws.update_manifest(status="uploading")

        # Save result to workspace
        result_path = ws.result_path
        result_bytes = json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        result_path.write_bytes(result_bytes)

        # Upload result (in production, this would upload to artifact storage)
        import hashlib
        output_sha256 = hashlib.sha256(result_bytes).hexdigest()
        output_key = f"ocr-results/{claimed.job_id}/document.ir.json"

        # Upload artifact (in production, upload to COS / streaming endpoint)
        _upload_artifact(
            self._config.SERVER_URL,
            self._config.WORKER_ID,
            self._config.API_KEY,
            claimed.job_id,
            output_key,
            result_bytes,
        )
        self._ensure_lease_active()

        # Stop heartbeat before the terminal transition to avoid a late
        # heartbeat racing with completion and receiving a false 409.
        self._stop_heartbeat()
        self._ensure_lease_active()
        self._client.complete(
            claimed.job_id,
            claimed.lease_token,
            output_artifact_key=output_key,
            output_sha256=output_sha256,
            worker_fingerprint=f"worker-{self._config.WORKER_ID}",
            complete_idempotency_key=output_sha256,
        )

        ws.update_manifest(status="completed", completed_at=datetime.now(UTC).isoformat())
        logger.info("Job %s completed successfully", claimed.job_id)

    def _start_heartbeat(
        self,
        job_id: str,
        lease_token: str,
        lease_expires_at: float,
    ) -> None:
        # Use a fresh Event per job.  Reusing/clearing an Event while an old
        # heartbeat request is still returning can resurrect the old loop and
        # heartbeat the wrong lease.
        stop_event = threading.Event()
        self._heartbeat_stop = stop_event
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, lease_token, lease_expires_at, stop_event),
            name=f"ocr-heartbeat-{job_id[:8]}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        stop_event = self._heartbeat_stop
        stop_event.set()
        thread = self._heartbeat_thread
        self._heartbeat_thread = None
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.is_alive()
        ):
            thread.join(timeout=2.0)

    def _heartbeat_loop(
        self,
        job_id: str,
        lease_token: str,
        lease_expires_at: float,
        stop_event: threading.Event,
    ) -> None:
        interval = max(1, self._config.HEARTBEAT_SECONDS)
        lease_deadline = (
            lease_expires_at
            if lease_expires_at > time.time()
            else time.time() + self._config.LEASE_SECONDS
        )
        while not stop_event.wait(interval):
            try:
                response = self._client.heartbeat(job_id, lease_token)
                lease_deadline = parse_iso_timestamp(
                    response.get("lease_expires_at"),
                    fallback=time.time() + self._config.LEASE_SECONDS,
                )
                logger.debug("Heartbeat sent for job %s", job_id)
            except WorkerClientError as exc:
                logger.warning("Heartbeat failed for job %s: %s", job_id, exc)
                fatal_http = "(409)" in str(exc) or "(401)" in str(exc)
                safety_margin = max(5.0, float(interval))
                if (
                    fatal_http
                    or time.time() >= lease_deadline - safety_margin
                ):
                    self._lease_lost.set()
                    # Abort native OCR promptly; continuing after lease loss can
                    # duplicate GPU work after the server reclaims the job.
                    self._executor.stop(timeout=0.0)
                    return

    def _ensure_lease_active(self) -> None:
        if self._lease_lost.is_set():
            raise WorkerClientError("OCR job lease was lost during processing")
        if _SHUTTING_DOWN:
            raise ExecutorError("Worker shutdown requested")

    def _workspace_limit_bytes(self) -> int:
        return max(1, self._config.MAX_WORKSPACE_GB) * 1024 * 1024 * 1024

    def _prune_workspaces(self) -> None:
        try:
            deleted, freed, remaining = JobWorkspace.prune(
                self._config.WORKSPACE_ROOT,
                retention_hours=self._config.RESULT_RETENTION_HOURS,
                max_bytes=self._workspace_limit_bytes(),
            )
            if deleted:
                logger.info(
                    "Pruned %d OCR workspaces (freed %.1f MB, remaining %.1f MB)",
                    deleted, freed / (1024 * 1024), remaining / (1024 * 1024),
                )
        except Exception:
            logger.exception("OCR workspace pruning failed")

    def _ensure_workspace_capacity(self, incoming_bytes: int) -> None:
        self._prune_workspaces()
        used = JobWorkspace.total_disk_usage(self._config.WORKSPACE_ROOT)
        limit = self._workspace_limit_bytes()
        if incoming_bytes < 0 or used + incoming_bytes > limit:
            raise ExecutorError(
                f"OCR workspace capacity exceeded: used={used}, "
                f"incoming={incoming_bytes}, limit={limit}"
            )

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
        """Bounded, idempotent shutdown."""
        with self._shutdown_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True

        logger.info("Shutting down worker")
        self._stop_heartbeat()
        self._executor.stop()
        if self._current_job_id and self._current_lease_token:
            try:
                self._client.release(
                    self._current_job_id, self._current_lease_token
                )
                logger.info("Released job %s", self._current_job_id)
            except WorkerClientError:
                logger.exception("Failed to release job during shutdown")
        self._client.close()
        logger.info(
            "Worker stopped: completed=%d failed=%d",
            self._completed_jobs, self._failed_jobs,
        )


# ── Helpers ───────────────────────────────────────────────

def _download_file(
    url: str,
    dest: str,
    *,
    max_bytes: int,
    expected_size: int | None = None,
) -> None:
    """Stream a download to disk with a hard size bound and atomic rename."""
    target = Path(dest)
    tmp = target.with_suffix(target.suffix + ".tmp")
    total = 0
    try:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                raw_length = response.headers.get("Content-Length")
                if raw_length:
                    try:
                        declared = int(raw_length)
                    except ValueError:
                        declared = -1
                    if max_bytes > 0 and declared > max_bytes:
                        raise ExecutorError(
                            f"Input exceeds workspace limit: {declared} > {max_bytes}"
                        )
                with tmp.open("wb") as fh:
                    # Use raw bytes so Content-Length/expected_size checks are
                    # not invalidated by transparent content decoding.
                    for chunk in response.iter_raw(chunk_size=1024 * 1024):
                        total += len(chunk)
                        if max_bytes > 0 and total > max_bytes:
                            raise ExecutorError(
                                f"Input exceeds workspace limit: {total} > {max_bytes}"
                            )
                        fh.write(chunk)
        if expected_size is not None and expected_size >= 0 and total != expected_size:
            raise ExecutorError(
                f"Downloaded size mismatch: expected={expected_size}, actual={total}"
            )
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _upload_artifact(
    server_url: str,
    worker_id: str,
    api_key: str,
    job_id: str,
    key: str,
    data: bytes,
) -> None:
    """Stream the existing hex-JSON artifact contract without a 2x copy."""
    import hashlib

    sha256 = hashlib.sha256(data).hexdigest()
    prefix = (
        "{"
        f"\"job_id\":{json.dumps(job_id)},"
        f"\"key\":{json.dumps(key)},"
        f"\"sha256\":{json.dumps(sha256)},"
        "\"data\":\""
    ).encode("utf-8")

    def _body_chunks():
        yield prefix
        view = memoryview(data)
        for offset in range(0, len(view), 64 * 1024):
            yield bytes(view[offset:offset + 64 * 1024]).hex().encode("ascii")
        yield b"\"}"

    headers = {
        "Worker-API-Key": f"{worker_id}/{api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        response = client.post(
            f"{server_url.rstrip('/')}/api/internal/ocr-worker/artifacts/upload",
            content=_body_chunks(),
            headers=headers,
        )
        response.raise_for_status()


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
