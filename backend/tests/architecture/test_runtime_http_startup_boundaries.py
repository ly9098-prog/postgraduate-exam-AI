"""HTTP startup diagnostics and directory ownership have direct consumers."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_http_startup_diagnostics_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.runtime_http_startup_diagnostics"] == {
        "app.core.config", "app.core.ocr_profile", "app.services.export.capability",
    }
    source = (APP / "services/runtime_http_startup_diagnostics.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
    main = (APP / "main.py").read_text()
    assert len(main.splitlines()) <= 545
    life = next(node for node in ast.parse(main).body if getattr(node, "name", None) == "lifespan")
    assert life.end_lineno - life.lineno + 1 <= 258


def test_http_lifespan_calls_actual_startup_helpers_with_original_order_and_ports():
    from app import main
    from app.core.runtime_resource_startup import ensure_http_runtime_directories
    from app.services import runtime_http_startup_diagnostics as diagnostics

    helpers = {
        "log_http_startup": (diagnostics.log_http_startup, ["settings", "role", "profile", "logger"]),
        "log_http_export_startup": (diagnostics.log_http_export_startup, ["role", "settings", "logger"]),
        "ensure_http_runtime_directories": (ensure_http_runtime_directories, ["settings"]),
    }
    tree = ast.parse((APP / "main.py").read_text())
    life = next(node for node in tree.body if getattr(node, "name", None) == "lifespan")
    calls = [node for node in ast.walk(life) if isinstance(node, ast.Call)]
    positions = {}
    for name, (function, arguments) in helpers.items():
        assert getattr(main, name) is function
        actual = [node for node in calls if getattr(node.func, "id", None) == name]
        assert len(actual) == 1
        assert [ast.unparse(arg) for arg in actual[0].args] == arguments
        assert not actual[0].keywords
        positions[name] = actual[0].lineno
    sweep = next(node for node in calls if getattr(node.func, "id", None) == "sweep_staging_on_startup")
    database = next(node for node in calls if getattr(node.func, "id", None) == "init_db")
    assert sweep.lineno < positions["log_http_startup"] < positions["log_http_export_startup"]
    assert positions["log_http_export_startup"] < positions["ensure_http_runtime_directories"] < database.lineno
    assert not any(isinstance(node, ast.Call) and ast.unparse(node.func) == "os.makedirs" for node in calls)
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "app.services.export.capability"
                   for node in ast.walk(life))


def test_http_diagnostics_import_does_not_load_config_profiles_resources_or_log():
    probe = """
import logging
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('diagnostic import must be inert')
logging.Logger.info = forbidden
logging.Logger.warning = forbidden
os.makedirs = forbidden
from app.services import runtime_http_startup_diagnostics as diagnostics
assert callable(diagnostics.log_http_startup)
assert callable(diagnostics.log_http_export_startup)
assert before == dict(os.environ)
for name in ('app.main', 'app.core.config', 'app.core.ocr_profile',
             'app.services.export.capability', 'app.core.database'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
