"""HTTP middleware owns request adaptation without importing application runtime."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_http_middleware_dependency_direction_and_budget():
    graph, _ = scan_application(APP)
    assert graph["app.core.http_middleware"] == {"app.core.log_context"}
    assert "app.core.http_middleware" in graph["app.main"]
    source = (APP / "core/http_middleware.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name


def test_main_uses_actual_middleware_and_preserves_order_and_options():
    from starlette.middleware.cors import CORSMiddleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    from app import main
    from app.core.http_middleware import log_requests

    registered = main.app.user_middleware
    assert len(registered) == 4
    assert registered[0].kwargs["dispatch"] is log_requests
    security = registered[1].kwargs["dispatch"]
    assert security.__module__ == "app.core.http_middleware"
    assert security.__name__ == "add_security_headers"
    assert registered[2].cls is CORSMiddleware
    assert registered[2].kwargs == {
        "allow_origins": main.settings.CORS_ORIGINS,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
        "expose_headers": ["X-Request-ID", "X-Trace-ID"],
    }
    assert registered[3].cls is TrustedHostMiddleware
    assert registered[3].kwargs == {"allowed_hosts": main.settings.ALLOWED_HOSTS}
    assert not hasattr(main, "log_requests")
    assert not hasattr(main, "add_security_headers")


def test_middleware_import_does_not_load_configuration_database_or_app():
    probe = """
import sys
from app.core.http_middleware import register_http_middleware
assert callable(register_http_middleware)
for name in ('app.main', 'app.core.config', 'app.core.database', 'app.api.router'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
