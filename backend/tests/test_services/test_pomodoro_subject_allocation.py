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
    from types import SimpleNamespace

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
