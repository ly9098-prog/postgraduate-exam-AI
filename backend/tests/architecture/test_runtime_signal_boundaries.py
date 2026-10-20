"""Signal mechanics stay independent while the runner retains stop ownership."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_signal_module_has_no_application_dependencies_and_small_functions():
    graph, _ = scan_application(APP)
    assert graph["app.core.runtime_signals"] == set()
    assert "app.core.runtime_signals" in graph["app.core.bootstrap"]
    source = (APP / "core/runtime_signals.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_runner_installs_real_handlers_after_initialization_and_before_wait_shutdown():
    from app.core import bootstrap, runtime_signals

    assert bootstrap.install_role_signal_handlers is runtime_signals.install_role_signal_handlers
    assert not hasattr(bootstrap, "_install_signal_handlers")
    tree = ast.parse((APP / "core/bootstrap.py").read_text())
    runner = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_role_async")
    calls = [node for node in ast.walk(runner) if isinstance(node, ast.Call)]
    installation = [node for node in calls if getattr(node.func, "id", None) == "install_role_signal_handlers"]
    assert len(installation) == 1
    assert [ast.unparse(arg) for arg in installation[0].args] == ["stop_event", "logger"]
    assert not installation[0].keywords
    stop_wait = next(node for node in calls if ast.unparse(node.func) == "stop_event.wait")
    shutdown = next(node for node in calls if getattr(node.func, "id", None) == "shutdown_role")
    scheduler = next(node for node in calls if getattr(node.func, "id", None) == "_init_scheduler_dependencies")
    assert scheduler.lineno < installation[0].lineno < stop_wait.lineno < shutdown.lineno
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "_install_signal_handlers" for node in tree.body)


def test_signal_module_import_registers_no_handlers_tasks_or_configuration():
    probe = """
import asyncio
import os
import signal
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not install signals or create tasks')
asyncio.create_task = forbidden
asyncio.get_running_loop = forbidden
signal.signal = forbidden
from app.core.runtime_signals import install_role_signal_handlers
assert callable(install_role_signal_handlers)
assert before == dict(os.environ)
for name in ('app.main', 'app.core.bootstrap', 'app.core.config', 'app.core.database'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
