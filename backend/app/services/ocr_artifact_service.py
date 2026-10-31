"""Receive OCR worker result artifacts streamed as hex-JSON.

Wire format (see ``ocr_worker.daemon._upload_artifact``)::

    {"job_id":"…","key":"…","sha256":"…","data":"<hex>"}

The body is decoded incrementally into a temporary file, hashed on the fly and
renamed into place only after the declared SHA-256 matches.
"""

from __future__ import annotations

import asyncio
import binascii
import fcntl
import hashlib
import json
import os
import re
import uuid
from collections.abc import AsyncIterable, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.models.ocr_job import OCRJob
from app.models.pipeline_enums import OCRJobStatus

_JOB_ID_RE = re.compile(r"[0-9a-f]{32}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_MARKER = b'"data":"'
_MAX_HEADER_BYTES = 4096
_MAX_TRAILER_BYTES = 16
_TEMP_GRACE_SEC = 3600
_LOCK_NAME = ".quota.lock"
_UPLOADABLE = {OCRJobStatus.RUNNING.value, OCRJobStatus.UPLOADING.value}


class ArtifactUploadError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def artifact_key(job_id: str) -> str:
    return f"ocr-results/{job_id}/document.ir.json"


def max_body_bytes() -> int:
    return settings.OCR_WORKER_ARTIFACT_MAX_BYTES * 2 + _MAX_HEADER_BYTES


def _root() -> Path:
    configured = settings.OCR_WORKER_ARTIFACT_DIR
    return Path(configured or Path(settings.STAGING_STORAGE_DIR) / "worker-artifacts")


def verify_stored_artifact(job_id: str, output_artifact_key: str, output_sha256: str) -> None:
    """Check a completion claim against the artifact the upload flow stored.

    Raises ValueError unless the key is the job's canonical key and the stored
    file exists, is within the size limit, hashes to ``output_sha256`` and holds
    a JSON object.
    """
    expected = artifact_key(job_id)
    if output_artifact_key != expected:
        raise ValueError("output_artifact_key does not belong to this job")
    path = _root() / expected
    limit = settings.OCR_WORKER_ARTIFACT_MAX_BYTES
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("result artifact is missing")
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise ValueError("result artifact is unreadable") from exc
    if len(raw) > limit:
        raise ValueError("result artifact exceeds the size limit")
    if hashlib.sha256(raw).hexdigest() != output_sha256:
        raise ValueError("output_sha256 does not match the stored artifact")
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValueError("result artifact is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("result artifact must be a JSON object")


def _parse_header(raw: bytes) -> dict:
    try:
        header = json.loads(raw.rstrip().removesuffix(b",") + b"}")
    except ValueError as exc:
        raise ArtifactUploadError(400, "Malformed artifact header") from exc
    if not isinstance(header, dict) or set(header) != {"job_id", "key", "sha256"}:
        raise ArtifactUploadError(400, "Malformed artifact header")
    job_id, key, sha = header["job_id"], header["key"], header["sha256"]
    if not all(isinstance(v, str) for v in (job_id, key, sha)):
        raise ArtifactUploadError(400, "Malformed artifact header")
    if not _JOB_ID_RE.fullmatch(job_id):
        raise ArtifactUploadError(400, "Invalid job_id")
    if key != artifact_key(job_id):
        raise ArtifactUploadError(400, "Artifact key does not belong to the job")
    if not _SHA_RE.fullmatch(sha):
        raise ArtifactUploadError(400, "Invalid sha256")
    return header


def authorize_upload(job: OCRJob | None, worker_id: str, header: dict) -> None:
    """A completed job accepts only its recorded output; others need the lease."""
    if job is None:
        raise ArtifactUploadError(404, "Job not found")
    if job.status == OCRJobStatus.COMPLETED.value:
        if job.output_sha256 != header["sha256"]:
            raise ArtifactUploadError(409, "Job completed with a different output")
        return
    if job.status not in _UPLOADABLE:
        raise ArtifactUploadError(409, f"Job cannot accept an upload in {job.status}")
    if job.lease_owner != worker_id:
        raise ArtifactUploadError(403, "Job is not leased to this worker")
    expires = job.lease_expires_at
    if expires is not None:
        expires = expires if expires.tzinfo else expires.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires:
            raise ArtifactUploadError(409, "Job lease has expired")


def _hex_decode(buffer: bytes) -> tuple[bytes, bytes]:
    even = len(buffer) - (len(buffer) % 2)
    try:
        return binascii.unhexlify(buffer[:even]), buffer[even:]
    except binascii.Error as exc:
        raise ArtifactUploadError(400, "Artifact data is not valid hex") from exc


async def _read_header(stream) -> tuple[dict, bytes]:
    buffer = b""
    async for chunk in stream:
        buffer += chunk
        index = buffer.find(_MARKER)
        if index >= 0:
            if index > _MAX_HEADER_BYTES:
                break
            return _parse_header(buffer[:index]), buffer[index + len(_MARKER) :]
        if len(buffer) > _MAX_HEADER_BYTES:
            break
    raise ArtifactUploadError(400, "Missing artifact header")


async def _write_body(stream, rest: bytes, handle, limit: int):
    digest, size, carry, trailer, closed = hashlib.sha256(), 0, b"", b"", False

    async def chunks():
        yield rest
        async for chunk in stream:
            yield chunk

    async for chunk in chunks():
        if closed:
            trailer += chunk
        else:
            quote = chunk.find(b'"')
            body, tail = (chunk, b"") if quote < 0 else (chunk[:quote], chunk[quote:])
            decoded, carry = _hex_decode(carry + body)
            size += len(decoded)
            if size > limit:
                raise ArtifactUploadError(413, "Artifact exceeds the size limit")
            digest.update(decoded)
            try:
                handle.write(decoded)
            except OSError as exc:
                raise ArtifactUploadError(503, "Artifact storage unavailable") from exc
            closed, trailer = quote >= 0, tail
        if len(trailer) > _MAX_TRAILER_BYTES:
            raise ArtifactUploadError(400, "Unexpected data after artifact")
    if carry or not closed or trailer != b'"}':
        raise ArtifactUploadError(400, "Truncated or malformed artifact body")
    return digest.hexdigest(), size


def _open_temp(target: Path):
    try:
        target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        return tmp, os.fdopen(fd, "wb")
    except OSError as exc:
        raise ArtifactUploadError(503, "Artifact storage unavailable") from exc


def _sync_file(handle) -> None:
    handle.flush()
    os.fsync(handle.fileno())


async def _run_io(func, *args) -> None:
    try:
        await asyncio.to_thread(func, *args)
    except OSError as exc:
        raise ArtifactUploadError(503, "Artifact storage unavailable") from exc


def _published_files(root: Path):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            if not path.is_symlink():
                yield path


def _usage_bytes(root: Path, exclude: Path) -> int:
    total = 0
    for path in _published_files(root):
        if path.name.endswith(".tmp") or path.name == _LOCK_NAME or path == exclude:
            continue
        with suppress(OSError):
            total += path.stat().st_size
    return total


def _publish_within_quota(tmp: Path, target: Path, size: int) -> None:
    """Check the aggregate quota and publish ``tmp`` as one step.

    The lock file serializes concurrent uploads across worker processes, so two
    uploads cannot both pass the check and then jointly exceed the quota.
    """
    root = _root()
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    with open(root / _LOCK_NAME, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        used = _usage_bytes(root, target)
        if used + size > settings.OCR_WORKER_ARTIFACT_TOTAL_MAX_BYTES:
            raise ArtifactUploadError(507, "Artifact storage quota exceeded")
        os.replace(tmp, target)


def cleanup_expired_artifacts() -> int:
    """Delete artifacts older than ``STAGING_RETENTION_SEC`` and stale temp files.

    Nothing reads a stored artifact after ``complete_job`` verified it, so expiry
    only needs to outlast a job's lifetime.
    """
    root = _root()
    if not root.is_dir():
        return 0
    now = datetime.now(UTC).timestamp()
    retention_cutoff = now - settings.STAGING_RETENTION_SEC
    temp_cutoff = now - _TEMP_GRACE_SEC
    removed = 0
    for path in list(_published_files(root)):
        if path.name == _LOCK_NAME:
            continue
        cutoff = temp_cutoff if path.name.endswith(".tmp") else retention_cutoff
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    for dirpath, _dirnames, _filenames in sorted(os.walk(root), reverse=True):
        if Path(dirpath) != root:
            with suppress(OSError):
                Path(dirpath).rmdir()
    return removed


async def receive_artifact(
    stream: AsyncIterable[bytes],
    *,
    validate: Callable[[dict], Awaitable[None]],
) -> dict:
    """Decode a hex-JSON body to disk after ``validate`` accepts its header."""
    iterator = aiter(stream)
    header, rest = await _read_header(iterator)
    await validate(header)
    target = _root() / artifact_key(header["job_id"])
    tmp, handle = _open_temp(target)
    try:
        with handle:
            sha, size = await _write_body(
                iterator, rest, handle, settings.OCR_WORKER_ARTIFACT_MAX_BYTES
            )
            if sha != header["sha256"]:
                raise ArtifactUploadError(422, "Artifact sha256 mismatch")
            await _run_io(_sync_file, handle)
        # The stream can outlive the lease: re-check right before publishing.
        await validate(header)
        await _run_io(_publish_within_quota, tmp, target, size)
    finally:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
    return {
        "job_id": header["job_id"],
        "key": artifact_key(header["job_id"]),
        "sha256": sha,
        "size": size,
    }
