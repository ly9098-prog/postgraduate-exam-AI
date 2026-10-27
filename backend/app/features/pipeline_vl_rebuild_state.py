"""Invocation-local VL rebuild state and original-module global lookup."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VlRebuildState:
    values: dict
    namespace: dict
    _is_cloud_vl: Any = field(init=False)
    api_token: Any = field(init=False)
    base_url: Any = field(init=False)
    best_text: Any = field(init=False)
    is_image: Any = field(init=False)
    is_pdf: Any = field(init=False)
    model: Any = field(init=False)
    new_blocks: Any = field(init=False)
    page_batches: Any = field(init=False)
    page_dim: Any = field(init=False)
    page_table_blocks: Any = field(init=False)
    pp_opt_count: Any = field(init=False)
    pp_text: Any = field(init=False)
    router: Any = field(init=False)
    detect_options_from_text: Any = field(init=False)
    extract_options_from_text: Any = field(init=False)
    repair_option_structure: Any = field(init=False)

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
