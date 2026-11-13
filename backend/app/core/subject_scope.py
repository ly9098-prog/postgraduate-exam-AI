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
    roots = [item for item in items if _record_product_code(item) == EXAM408_ROOT_CODE]
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
        item
        for item in items
        if _record_id(item) in selected_ids and _record_active(item)
    ]


def selected_408_subject_ids(records: Iterable[Any]) -> set[int]:
    return {
        rid
        for record in select_408_subject_records(records)
        if (rid := _record_id(record)) is not None
    }


# Additional study subjects that should be available in the student-facing
# selectors alongside the computer-science catalog.  Historical databases may
# still use older canonical codes for these rows, so matching intentionally
# accepts the known code variants and the stable Chinese display names.
EXTRA_STUDY_SUBJECT_CODES: frozenset[str] = frozenset(
    {
        "advanced_math",
        "math2-calculus",
        "linear_algebra",
        "math2-linalg",
        "english",
        "politics",
        "pol",
    }
)
EXTRA_STUDY_PARENT_CODES: frozenset[str] = frozenset({"math", "math2"})
EXTRA_STUDY_SUBJECT_NAMES: frozenset[str] = frozenset(
    {
        "高等数学",
        "高数",
        "线性代数",
        "线代",
        "英语",
        "政治",
    }
)


def _raw_record_code(record: Any) -> str:
    return (
        str(
            _record_attr(record, "code", _record_attr(record, "subject_code", "")) or ""
        )
        .strip()
        .lower()
    )


def _raw_record_name(record: Any) -> str:
    return str(
        _record_attr(
            record,
            "name",
            _record_attr(
                record, "subject_name", _record_attr(record, "display_name", "")
            ),
        )
        or ""
    ).strip()


def is_extra_study_subject(record: Any) -> bool:
    return (
        _raw_record_code(record) in EXTRA_STUDY_SUBJECT_CODES
        or _raw_record_name(record) in EXTRA_STUDY_SUBJECT_NAMES
    )


def is_extra_study_parent(record: Any) -> bool:
    return _raw_record_code(record) in EXTRA_STUDY_PARENT_CODES


def is_study_subject_enabled(record: Any) -> bool:
    """Require an active subject within the supported study catalog."""
    return _record_active(record) and bool(
        canonical_408_code(_raw_record_code(record))
        or is_extra_study_subject(record)
        or is_extra_study_parent(record)
    )


def select_study_subject_records(records: Iterable[Any]) -> list[Any]:
    """Select the computer-science tree plus 高数/线代/英语/政治.

    Retain active ancestors of math leaves for tree grouping. Disabled or
    invalid ancestor chains make the entire branch unavailable.
    """
    items = list(records)
    selected_ids = {
        rid
        for record in select_408_subject_records(items)
        if (rid := _record_id(record)) is not None
    }

    by_id = {rid: record for record in items if (rid := _record_id(record)) is not None}
    for record in items:
        if not is_extra_study_subject(record) or not is_study_subject_enabled(record):
            continue
        rid = _record_id(record)
        if rid is None:
            continue
        branch_ids = {rid}
        parent_id = _record_parent_id(record)
        while parent_id is not None:
            parent = by_id.get(parent_id)
            if (
                parent_id in branch_ids
                or parent is None
                or not _record_active(parent)
            ):
                break
            branch_ids.add(parent_id)
            parent_id = _record_parent_id(parent)
        else:
            selected_ids.update(branch_ids)

    return [
        record
        for record in items
        if _record_id(record) in selected_ids and is_study_subject_enabled(record)
    ]


def selected_study_subject_ids(records: Iterable[Any]) -> set[int]:
    return {
        rid
        for record in select_study_subject_records(records)
        if (rid := _record_id(record)) is not None
    }


def study_subject_display_name(value: str | None) -> str:
    """Remove the old product number from subject labels shown in the mini app."""
    text = str(value or "").replace("408", "").strip()
    return text or "计算机综合"
