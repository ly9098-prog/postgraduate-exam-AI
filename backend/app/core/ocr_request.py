"""OCRRequest — 统一的 OCR Adapter 输入契约。

替代 ``source: bytes | str`` 的裸参数传递，强制要求调用方明确提供
source_type、mime、页范围和安全限制。

规则：
- source 必须为 bytes（不允许将任意字符串默认解释为路径或 URL）
- page_start >= 1, page_end > page_start
- source 非空，大小不超过 max_bytes
- 构造时自动计算 source_sha256
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Supported source types and MIME types
# ---------------------------------------------------------------------------

SUPPORTED_SOURCE_TYPES: frozenset[str] = frozenset({"pdf", "png", "jpeg", "jpg", "tiff", "bmp"})
SUPPORTED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "image/bmp",
})

MIME_FROM_TYPE: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "tiff": "image/tiff",
    "bmp": "image/bmp",
}

DEFAULT_MAX_PAGES = 200
DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB


@dataclass
class OCRRequest:
    """OCR 适配器输入请求。

    Args:
        source: 文档二进制内容（必须为 bytes，不接受字符串路径）
        source_type: "pdf" | "png" | "jpeg" | "tiff" | "bmp"
        mime: MIME type，未指定时从 source_type 推断
        filename: 原始文件名（可选，用于日志和追踪）
        page_start: 起始页码（1-based），默认 1
        page_end: 结束页码（含），默认 None = 全部
        client_hash: 调用方提供的去重 hash（可选）
        max_pages: 硬限制，默认 200
        max_bytes: 硬限制，默认 100 MB

    Raises:
        ValueError: 输入无效时（空数据、超限、不支持的 type）
    """
    source: bytes
    source_type: str
    mime: str = ""
    filename: str = ""
    source_sha256: str = field(default="", init=False)  # computed in __post_init__
    page_start: int = 1
    page_end: int | None = None
    client_hash: str = ""
    max_pages: int = DEFAULT_MAX_PAGES
    max_bytes: int = DEFAULT_MAX_BYTES

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        """Validate all fields and compute source_sha256."""
        # Source must be non-empty bytes
        if not isinstance(self.source, bytes):
            raise ValueError(
                f"OCRRequest.source must be bytes, got {type(self.source).__name__}"
            )
        if len(self.source) == 0:
            raise ValueError("OCRRequest.source must not be empty")

        # Size limit
        if len(self.source) > self.max_bytes:
            mb = self.max_bytes / (1024 * 1024)
            raise ValueError(
                f"OCRRequest.source exceeds max_bytes ({mb:.0f} MB): "
                f"{len(self.source)} bytes"
            )

        # Source type validation
        if self.source_type not in SUPPORTED_SOURCE_TYPES:
            raise ValueError(
                f"OCRRequest.source_type must be one of {sorted(SUPPORTED_SOURCE_TYPES)}, "
                f"got '{self.source_type}'"
            )

        # MIME type
        if not self.mime:
            object.__setattr__(self, "mime", MIME_FROM_TYPE.get(self.source_type, "application/octet-stream"))
        elif self.mime not in SUPPORTED_MIME_TYPES:
            raise ValueError(
                f"OCRRequest.mime must be one of {sorted(SUPPORTED_MIME_TYPES)}, "
                f"got '{self.mime}'"
            )

        # Page range validation
        if self.page_start < 1:
            raise ValueError(f"OCRRequest.page_start must be >= 1, got {self.page_start}")
        if self.page_end is not None and self.page_end < self.page_start:
            raise ValueError(
                f"OCRRequest.page_end ({self.page_end}) must be >= page_start ({self.page_start})"
            )

        # Max pages limit
        if self.page_end is not None:
            pages = self.page_end - self.page_start + 1
            if pages > self.max_pages:
                raise ValueError(
                    f"OCRRequest page range ({pages} pages) exceeds max_pages ({self.max_pages})"
                )

        # Compute source SHA256
        object.__setattr__(self, "source_sha256", hashlib.sha256(self.source).hexdigest())

    def estimated_pages(self) -> int:
        """Return the number of pages in the requested range."""
        if self.source_type != "pdf":
            return 1  # images are single-page
        if self.page_end is not None:
            return self.page_end - self.page_start + 1
        return self.max_pages  # unknown PDF, return limit

    def describe(self) -> str:
        """Human-readable description for logging."""
        sha = self.source_sha256[:12] if self.source_sha256 else "?"
        pages = f"p{self.page_start}"
        if self.page_end is not None:
            pages += f"-{self.page_end}"
        return f"{self.source_type}({sha}) {pages} {self.filename or ''}"
