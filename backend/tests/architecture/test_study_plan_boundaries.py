"""Guard the study-plan rules/completion/views decomposition and service budgets."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE_PATH = APP / "services/study_plan_service.py"
REQUEST_PATH = APP / "services/study_plan_request.py"
ACTIVITY_PATH = APP / "services/study_plan_activity.py"
MODULES = {
    "app.services.study_plan_rules": (APP / "services/study_plan_rules.py", 260),
    "app.services.study_plan_completion": (
        APP / "services/study_plan_completion.py",
        300,
    ),
    "app.services.study_plan_views": (APP / "services/study_plan_views.py", 230),
    "app.services.study_plan_request": (REQUEST_PATH, 300),
    "app.services.study_plan_activity": (ACTIVITY_PATH, 300),
}
SERVICE_BUDGET = 600
OVERVIEW_ORDER = (
    "_load_day_start_minute",
    "_load_active_plan",
    "_load_overview_inputs",
    "_materialize_overview_day",
    "_load_overview_facts",
    "_overview_totals",
    "_overview_response",
)
OVERVIEW_HELPERS = (
    "get_study_plan_overview",
    "_today_completion",
    "_load_active_plan",
    "_load_overview_inputs",
    "_materialize_overview_day",
    "_load_overview_facts",
    "_overview_totals",
    "_completed_total",
    "_completion_percent",
    "_primary_category",
    "_overview_active_days",
    "_phase_label",
    "_plan_payload",
    "_overview_response",
)
LEGACY_CEILINGS = {
    "_load_day_start_minute": 10,
    "_plan_select": 10,
    "_get_user_plan": 10,
    "_load_scope_ids": 10,
    "_load_exam_suggestion": 32,
    "_load_overview_inputs": 32,
    "_materialize_overview_day": 32,
    "_load_overview_facts": 34,
    "_overview_totals": 48,
    "_overview_response": 48,
    "get_study_plan_overview": 38,
}
WRITE_CALLS = {
    "commit",
    "rollback",
    "flush",
    "begin_nested",
    "add",
    "add_all",
    "delete",
}
DB_CALLS = {"execute", "scalar", "scalars", "commit", "rollback", "flush"}


def function(tree: ast.Module, name: str):
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def check_module_budgets(path: Path, budget: int) -> None:
    source = path.read_text()
    assert len(source.splitlines()) <= budget, path.name
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            name = getattr(node, "name", "lambda")
            assert node.end_lineno - node.lineno + 1 <= 50, name


def check_service_budgets(tree: ast.Module) -> None:
    assert len(SERVICE_PATH.read_text().splitlines()) <= SERVICE_BUDGET
    for name in OVERVIEW_HELPERS:
        node = function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= 50, name
    for name, ceiling in LEGACY_CEILINGS.items():
        node = function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= ceiling, name


def check_overview_delegation(tree: ast.Module) -> None:
    source = ast.unparse(function(tree, "get_study_plan_overview"))
    for forbidden in ("select(", "_ensure_day_snapshot(", "_today_completion("):
        assert forbidden not in source, forbidden
    positions = [source.index(f"{name}(") for name in OVERVIEW_ORDER]
    assert positions == sorted(positions)
    assert len(positions) == len(set(positions))


def check_completion_is_read_only(source: str) -> None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            attr = getattr(node.func, "attr", "")
            assert attr not in WRITE_CALLS


def check_rules_are_pure(source: str) -> None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            attr = getattr(node.func, "attr", "")
            assert attr not in DB_CALLS
        if isinstance(node, ast.Name):
            assert node.id != "db"


def check_request_delegation(tree: ast.Module) -> None:
    for name, target in (
        ("_load_activity_dates", "_activity"),
        ("_ensure_day_snapshot", "_request"),
        ("upsert_study_plan", "_request"),
        ("deactivate_study_plan", "_request"),
    ):
        node = function(tree, name)
        assert len(node.body) == 1
        statement = node.body[0]
        assert isinstance(
            statement, ast.Expr if name == "deactivate_study_plan" else ast.Return
        )
        assert isinstance(statement.value, ast.Await)
        call = statement.value.value
        assert isinstance(call, ast.Call)
        assert ast.unparse(call.func) == f"{target}.{name}"
        assert ast.unparse(call.keywords[-1]) == "ports=_study_plan_request_port"


def test_extracted_modules_stay_within_budget():
    for path, budget in MODULES.values():
        check_module_budgets(path, budget)
    check_service_budgets(ast.parse(SERVICE_PATH.read_text()))


def test_rules_and_views_have_no_database_dependencies():
    graph, _ = scan_application(APP)
    assert graph["app.services.study_plan_rules"] == {
        "app.services.pomodoro_attribution"
    }
    assert graph["app.services.study_plan_views"] == {"app.services.study_plan_rules"}
    assert (
        "app.services.study_plan_service" not in graph["app.services.study_plan_rules"]
    )
    assert (
        "app.services.study_plan_service" not in graph["app.services.study_plan_views"]
    )
    assert graph["app.services.study_plan_completion"] >= {
        "app.services.study_plan_rules"
    }
    assert (
        "app.services.study_plan_service"
        not in graph["app.services.study_plan_completion"]
    )
    for module in MODULES:
        assert module in graph["app.services.study_plan_service"]
    check_rules_are_pure((APP / "services/study_plan_rules.py").read_text())
    check_completion_is_read_only(
        (APP / "services/study_plan_completion.py").read_text()
    )
    check_completion_is_read_only(ACTIVITY_PATH.read_text())


def test_overview_entry_delegates_in_source_order():
    check_overview_delegation(ast.parse(SERVICE_PATH.read_text()))


def test_service_aliases_point_to_module_definitions():
    from app.services import study_plan_rules, study_plan_service, study_plan_views

    assert study_plan_service._allocate_integer is study_plan_rules.allocate_integer
    assert study_plan_service._build_weights is study_plan_rules.build_weights
    assert (
        study_plan_service._category_availability
        is study_plan_rules.category_availability
    )
    assert study_plan_service._ceil_minutes is study_plan_rules.ceil_minutes
    assert (
        study_plan_service._credit_supplemental_focus
        is study_plan_rules.credit_supplemental_focus
    )
    assert study_plan_service._dynamic_remaining is study_plan_rules.dynamic_remaining
    assert (
        study_plan_service._focus_duration_for_subject_scope
        is study_plan_rules.focus_duration_for_subject_scope
    )
    assert study_plan_service._phase_for_days is study_plan_rules.phase_for_days
    assert (
        study_plan_service._build_allocation_views
        is study_plan_views.build_allocation_views
    )
    assert (
        study_plan_service._build_snapshot_payload
        is study_plan_views.build_snapshot_payload
    )


def test_gate_rejects_budget_growth_database_leaks_and_missing_delegation():
    with pytest.raises(AssertionError):
        check_module_budgets(
            MODULES["app.services.study_plan_rules"][0],
            MODULES["app.services.study_plan_rules"][1] - 20,
        )

    with pytest.raises(AssertionError):
        check_completion_is_read_only("async def leak(db):\n    await db.commit()\n")

    with pytest.raises(AssertionError):
        check_rules_are_pure("def leak(db):\n    return db\n")
    with pytest.raises(AssertionError):
        check_rules_are_pure("def leak(db):\n    return db.execute('select 1')\n")

    tree = ast.parse(SERVICE_PATH.read_text())
    overview = function(tree, "get_study_plan_overview")
    overview.body.insert(
        0,
        ast.parse("rows = select(StudyPlan).all()").body[0],
    )
    with pytest.raises(AssertionError):
        check_overview_delegation(tree)

    tree = ast.parse(SERVICE_PATH.read_text())
    overview = function(tree, "get_study_plan_overview")
    overview.body = [
        node
        for node in overview.body
        if "_load_overview_inputs" not in ast.unparse(node)
    ]
    with pytest.raises((AssertionError, ValueError)):
        check_overview_delegation(tree)


def test_request_module_owns_activity_snapshot_and_settings_writes():
    tree = ast.parse(REQUEST_PATH.read_text())
    functions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions == [
        "_claim_day_snapshot",
        "_ensure_day_snapshot",
        "upsert_study_plan",
        "deactivate_study_plan",
    ]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert [arg.arg for arg in node.args.kwonlyargs][-1] == "ports"
            assert node.args.kw_defaults[-1] is None
            assert node.end_lineno - node.lineno + 1 <= 50
    check_request_delegation(ast.parse(SERVICE_PATH.read_text()))


@pytest.mark.parametrize("mutation", ["extra_statement", "target", "ports"])
def test_request_gate_rejects_bypassed_delegation(mutation):
    tree = ast.parse(SERVICE_PATH.read_text())
    node = function(tree, "upsert_study_plan")
    if mutation == "extra_statement":
        node.body.insert(0, ast.parse("await db.commit()").body[0])
    elif mutation == "target":
        node.body[0].value.value.func.attr = "deactivate_study_plan"
    else:
        node.body[0].value.value.keywords[-1].value.id = "globals"
    with pytest.raises(AssertionError):
        check_request_delegation(tree)


def test_new_module_gate_rejects_long_functions(tmp_path):
    path = tmp_path / "oversized.py"
    path.write_text("def oversized():\n" + "    value = 1\n" * 50)
    with pytest.raises(AssertionError, match="oversized"):
        check_module_budgets(path, 300)
