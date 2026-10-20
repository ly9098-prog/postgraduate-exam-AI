"""Readiness probes must not depend on HTTP assembly or create runtime on import."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
FUNCTIONS = (
    "get_db_pool_metrics", "check_database", "check_redis", "check_alembic_head",
    "check_staging", "check_staging_space", "check_queue",
)


def test_infrastructure_probes_depend_on_original_ports_and_keep_budgets():
    graph, violations = scan_application(APP)
    assert not violations
    assert graph["app.services.readiness_dependency_probes"] == {
        "app.core.database", "app.core.cache", "app.core.deployment_profile",
        "app.services.staging_storage", "app.services.task_queue_service",
    }
    assert "app.services.readiness_dependency_probes" in graph["app.main"]
    source = (APP / "services/readiness_dependency_probes.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name


def test_main_consumes_actual_probe_definitions_without_old_private_forwarders():
    from app import main
    from app.services import readiness_dependency_probes

    for name in FUNCTIONS:
        assert getattr(main, name) is getattr(readiness_dependency_probes, name)
        assert not hasattr(main, "_" + name)
    source = (APP / "main.py").read_text()
    assert "script_location=os.path.join(os.path.dirname(__file__), \"../alembic\")" in source


def test_infrastructure_probe_import_does_not_initialize_runtime():
    probe = """
import sys
from app.services.readiness_dependency_probes import check_database, check_redis
assert callable(check_database) and callable(check_redis)
for name in ('app.main', 'app.core.config', 'app.core.database', 'app.core.cache',
             'app.services.staging_storage', 'app.services.task_queue_service'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
