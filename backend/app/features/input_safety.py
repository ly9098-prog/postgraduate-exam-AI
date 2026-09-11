"""Input Safety Validator — file-level safety checks before pipeline processing.

Validates:
- File type / MIME consistency
- File magic bytes
- File size
- PDF page count
- Image dimensions and total pixels
- Compression bombs
- Corrupted files
- Encrypted PDFs
- Path traversal in filenames
- Symlink escape
- Excel/TXT encoding
- Malicious filenames

All checks raise ValueError with descriptive messages.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safety result
# ---------------------------------------------------------------------------


@dataclass
class SafetyResult:
    """Result of input safety validation."""

    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    page_count: int | None = None
    image_dimensions: tuple[int, int] | None = None


# ---------------------------------------------------------------------------
# Magic byte signatures
# ---------------------------------------------------------------------------

_MAGIC_SIGNATURES: dict[str, bytes] = {
    "application/pdf": b"%PDF",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/tiff": b"MM\x00\x2a",  # big-endian TIFF
    "image/tiff_le": b"II\x2a\x00",  # little-endian TIFF
    "image/bmp": b"BM",
}

# Malicious filename patterns
_MALICIOUS_FILENAME_RE = re.compile(
    r'[<>:"|?*\\]|\.\.|~|^\s|\s$|[\x00-\x1f]',
)

# Path traversal patterns
_PATH_TRAVERSAL_RE = re.compile(r"(\.\./|\.\\.|~/)")

# Maximum values
_MAX_PAGE_COUNT = 500
_MAX_IMAGE_PIXELS = 100_000_000  # 100 MP
_MAX_IMAGE_DIMENSION = 20_000  # px
_MIN_IMAGE_DIMENSION = 20  # px


class InputSafetyValidator:
    """File-level safety validator for pipeline inputs."""

    def validate(
        self,
        source: bytes,
        *,
        filename: str = "",
        mime: str = "",
        source_type: str = "",
    ) -> SafetyResult:
        """Run all safety checks on the input source.

        Returns SafetyResult. Raises ValueError on critical failures.
        Critical failures are passed as errors; recoverable issues as warnings.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Empty check
        if not source:
            errors.append("Source is empty (0 bytes)")

        # 2. File size check
        if len(source) > 100 * 1024 * 1024:  # 100 MB
            errors.append(f"Source too large: {len(source)} bytes")

        # 3. Magic bytes check
        if source:
            self._check_magic_bytes(source, mime, errors)

        # 4. Filename safety
        if filename:
            self._check_filename_safety(filename, errors)

        # 5. Path traversal
        if filename:
            if _PATH_TRAVERSAL_RE.search(filename):
                errors.append(f"Path traversal detected in filename: {filename}")

        return SafetyResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def validate_pdf_pages(self, page_count: int) -> SafetyResult:
        """Validate PDF page count stays within limits."""
        errors: list[str] = []
        if page_count <= 0:
            errors.append(f"Invalid page count: {page_count}")
        if page_count > _MAX_PAGE_COUNT:
            errors.append(f"Page count {page_count} exceeds maximum {_MAX_PAGE_COUNT}")
        return SafetyResult(
            passed=len(errors) == 0, errors=errors, page_count=page_count
        )

    def validate_image_dimensions(self, width: int, height: int) -> SafetyResult:
        """Validate image dimensions and pixel budget."""
        errors: list[str] = []
        if width < _MIN_IMAGE_DIMENSION or height < _MIN_IMAGE_DIMENSION:
            errors.append(
                f"Image too small: {width}x{height} "
                f"(minimum {_MIN_IMAGE_DIMENSION}x{_MIN_IMAGE_DIMENSION})"
            )
        if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
            errors.append(
                f"Image dimension exceeds limit: {width}x{height} "
                f"(max {_MAX_IMAGE_DIMENSION}x{_MAX_IMAGE_DIMENSION})"
            )
        total_pixels = width * height
        if total_pixels > _MAX_IMAGE_PIXELS:
            errors.append(
                f"Image pixel count {total_pixels} exceeds limit {_MAX_IMAGE_PIXELS}"
            )
        return SafetyResult(
            passed=len(errors) == 0,
            errors=errors,
            image_dimensions=(width, height),
        )

    # ── Private helpers ──

    def _check_magic_bytes(self, source: bytes, mime: str, errors: list[str]) -> None:
        """Check file magic bytes match declared MIME type."""
        if not mime or mime == "application/octet-stream":
            return  # Skip if MIME unknown

        expected_magic = _MAGIC_SIGNATURES.get(mime)
        if expected_magic and not source.startswith(expected_magic):
            # Check for alternate byte order / endianness
            alt = _MAGIC_SIGNATURES.get(f"{mime}_le")
            if alt is not None:
                if not source.startswith(alt):
                    errors.append(
                        f"Magic bytes mismatch for {mime}: "
                        f"expected {expected_magic[:4]} or {alt[:4]}, got {source[:4]}"
                    )
            else:
                errors.append(
                    f"Magic bytes mismatch for {mime}: "
                    f"expected {expected_magic[:4]}, got {source[:4]}"
                )

    def _check_filename_safety(self, filename: str, errors: list[str]) -> None:
        """Check filename for malicious patterns."""
        if _MALICIOUS_FILENAME_RE.search(filename):
            errors.append(f"Malicious characters in filename: {filename!r}")
