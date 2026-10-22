"""Create the durable owner row before an import task enters the queue."""

import hashlib
from pathlib import Path

from app.core.database import async_session
from app.features.pipeline_checkpoint import ensure_pipeline_record
from app.services.import_upload_request import UploadRequest


def _hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def admit_pipeline_record(
    request: UploadRequest,
    *,
    pipeline_id: str,
    source_type: str,
    chunk_size: int,
) -> str | None:
    """Persist ownership/status and return the source digest when available.

    The record is deliberately created before enqueueing because the durable
    worker takes a DB fence on it before dispatching any import handler.
    """
    source_sha256 = request.source_sha256
    if source_sha256 is None and Path(request.file_path).is_file():
        source_sha256 = _hash_file(request.file_path)

    async with async_session() as db:
        await ensure_pipeline_record(
            db,
            pipeline_id=pipeline_id,
            source_type=source_type,
            source_file=request.filename or None,
            total_pages=None,
            chunk_size=chunk_size,
            created_by=request.created_by,
            source_sha256=source_sha256,
            status="queued",
        )
    return source_sha256
