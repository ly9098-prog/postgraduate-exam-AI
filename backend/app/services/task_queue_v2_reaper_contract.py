"""Normalize v2 reaper results without owning Redis state transitions."""

from __future__ import annotations

from typing import Any


def normalize_v2_reaper_result(result: Any) -> int:
    """Preserve the historical nil-to-zero and integer reaper result."""
    if result is None:
        return 0
    return int(result)


def apply_v2_reaper_result(reclaimed: int) -> bool:
    """Return whether a positive reclaim count should be logged and counted."""
    return reclaimed > 0


def normalize_v1_reaper_result(result: Any) -> int:
    """Preserve the historical nil-to-zero and integer v1 reaper result."""
    if result is None:
        return 0
    return int(result)


def apply_v1_reaper_result(reclaimed: int) -> bool:
    """Return whether a positive v1 reclaim count should be logged and counted."""
    return reclaimed > 0
