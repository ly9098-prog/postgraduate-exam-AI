"""Pipeline stage modules — extracted business logic from pipeline_orchestrator.py.

Each stage module exposes an async ``run_<stage>_stage`` function that accepts
a pipeline context + stage-specific data and returns the stage result dict.

The ``PipelineStageContext`` dataclass bundles shared pipeline metadata that
multiple stages need (pipeline_id, options, diagnostics accumulator, etc.).

Design principles:
1. Stage files own the business logic; orchestrator owns the lifecycle.
2. No stage file imports from pipeline_orchestrator.py.
3. Each function signature is explicit about what data it needs.
4. No global state mutation inside stage functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineStageContext:
    """Lightweight shared context passed through pipeline stages.

    Not all fields are used by all stages — each stage pulls what it needs.
    """

    pipeline_id: str
    options: dict
    diagnostics: dict = field(default_factory=dict)
    db: Any = None
    page_image_refs: dict[int, str] | None = None
    page_images: dict[int, bytes] | None = None
    source_type: str = ""
    source_file: str = ""
    subject: str | None = None
    import_mode: Any = None
    strategy: dict | None = None
    watermark_patterns: list | None = None


__all__ = [
    "PipelineStageContext",
]
