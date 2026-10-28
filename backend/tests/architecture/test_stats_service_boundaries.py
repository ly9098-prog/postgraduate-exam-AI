"""Statistics service ownership, budget and dependency gates."""

import ast
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
STATS = APP / "services" / "stats_service.py"
QUERY = APP / "services" / "stats_query_service.py"
GROWTH = APP / "services" / "stats_growth_projection.py"
RECOMMENDATION = APP / "services" / "stats_recommendation_projection.py"

FUNCTION_BUDGET = 50
STATS_CEILING = 614
NEW_MODULE_CEILING = 300


def _functions(source: str) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def budget_violations(source: str, ceiling: int) -> list[str]:
    violations = []
    if len(source.splitlines()) > ceiling:
        violations.append(f"file exceeds frozen ceiling {ceiling}")
    for name, node in _functions(source).items():
        size = node.end_lineno - node.lineno + 1
        if size > FUNCTION_BUDGET:
            violations.append(f"{name} is {size} lines")
    return violations


def _ordered(text: str, sequence: tuple[str, ...]) -> list[str]:
    violations = []
    positions = []
    for name in sequence:
        if name not in text:
            violations.append(f"lost {name}")
        else:
            positions.append(text.index(name))
    if positions != sorted(positions):
        violations.append("call order changed")
    return violations


def ownership_violations(source: str) -> list[str]:
    violations = []
    functions = _functions(source)
    for helper in (
        "_count_consecutive_days",
        "_subject_stat_row",
        "_fill_trend_points",
        "_empty_hourly_activity",
        "_pseudo_mastered_items",
        "_load_dashboard_trends",
        "_dashboard_growth",
        "_dashboard_adaptive",
        "_dashboard_yearly",
        "_load_ai_diagnosis_runtime",
        "_local_ai_diagnosis",
        "_call_ai_diagnosis_provider",
        "_parse_ai_diagnosis_or_local",
        "_load_dashboard_ai_payload",
        "_call_dashboard_ai",
        "_parse_dashboard_ai_response",
    ):
        if helper not in functions:
            violations.append(f"missing helper {helper}")

    overview = functions.get("get_overview")
    if overview is None:
        violations.append("missing entry get_overview")
    else:
        text = ast.unparse(overview)
        violations += _ordered(
            text,
            (
                "load_practice_totals",
                "load_today_practice_totals",
                "_calc_consecutive_days",
                "load_wrong_question_totals",
                "load_active_408_subject_ids",
                "count_due_reviews",
            ),
        )

    forgetting = functions.get("get_forgetting_trends")
    if forgetting is None:
        violations.append("missing entry get_forgetting_trends")
    else:
        text = ast.unparse(forgetting)
        for fragment in (
            "count_stuck_questions",
            "load_pseudo_mastered_rows",
            "count_long_unmastered",
            "load_top_forgotten_topic_rows",
            "_pseudo_mastered_items",
        ):
            if fragment not in text:
                violations.append(f"forgetting entry lost {fragment}")

    dashboard = functions.get("get_dashboard_v2")
    if dashboard is None:
        violations.append("missing entry get_dashboard_v2")
    else:
        text = ast.unparse(dashboard)
        violations += _ordered(
            text,
            (
                "get_overview",
                "get_forgetting_trends",
                "get_subject_stats",
                "_build_recommendation",
                "_load_dashboard_trends",
                "_dashboard_growth",
                "_dashboard_adaptive",
                "_dashboard_yearly",
                "cache.set",
            ),
        )

    diagnosis = functions.get("get_ai_diagnosis")
    if diagnosis is None:
        violations.append("missing entry get_ai_diagnosis")
    else:
        text = ast.unparse(diagnosis)
        for fragment in (
            "load_ai_diagnosis_subject_rows",
            "_load_ai_diagnosis_runtime",
            "_call_ai_diagnosis_provider",
            "_parse_ai_diagnosis_or_local",
        ):
            if fragment not in text:
                violations.append(f"AI diagnosis entry lost {fragment}")

    llm = functions.get("get_dashboard_llm_analysis")
    if llm is None:
        violations.append("missing entry get_dashboard_llm_analysis")
    else:
        text = ast.unparse(llm)
        for fragment in (
            "_load_dashboard_ai_payload",
            "_call_dashboard_ai",
            "_parse_dashboard_ai_response",
        ):
            if fragment not in text:
                violations.append(f"dashboard LLM entry lost {fragment}")
    return violations


def purity_violations(source: str, *, forbidden_imports=()) -> list[str]:
    violations = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in {
            "execute",
            "commit",
            "rollback",
            "flush",
            "create_task",
        }:
            violations.append(f"forbidden call {getattr(node.func, 'attr', '')}")
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("app.api") or module == "app.services":
                violations.append(f"forbidden import {module}")
            if module in forbidden_imports:
                violations.append(f"forbidden import {module}")
    return violations


def test_statistics_service_budget_and_frozen_ceiling():
    source = STATS.read_text(encoding="utf-8")
    assert budget_violations(source, STATS_CEILING) == []
    assert ownership_violations(source) == []


def test_statistics_query_and_projection_modules_stay_small_and_pure():
    for path in (QUERY, GROWTH, RECOMMENDATION):
        source = path.read_text(encoding="utf-8")
        assert budget_violations(source, NEW_MODULE_CEILING) == []
    assert purity_violations(GROWTH.read_text(encoding="utf-8")) == []
    assert purity_violations(RECOMMENDATION.read_text(encoding="utf-8")) == []


def test_statistics_dependencies_stay_within_service_boundary():
    graph, _ = scan_application(APP)
    dependencies = graph["app.services.stats_service"]
    for module in (
        "app.services.learning_time_projection",
        "app.services.stats_query_service",
        "app.services.stats_growth_projection",
        "app.services.stats_recommendation_projection",
    ):
        assert module in dependencies
    assert not any(
        name == "app.api" or name.startswith("app.api.") for name in dependencies
    )
    assert "app.services.stats_service" not in graph["app.services.stats_query_service"]


def test_budget_gate_rejects_injected_long_function():
    source = STATS.read_text(encoding="utf-8")
    source += "def injected():\n" + "\n".join("    value = 1" for _ in range(50)) + "\n"
    assert "injected is 51 lines" in budget_violations(source, STATS_CEILING)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            "load_today_practice_totals(",
            "load_practice_totals(",
            "lost load_today_practice_totals",
        ),
        (
            "load_top_forgotten_topic_rows(",
            "load_stuck_questions(",
            "forgetting entry lost load_top_forgotten_topic_rows",
        ),
        (
            "_dashboard_growth(",
            "_dashboard_yearly(",
            "lost _dashboard_growth",
        ),
        (
            "load_ai_diagnosis_subject_rows(",
            "load_practice_totals(",
            "AI diagnosis entry lost load_ai_diagnosis_subject_rows",
        ),
        (
            "_parse_dashboard_ai_response(",
            "_rule_based_dashboard_analysis(",
            "dashboard LLM entry lost _parse_dashboard_ai_response",
        ),
    ],
)
def test_ownership_gate_rejects_injected_mutations(old, new, expected):
    source = STATS.read_text(encoding="utf-8")
    assert old in source, old
    violations = ownership_violations(source.replace(old, new, 1))
    assert any(expected in violation for violation in violations), violations


def test_ownership_gate_rejects_removed_helper():
    source = STATS.read_text(encoding="utf-8")
    node = _functions(source)["_load_dashboard_trends"]
    lines = source.splitlines()
    mutated = "\n".join(lines[: node.lineno - 1] + lines[node.end_lineno :]) + "\n"
    violations = ownership_violations(mutated)
    assert any("_load_dashboard_trends" in violation for violation in violations)
