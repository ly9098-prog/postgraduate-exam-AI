"""OCR 公共类型 — Engine / Worker / Gateway 共享。

所有业务模块只需 import 此文件获取类型，无需 import Engine。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# OCR 结果类型
# ---------------------------------------------------------------------------


@dataclass
class OcrLine:
    """单行 OCR 识别结果。"""
    text: str
    polygon: list[float]          # [x0,y0,x1,y1,x2,y2,x3,y3]
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    confidence: float = 0.0
    line_id: str = ""


@dataclass
class OcrPageResult:
    """单页 OCR 识别结果。

    保留 P3 所需的 line-level 数据：text、polygon/bbox、confidence、
    transforms、coordinate space 完整信息。
    """
    page_index: int
    text: str                     # 拼接全文
    lines: list[OcrLine] = field(default_factory=list)
    confidence: float = 0.0
    transforms: list[dict] | None = None  # TransformRecord list
    coordinate_space: str = "image"       # "image" | "original"
    failed: bool = False
    error: str | None = None
    engine_fingerprint: str = ""


@dataclass
class OcrCandidateResult:
    """OCR 推理候选结果（含原始 PaddleOCR 输出）。"""
    result: Any
    image_size: tuple[int, int]


# ---------------------------------------------------------------------------
# Worker IPC 类型
# ---------------------------------------------------------------------------


_PROTOCOL_VERSION = 1


@dataclass
class WorkerRequest:
    """父进程 → Worker 子进程的 IPC 请求。"""
    protocol_version: int = _PROTOCOL_VERSION
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    page_index: int = 0
    mode: str = "boxes"           # "text" | "boxes" | "raw"
    worker_generation: int = 0
    submitted_monotonic: float = 0.0
    deadline_monotonic: float = 0.0
    image_hash: str = ""          # SHA256 prefix
    image_bytes: bytes = b""
    options: dict = field(default_factory=dict)

    def describe(self) -> str:
        return (
            f"WorkerRequest(id={self.request_id[:8]} idx={self.page_index} "
            f"mode={self.mode} gen={self.worker_generation})"
        )


@dataclass
class WorkerResult:
    """Worker 子进程 → 父进程的 IPC 结果。"""
    protocol_version: int = _PROTOCOL_VERSION
    request_id: str = ""
    page_index: int = 0
    worker_id: int = 0
    worker_pid: int = 0
    worker_generation: int = 0
    status: str = "failed"        # "success" | "failed" | "timeout"
    result: dict | None = None
    stable_error_code: str | None = None  # "QUEUE_TIMEOUT" | "EXECUTION_TIMEOUT" | "ENGINE_ERROR" | ...
    error_type: str | None = None
    started_monotonic: float = 0.0
    finished_monotonic: float = 0.0
    engine_fingerprint: str = ""


@dataclass
class HandshakeMessage:
    """Worker 启动后的 readiness handshake。"""
    status: str                   # "ready" | "error"
    pid: int = 0
    fingerprint: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# OCR 选项
# ---------------------------------------------------------------------------


@dataclass
class OcrOptions:
    """OCR 识别选项。"""
    mode: str = "boxes"           # "text" | "boxes" | "raw"
    skip_rotation: bool = False
    language: str = "ch"


# ---------------------------------------------------------------------------
# Worker Pool 指标
# ---------------------------------------------------------------------------


@dataclass
class WorkerPoolMetrics:
    """Worker pool 生命周期指标。"""
    accepted: int = 0             # 总提交任务数
    queued: int = 0               # 当前在队列中的任务数
    running: int = 0              # 当前正在执行的任务数
    finished: int = 0             # 成功完成数
    failed: int = 0               # 失败数
    timed_out: int = 0            # 执行超时数
    late_finished: int = 0        # 超时后 worker 才返回结果数
    crashed: int = 0              # worker crash 数
    restarted: int = 0            # worker 重启数
    stale_discarded: int = 0      # 旧 generation 迟到结果丢弃数
    queue_full: int = 0           # 队列满拒绝数
    queue_wait_timeout: int = 0   # 队列等待超时数
    active_leases: int = 0        # 当前未释放的 lease 数

    def snapshot(self) -> dict:
        return {
            "accepted": self.accepted,
            "queued": self.queued,
            "running": self.running,
            "finished": self.finished,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "late_finished": self.late_finished,
            "crashed": self.crashed,
            "restarted": self.restarted,
            "stale_discarded": self.stale_discarded,
            "queue_full": self.queue_full,
            "queue_wait_timeout": self.queue_wait_timeout,
            "active_leases": self.active_leases,
        }


# ---------------------------------------------------------------------------
# 稳定错误码（不做 metric label 用的原始异常文本）
# ---------------------------------------------------------------------------

STABLE_ERROR_CODES = {
    "QUEUE_FULL": "ocr.queue_full",
    "QUEUE_TIMEOUT": "ocr.queue_wait_timeout",
    "EXECUTION_TIMEOUT": "ocr.execution_timeout",
    "ENGINE_ERROR": "ocr.engine_error",
    "WORKER_CRASH": "ocr.worker_crash",
    "WORKER_STARTUP_FAILED": "ocr.worker_startup_failed",
    "SHUTDOWN": "ocr.shutdown",
    "ENGINE_NOT_AVAILABLE": "ocr.engine_not_available",
    # Remote (PaddleX HTTP) error codes
    "REMOTE_CONNECT_ERROR": "ocr.remote_connect_error",
    "REMOTE_TIMEOUT": "ocr.remote_timeout",
    "REMOTE_HTTP_ERROR": "ocr.remote_http_error",
    "REMOTE_PROTOCOL_ERROR": "ocr.remote_protocol_error",
    "REMOTE_SERVICE_ERROR": "ocr.remote_service_error",
    "REMOTE_CLOSED": "ocr.remote_closed",
    "REMOTE_CANCELLED": "ocr.remote_cancelled",
}
