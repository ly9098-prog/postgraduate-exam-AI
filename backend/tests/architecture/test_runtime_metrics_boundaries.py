"""Metrics collectors stay below HTTP assembly and retain one state owner."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULES = (
    "core/observability_access.py",
    "services/task_queue_metrics.py",
    "services/runtime_inference_metrics.py",
)


def test_metrics_modules_have_one_way_dependencies_and_short_functions():
    graph, violations = scan_application(APP)
    assert not violations
    assert graph["app.core.observability_access"] == set()
    assert graph["app.services.task_queue_metrics"] == {"app.services.task_queue_service"}
    assert graph["app.services.runtime_inference_metrics"] == {
        "app.services.ocr_service", "app.core.ai_runtime_guard", "app.features.token_budget",
    }
    for relative in MODULES:
        name = "app." + relative.removesuffix(".py").replace("/", ".")
        assert name in graph["app.main"]
        assert "app.main" not in graph[name]
        source = (APP / relative).read_text()
        assert len(source.splitlines()) <= 300
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 50, node.name


def test_metrics_consumers_use_actual_definitions_without_main_forwarders():
    from app import main
    from app.core.observability_access import require_observability_access
    from app.services.runtime_inference_metrics import (
        append_ai_metrics,
        append_ocr_metrics,
    )
    from app.services.task_queue_metrics import (
        append_queue_counters,
        append_queue_depth_metrics,
    )

    assert not hasattr(main, "_require_observability_access")
    for function in (
        require_observability_access, append_ai_metrics, append_ocr_metrics,
        append_queue_counters, append_queue_depth_metrics,
    ):
        assert getattr(main, function.__name__) is function
    endpoint = next(route.endpoint for route in main.app.routes if route.path == "/health/metrics")
    assert endpoint is main.metrics_endpoint


def test_metrics_modules_import_without_application_configuration_or_runtime():
    for relative in MODULES:
        name = "app." + relative.removesuffix(".py").replace("/", ".")
        probe = f"""
import importlib
import sys
importlib.import_module({name!r})
for name in ('app.main', 'app.core.config', 'app.core.database',
             'app.services.task_queue_service', 'app.services.ocr_service',
             'app.core.ai_runtime_guard', 'app.features.token_budget'):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-c", probe], cwd=APP.parent,
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
