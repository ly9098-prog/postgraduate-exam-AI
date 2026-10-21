"""Own standalone role resources without mixing OCR and task lifetimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.runtime_ocr_startup import HttpOcrResources

if TYPE_CHECKING:
    from app.core.runtime_task_registry import TaskRegistry


@dataclass
class StandaloneRuntimeResources:
    role: str
    registry: TaskRegistry = field(default_factory=lambda: _new_task_registry())
    ocr: HttpOcrResources = field(default_factory=HttpOcrResources)


def _new_task_registry() -> TaskRegistry:
    from app.core import runtime_task_registry

    return runtime_task_registry.TaskRegistry()
