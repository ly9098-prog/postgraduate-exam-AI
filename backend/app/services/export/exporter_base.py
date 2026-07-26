"""Abstract exporter interface — allows future DOCX exporters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ExportResult:
    """Result of an export operation."""
    success: bool
    file_bytes: bytes | None = None
    file_name: str = ""
    error_message: str | None = None
    skip_count: int = 0
    skip_reasons: dict | None = None


class Exporter(ABC):
    """Base class for document exporters (PDF, future DOCX)."""

    @abstractmethod
    async def export(self, snapshot_data: dict, output_dir: str) -> ExportResult:
        """Generate the export document from snapshot data.

        Args:
            snapshot_data: The full snapshot dict with questions + config.
            output_dir: Temporary directory for intermediate files.

        Returns:
            ExportResult with the generated file bytes.
        """
        ...

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Human-readable format name (e.g., 'PDF', 'DOCX')."""
        ...
