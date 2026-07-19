"""OcrWorkerProcess — 单个可杀 Worker 进程。

使用 ``multiprocessing.Process`` + ``Connection`` Pipe 通信。
超时时真正的 SIGTERM → SIGKILL，而非 ``wait=False``。

每个 worker 同一时间只持有一个 active task。
"""

from __future__ import annotations

import logging
import os
import signal
import time
from multiprocessing import connection
from multiprocessing.context import BaseContext
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Any

from app.core.ocr_types import (
    HandshakeMessage,
    STABLE_ERROR_CODES,
    WorkerRequest,
    WorkerResult,
    _PROTOCOL_VERSION,
)

logger = logging.getLogger(__name__)

_SENTINEL = None


def _worker_main(
    conn: Connection,
    config: Any,
    worker_id: int,
) -> None:
    """Worker 子进程入口。

    Args:
        conn: 与父进程的 Pipe 连接（子进程端）。
        config: ``OcrRuntimeConfig`` frozen dataclass。
        worker_id: 此 worker 的 ID。
    """
    os.environ["GLOG_minloglevel"] = "2"

    try:
        from app.core.ocr_engine import OcrEngine

        engine = OcrEngine(config)
        pid = os.getpid()
        conn.send({
            "status": "ready",
            "pid": pid,
            "fingerprint": engine.fingerprint,
        })
        logger.info("Worker[%d] ready (pid=%d fingerprint=%s)",
                     worker_id, pid, engine.fingerprint)

        # Main loop: receive request → run engine → send result
        while True:
            try:
                req_data = conn.recv()
            except (EOFError, ConnectionError):
                logger.info("Worker[%d] pipe closed, exiting", worker_id)
                break

            if req_data is _SENTINEL:
                logger.info("Worker[%d] received shutdown sentinel", worker_id)
                break

            req = _dict_to_worker_request(req_data)
            started = time.monotonic()

            try:
                result_dict = engine.recognize(
                    req.image_bytes,
                    page_index=req.page_index,
                    skip_rotation=req.options.get("skip_rotation", False),
                    mode=req.mode,
                )
            except Exception as exc:
                logger.error("Worker[%d] engine error: %s", worker_id, exc)
                result_dict = {
                    "page_index": req.page_index,
                    "text": "", "lines": [], "boxes": [],
                    "confidence": 0.0, "transforms": None,
                    "coordinate_space": "image",
                    "engine_fingerprint": engine.fingerprint,
                    "failed": True, "error": str(exc),
                }

            finished = time.monotonic()
            result = WorkerResult(
                request_id=req.request_id,
                page_index=req.page_index,
                worker_id=worker_id,
                worker_pid=pid,
                worker_generation=req.worker_generation,
                status="success" if not result_dict.get("failed") else "failed",
                result=result_dict,
                started_monotonic=started,
                finished_monotonic=finished,
                engine_fingerprint=engine.fingerprint,
                stable_error_code=(
                    None if not result_dict.get("failed")
                    else STABLE_ERROR_CODES["ENGINE_ERROR"]
                ),
                error_type=result_dict.get("error") if result_dict.get("failed") else None,
            )

            try:
                conn.send(_worker_result_to_dict(result))
            except (BrokenPipeError, ConnectionError):
                logger.warning("Worker[%d] cannot send result, parent disconnected", worker_id)
                break

    except Exception as exc:
        logger.critical("Worker[%d] startup failed: %s", worker_id, exc)
        try:
            conn.send({"status": "error", "error": str(exc)})
        except Exception:
            pass


def _dict_to_worker_request(d: dict) -> WorkerRequest:
    return WorkerRequest(
        protocol_version=d.get("protocol_version", _PROTOCOL_VERSION),
        request_id=d.get("request_id", ""),
        page_index=d.get("page_index", 0),
        mode=d.get("mode", "boxes"),
        worker_generation=d.get("worker_generation", 0),
        submitted_monotonic=d.get("submitted_monotonic", 0.0),
        deadline_monotonic=d.get("deadline_monotonic", 0.0),
        image_hash=d.get("image_hash", ""),
        image_bytes=d.get("image_bytes", b""),
        options=d.get("options", {}),
    )


def _worker_result_to_dict(r: WorkerResult) -> dict:
    return {
        "protocol_version": r.protocol_version,
        "request_id": r.request_id,
        "page_index": r.page_index,
        "worker_id": r.worker_id,
        "worker_pid": r.worker_pid,
        "worker_generation": r.worker_generation,
        "status": r.status,
        "result": r.result,
        "stable_error_code": r.stable_error_code,
        "error_type": r.error_type,
        "started_monotonic": r.started_monotonic,
        "finished_monotonic": r.finished_monotonic,
        "engine_fingerprint": r.engine_fingerprint,
    }


class OcrWorkerProcess:
    """单个 worker 进程。通过专属 Pipe 与父进程通信。

    每次 ``start()`` 创建一个新进程 + 新 Pipe。
    kill/terminate 后必须 ``close_pipe()`` + ``start()`` 才能复用。
    """

    def __init__(
        self,
        worker_id: int,
        generation: int,
        config: Any,
        *,
        mp_context: BaseContext | None = None,
    ) -> None:
        self._worker_id = worker_id
        self._generation = generation
        self._config = config

        self._process: BaseProcess | None = None
        self._parent_conn: Connection | None = None
        self._child_conn: Connection | None = None

        self._pid: int | None = None
        self._fingerprint: str = ""
        self._started_at: float = 0.0
        self._tasks_completed: int = 0

        # Track the currently assigned request_id
        self._current_request_id: str = ""

        import multiprocessing
        self._mp_context = mp_context or multiprocessing.get_context(
            config.start_method or "spawn",
        )

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the worker subprocess and wait for readiness handshake."""
        if self._process is not None and self._process.is_alive():
            logger.warning("Worker[%d] already running (pid=%d), skipping start",
                           self._worker_id, self._pid)
            return

        # Create new Pipe for this generation
        self._parent_conn, self._child_conn = self._mp_context.Pipe(duplex=True)

        self._process = self._mp_context.Process(
            target=_worker_main,
            args=(self._child_conn, self._config, self._worker_id),
            name=f"ocr-worker-{self._worker_id}-g{self._generation}",
        )
        self._process.start()
        self._started_at = time.monotonic()
        self._pid = self._process.pid

        logger.info(
            "Worker[%d] g%d started (pid=%d)",
            self._worker_id, self._generation, self._pid,
        )

        # Wait for readiness handshake
        self._wait_for_handshake()

    def _wait_for_handshake(self) -> None:
        """Wait for worker readiness handshake with timeout."""
        timeout = self._config.startup_timeout
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if self._parent_conn is None:
                raise RuntimeError("Worker pipe not initialized")
            try:
                if self._parent_conn.poll(timeout=min(1.0, deadline - time.monotonic())):
                    msg = self._parent_conn.recv()
                    if isinstance(msg, dict) and msg.get("status") == "ready":
                        self._fingerprint = msg.get("fingerprint", "")
                        logger.info(
                            "Worker[%d] g%d handshake OK (pid=%s fingerprint=%s)",
                            self._worker_id, self._generation,
                            msg.get("pid"), self._fingerprint,
                        )
                        return
                    elif isinstance(msg, dict) and msg.get("status") == "error":
                        raise RuntimeError(
                            f"Worker startup failed: {msg.get('error', 'unknown')}"
                        )
            except (EOFError, ConnectionError):
                raise RuntimeError("Worker pipe broken during handshake")

        raise TimeoutError(
            f"Worker handshake timed out after {timeout}s"
        )

    # ── IPC ─────────────────────────────────────────────────────────────────

    def send_request(self, req: WorkerRequest) -> None:
        """Send a request to the worker.

        Raises:
            RuntimeError: Worker not started or pipe broken.
        """
        if self._parent_conn is None:
            raise RuntimeError("Worker pipe not initialized")

        self._current_request_id = req.request_id
        try:
            self._parent_conn.send({
                "protocol_version": req.protocol_version,
                "request_id": req.request_id,
                "page_index": req.page_index,
                "mode": req.mode,
                "worker_generation": req.worker_generation,
                "submitted_monotonic": req.submitted_monotonic,
                "deadline_monotonic": req.deadline_monotonic,
                "image_hash": req.image_hash,
                "image_bytes": req.image_bytes,
                "options": req.options,
            })
        except (BrokenPipeError, ConnectionError) as exc:
            raise RuntimeError(
                f"Worker pipe broken when sending request {req.request_id[:8]}"
            ) from exc

    def try_receive_result(self, timeout: float) -> WorkerResult | None:
        """Try to receive a result from the worker.

        Args:
            timeout: Max seconds to wait.

        Returns:
            ``WorkerResult`` if data is available, ``None`` if timeout.
        """
        if self._parent_conn is None:
            raise RuntimeError("Worker pipe not initialized")

        try:
            if self._parent_conn.poll(timeout=timeout):
                data = self._parent_conn.recv()
                if isinstance(data, dict):
                    result = WorkerResult(
                        protocol_version=data.get("protocol_version", _PROTOCOL_VERSION),
                        request_id=data.get("request_id", ""),
                        page_index=data.get("page_index", 0),
                        worker_id=data.get("worker_id", self._worker_id),
                        worker_pid=data.get("worker_pid", self._pid or 0),
                        worker_generation=data.get("worker_generation", self._generation),
                        status=data.get("status", "failed"),
                        result=data.get("result"),
                        stable_error_code=data.get("stable_error_code"),
                        error_type=data.get("error_type"),
                        started_monotonic=data.get("started_monotonic", 0.0),
                        finished_monotonic=data.get("finished_monotonic", 0.0),
                        engine_fingerprint=data.get("engine_fingerprint", ""),
                    )
                    self._current_request_id = ""
                    self._tasks_completed += 1
                    return result
        except (EOFError, ConnectionError):
            logger.warning("Worker[%d] pipe broken during receive", self._worker_id)
            return None

        return None

    def receive_result_blocking(self) -> WorkerResult:
        """Block until a result is received from the worker.

        This is a BLOCKING call. Must be run in a thread (via
        ``run_in_executor``) from async context.

        Raises:
            RuntimeError: Pipe broken or worker died.
        """
        if self._parent_conn is None:
            raise RuntimeError("Worker pipe not initialized")

        try:
            data = self._parent_conn.recv()
            if isinstance(data, dict):
                result = WorkerResult(
                    protocol_version=data.get("protocol_version", _PROTOCOL_VERSION),
                    request_id=data.get("request_id", ""),
                    page_index=data.get("page_index", 0),
                    worker_id=data.get("worker_id", self._worker_id),
                    worker_pid=data.get("worker_pid", self._pid or 0),
                    worker_generation=data.get("worker_generation", self._generation),
                    status=data.get("status", "failed"),
                    result=data.get("result"),
                    stable_error_code=data.get("stable_error_code"),
                    error_type=data.get("error_type"),
                    started_monotonic=data.get("started_monotonic", 0.0),
                    finished_monotonic=data.get("finished_monotonic", 0.0),
                    engine_fingerprint=data.get("engine_fingerprint", ""),
                )
                self._current_request_id = ""
                self._tasks_completed += 1
                return result
        except (EOFError, ConnectionError) as exc:
            raise RuntimeError(f"Worker pipe broken during blocking receive: {exc}") from exc

        raise RuntimeError("Unexpected data from worker pipe")
        """Check if the worker pipe is still usable."""
        if self._parent_conn is None:
            return True
        try:
            return self._parent_conn.closed
        except Exception:
            return True

    # ── Termination ─────────────────────────────────────────────────────────

    def terminate(self) -> None:
        """Send SIGTERM to worker process."""
        if self._process is not None and self._process.is_alive():
            logger.info("Worker[%d] g%d sending SIGTERM (pid=%d)",
                        self._worker_id, self._generation, self._pid)
            try:
                self._process.terminate()
            except Exception as exc:
                logger.warning("Worker[%d] terminate error: %s", self._worker_id, exc)

    def kill(self) -> None:
        """Send SIGKILL to worker process."""
        if self._process is not None and self._process.is_alive():
            logger.info("Worker[%d] g%d sending SIGKILL (pid=%d)",
                        self._worker_id, self._generation, self._pid)
            try:
                os.kill(self._pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError) as exc:
                logger.warning("Worker[%d] kill error: %s", self._worker_id, exc)
            except Exception as exc:
                logger.warning("Worker[%d] kill unexpected error: %s", self._worker_id, exc)

    def join(self, timeout: float | None = None) -> None:
        """Wait for the process to exit."""
        if self._process is not None:
            try:
                self._process.join(timeout=timeout)
            except Exception as exc:
                logger.warning("Worker[%d] join error: %s", self._worker_id, exc)

    def close_pipe(self) -> None:
        """Close the parent-side pipe connection."""
        if self._parent_conn is not None:
            try:
                self._parent_conn.close()
            except Exception:
                pass
            self._parent_conn = None
        if self._child_conn is not None:
            try:
                self._child_conn.close()
            except Exception:
                pass
            self._child_conn = None

    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def ensure_dead(self, kill_timeout: float = 5.0) -> bool:
        """Ensure the process is fully dead (SIGTERM → SIGKILL escalation).

        Returns:
            True if process is confirmed dead.
        """
        if not self.is_alive():
            return True

        self.terminate()
        self.join(timeout=kill_timeout / 2)

        if self.is_alive():
            self.kill()
            self.join(timeout=kill_timeout / 2)

        return not self.is_alive()

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def worker_id(self) -> int:
        return self._worker_id

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def pid(self) -> int | None:
        return self._pid

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def tasks_completed(self) -> int:
        return self._tasks_completed

    @property
    def current_request_id(self) -> str:
        return self._current_request_id

    @property
    def started_at(self) -> float:
        return self._started_at
