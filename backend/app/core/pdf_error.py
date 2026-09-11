"""PDF resource limit errors — structured, no HTTP dependency.

Core renderer raises these; API error mappers and worker failure handlers
translate to the appropriate HTTP status or task outcome.
"""

from __future__ import annotations


class PdfResourceLimitError(RuntimeError):
    """Resource limit exceeded during PDF processing.

    Attributes:
        code: Machine-readable error code (see ERROR_CODES).
        retryable: Whether the operation may succeed if retried later.
        details: Arbitrary metadata (page number, actual size, limit, etc.).
    """

    ERROR_CODES = frozenset(
        {
            "file_too_large",
            "too_many_pages",
            "page_pixel_limit",
            "decoded_memory_limit",
            "renderer_queue_full",
            "staging_quota_exceeded",
            "pipeline_timeout",
        }
    )

    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        details: dict | None = None,
    ) -> None:
        if code not in self.ERROR_CODES:
            raise ValueError(f"Unknown PDF error code: {code!r}")
        self.code = code
        self.retryable = retryable
        self.details = details or {}
        super().__init__(f"[{code}] {self._format_message()}")

    def _format_message(self) -> str:
        return self.details.get("message", self.code.replace("_", " "))
