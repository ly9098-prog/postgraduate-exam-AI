"""Role checks consume original runtime ports without importing HTTP assembly."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_role_readiness_dependencies_and_budgets():
    graph, violations = scan_application(APP)
    assert not violations
    assert graph["app.services.role_readiness"] == {
        "app.core.config", "app.core.ocr_isolation", "app.services.task_queue_worker",
        "app.services.audit_cleanup_scheduler", "app.services.recommendation_metrics_scheduler",
    }
    assert "app.services.role_readiness" in graph["app.main"]
    source = (APP / "services/role_readiness.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name


def test_main_consumes_real_role_check_without_forwarder():
    from app import main
    from app.services.role_readiness import check_role_dependencies

    assert main.check_role_dependencies is check_role_dependencies
    assert not hasattr(main, "_check_role_deps")
    assert "await check_role_dependencies(settings)" in (APP / "main.py").read_text()


def test_role_readiness_import_does_not_start_runtime():
    probe = """
import sys
from app.services.role_readiness import check_role_dependencies
assert callable(check_role_dependencies)
for name in ('app.main', 'app.core.config', 'app.core.database', 'app.core.ocr_isolation',
             'app.services.task_queue_worker', 'app.services.audit_cleanup_scheduler',
             'app.services.recommendation_metrics_scheduler'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
