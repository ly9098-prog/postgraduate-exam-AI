"""HTTP error adapters must remain separate from application assembly."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_http_error_modules_are_one_way_and_within_budget():
    graph, _ = scan_application(APP)
    policy = "app.core.http_error_contract"
    handlers = "app.core.http_error_handlers"
    assert graph[policy] == {"app.core.error_codes", "app.core.log_context"}
    assert policy in graph[handlers]
    assert handlers in graph["app.main"]
    for name in ("http_error_contract", "http_error_handlers"):
        assert "app.main" not in graph[f"app.core.{name}"]
        path = APP / "core" / f"{name}.py"
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 300
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 50, node.name


def test_main_registers_real_handlers_without_forwarding():
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException

    from app import main
    from app.core import http_error_handlers as handlers
    from app.core.ai_runtime_guard import AIResourceRejectedError
    from app.core.error_codes import ApiError

    expected = {
        ApiError: handlers.api_error_handler,
        AIResourceRejectedError: handlers.ai_resource_rejected_handler,
        HTTPException: handlers.http_exception_handler,
        RequestValidationError: handlers.validation_exception_handler,
        Exception: handlers.unhandled_exception_handler,
    }
    for exception, function in expected.items():
        assert main.app.exception_handlers[exception] is function
        assert not hasattr(main, function.__name__)


def test_policy_can_load_without_runtime_config_database_or_main():
    probe = """
import sys
from app.core.http_error_contract import _extract_public_error_code
assert _extract_public_error_code('SAFE_CODE', 400) == 'SAFE_CODE'
for name in ('app.main', 'app.core.config', 'app.core.database', 'app.core.ai_runtime_guard'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
