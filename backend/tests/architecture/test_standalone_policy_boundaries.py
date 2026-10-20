"""Standalone startup policies stay neutral with actual runtime consumers."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_standalone_policy_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.core.standalone_runtime_policy"] == {
        "app.core.config", "app.core.deployment_profile",
    }
    assert "app.core.standalone_runtime_policy" in graph["app.core.bootstrap"]
    source = (APP / "core/standalone_runtime_policy.py").read_text()
    assert len(source.splitlines()) <= 300
    assert len((APP / "core/bootstrap.py").read_text().splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_bootstrap_uses_actual_guard_scratch_reporter_and_role_set_without_old_forwarders():
    from app.core import bootstrap
    from app.core import standalone_runtime_policy as policy

    helpers = {
        "reject_standalone_http_launch": ["role"],
        "ensure_worker_scratch_directory": ["settings"],
        "create_standalone_failure_reporter": ["profile", "settings", "logger"],
    }
    tree = ast.parse((APP / "core/bootstrap.py").read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    for name, arguments in helpers.items():
        assert getattr(bootstrap, name) is getattr(policy, name)
        actual = [node for node in calls if getattr(node.func, "id", None) == name]
        assert len(actual) == 1
        assert [ast.unparse(arg) for arg in actual[0].args] == arguments
        assert not actual[0].keywords
    assert bootstrap.STANDALONE_ROLES is policy.STANDALONE_ROLES
    assert policy.STANDALONE_ROLES == frozenset({"worker", "scheduler"})
    for name in ["_guard_http_role", "_ensure_scratch_dir", "_startup_failure_reporter", "_FORBIDDEN_HTTP_ROLES"]:
        assert not hasattr(bootstrap, name)
    runner = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_role")
    assert ast.unparse(runner.body[1].test) == "role not in STANDALONE_ROLES"
    assert ast.unparse(runner.body[2]) == "reject_standalone_http_launch(role)"
    assert ast.unparse(runner.body[3]) == "os.environ['PROCESS_ROLE'] = role"
    assert ast.unparse(runner.body[4]) == "settings.PROCESS_ROLE = role"


def test_policy_import_does_not_load_configuration_create_directories_or_mutate_process():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create runtime state')
asyncio.create_task = forbidden
os.makedirs = forbidden
from app.core import standalone_runtime_policy as policy
assert callable(policy.create_standalone_failure_reporter)
assert callable(policy.ensure_worker_scratch_directory)
assert callable(policy.reject_standalone_http_launch)
assert before == dict(os.environ)
for name in ('app.main', 'app.core.bootstrap', 'app.core.config', 'app.core.database',
             'app.core.deployment_profile'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
