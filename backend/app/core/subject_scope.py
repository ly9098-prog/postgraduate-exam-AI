"""Product-level subject scope helpers.

The subjects table remains the source of truth for subject IDs.  This module only
normalizes the historical code aliases used by MemoGrad so product surfaces can
consistently identify the 408 root and its four core disciplines without
hard-coding database IDs.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

EXAM408_ROOT_CODE = "exam408"
EXAM408_CORE_CODES: tuple[str, ...] = (
    "exam408-ds",
    "exam408-co",
    "exam408-os",
    "exam408-cn",
)
EXAM408_ALL_CODES: tuple[str, ...] = (EXAM408_ROOT_CODE, *EXAM408_CORE_CODES)

# Preferred product code -> historical/runtime aliases.  Keep this list focused
# on identity aliases only; it must not grow into a generic fuzzy matcher.
_EXAM408_CODE_ALIASES: dict[str, frozenset[str]] = {
    EXAM408_ROOT_CODE: frozenset({
        "exam408", "computer", "408", "cs", "computer_science",
    }),
    "exam408-ds": frozenset({
        "exam408-ds", "ds", "data_structure",
    }),
    "exam408-co": frozenset({
        "exam408-co", "co", "computer_organization",
    }),
    "exam408-os": frozenset({
        "exam408-os", "os", "operating_system",
    }),
    "exam408-cn": frozenset({
        "exam408-cn", "cn", "computer_network",
    }),
}

_EXAM408_NAME_ALIASES: dict[str, str] = {
    "408": EXAM408_ROOT_CODE,
    "408计算机综合": EXAM408_ROOT_CODE,
    "计算机学科专业基础综合": EXAM408_ROOT_CODE,
    "计算机基础": EXAM408_ROOT_CODE,
    "数据结构": "exam408-ds",
    "计算机组成原理": "exam408-co",
    "组成原理": "exam408-co",
    "计组": "exam408-co",
    "操作系统": "exam408-os",
    "计算机网络": "exam408-cn",
    "计网": "exam408-cn",
}

EXAM408_DISPLAY_ORDER: dict[str, int] = {
    EXAM408_ROOT_CODE: 0,
    "exam408-ds": 10,
    "exam408-co": 20,
    "exam408-os": 30,
    "exam408-cn": 40,
}

# Formula data has its own exam_scope field and historically used more than one
# spelling.  Public 408 surfaces should accept all of them without exposing math
# cards when the mini-program requests the 408 scope.
EXAM408_FORMULA_SCOPE_ALIASES: tuple[str, ...] = ("408", "exam408", "computer")


def canonical_408_code(code: str | None, name: str | None = None) -> str | None:
    """Return the preferred 408 product code for a code/name pair."""
    raw_code = str(code or "").strip().lower()
    if raw_code:
        for canonical, aliases in _EXAM408_CODE_ALIASES.items():
            if raw_code in aliases:
                return canonical

    raw_name = str(name or "").strip()
    if raw_name:
        return _EXAM408_NAME_ALIASES.get(raw_name)
    return None


def is_408_root(code: str | None, name: str | None = None) -> bool:
    return canonical_408_code(code, name) == EXAM408_ROOT_CODE


def is_408_core_subject(code: str | None, name: str | None = None) -> bool:
    return canonical_408_code(code, name) in EXAM408_ALL_CODES


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
        _record_attr(record, "code", _record_attr(record, "subject_code")),
        _record_attr(record, "name", _record_attr(record, "subject_name")),
    )


def _record_active(record: Any) -> bool:
    return _record_attr(record, "is_active", True) is not False


def _root_preference(record: Any) -> tuple[int, int, int]:
    raw_code = str(_record_attr(record, "code", "") or "").strip().lower()
    preferred = 0 if raw_code == EXAM408_ROOT_CODE else 1
    sort_order = int(_record_attr(record, "sort_order", 0) or 0)
    record_id = _record_id(record) or 0
    return preferred, sort_order, record_id


def select_408_subject_records(records: Iterable[Any]) -> list[Any]:
    """Select the active 408 product subtree from subject records.

    If a recognized 408 root exists, its active state gates the whole public
    product scope.  Only the four recognized core branches are exposed below
    that root; descendants of those branches are preserved for future deeper
    subject trees.  If a legacy database has no root at all, recognized core
    disciplines are returned as a compatibility fallback.
    """
    items = list(records)
    children: dict[int | None, list[Any]] = {}
    for item in items:
        children.setdefault(_record_parent_id(item), []).append(item)

    roots = [item for item in items if _record_product_code(item) == EXAM408_ROOT_CODE]
    if roots:
        root = sorted(roots, key=_root_preference)[0]
        if not _record_active(root):
            return []

        selected_ids: set[int] = set()
        root_id = _record_id(root)
        if root_id is None:
            return []
        selected_ids.add(root_id)

        # A core branch must live under the selected root.  This prevents an old
        # orphaned/duplicate subject row from silently becoming a public entry.
        direct_core: dict[str, Any] = {}
        for child in children.get(root_id, []):
            product_code = _record_product_code(child)
            if product_code not in EXAM408_CORE_CODES or not _record_active(child):
                continue
            current = direct_core.get(product_code)
            if current is None or _root_preference(child) < _root_preference(current):
                direct_core[product_code] = child

        def add_active_descendants(parent_id: int) -> None:
            for child in children.get(parent_id, []):
                if not _record_active(child):
                    continue
                child_id = _record_id(child)
                if child_id is None:
                    continue
                selected_ids.add(child_id)
                add_active_descendants(child_id)

        for product_code in EXAM408_CORE_CODES:
            branch = direct_core.get(product_code)
            if branch is None:
                continue
            branch_id = _record_id(branch)
            if branch_id is None:
                continue
            selected_ids.add(branch_id)
            add_active_descendants(branch_id)

        return [item for item in items if _record_id(item) in selected_ids and _record_active(item)]

    # Legacy fallback: no root exists at all.  Keep recognized 408 core rows
    # usable while making the missing root visible to admins rather than exposing
    # unrelated active subjects.
    core_items = [
        item for item in items
        if _record_product_code(item) in EXAM408_CORE_CODES and _record_active(item)
    ]
    return sorted(
        core_items,
        key=lambda item: (
            EXAM408_DISPLAY_ORDER.get(_record_product_code(item) or "", 999),
            int(_record_attr(item, "sort_order", 0) or 0),
            _record_id(item) or 0,
        ),
    )


def selected_408_subject_ids(records: Iterable[Any]) -> set[int]:
    return {
        rid for record in select_408_subject_records(records)
        if (rid := _record_id(record)) is not None
    }
