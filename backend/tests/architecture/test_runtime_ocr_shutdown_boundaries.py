"""OCR executor policy stays lazy while lifespan owns gateway/client cleanup."""

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
            isinstance(item, ast.Expr) and isinstance(item.value, ast.Await)
            and item.value.value is call for item in node.body
        )
    )
    assert ast.dump(owner.test) == ast.dump(ast.parse('role in ("web", "all")', mode="eval").body)
    positions = [source.index(fragment) for fragment in [
        "await shutdown_formula_pool()", "await shutdown_ocr_executor()",
        "await _ocr_gateway.shutdown()", "await _ocr_shared_http_client.aclose()",
        "await shutdown_render_resources()",
    ]]
    assert positions == sorted(positions)
    client_try = next(
        node for node in owner.body if isinstance(node, ast.Try)
        and any(isinstance(item, ast.Expr) and isinstance(item.value, ast.Name)
                and item.value.id == "_ocr_shared_http_client" for item in node.body)
    )
    assert [ast.dump(handler.type) for handler in client_try.handlers] == [
        ast.dump(ast.Name(id="NameError", ctx=ast.Load())),
    ]


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
