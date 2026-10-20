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
    "services/runtime_system_metrics.py",
    "services/runtime_sse_metrics.py",
)


def test_metrics_modules_have_one_way_dependencies_and_short_functions():
    graph, violations = scan_application(APP)
    assert not violations
    assert graph["app.core.observability_access"] == set()
    assert graph["app.services.task_queue_metrics"] == {"app.services.task_queue_service"}
    assert graph["app.services.runtime_inference_metrics"] == {
        "app.services.ocr_service", "app.core.ai_runtime_guard", "app.features.token_budget",
    }
    assert graph["app.services.runtime_system_metrics"] == {
        "app.core.resource_guard", "app.core.database", "app.services.staging_storage",
        "app.services.task_queue_worker", "app.services.audit_cleanup_scheduler",
        "app.services.recommendation_metrics_scheduler",
    }
    assert graph["app.services.runtime_sse_metrics"] == {
        "app.services.sse_pubsub", "app.features.batch_image_import_service",
        "app.services.import_sse_metrics",
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


def test_sse_counter_owner_is_neutral_and_route_only_consumes_it():
    from app.api.v1 import admin_imports
    from app.services import import_sse_metrics

    assert admin_imports.import_sse_metrics is import_sse_metrics
    assert not hasattr(admin_imports, "_sse_metrics")
    source = (APP / "services/import_sse_metrics.py").read_text()
    tree = ast.parse(source)
    assert len(source.splitlines()) <= 300
    values = [n for n in tree.body if isinstance(n, ast.AnnAssign)]
    assert len(values) == 1
    assert isinstance(values[0].target, ast.Name) and values[0].target.id == "counters"
    assert ast.literal_eval(values[0].value) == {
        "active": 0, "per_user_rejected": 0, "global_rejected": 0,
        "disconnected": 0, "max_duration_closed": 0, "max_idle_closed": 0,
    }
    graph, _ = scan_application(APP)
    assert graph["app.services.import_sse_metrics"] == set()
    assert "app.services.import_sse_metrics" in graph["app.api.v1.admin_imports"]


def test_sse_counter_import_does_not_load_api_or_other_runtime():
    probe = """
import sys
from app.services.import_sse_metrics import counters
assert len(counters) == 6
for name in ('app.main', 'app.core.config', 'app.core.database',
             'app.api.v1.admin_imports', 'app.features.batch_image_import_service'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
