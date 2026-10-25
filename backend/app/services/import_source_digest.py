"""Best-effort source digest for import resume identity checks."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)
_READ_CHUNK_SIZE = 1024 * 1024


@dataclass(slots=True)
class SourceDigestRequest:
    pipeline_id: str
    file_path: str
    provided_sha256: str | None
    open_file: Callable[..., object]
    logger: logging.Logger


def resolve_source_digest(request: SourceDigestRequest) -> str | None:
    """Return the supplied digest, or hash the staged file best-effort."""
    if request.provided_sha256 is not None:
        return request.provided_sha256
    try:
        hasher = hashlib.sha256()
        with request.open_file(request.file_path, "rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(_READ_CHUNK_SIZE), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        request.logger.exception(
            "compute source_sha256 failed for pipeline %s; "
            "resume identity check will be skipped",
            request.pipeline_id,
        )
        return None


def default_open_file(path: str, mode: str):
    return Path(path).open(mode)
