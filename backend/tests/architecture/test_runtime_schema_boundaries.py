"""Legacy schema compatibility stays isolated from app assembly and resource creation."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULES = [
    "services/export/schema_compatibility.py",
    "services/runtime_schema_diagnostics.py",
]


def test_schema_service_dependencies_budgets_and_original_transaction_owners():
    graph, _ = scan_application(APP)
    for module in ["app.services.export.schema_compatibility", "app.services.runtime_schema_diagnostics"]:
        assert graph[module] == {"app.core.database"}
        assert module in graph["app.main"]
    for path in MODULES:
        source = (APP / path).read_text()
        assert len(source.splitlines()) <= 300
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 50
        calls = [
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "commit"
        ]
        assert len(calls) == int("schema_compatibility" in path)
    repair = ast.parse((APP / MODULES[0]).read_text())
    run_sync = next(
        node for node in ast.walk(repair)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run_sync"
    )
    assert [ast.unparse(arg) for arg in run_sync.args] == [
        "_repair_sqlite_export_idempotency_index", "_sa_inspect",
    ]
    assert not run_sync.keywords


def test_main_keeps_real_schema_services_between_database_init_and_seeding():
    from app import main
    from app.services.export.schema_compatibility import (
        repair_export_idempotency_schema,
    )
    from app.services.runtime_schema_diagnostics import log_runtime_schema_divergence

    assert main.repair_export_idempotency_schema is repair_export_idempotency_schema
    assert main.log_runtime_schema_divergence is log_runtime_schema_divergence
    source = (APP / "main.py").read_text()
    calls = sorted(
        [node for node in ast.walk(ast.parse(source))
         if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
         and node.func.id in {"repair_export_idempotency_schema", "log_runtime_schema_divergence"}],
        key=lambda node: node.lineno,
    )
    assert [node.func.id for node in calls] == [
        "repair_export_idempotency_schema", "log_runtime_schema_divergence",
    ]
    for node in calls:
        assert [ast.unparse(arg) for arg in node.args] == ["async_session"]
        assert not node.keywords
    positions = [source.index(fragment) for fragment in [
        "await init_db()", "await repair_export_idempotency_schema(",
        "await log_runtime_schema_divergence(", "await initialize_dev_admin(",
    ]]
    assert positions == sorted(positions)


def test_importing_schema_services_does_not_load_app_or_create_runtime_resources():
    probe = """
import asyncio
import sys
import sqlalchemy
from sqlalchemy.ext import asyncio as sa_async
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create engines or tasks')
asyncio.create_task = forbidden
sqlalchemy.create_engine = forbidden
sa_async.create_async_engine = forbidden
from app.services.export.schema_compatibility import repair_export_idempotency_schema
from app.services.runtime_schema_diagnostics import log_runtime_schema_divergence
assert callable(repair_export_idempotency_schema) and callable(log_runtime_schema_divergence)
for name in ('app.main', 'app.core.config', 'app.core.database', 'alembic'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
