"""Startup session owners remain independent of application assembly."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
HELPERS = ["initialize_dev_admin", "seed_recommendation_strategies", "log_ai_model_configuration"]


def test_startup_checks_depend_on_original_services_and_keep_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.runtime_startup_checks"] == {
        "app.services.recommendation_seed_service", "app.services.health_check_service",
        "app.core.config",
    }
    assert "app.services.runtime_startup_checks" in graph["app.main"]
    source = (APP / "services/runtime_startup_checks.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
    functions = {
        node.name: node for node in ast.parse(source).body
        if isinstance(node, ast.AsyncFunctionDef)
    }
    for name, count in zip(HELPERS, [1, 1, 0], strict=True):
        assert sum(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "commit" for node in ast.walk(functions[name])
        ) == count


def test_main_uses_real_helpers_with_original_factory_order_and_admin_initializer():
    from app import main
    from app.services import runtime_startup_checks

    for name in HELPERS:
        assert getattr(main, name) is getattr(runtime_startup_checks, name)
    source = (APP / "main.py").read_text()
    calls = sorted(
        [node for node in ast.walk(ast.parse(source))
         if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
         and node.func.id in HELPERS], key=lambda node: node.lineno,
    )
    assert [node.func.id for node in calls] == HELPERS
    for node in calls:
        assert not node.keywords
        assert ast.dump(node.args[0]) == ast.dump(ast.Name(id="async_session", ctx=ast.Load()))
    assert [ast.unparse(arg) for arg in calls[0].args[1:]] == [
        "ensure_dev_super_admin", "settings",
    ]
    positions = [source.index(f"await {name}(") for name in HELPERS]
    assert source.index("await log_runtime_schema_divergence(") < positions[0]
    assert positions[-1] < source.index("_executors = init_executors_for_role(")


def test_importing_startup_checks_does_not_initialize_configuration_or_resources():
    probe = """
import asyncio
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.services.runtime_startup_checks import (
    initialize_dev_admin, seed_recommendation_strategies, log_ai_model_configuration,
)
assert all(callable(fn) for fn in (
    initialize_dev_admin, seed_recommendation_strategies, log_ai_model_configuration,
))
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.services.admin_bootstrap_service',
    'app.services.recommendation_seed_service', 'app.services.health_check_service', 'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
