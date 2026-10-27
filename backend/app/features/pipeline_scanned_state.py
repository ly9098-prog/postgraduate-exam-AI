"""Invocation-local scanned PDF state with the entrypoint's live namespace."""

from __future__ import annotations

from builtins import NameError as _NameError
from builtins import __dict__ as _bound_builtins
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScannedPdfState:
    namespace: dict
    content_or_path: bytes | str
    pipeline_id: str
    page_start: int
    page_end: int | None
    gc: Any = field(init=False)
    time: Any = field(init=False)
    ocr_pages: Any = field(init=False)
    ocr_pages_with_boxes: Any = field(init=False)
    profile: Any = field(init=False)
    max_pages: Any = field(init=False)
    timeout: Any = field(init=False)
    batch_size: Any = field(init=False)
    doc: Any = field(init=False)
    total_pages: Any = field(init=False)
    start_idx: Any = field(init=False)
    end_idx: Any = field(init=False)
    pages_in_range: Any = field(init=False)
    pages_to_process: Any = field(init=False)
    blocks: Any = field(init=False)
    page_dimensions: Any = field(init=False)
    ocr_text_fallback_unavailable_pages: Any = field(init=False)
    timed_out: Any = field(init=False)
    start_time: Any = field(init=False)
    progress_started: bool = False

    def port(self, name: str) -> Any:
        if name in self.namespace:
            return self.namespace[name]
        if name in _bound_builtins:
            return _bound_builtins[name]
        raise _NameError(f"name '{name}' is not defined", name=name)
