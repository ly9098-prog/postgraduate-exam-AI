"""Window planning must stay pure and leave IO/attribution with the caller."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = "app.services.pomodoro_statistics_window"
RESPONSE = "app.services.pomodoro_statistics_response"
ACCUMULATION = "app.services.pomodoro_statistics_accumulation"


def test_window_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph[MODULE] == set()
    assert MODULE in graph["app.services.pomodoro_service"]
    source = (APP / "services/pomodoro_statistics_window.py").read_text()
    assert len(source.splitlines()) <= 100
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "commit",
                "rollback",
                "flush",
                "create_task",
            }


def test_snapshot_passes_original_policy_and_time_ports():
    from app.services import pomodoro_service, pomodoro_statistics_window

    assert (
        pomodoro_service.requested_statistics_period
        is pomodoro_statistics_window.requested_statistics_period
    )
    tree = ast.parse((APP / "services/pomodoro_service.py").read_text())
    entry = next(
        node
        for node in tree.body
        if getattr(node, "name", "") == "build_pomodoro_statistics_snapshot"
    )
    calls = [node for node in ast.walk(entry) if isinstance(node, ast.Call)]
    planning = [
        node
        for node in calls
        if getattr(node.func, "id", "") == "requested_statistics_period"
    ]
    assert len(planning) == 1
    assert len(planning[0].args) == 1
    request = planning[0].args[0]
    assert isinstance(request, ast.Call) and isinstance(request.func, ast.Name)
    assert request.func.id == "StatisticsWindowRequest"
    assert {kw.arg: ast.unparse(kw.value) for kw in request.keywords} == {
        "day_start_minute": "dsm",
        "today": "today",
        "target": "target",
        "trends_days": "trends_days",
        "need_stats": "need_stats",
        "need_trends": "need_trends",
        "need_daily_summary": "need_daily_summary",
        "range_start": "range_start",
        "range_end": "range_end",
        "need_range_summary": "need_range_summary",
    }
    assert {kw.arg: ast.unparse(kw.value) for kw in planning[0].keywords} == {
        "day_range": "study_day_utc_range",
        "week_range": "study_week_utc_range",
    }
    assert "ranges" not in {
        node.id for node in ast.walk(entry) if isinstance(node, ast.Name)
    }
    assert (
        len(
            [
                node
                for node in calls
                if getattr(node.func, "id", "") == "study_week_utc_range"
            ]
        )
        == 1
    )
    assert (
        len(
            [
                node
                for node in calls
                if getattr(node.func, "id", "") == "_load_overlapping_sessions"
            ]
        )
        == 1
    )
    assert (
        len(
            [
                node
                for node in calls
                if getattr(node.func, "id", "") == "_load_overlapping_practice_sessions"
            ]
        )
        == 1
    )


def test_window_import_has_no_application_or_resource_side_effects():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("window import must not create tasks")
asyncio.create_task = forbidden
from app.services.pomodoro_statistics_window import requested_statistics_period
assert callable(requested_statistics_period)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.core.time_utils',
    'app.services.pomodoro_service', 'sqlalchemy', 'fastapi',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_response_builder_is_pure_and_consumed_by_snapshot():
    from app.services import pomodoro_service, pomodoro_statistics_response

    graph, _ = scan_application(APP)
    assert graph[RESPONSE] == set()
    assert RESPONSE in graph["app.services.pomodoro_service"]
    assert (
        pomodoro_service.build_statistics_response
        is pomodoro_statistics_response.build_statistics_response
    )
    source = (APP / "services/pomodoro_statistics_response.py").read_text()
    assert len(source.splitlines()) <= 100
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "commit",
                "rollback",
                "flush",
                "create_task",
            }
    snapshot_tree = ast.parse((APP / "services/pomodoro_service.py").read_text())
    entry = next(
        node
        for node in snapshot_tree.body
        if getattr(node, "name", "") == "build_pomodoro_statistics_snapshot"
    )
    calls = [
        node
        for node in ast.walk(entry)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "build_statistics_response"
    ]
    assert len(calls) == 1


def test_response_order_is_nonmutating_and_stable_for_ties():
    from datetime import date

    from app.services.pomodoro_statistics_response import build_statistics_response

    groups = {
        8: dict(
            subject_id=8,
            subject_code="b",
            subject_name="B",
            sessions=0,
            participation_sessions=0,
            duration_sec=5,
        ),
        7: dict(
            subject_id=7,
            subject_code="a",
            subject_name="A",
            sessions=0,
            participation_sessions=0,
            duration_sec=5,
        ),
    }
    before = list(groups.items())
    response = build_statistics_response(
        need_stats=False,
        need_trends=False,
        need_daily_summary=True,
        need_range_summary=True,
        today=date(2026, 10, 22),
        week_start_date=date(2026, 10, 19),
        target=date(2026, 10, 22),
        day_start_minute=360,
        day_start_time="06:00",
        trends=None,
        stats_values={},
        daily_values={"sessions": 0, "duration_sec": 10, "groups": groups},
        range_values={
            "start_date": date(2026, 10, 21),
            "end_date": date(2026, 10, 22),
            "sessions": 0,
            "duration_sec": 10,
            "active_days": 0,
            "groups": groups,
        },
    )
    expected = [dict(groups[8]), dict(groups[7])]
    assert response["daily_summary"]["subjects"] == expected
    assert response["range_summary"]["subjects"] == expected
    assert list(groups.items()) == before
    assert set(response) == {"daily_summary", "range_summary"}


def test_response_import_has_no_application_or_resource_side_effects():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("response import must not create tasks")
asyncio.create_task = forbidden
from app.services.pomodoro_statistics_response import build_statistics_response
assert callable(build_statistics_response)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models.pomodoro',
    'app.services.pomodoro_service', 'sqlalchemy', 'fastapi',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_accumulation_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph[ACCUMULATION] == set()
    assert ACCUMULATION in graph["app.services.pomodoro_service"]
    source = (APP / "services/pomodoro_statistics_accumulation.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "commit",
                "rollback",
                "flush",
                "create_task",
            }


def test_snapshot_calls_accumulators_in_source_order_with_shared_state():
    tree = ast.parse((APP / "services/pomodoro_service.py").read_text())
    entry = next(
        node
        for node in tree.body
        if getattr(node, "name", "") == "build_pomodoro_statistics_snapshot"
    )
    calls = [
        node.value.func.id
        for node in entry.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    ]
    assert calls.index("accumulate_focus_sessions") < calls.index(
        "accumulate_supplemental_sessions"
    )
    focus = next(
        node.value
        for node in entry.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", "") == "accumulate_focus_sessions"
    )
    supplemental = next(
        node.value
        for node in entry.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", "") == "accumulate_supplemental_sessions"
    )
    assert ast.unparse(focus.args[1]) == ast.unparse(supplemental.args[1]) == "state"


def test_new_process_accumulation_import_has_no_runtime_resources():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("accumulation import must not create tasks")
asyncio.create_task = forbidden
from app.services.pomodoro_statistics_accumulation import accumulate_focus_sessions
assert callable(accumulate_focus_sessions)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models.pomodoro',
    'app.services.pomodoro_service', 'sqlalchemy', 'fastapi',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
