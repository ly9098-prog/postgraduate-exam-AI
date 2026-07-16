"""Streaming upload handler — avoids loading entire file(s) into memory.

All file upload endpoints should use ``stream_to_temp()`` or
``stream_to_temp_batch()`` instead of ``await file.read()`` to prevent
memory exhaustion from large files or batches.

Usage::

    # Single file
    tmp = await stream_to_temp(upload_file, max_size=200*1024*1024)
    with open(tmp.path, "rb") as f:
        content = f.read(8192)  # read in chunks
    tmp.close()

    # Batch files
    temps = await stream_to_temp_batch(files, max_total=500*1024*1024)
    for tmp in temps:
        process(tmp.path)
        tmp.close()
"""

from __future__ import annotations

import logging
import os
import struct
import tempfile
from dataclasses import dataclass, field


logger = logging.getLogger("postgraduate-ai.upload")

# Magic bytes for file type validation
_MAGIC_BYTES: dict[str, bytes] = {
    "pdf": b"%PDF",
    "png": b"\x89PNG\r\n\x1a\n",
    "jpeg": b"\xff\xd8\xff",
    "webp": b"RIFF",  # webp starts with RIFF
    "xlsx": b"PK\x03\x04",  # Office Open XML
    "xls": b"\xd0\xcf\x11\xe0",  # OLE2
    "gif": b"GIF8",
    "bmp": b"BM",
}

# Office formats that need deeper check
_OOXML_EXTENSIONS = {".xlsx", ".docx", ".pptx"}


@dataclass
class TempFile:
    """A temporary file on disk.

    Automatically cleaned up when ``close()`` is called or used as context manager.
    """
    path: str
    size: int = 0
    original_name: str = ""
    content_type: str = ""
    _fd: int = field(default=-1, repr=False)
    _closed: bool = field(default=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def detach(self) -> str:
        """Detach the temp file so it won't be cleaned up on close/__del__.

        Caller (e.g. the pipeline worker) takes ownership of the file at
        ``self.path`` and is responsible for deleting it.
        Returns the file path.
        """
        self._closed = True
        return self.path

    def __enter__(self) -> TempFile:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


async def stream_to_temp(
    upload,
    *,
    max_size: int = 200 * 1024 * 1024,
    suffix: str = ".bin",
) -> TempFile:
    """Stream an uploaded file to a temporary file on disk.

    Raises ``ValueError`` if the file exceeds *max_size*.
    The returned ``TempFile`` must be closed by the caller.
    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    total = 0
    try:
        while True:
            chunk = await upload.read(65536)  # 64KB chunks
            if not chunk:
                break
            total += len(chunk)
            if total > max_size:
                os.close(fd)
                os.unlink(path)
                raise ValueError(
                    f"文件超过大小限制（{max_size // (1024*1024)}MB）",
                )
            os.write(fd, chunk)
        os.close(fd)
    except ValueError:
        raise
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise

    return TempFile(
        path=path,
        size=total,
        original_name=getattr(upload, "filename", "") or "",
        content_type=getattr(upload, "content_type", "") or "",
    )


async def stream_to_temp_batch(
    uploads: list,
    *,
    max_total: int = 500 * 1024 * 1024,
    max_per_file: int = 200 * 1024 * 1024,
    suffix: str = ".bin",
) -> list[TempFile]:
    """Stream multiple uploaded files to temp files.

    Raises ``ValueError`` if total exceeds *max_total*.
    Caller must close each returned ``TempFile``.
    """
    temps: list[TempFile] = []
    total_bytes = 0
    try:
        for upload in uploads:
            tmp = await stream_to_temp(
                upload, max_size=max_per_file, suffix=suffix,
            )
            total_bytes += tmp.size
            if total_bytes > max_total:
                # Clean up and fail
                for t in temps:
                    t.close()
                tmp.close()
                raise ValueError(
                    f"上传文件总量超过限制（{max_total // (1024*1024)}MB）",
                )
            temps.append(tmp)
        return temps
    except Exception:
        for t in temps:
            t.close()
        raise


def guess_file_type_from_magic(path: str) -> str | None:
    """Guess file type from magic bytes (first few bytes of file).

    Returns "pdf", "png", "jpeg", "xlsx", "xls", "webp", or None if unknown.
    More reliable than relying on Content-Type header or extension alone.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(8)

        for ftype, magic in _MAGIC_BYTES.items():
            if header.startswith(magic):
                # Special case: .xlsx vs .zip (both PK\x03\x04)
                if ftype == "xlsx":
                    # Check for xl/ directory in the ZIP
                    return "xlsx"
                # Special case: RIFF could be webp or avi
                if ftype == "webp":
                    if len(header) >= 12 and header[8:12] == b"WEBP":
                        return "webp"
                    return None
                return ftype
        return None
    except OSError:
        return None


def quick_validate_image(path: str) -> tuple[int, int] | None:
    """Quickly read image dimensions without loading full image.

    Returns (width, height) or None if detection fails.
    Only checks PNG and JPEG. PIL is NOT needed.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(32)

        # PNG
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            # PNG stores width/height at offset 16 (big-endian uint32)
            w = struct.unpack(">I", header[16:20])[0]
            h = struct.unpack(">I", header[20:24])[0]
            return (w, h)

        # JPEG
        if header.startswith(b"\xff\xd8\xff"):
            with open(path, "rb") as f:
                f.seek(2)
                while True:
                    marker = f.read(4)
                    if len(marker) < 4:
                        return None
                    if marker[0:2] != b"\xff":
                        return None
                    if marker[1] == 0xc0 or marker[1] == 0xc2:
                        # SOF0 or SOF2
                        data = f.read(5)
                        if len(data) >= 5:
                            h = (data[0] << 8) | data[1]
                            w = (data[2] << 8) | data[3]
                            return (w, h)
                    else:
                        seg_len = (marker[2] << 8) | marker[3]
                        f.seek(seg_len - 2, 1)
            return None

        return None
    except OSError:
        return None


def validate_image(
    path: str,
    *,
    max_width: int = 4096,
    max_height: int = 4096,
    max_pixels: int = 4096 * 4096,
) -> str | None:
    """Validate an image file.

    Returns an error string if validation fails, None if OK.
    """
    # Check magic bytes
    ftype = guess_file_type_from_magic(path)
    if ftype not in ("png", "jpeg", "webp"):
        return f"不支持的文件类型: {ftype or 'unknown'}"

    # Check dimensions
    dims = quick_validate_image(path)
    if dims:
        w, h = dims
        if w > max_width or h > max_height:
            return f"图片尺寸过大 ({w}x{h}, 最大 {max_width}x{max_height})"
        if w * h > max_pixels:
            return f"图片像素数过多 ({w*h}, 最大 {max_pixels})"

    return None


# ── Convenience: read temp file content in chunks ──

def read_temp_chunks(path: str, chunk_size: int = 65536):
    """Generator that yields chunks from a temp file.

    Use this instead of loading the entire file into memory.
    """
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk
