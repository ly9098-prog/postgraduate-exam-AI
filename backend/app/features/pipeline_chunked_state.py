"""Invocation-local chunked state and original-module global lookup."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChunkedRunState:
    values: dict
    namespace: dict
    _chunked_logger: Any = field(init=False)
    _chunked_start: Any = field(init=False)
    agg_stats: Any = field(init=False)
    any_chunk_failed: Any = field(init=False)
    chunk_overlap: Any = field(init=False)
    chunk_results: Any = field(init=False)
    chunk_size: Any = field(init=False)
    finished_at: Any = field(init=False)
    first_batch_id: Any = field(init=False)
    hash_index: Any = field(init=False)
    overall_status: Any = field(init=False)
    pipeline_errors: Any = field(init=False)
    risk_flag_counts: Any = field(init=False)
    seen_hashes: Any = field(init=False)
    session_factory: Any = field(init=False)
    shared: Any = field(init=False)
    total_pages: Any = field(init=False)
    watermark_snapshot: Any = field(init=False)

    def port(self, name: str) -> Any:
        """Resolve the original global or builtin at each expression site."""
        if name in self.namespace:
            return self.namespace[name]
        builtins = self.namespace["__builtins__"]
        if not isinstance(builtins, dict):
            builtins = vars(builtins)
        if name in builtins:
            return builtins[name]
        raise NameError(f"name '{name}' is not defined", name=name)
