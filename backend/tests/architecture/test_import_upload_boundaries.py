"""Upload admission depends on execution helpers; execution never imports producers."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import cyclic_edges, scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULES = (
    "import_upload_request", "import_upload_service", "import_image_upload",
    "import_excel_upload", "import_document_upload", "import_pipeline_admission",
)


def test_upload_and_worker_import_graph_has_no_remaining_cycles():
    graph, violations = scan_application(APP)
    assert not violations
    assert cyclic_edges(graph) == set()
    runtime = graph["app.services.import_pipeline_service"]
    assert "app.services.task_queue_worker" not in runtime
    assert not runtime & {f"app.services.{name}" for name in MODULES}
    for name in ("app.api.v1.imports", "app.api.v1.admin_imports"):
        assert "app.services.import_upload_service" in graph[name]
    for name in ("import_image_upload", "import_excel_upload", "import_document_upload"):
        assert "app.services.task_queue_worker" in graph[f"app.services.{name}"]


def test_upload_modules_have_bounded_typed_functions():
    for name in MODULES:
        path = APP / "services" / f"{name}.py"
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 300
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 50, (name, node.name)
                assert node.returns is not None, (name, node.name)


def test_routes_share_one_upload_entry_and_runtime_has_no_forwarder():
    from app.api.v1 import admin_imports, imports
    from app.services import import_pipeline_service, import_upload_service

    assert imports.svc_start_import_pipeline is import_upload_service.start_import_pipeline
    assert admin_imports.svc_start_import_pipeline is import_upload_service.start_import_pipeline
    assert not hasattr(import_pipeline_service, "start_import_pipeline")


def test_execution_runtime_import_does_not_load_upload_producers():
    probe = """
import sys
from app.services import import_pipeline_service
for name in (
    'import_upload_service', 'import_document_upload',
    'import_excel_upload', 'import_image_upload',
):
    assert 'app.services.' + name not in sys.modules, name
assert not hasattr(import_pipeline_service, 'start_import_pipeline')
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
