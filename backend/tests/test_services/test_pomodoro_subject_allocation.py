from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _four_equal_rows():
    return [
        (1, "data_structure", "数据结构", 2500),
        (2, "computer_organization", "计算机组成原理", 2500),
        (3, "operating_system", "操作系统", 2500),
        (4, "computer_network", "计算机网络", 2500),
    ]


def test_equal_allocation_conserves_integer_seconds_with_stable_remainder():
    from app.services.pomodoro_subject_projection import allocate_seconds_by_weight

    rows = _four_equal_rows()

    assert allocate_seconds_by_weight(3601, rows) == [901, 900, 900, 900]
    assert allocate_seconds_by_weight(3, rows) == [1, 1, 1, 0]
    assert allocate_seconds_by_weight(0, rows) == [0, 0, 0, 0]


def test_weighted_allocation_conserves_duration_and_supports_single_subject():
    from app.services.pomodoro_subject_projection import allocate_seconds_by_weight

    rows = [
        (1, "data_structure", "数据结构", 2500),
        (2, "computer_organization", "计算机组成原理", 2500),
        (3, "operating_system", "操作系统", 2500),
        (4, "computer_network", "计算机网络", 2500),
    ]
    result = allocate_seconds_by_weight(10_001, rows)
    assert result == [2501, 2500, 2500, 2500]
    assert sum(result) == 10_001
    assert allocate_seconds_by_weight(7, [(1, "english", "英语", 10000)]) == [7]


def test_study_plan_scope_counts_allocations_once_and_filters_subjects():
    from app.services.study_plan_service import _focus_duration_for_subject_scope

    session = SimpleNamespace(
        subject_id=99,
        subject_allocations=[
            SimpleNamespace(subject_id=subject_id, weight_basis_points=2500)
            for subject_id in (1, 2, 3, 4)
        ],
    )

    assert _focus_duration_for_subject_scope(session, {object(): 3601}, {1, 2, 3, 4}) == 3601
    assert _focus_duration_for_subject_scope(session, {object(): 3601}, {1}) == 901


@pytest.mark.asyncio
async def test_new_single_subject_session_rejects_disabled_parent_branch():
    from app.services.pomodoro_service import _resolve_start_subjects

    parent = SimpleNamespace(id=1, code="math", name="数学", parent_id=None, is_active=False)
    leaf = SimpleNamespace(id=2, code="advanced_math", name="高数", parent_id=1, is_active=True)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [parent, leaf]
    database = SimpleNamespace(get=AsyncMock(return_value=leaf), execute=AsyncMock(return_value=result))
    with pytest.raises(ValueError, match="科目不可用"):
        await _resolve_start_subjects(database, 2, "single")
