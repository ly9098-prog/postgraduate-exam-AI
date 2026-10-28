"""Guard the study-plan rules/completion/views decomposition and service budgets."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE_PATH = APP / "services/study_plan_service.py"
MODULES = {
    "app.services.study_plan_rules": (APP / "services/study_plan_rules.py", 260),
    "app.services.study_plan_completion": (
        APP / "services/study_plan_completion.py",
        300,
    ),
    "app.services.study_plan_views": (APP / "services/study_plan_views.py", 230),
}
SERVICE_BUDGET = 820
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
    "_load_activity_dates": 150,
    "_ensure_day_snapshot": 80,
    "upsert_study_plan": 65,
}
WRITE_CALLS = {"commit", "rollback", "flush", "begin_nested", "add", "add_all", "delete"}
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
    assert "app.services.study_plan_service" not in graph["app.services.study_plan_rules"]
    assert "app.services.study_plan_service" not in graph["app.services.study_plan_views"]
    assert graph["app.services.study_plan_completion"] >= {
        "app.services.study_plan_rules"
    }
    assert "app.services.study_plan_service" not in graph[
        "app.services.study_plan_completion"
    ]
    for module in MODULES:
        assert module in graph["app.services.study_plan_service"]
    check_rules_are_pure((APP / "services/study_plan_rules.py").read_text())
    check_completion_is_read_only(
        (APP / "services/study_plan_completion.py").read_text()
    )


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
        check_completion_is_read_only(
            "async def leak(db):\n    await db.commit()\n"
        )

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
