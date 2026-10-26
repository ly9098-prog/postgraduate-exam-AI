"""Invocation-local resume state and original-module global lookup."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResumeRunState:
    values: dict
    namespace: dict
    all_chunks: Any = field(init=False)
    any_chunk_failed: Any = field(init=False)
    chunk_overlap: Any = field(init=False)
    chunk_results: Any = field(init=False)
    completed_batch_ids: Any = field(init=False)
    hash_index: Any = field(init=False)
    import_mode: Any = field(init=False)
    max_chunk_index: Any = field(init=False)
    mode_str: Any = field(init=False)
    opts: Any = field(init=False)
    pending: Any = field(init=False)
    pipeline: Any = field(init=False)
    pipeline_row: Any = field(init=False)
    session_factory: Any = field(init=False)
    shared: Any = field(init=False)
    snapshot: Any = field(init=False)
    started_at: Any = field(init=False)
    strategy: Any = field(init=False)
    total_pages: Any = field(init=False)
    watermark_patterns: Any = field(init=False)

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
