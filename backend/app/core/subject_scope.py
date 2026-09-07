"""Canonical 408 subject catalog and product-scope helpers.

Runtime code intentionally accepts only canonical subject codes. Historical
aliases are handled exclusively by Alembic data migrations; they must never be
reintroduced into request handling, product filtering, or persistence logic.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

EXAM408_ROOT_CODE = "exam408"
EXAM408_CORE_CODES: tuple[str, ...] = (
    "data_structure",
    "computer_organization",
    "operating_system",
    "computer_network",
)
EXAM408_ALL_CODES: tuple[str, ...] = (EXAM408_ROOT_CODE, *EXAM408_CORE_CODES)
EXAM408_FORMULA_SCOPE = EXAM408_ROOT_CODE

EXAM408_DISPLAY_ORDER: dict[str, int] = {
    EXAM408_ROOT_CODE: 0,
    "data_structure": 10,
    "computer_organization": 20,
    "operating_system": 30,
    "computer_network": 40,
}

def canonical_408_code(code: str | None) -> str | None:
    """Return ``code`` only when it is already a canonical 408 code."""
    raw = str(code or "").strip().lower()
    return raw if raw in EXAM408_ALL_CODES else None


def is_408_root(code: str | None) -> bool:
    return canonical_408_code(code) == EXAM408_ROOT_CODE


def is_408_core_subject(code: str | None) -> bool:
    return canonical_408_code(code) in EXAM408_CORE_CODES


def _record_attr(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _record_id(record: Any) -> int | None:
    value = _record_attr(record, "id", _record_attr(record, "subject_id"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _record_parent_id(record: Any) -> int | None:
    value = _record_attr(record, "parent_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _record_product_code(record: Any) -> str | None:
    return canonical_408_code(
        _record_attr(record, "code", _record_attr(record, "subject_code"))
    )


def _record_active(record: Any) -> bool:
    return _record_attr(record, "is_active", True) is not False


def select_408_subject_records(records: Iterable[Any]) -> list[Any]:
    """Select the active canonical 408 subtree.

    A valid product scope requires exactly one canonical ``exam408`` root. No
    fallback by name, suffix, historical alias, or orphan core subject is
    performed. This fail-closed behavior makes stale data immediately visible
    instead of masking it behind compatibility rules.
    """
    items = list(records)
    roots = [
        item for item in items
        if _record_product_code(item) == EXAM408_ROOT_CODE
    ]
    if len(roots) != 1:
        return []

    root = roots[0]
    if not _record_active(root):
        return []
    root_id = _record_id(root)
    if root_id is None:
        return []

    children: dict[int | None, list[Any]] = {}
    for item in items:
        children.setdefault(_record_parent_id(item), []).append(item)

    selected_ids: set[int] = {root_id}
    direct_core: dict[str, Any] = {}
    for child in children.get(root_id, []):
        code = _record_product_code(child)
        if code not in EXAM408_CORE_CODES or not _record_active(child):
            continue
        # Duplicate canonical core rows are invalid; fail closed rather than
        # arbitrarily picking one and hiding a data-integrity problem.
        if code in direct_core:
            return []
        direct_core[code] = child

    def add_active_descendants(parent_id: int) -> None:
        for child in children.get(parent_id, []):
            if not _record_active(child):
                continue
            child_id = _record_id(child)
            if child_id is None:
                continue
            selected_ids.add(child_id)
            add_active_descendants(child_id)

    for code in EXAM408_CORE_CODES:
        branch = direct_core.get(code)
        if branch is None:
            continue
        branch_id = _record_id(branch)
        if branch_id is None:
            continue
        selected_ids.add(branch_id)
        add_active_descendants(branch_id)

    return [
        item for item in items
        if _record_id(item) in selected_ids and _record_active(item)
    ]


def selected_408_subject_ids(records: Iterable[Any]) -> set[int]:
    return {
        rid
        for record in select_408_subject_records(records)
        if (rid := _record_id(record)) is not None
    }
