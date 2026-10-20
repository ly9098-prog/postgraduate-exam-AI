"""Lag has one process-local owner and keeps its existing lifecycle position."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_lag_module_is_neutral_and_consumers_share_the_same_owner():
    from app import main
    from app.core.event_loop_health import event_loop_health, monitor_event_loop_lag

    assert main.event_loop_health is event_loop_health
    assert main.monitor_event_loop_lag is monitor_event_loop_lag
    assert not hasattr(main, "_elapsed_monitor_event_loop_lag_ms")
    assert not hasattr(main, "_event_loop_lag_monitor")
    graph, violations = scan_application(APP)
    assert not violations
    assert graph["app.core.event_loop_health"] == set()
    assert "app.core.event_loop_health" in graph["app.main"]
    assert "app.core.event_loop_health" in graph["app.core.resource_guard"]
    source = (APP / "core/event_loop_health.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
    guard = (APP / "core/resource_guard.py").read_text()
    assert '_sys.modules.get("app.main")' not in guard


def test_lifespan_still_starts_one_monitor_and_cancels_it_before_export_drain():
    source = (APP / "main.py").read_text()
    assert source.count("monitor_event_loop_lag(event_loop_health)") == 1
    assert source.count('name="event-loop-lag-monitor"') == 1
    start = source.index("monitor_event_loop_lag(event_loop_health)")
    assert source.index("initialize_role_executors(role)") < start
    assert start < source.index('if role in ("web", "all"):', start)
    stop = source.index("_lag_monitor_task.cancel()")
    assert stop < source.index("await _lag_monitor_task", stop)
    assert stop < source.index("if _export_processor_task is not None:", stop)


def test_importing_lag_module_does_not_create_runtime_or_tasks():
    probe = """
import asyncio
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('import must not start a task')
asyncio.create_task = forbidden
from app.core.event_loop_health import event_loop_health, monitor_event_loop_lag
assert event_loop_health.lag_ms == 0.0
for name in ('app.main', 'app.core.config', 'app.core.database', 'app.core.resource_guard'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
