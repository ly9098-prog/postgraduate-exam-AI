"""HTTP startup policies own their guards without owning runtime resources."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
COMPONENTS = [
    "Executors", "OCR Gateway", "Pipeline dispatcher v2", "Reaper",
    "AI prewarm worker", "Scheduler heartbeat", "Audit log cleanup scheduler",
    "Recommendation metrics scheduler",
]


def test_http_policy_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.core.http_runtime_policy"] == {
        "app.core.config", "app.core.deployment_profile",
    }
    assert "app.core.http_runtime_policy" in graph["app.main"]
    source = (APP / "core/http_runtime_policy.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_main_uses_real_policies_original_ports_components_and_startup_positions():
    from app import main
    from app.core import http_runtime_policy

    for name in [
        "prepare_http_runtime_role", "assert_http_ocr_isolation", "report_http_startup_failure",
    ]:
        assert getattr(main, name) is getattr(http_runtime_policy, name)
    assert not hasattr(main, "_report_startup_failure")
    source = (APP / "main.py").read_text()
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    role = [node for node in calls if node.func.id == "prepare_http_runtime_role"]
    isolation = [node for node in calls if node.func.id == "assert_http_ocr_isolation"]
    reports = sorted(
        [node for node in calls if node.func.id == "report_http_startup_failure"],
        key=lambda node: node.lineno,
    )
    assert len(role) == len(isolation) == 1
    assert [ast.unparse(arg) for arg in role[0].args] == [
        "settings", "resolve_effective_process_role",
    ]
    assert [ast.unparse(arg) for arg in isolation[0].args] == [
        "loaded_local_ocr_modules", "is_restricted_ocr_environment",
    ]
    assert [ast.literal_eval(node.args[0]) for node in reports] == COMPONENTS
    for node in [*role, *isolation, *reports]:
        assert not node.keywords
    for node in reports:
        assert [ast.unparse(arg) for arg in node.args[1:]] == ["e", "_production_mode"]
    positions = [source.index(fragment) for fragment in [
        "role = prepare_http_runtime_role(", "    validate_production_config()",
        "await validate_production_config_async()", "    assert_http_ocr_isolation(",
        "profile = get_ocr_profile()",
    ]]
    assert positions == sorted(positions)


def test_importing_http_policy_does_not_load_configuration_resources_or_mutate_environment():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.core.http_runtime_policy import (
    prepare_http_runtime_role, assert_http_ocr_isolation, report_http_startup_failure,
)
assert all(callable(fn) for fn in (
    prepare_http_runtime_role, assert_http_ocr_isolation, report_http_startup_failure,
))
assert dict(os.environ) == before
for name in ('app.main', 'app.core.config', 'app.core.database', 'app.core.ocr_isolation',
             'app.core.deployment_profile'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
