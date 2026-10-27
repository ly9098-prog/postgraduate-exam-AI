"""Formula batch creation and execution must not close the worker dependency cycle."""

import ast
from pathlib import Path

from tests.architecture.dependency_scan import cyclic_edges, scan_application

APP = Path(__file__).resolve().parents[2] / "app"
PREFIX = "app.services.formula_graph_"


def test_formula_batch_has_one_state_owner_and_one_way_execution():
    graph, _ = scan_application(APP)
    service = f"{PREFIX}spec_service"
    producer = f"{PREFIX}batch_service"
    runner = f"{PREFIX}batch_runner"
    state = f"{PREFIX}batch_state"
    worker = "app.services.task_queue_worker"
    legacy = "app.services.worker_legacy_handlers"
    assert worker in graph[producer]
    assert runner in graph[legacy]
    assert service in graph[runner]
    assert state in graph[producer] and state in graph[runner]
    assert graph[state] == set()
    assert worker not in graph[service]
    assert service not in graph[worker]
    assert service not in graph[legacy]
    assert not any(source.startswith(PREFIX) or target.startswith(PREFIX)
                   for source, target in cyclic_edges(graph))


def test_formula_batch_modules_have_bounded_functions_and_no_compatibility_exports():
    for name in ("batch_service", "batch_runner", "batch_state"):
        path = APP / "services" / f"formula_graph_{name}.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert len(source.splitlines()) <= 300, path
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 50, (path, node.name)
    tree = ast.parse((APP / "services/formula_graph_spec_service.py").read_text(encoding="utf-8"))
    forbidden = {"start_batch_generate", "get_batch_status", "_process_batch", "_batch_jobs"}
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden
        for node in ast.walk(tree)
    )
