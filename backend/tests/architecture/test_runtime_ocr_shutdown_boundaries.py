"""OCR shutdown stays lazy while lifespan passes its owned gateway and client."""

import ast
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def test_main_uses_real_executor_policy_inside_original_role_and_cleanup_position():
    from app import main
    from app.core.runtime_resource_shutdown import shutdown_ocr_executor

    assert main.shutdown_ocr_executor is shutdown_ocr_executor
    source = (APP / "main.py").read_text()
    tree = ast.parse(source)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "shutdown_ocr_executor"
    ]
    assert len(calls) == 1
    call = calls[0]
    assert not call.args and not call.keywords
    owner = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.If) and any(
            isinstance(item, ast.Try) for item in node.body
        ) and any(
            isinstance(item, ast.Call) and item is call for item in ast.walk(node)
        )
    )
    assert ast.dump(owner.test) == ast.dump(ast.parse('role in ("web", "all")', mode="eval").body)
    positions = [source.index(fragment) for fragment in [
        "await shutdown_formula_pool()", "await shutdown_ocr_executor()",
        "await shutdown_http_ocr_gateway(ocr_resources)",
        "await shutdown_render_resources()",
    ]]
    assert positions == sorted(positions)


def test_http_shutdown_attempts_gateway_worker_and_shared_client_in_order():
    source = (APP / "core/runtime_resource_shutdown.py").read_text()
    shutdown = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "shutdown_http_ocr_gateway"
    )
    assert shutdown.end_lineno - shutdown.lineno + 1 <= 50
    calls = [ast.unparse(node) for node in ast.walk(shutdown) if isinstance(node, ast.Call)]
    assert "resources.gateway.shutdown()" in calls
    assert "resources.worker_client.shutdown()" in calls
    assert "resources.shared_http_client.aclose()" in calls
    warning_calls = [
        node for node in ast.walk(shutdown)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "_warn_safely"
    ]
    assert len(warning_calls) == 4
    worker_clear = next(
        node.lineno for node in ast.walk(shutdown)
        if isinstance(node, ast.Assign)
        and ast.unparse(node.targets[0]) == "resources.worker_client"
        and ast.unparse(node.value) == "None"
    )
    client_close = next(
        node.lineno for node in ast.walk(shutdown)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) == "resources.shared_http_client.aclose"
    )
    assert worker_clear < client_close


def test_ocr_shutdown_policy_import_does_not_load_local_ocr_or_runtime_resources():
    probe = """
import asyncio
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.core.runtime_resource_shutdown import shutdown_ocr_executor
assert callable(shutdown_ocr_executor)
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.core.deployment_profile',
    'app.services.ocr_executor_service', 'app.features.ocr_gateway', 'paddleocr', 'paddle',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
