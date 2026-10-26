"""Invocation-local correction state and historical namespace lookups."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RouterStageState:
    pipeline: Any
    normalized_blocks: list[dict]
    options: dict
    db: Any
    keyword_arguments: dict
    router_config: Any = field(init=False)
    router: Any = field(init=False)
    page_images: Any = field(init=False)
    metrics: Any = field(init=False)
    corrections: Any = field(init=False)
    corrected_blocks: Any = field(init=False)
    stats: Any = field(init=False)
    quality_gate_shadow_records: Any = field(init=False)
    model_call_totals: Any = field(init=False)
    to_correct: Any = field(init=False)
    fix_results: Any = field(init=False)


@dataclass
class RouterCandidate:
    idx: int
    block: dict
    text: str
    noise_score: float
    structure_score: float
    fix_result: Any
    accepted: Any = field(init=False)
    diff: Any = field(init=False)
    evaluation: Any = field(init=False)
    is_vl: Any = field(init=False)
    new_block: Any = field(init=False)
    reason_code: Any = field(init=False)
    result: Any = field(init=False)
    risk_flags: Any = field(init=False)
    safe_text: Any = field(init=False)
    safety_dict: Any = field(init=False)


def resolve_router_port(namespace: dict, name: str) -> Any:
    """Resolve original globals and builtins only when their expression executes."""
    if name in namespace:
        return namespace[name]
    builtins = namespace["__builtins__"]
    if not isinstance(builtins, dict):
        builtins = vars(builtins)
    if name in builtins:
        return builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)
