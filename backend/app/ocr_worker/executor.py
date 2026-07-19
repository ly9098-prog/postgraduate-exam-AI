"""OCR Worker executor — isolated subprocess that runs PaddleOCR.

Design:
- Single subprocess managed by the daemon parent.
- PaddleOCR loads ONCE per child process (not per page).
- Child process receives job data via stdin pipe, outputs ModuleResult via stdout JSON.
- Parent monitors child RSS/GPU memory and terminates if thresholds exceeded.
- Child auto-exits after MAX_TASKS_PER_CHILD pages (graceful recycle).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("postgraduate-ai.ocr-worker.executor")


class ExecutorError(Exception):
    """Raised on executor failures."""


class OcrExecutorProcess:
    """Manages a single PaddleOCR subprocess.

    The subprocess runs a small Python loop:
      - Read a task dict (JSON line) from stdin
      - Load PaddleOCR (once, on first task)
      - Run OCR, write result (JSON line) to stdout
      - Repeat until stdin closes
    """

    def __init__(
        self,
        python_path: str = sys.executable,
        gpu_memory_limit_mb: int = 3600,
        ocr_timeout_seconds: int = 600,
        max_tasks: int = 20,
    ) -> None:
        self._python_path = python_path
        self._gpu_memory_limit_mb = gpu_memory_limit_mb
        self._ocr_timeout_seconds = ocr_timeout_seconds
        self._max_tasks = max_tasks
        self._process: subprocess.Popen | None = None
        self._task_count = 0

    @property
    def is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    @property
    def task_count(self) -> int:
        return self._task_count

    def start(self) -> None:
        """Start the OCR child subprocess."""
        if self.is_running:
            logger.warning("Executor already running")
            return

        script = _build_subprocess_script()
        self._process = subprocess.Popen(
            [self._python_path, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
        self._task_count = 0
        logger.info("OCR executor subprocess started (pid=%d)", self._process.pid)

    def stop(self, timeout: float = 10.0) -> None:
        """Gracefully stop the subprocess."""
        if self._process is None:
            return

        if self._process.stdin:
            try:
                self._process.stdin.close()
            except OSError:
                pass

        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Executor subprocess did not exit in %.1fs, sending SIGTERM", timeout)
            self._process.terminate()
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                logger.warning("Executor subprocess still alive, sending SIGKILL")
                self._process.kill()
                self._process.wait()

        self._process = None
        logger.info("OCR executor subprocess stopped")

    def run_ocr(self, page_images: list[tuple[int, bytes]]) -> dict[str, Any]:
        """Send page images to the subprocess and get OCR results.

        Args:
            page_images: List of (page_index, png_bytes) tuples.

        Returns:
            Dict with keys: pages, metadata, error, latency_ms

        Raises ExecutorError on subprocess crash or timeout.
        """
        if not self.is_running:
            raise ExecutorError("Executor subprocess not running")

        task_id = str(uuid.uuid4().hex[:12])
        task = {
            "task_id": task_id,
            "pages": [
                {"index": idx, "data": _bytes_to_b64(data)}
                for idx, data in page_images
            ],
            "gpu_memory_limit_mb": self._gpu_memory_limit_mb,
        }

        start = time.perf_counter()

        # Write task
        if self._process.stdin is None:
            raise ExecutorError("Executor stdin is None")
        self._process.stdin.write(json.dumps(task) + "\n")
        self._process.stdin.flush()

        # Read result — timeout-based read
        result_line: str | None = None
        deadline = time.perf_counter() + self._ocr_timeout_seconds
        while time.perf_counter() < deadline:
            if self._process.stdout is None:
                raise ExecutorError("Executor stdout is None")
            line = self._process.stdout.readline()
            if line:
                result_line = line.strip()
                break

            # Check if process died
            if self._process.poll() is not None:
                stderr = ""
                if self._process.stderr:
                    stderr = self._process.stderr.read()
                raise ExecutorError(
                    f"Executor subprocess died (pid={self._process.pid}): {stderr[:500]}"
                )

            time.sleep(0.05)

        if result_line is None:
            self._terminate_and_raise("OCR timeout")

        try:
            result = json.loads(result_line)
        except json.JSONDecodeError as e:
            self._terminate_and_raise(f"Invalid JSON from executor: {e}")

        elapsed = (time.perf_counter() - start) * 1000
        result.setdefault("latency_ms", elapsed)
        self._task_count += 1

        if result.get("error"):
            raise ExecutorError(f"OCR error: {result['error']}")

        return result

    def _terminate_and_raise(self, msg: str) -> None:
        self.stop()
        raise ExecutorError(msg)


# ── Helpers ───────────────────────────────────────────────

def _bytes_to_b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode()


def _b64_to_bytes(s: str) -> bytes:
    import base64
    return base64.b64decode(s)


def _build_subprocess_script() -> str:
    """Build a self-contained Python script for the subprocess.

    This keeps the subprocess self-contained without needing file access.
    """
    return r'''
import json
import sys
import time

# Lazy-load PaddleOCR — imported here, not in parent process
_ocr = None

def _get_ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(use_angle_cls=True, lang="ch", use_gpu=True)
    return _ocr

def _process_pages(pages):
    ocr = _get_ocr()
    results = []
    for page in pages:
        idx = page["index"]
        data = __import__("base64").b64decode(page["data"])
        ocr_result = ocr.ocr(data, cls=True)
        lines = []
        if ocr_result and ocr_result[0]:
            for line in ocr_result[0]:
                poly = line[0]
                text = line[1][0]
                conf = line[1][1]
                lines.append({
                    "polygon": poly,
                    "text": text,
                    "confidence": conf,
                })
        results.append({"page_index": idx, "lines": lines})
    return results

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        task = json.loads(line)
        pages = task.get("pages", [])
        result = _process_pages(pages)
        output = {"task_id": task["task_id"], "pages": result, "error": None}
    except Exception as e:
        output = {"task_id": task.get("task_id", "?"), "pages": [], "error": str(e)}
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    sys.stdout.flush()
'''
