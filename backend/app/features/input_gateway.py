"""Input Gateway — Unified input entry for the OCR pipeline.

Provides:
- InputDocument: Standardised input model for all subsequent stages.
- InputGateway: Creates InputDocument from ImportRequest, persists to local path,
  delegates safety validation, and produces the canonical input handle.

All downstream stages read from the persisted local_path. Large byte blobs
are NOT carried through the pipeline context.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input type detection
# ---------------------------------------------------------------------------

EXTENSION_TO_SOURCE_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".txt": "txt",
    ".xlsx": "excel",
    ".xls": "excel",
}

MIME_TO_SOURCE_TYPE: dict[str, str] = {
    "application/pdf": "pdf",
    "image/png": "image",
    "image/jpeg": "image",
    "image/tiff": "image",
    "image/bmp": "image",
    "text/plain": "txt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    "application/vnd.ms-excel": "excel",
}


def detect_source_type(filename: str = "", mime: str = "") -> str:
    """Detect source type from filename extension or MIME type."""
    if filename:
        ext = Path(filename).suffix.lower()
        st = EXTENSION_TO_SOURCE_TYPE.get(ext)
        if st:
            return st
    if mime:
        st = MIME_TO_SOURCE_TYPE.get(mime)
        if st:
            return st
    return "unknown"


# ---------------------------------------------------------------------------
# InputDocument
# ---------------------------------------------------------------------------


@dataclass
class InputDocument:
    """Canonical input document representation.

    All subsequent pipeline stages read from ``local_path``.
    The original bytes are persisted at input time and NOT carried in context.
    """
    source_type: str = ""
    mime_type: str = ""
    filename: str = ""
    sha256: str = ""
    size_bytes: int = 0
    local_path: str = ""
    page_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# InputGateway
# ---------------------------------------------------------------------------

_INPUT_STORAGE_ROOT = os.environ.get(
    "INPUT_STORAGE_ROOT",
    os.path.join(tempfile.gettempdir(), "pipeline_inputs"),
)


class InputGateway:
    """Unified input entry point.

    Creates an InputDocument from source bytes, persists to local storage,
    validates safety, and returns the canonical handle.

    Usage::

        gateway = InputGateway()
        doc = await gateway.accept(source_bytes, filename="test.pdf")
        # doc.local_path points to the persisted file
    """

    def __init__(self, storage_root: str = "") -> None:
        self._storage_root = storage_root or _INPUT_STORAGE_ROOT

    def accept(
        self,
        source: bytes,
        *,
        filename: str = "",
        mime: str = "",
        page_count: int | None = None,
    ) -> InputDocument:
        """Accept source bytes, persist to local storage, return InputDocument.

        Steps:
        1. Compute SHA256
        2. Detect source type
        3. Persist to local storage
        4. Return InputDocument handle

        Does NOT validate safety — call InputSafetyValidator separately.
        """
        sha256 = hashlib.sha256(source).hexdigest()
        source_type = detect_source_type(filename, mime)

        # Determine MIME type
        resolved_mime = mime
        if not resolved_mime:
            mime_map = {
                "pdf": "application/pdf",
                "image": "image/png",
                "txt": "text/plain",
                "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
            resolved_mime = mime_map.get(source_type, "application/octet-stream")

        # Persist to local storage (subdirectory by sha256 prefix)
        subdir = os.path.join(self._storage_root, sha256[:4])
        os.makedirs(subdir, exist_ok=True)

        ext_map = {
            "pdf": ".pdf", "image": ".png", "txt": ".txt", "excel": ".xlsx",
        }
        ext = ext_map.get(source_type, ".bin")
        local_path = os.path.join(subdir, f"{sha256}{ext}")

        if not os.path.exists(local_path):
            with open(local_path, "wb") as f:
                f.write(source)
            logger.info("Persisted input to %s (%d bytes)", local_path, len(source))

        return InputDocument(
            source_type=source_type,
            mime_type=resolved_mime,
            filename=filename or sha256[:12],
            sha256=sha256,
            size_bytes=len(source),
            local_path=local_path,
            page_count=page_count,
        )

    def read_source(self, doc: InputDocument) -> bytes:
        """Read source bytes from persisted local_path."""
        with open(doc.local_path, "rb") as f:
            return f.read()
