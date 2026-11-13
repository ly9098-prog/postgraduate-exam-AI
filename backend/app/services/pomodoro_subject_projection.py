"""Pure subject snapshots and integer-second allocation for focus statistics."""

from app.core.subject_scope import (
    EXAM408_CORE_CODES,
    canonical_408_code,
    is_extra_study_parent,
    is_extra_study_subject,
    is_study_subject_enabled,
)


def resolve_subject(session) -> tuple[int | None, str, str]:
    """Return (group_key, code, name) for a session's subject.

    Subjects enabled by the product scope render under their real id/name.
    Legacy extra-subject records keep their existing attribution even when
    disabled for new sessions. Other unavailable subjects merge into 未分类.
    """
    ref = session.subject_ref
    if (
        session.subject_id is not None
        and ref is not None
        and (
            is_study_subject_enabled(ref)
            or (
                not canonical_408_code(ref.code)
                and (is_extra_study_subject(ref) or is_extra_study_parent(ref))
            )
        )
    ):
        return session.subject_id, ref.code or "", ref.name or ""
    return None, "", "未分类"


def resolve_allocations(session) -> list[tuple[int | None, str, str, int]]:
    """Resolve persisted attribution rows; legacy sessions remain single-subject."""
    rows = list(getattr(session, "subject_allocations", []) or [])
    if not rows:
        key, code, name = resolve_subject(session)
        return [(key, code, name, 10000)]
    order = {code: index for index, code in enumerate(EXAM408_CORE_CODES)}

    def allocation_code(row) -> str:
        return getattr(row, "subject_code_snapshot", getattr(row, "subject_code", ""))

    def allocation_name(row) -> str:
        return getattr(row, "subject_name_snapshot", getattr(row, "subject_name", ""))

    rows.sort(
        key=lambda row: (
            order.get(allocation_code(row), len(order)),
            allocation_code(row),
        )
    )
    return [
        (
            row.subject_id,
            allocation_code(row),
            allocation_name(row),
            row.weight_basis_points,
        )
        for row in rows
    ]


def allocation_group_key(subject_id: int | None, code: str):
    if subject_id is not None or not code:
        return subject_id
    return ("deleted-subject", code)


def allocate_seconds_by_weight(
    total_sec: int, rows: list[tuple[int | None, str, str, int]]
) -> list[int]:
    """Largest-remainder allocation with row-order tie breaking and exact conservation."""
    total_sec = max(0, int(total_sec))
    if not rows:
        return []
    weight_sum = sum(max(0, int(row[3])) for row in rows)
    if weight_sum <= 0:
        raise ValueError("科目分配权重无效")
    exact = [total_sec * max(0, int(row[3])) / weight_sum for row in rows]
    allocated = [int(value) for value in exact]
    remaining = total_sec - sum(allocated)
    order = sorted(range(len(rows)), key=lambda i: (-(exact[i] - allocated[i]), i))
    for index in order[:remaining]:
        allocated[index] += 1
    return allocated
