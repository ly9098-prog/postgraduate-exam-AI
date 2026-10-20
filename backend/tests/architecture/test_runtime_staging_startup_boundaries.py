"""The startup sweep has one lazy implementation and original consumers."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_staging_startup_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.runtime_staging_startup"] == {
        "app.core.log_context", "app.services.staging_storage",
    }
    source = (APP / "services/runtime_staging_startup.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
    bootstrap = ast.parse((APP / "core/bootstrap.py").read_text())
    runner = next(node for node in bootstrap.body if getattr(node, "name", None) == "_run_role_async")
    assert runner.end_lineno - runner.lineno + 1 <= 50


def test_both_entrypoints_call_real_sweep_with_original_logger_and_position():
    from app import main
    from app.core import bootstrap
    from app.services.runtime_staging_startup import sweep_staging_on_startup

    assert main.sweep_staging_on_startup is sweep_staging_on_startup
    assert bootstrap.sweep_staging_on_startup is sweep_staging_on_startup
    for path, owner_name in [("main.py", "lifespan"), ("core/bootstrap.py", "_run_role_async")]:
        tree = ast.parse((APP / path).read_text())
        assert not any(
            isinstance(node, ast.ImportFrom) and node.module == "app.services.staging_storage"
            for node in ast.walk(tree)
        )
        owner = next(node for node in tree.body if getattr(node, "name", None) == owner_name)
        calls = [
            (index, node.value.value) for index, node in enumerate(owner.body)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Await)
            and isinstance(node.value.value, ast.Call)
            and getattr(node.value.value.func, "id", None) == "sweep_staging_on_startup"
        ]
        assert len(calls) == 1
        index, call = calls[0]
        assert [ast.unparse(arg) for arg in call.args] == ["logger"]
        assert not call.keywords
        if owner_name == "_run_role_async":
            assert ast.unparse(owner.body[index - 1]) == "detect_deployment_profile()"
            assert ast.unparse(owner.body[index + 1]) == "registry = TaskRegistry()"
        else:
            assert ast.unparse(owner.body[index - 1]) == "profile = get_ocr_profile()"
            assert ast.unparse(owner.body[index + 1]) == "log_http_startup(settings, role, profile, logger)"


def test_import_staging_startup_does_not_load_config_resources_or_start_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('startup helper import must not initialize resources')
asyncio.create_task = forbidden
os.makedirs = forbidden
from app.services.runtime_staging_startup import sweep_staging_on_startup
assert callable(sweep_staging_on_startup)
assert before == dict(os.environ)
for name in ('app.main', 'app.core.bootstrap', 'app.core.config',
             'app.services.staging_storage', 'app.core.log_context'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
