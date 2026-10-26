"""Invocation-local single-pass inputs, state and original namespace lookups."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SinglePassRequest:
    file_content: bytes | None
    file_path: str | None
    source_type: str
    source_file: str
    subject: str | None
    subject_id: int | None
    opts: dict
    db: Any
    shared: dict
    progress_callback: Any
    started_at: str
    page_start: int | None
    page_end: int | None
    chunk_seen_hashes: set | None
    chunk_logical_end: int | None
    page_images: dict[int, bytes] | None
    page_image_refs: dict[int, str] | None
    pre_extracted_blocks: list[dict] | None
    resume_from_checkpoint: dict | None


@dataclass
class SinglePassState:
    pipeline: Any
    request: SinglePassRequest
    options: Any = field(init=False)
    pass_logger: Any = field(init=False)
    started_clock: Any = field(init=False)
    vision_config: Any = field(init=False)
    data: Any = field(init=False)
    errors: Any = field(init=False)
    status: Any = field(init=False)
    chunked: Any = field(init=False)
    completed_stages: Any = field(init=False)
    has_resume: Any = field(init=False)
    artifact_skipped: Any = field(init=False)
    current_name: Any = field(init=False)
    current_stage: Any = field(init=False)
    result: Any = field(init=False)
    stats: Any = field(init=False)
    diagnostics: Any = field(init=False)
    finished_at: Any = field(init=False)
    quality_report: Any = field(init=False)
    perf_profile: Any = field(init=False)
    routing_metrics: Any = field(init=False)
    split_quality: Any = field(init=False)
    artifacts_list: Any = field(init=False)


def resolve_pass_port(namespace: dict, name: str) -> Any:
    """Resolve original globals and builtin overrides at their expression sites."""
    if name in namespace:
        return namespace[name]
    builtins = namespace["__builtins__"]
    if not isinstance(builtins, dict):
        builtins = vars(builtins)
    if name in builtins:
        return builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)
