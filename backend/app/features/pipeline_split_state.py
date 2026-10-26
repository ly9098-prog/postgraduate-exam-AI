"""Invocation-local split state and live historical namespace lookups."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SplitState:
    pipeline: Any
    normalized_blocks: list[dict]
    structure: dict | None
    keyword_arguments: dict
    strategy: Any = field(init=False)
    gap_tolerance: Any = field(init=False)
    raw_im: Any = field(init=False)
    import_mode_str: Any = field(init=False)
    split_blocks: Any = field(init=False)
    warnings: Any = field(init=False)
    extra_data: Any = field(init=False)
    layout_filter_diagnostics: Any = field(init=False)
    layout_result: Any = field(init=False)
    split_mode: Any = field(init=False)
    frozen_option_registry: Any = field(init=False)
    raw_questions: Any = field(init=False)
    text_blocks: Any = field(init=False)
    split_diagnostics: Any = field(init=False)
    seen_hashes: Any = field(init=False)
    logical_end: Any = field(init=False)


def resolve_split_port(namespace: dict, name: str) -> Any:
    """Resolve at use time against the original orchestrator and its builtins."""
    if name in namespace:
        return namespace[name]
    builtins = namespace["__builtins__"]
    if not isinstance(builtins, dict):
        builtins = vars(builtins)
    if name in builtins:
        return builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)
