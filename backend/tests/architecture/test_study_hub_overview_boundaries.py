"""Guard study hub overview delegation order, slot cap and copy semantics."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE = APP / "services/study_hub_service.py"
ENTRY = "get_study_hub_overview"
HELPERS = (
    "_scope_not_ready_overview",
    "_load_study_hub_inputs",
    "_build_review_task",
    "_build_weakness_task",
    "_build_hard_task",
    "_build_path_task",
    "_build_smart_task",
    "_collect_study_hub_tasks",
    "_finalize_study_hub_tasks",
    "_build_review_summary",
)


def load():
    return ast.parse(SERVICE.read_text())


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def source_of(tree, name):
    return ast.unparse(function(tree, name))


def check_budgets(tree):
    for name in (ENTRY,) + HELPERS:
        node = function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= 50, name


def check_entry(tree):
    source = source_of(tree, ENTRY)
    steps = [
        "await _load_subject_scope(db)",
        "return _scope_not_ready_overview()",
        "= await _load_study_hub_inputs(db, user_id, core_subjects)",
        "remaining_review = int(review_overview.get('today_remaining_count') or 0)",
        "tasks = _collect_study_hub_tasks(",
        "tasks.append(_build_smart_task(root, root_id, is_new_user))",
        "= await _finalize_study_hub_tasks(",
        "'review': _build_review_summary(review_overview, remaining_review)",
    ]
    for step in steps:
        assert step in source, step
    indexes = [source.index(step) for step in steps]
    assert indexes == sorted(indexes), steps
    assert "await _pick_" not in source
    assert "review_scheduler" not in source
    assert "task_order" not in source
    assert "'recommendation_limit': 3" in source
    assert "if root is None or len(core_subjects) != len(EXAM408_CORE_CODES):" in source

    entry = function(tree, ENTRY)
    unpack = next(
        node
        for node in ast.walk(entry)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Tuple)
        and "_load_study_hub_inputs" in ast.unparse(node.value)
    )
    entry_names = [ast.unparse(element) for element in unpack.targets[0].elts]
    loader_return = next(
        node
        for node in ast.walk(function(tree, "_load_study_hub_inputs"))
        if isinstance(node, ast.Return)
    )
    loader_names = [ast.unparse(element) for element in loader_return.value.elts]
    assert entry_names == loader_names


def check_loader(tree):
    source = source_of(tree, "_load_study_hub_inputs")
    order = [
        "await review_scheduler.get_today_review_overview(db, user_id)",
        "await _load_408_practice_counts(",
        "await _build_subject_mastery(db, user_id, core_subjects)",
        "await _pick_chapter_recommendation(db, user_id, subject_mastery)",
        "await _pick_weak_point(db, user_id, core_ids)",
        "await _pick_hard_questions(db, user_id, core_ids)",
        "await _pick_path_prerequisite(db, user_id, core_ids)",
    ]
    for item in order:
        assert item in source, item
    indexes = [source.index(item) for item in order]
    assert indexes == sorted(indexes), order
    assert (
        "chapter_task = await _pick_chapter_recommendation(db, user_id, subject_mastery) "
        "if total_practice_count > 0 else None"
    ) in source
    assert "core_ids = [int(subject.id) for subject in core_subjects]" in source


def check_collector(tree):
    source = source_of(tree, "_collect_study_hub_tasks")
    assert "tasks: list[dict] = []" in source
    assert "if remaining_review > 0:" in source
    assert (
        "tasks.append(_build_review_task(review_overview, remaining_review))" in source
    )
    assert "if chapter_task is not None:\n        tasks.append(chapter_task)" in source
    assert (
        "int(chapter_task.get('subject_id') or 0) != int(weak_point.get('subject_id') or 0)"
        in source
    )
    assert "tasks.append(_build_weakness_task(weak_point))" in source
    assert (
        "if hard_questions:\n        tasks.append(_build_hard_task(root, root_id, hard_questions))"
        in source
    )
    assert (
        "used_kp_ids = {int(task['knowledge_point_id']) for task in tasks if task.get('knowledge_point_id') is not None}"
        in source
    )
    assert (
        "if path_prereq is not None and path_prereq['knowledge_point_id'] not in used_kp_ids:"
        in source
    )
    assert source.rstrip().endswith("return tasks")


def check_builders(tree):
    review = source_of(tree, "_build_review_task")
    assert "'key': 'review:due'" in review
    assert "if overdue > 0" in review
    assert "if overdue > 0 else '这些题已经进入最佳复习窗口" in review

    weak = source_of(tree, "_build_weakness_task")
    assert "if recent_wrong >= 2:" in weak
    assert "min(WEAK_TASK_COUNT, int(weak_point['available_question_count']))" in weak
    assert "allow_repeat=True" in weak

    hard = source_of(tree, "_build_hard_task")
    assert "max((int(item['wrong_count']) for item in hard_questions))" in hard
    assert "per_question_sec=120" in hard

    path = source_of(tree, "_build_path_task")
    assert "min(PATH_TASK_COUNT, int(path_prereq['available_question_count']))" in path
    assert "'后续知识点'" in path

    smart = source_of(tree, "_build_smart_task")
    assert "smart_mode = 'random' if is_new_user else 'smart'" in smart
    assert "'practice:fallback' if is_new_user else 'practice:smart'" in smart
    assert "SMART_TASK_COUNT" in smart


def ordered(source, *items):
    for item in items:
        assert item in source, item
    indexes = [source.index(item) for item in items]
    assert indexes == sorted(indexes), items


def check_finalize(tree):
    source = source_of(tree, "_finalize_study_hub_tasks")
    ordered(
        source,
        "task_order = {",
        "tasks.sort(key=lambda task: (task_order[task['task_type']], task['key']))",
        "plan_date = shanghai_today()",
        "completed_plan_keys = await _load_completed_plan_task_keys(",
        "str(task.get('key') or '') in completed_key_set",
        "1 if task.get('completed_today') else 0",
        "tasks = tasks[:3]",
        "task['priority'] = index",
        "plan_date=plan_date.isoformat()",
        "return (tasks, plan_date, completed_plan_keys)",
    )


def check_summary(tree):
    source = source_of(tree, "_build_review_summary")
    for field in (
        "due_count",
        "completed_count",
        "remaining_count",
        "overdue_count",
        "estimated_minutes",
    ):
        assert f"'{field}'" in source
    assert "'remaining_count': remaining_review" in source


def test_overview_helpers_stay_within_budget():
    check_budgets(load())


def test_overview_delegation_and_copy_semantics():
    tree = load()
    check_entry(tree)
    check_loader(tree)
    check_collector(tree)
    check_builders(tree)
    check_finalize(tree)
    check_summary(tree)


def test_gate_rejects_widened_slot_cap_and_swapped_smart_mode():
    tree = load()
    finalize = function(tree, "_finalize_study_hub_tasks")
    for node in ast.walk(finalize):
        if isinstance(node, ast.Assign) and ast.unparse(node) == "tasks = tasks[:3]":
            node.value = ast.Subscript(
                value=ast.Name(id="tasks", ctx=ast.Load()),
                slice=ast.Slice(lower=None, upper=ast.Constant(value=4), step=None),
                ctx=ast.Load(),
            )
            break
    with pytest.raises(AssertionError):
        check_finalize(tree)

    tree = load()
    smart = function(tree, "_build_smart_task")
    for node in ast.walk(smart):
        if isinstance(node, ast.IfExp) and "'random'" in ast.unparse(node):
            node.body, node.orelse = node.orelse, node.body
            break
    with pytest.raises(AssertionError):
        check_builders(tree)
