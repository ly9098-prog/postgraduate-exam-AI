"""OCR Worker executor — isolated subprocess that runs PaddleOCR.

The parent keeps the native OCR process killable, bounds every IPC wait, and
continuously drains stderr so verbose native libraries cannot deadlock the child.
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from typing import Any, TextIO

logger = logging.getLogger("postgraduate-ai.ocr-worker.executor")


class ExecutorError(Exception):
    """Raised on executor failures."""


class OcrExecutorProcess:
    """Manage one long-lived, killable PaddleOCR subprocess."""

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
        self._process: subprocess.Popen[str] | None = None
        self._task_count = 0
        self._state_lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._stderr_thread: threading.Thread | None = None
        self._stderr_tail: deque[str] = deque(maxlen=50)

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._process is not None and self._process.poll() is None

    @property
    def task_count(self) -> int:
        with self._state_lock:
            return self._task_count

    def start(self) -> None:
        """Start the OCR child and a daemon thread that drains stderr."""
        with self._state_lock:
            if self._process is not None and self._process.poll() is None:
                return
            script = _build_subprocess_script()
            process = subprocess.Popen(
                [self._python_path, "-c", script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._process = process
            self._task_count = 0
            self._stderr_tail.clear()
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(process,),
                name=f"ocr-executor-stderr-{process.pid}",
                daemon=True,
            )
            self._stderr_thread.start()
        logger.info("OCR executor subprocess started (pid=%d)", process.pid)

    def _drain_stderr(self, process: subprocess.Popen[str]) -> None:
        stream = process.stderr
        if stream is None:
            return
        try:
            for line in stream:
                clean = line.rstrip()
                if clean:
                    self._stderr_tail.append(clean[:2000])
                    logger.debug("OCR child[%d]: %s", process.pid, clean)
        except (OSError, ValueError):
            return

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the subprocess with bounded TERM/KILL escalation."""
        with self._state_lock:
            process = self._process
            self._process = None
        if process is None:
            return

        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass

        try:
            process.wait(timeout=max(0.0, timeout))
        except subprocess.TimeoutExpired:
            logger.warning(
                "Executor subprocess did not exit in %.1fs, terminating", timeout
            )
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                logger.warning("Executor subprocess still alive, killing")
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    logger.error("Executor subprocess could not be reaped")

        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        logger.info("OCR executor subprocess stopped (pid=%d)", process.pid)

    def run_ocr(self, page_images: list[tuple[int, bytes]]) -> dict[str, Any]:
        """Run pages serially with one overall timeout and bounded IPC waits.

        Sending one page per child request avoids retaining Base64 copies for an
        entire document in both parent and child at the same time.
        """
        if not page_images:
            return {"pages": [], "error": None, "latency_ms": 0.0}

        with self._run_lock:
            if not self.is_running:
                self.start()
            started = time.perf_counter()
            deadline = started + float(self._ocr_timeout_seconds)
            pages: list[dict[str, Any]] = []

            for position, (page_index, image_bytes) in enumerate(page_images):
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    self._terminate_and_raise("OCR timeout")
                result = self._run_single_page(
                    page_index, image_bytes, timeout=remaining
                )
                pages.extend(result.get("pages", []))
                with self._state_lock:
                    self._task_count += 1
                    should_recycle = self._task_count >= self._max_tasks
                if should_recycle and position + 1 < len(page_images):
                    self.stop()
                    self.start()

            elapsed = (time.perf_counter() - started) * 1000
            return {"pages": pages, "error": None, "latency_ms": elapsed}

    def _run_single_page(
        self,
        page_index: int,
        image_bytes: bytes,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        with self._state_lock:
            process = self._process
        if process is None or process.poll() is not None:
            raise ExecutorError("Executor subprocess not running")
        if process.stdin is None or process.stdout is None:
            self._terminate_and_raise("Executor pipes are unavailable")

        task_id = uuid.uuid4().hex[:12]
        payload = json.dumps({
            "task_id": task_id,
            "pages": [{"index": page_index, "data": _bytes_to_b64(image_bytes)}],
            "gpu_memory_limit_mb": self._gpu_memory_limit_mb,
        }) + "\n"
        deadline = time.perf_counter() + timeout

        try:
            self._call_with_timeout(
                lambda: self._write_payload(process.stdin, payload),
                max(0.001, deadline - time.perf_counter()),
                "Executor stdin write timeout",
            )
            line = self._call_with_timeout(
                process.stdout.readline,
                max(0.001, deadline - time.perf_counter()),
                "OCR timeout",
            )
        except ExecutorError:
            self.stop(timeout=0.0)
            raise

        if not line:
            stderr = " | ".join(self._stderr_tail)[-2000:]
            code = process.poll()
            self.stop(timeout=0.0)
            raise ExecutorError(
                f"Executor subprocess exited (code={code}): {stderr or 'no stderr'}"
            )

        try:
            result = json.loads(line)
        except json.JSONDecodeError as exc:
            self._terminate_and_raise(f"Invalid JSON from executor: {exc}")
        if result.get("task_id") != task_id:
            self._terminate_and_raise("Executor protocol desynchronised")
        if result.get("error"):
            raise ExecutorError(f"OCR error: {result['error']}")
        return result

    @staticmethod
    def _write_payload(stream: TextIO, payload: str) -> None:
        stream.write(payload)
        stream.flush()

    @staticmethod
    def _call_with_timeout(call, timeout: float, message: str):
        result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def _runner() -> None:
            try:
                result_queue.put((True, call()))
            except BaseException as exc:
                result_queue.put((False, exc))

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        try:
            ok, value = result_queue.get(timeout=max(0.001, timeout))
        except queue.Empty as exc:
            raise ExecutorError(message) from exc
        if ok:
            return value
        raise ExecutorError(f"Executor IPC failed: {value}") from value

    def _terminate_and_raise(self, msg: str) -> None:
        self.stop(timeout=0.0)
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
