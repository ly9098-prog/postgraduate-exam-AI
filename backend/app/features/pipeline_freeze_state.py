"""Invocation-local freeze inputs with original-module live global lookup."""

from __future__ import annotations

from builtins import NameError as _NameError
from builtins import UnboundLocalError as _UnboundLocalError
from builtins import __dict__ as _bound_builtins
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FreezeState:
    namespace: dict
    mode: Any
    legacy_result: Any
    legacy_registry: Any
    doc_ir: Any
    ir_result: Any = field(default_factory=dict)
    ir_registry_raw: Any = field(default_factory=dict)
    ir_to_legacy: Any = field(init=False)

    def converter(self) -> Any:
        """Keep the original local-variable failure when no import bound it."""
        if "ir_to_legacy" not in self.__dict__:
            raise _UnboundLocalError(
                "cannot access local variable '_ir_to_legacy' "
                "where it is not associated with a value"
            )
        return self.ir_to_legacy

    def port(self, name: str) -> Any:
        """Match globals then the interpreter builtins bound to the entrypoint."""
        if name in self.namespace:
            return self.namespace[name]
        if name in _bound_builtins:
            return _bound_builtins[name]
        raise _NameError(f"name '{name}' is not defined", name=name)
