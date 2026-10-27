"""Bounded, synchronous and lazy local-PDF OCR with an explicit resource owner."""

import ast
from pathlib import Path

import pytest

FEATURES = Path(__file__).resolve().parents[2] / "app/features"
ROLES = ("state", "inputs", "batch", "execution", "output")


def load_role(role):
    path = FEATURES / f"pipeline_scanned_{role}.py"
    assert path.is_file(), path
    source = path.read_text()
    return source, ast.parse(source, feature_version=(3, 11))


def enforce_budgets(source):
    assert len(source.splitlines()) <= 300
    functions = [
        n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)
    ]
    assert functions, "budget gate must inspect executable functions"
    assert all(n.end_lineno - n.lineno + 1 <= 50 for n in functions)


@pytest.mark.parametrize("role", ROLES)
def test_helpers_are_bounded_synchronous_and_do_not_import_owner(role):
    source, tree = load_role(role)
    enforce_budgets(source)
    assert not any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.features.pipeline_orchestrator"
        if isinstance(node, ast.Import):
            assert all(
                a.name != "app.features.pipeline_orchestrator" for a in node.names
            )


@pytest.mark.parametrize("source", ["", "def oversized():\n" + "    pass\n" * 51])
def test_budget_gate_rejects_empty_or_oversized_code(source):
    with pytest.raises(AssertionError):
        enforce_budgets(source)


def test_entry_retains_signature_docstring_and_lazy_delegation():
    tree = ast.parse((FEATURES / "pipeline_orchestrator.py").read_text())
    entry = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_ocr_scanned_pdf"
    )
    assert [a.arg for a in entry.args.args] == [
        "content_or_path",
        "pipeline_id",
        "page_start",
        "page_end",
    ]
    assert [ast.literal_eval(n) for n in entry.args.defaults] == ["", 1, None]
    assert ast.get_docstring(entry)
    assert len(entry.body) == 3
    assert isinstance(entry.body[1], ast.ImportFrom)
    assert entry.body[1].module == "app.features.pipeline_scanned_execution"
    assert isinstance(entry.body[2], ast.Return)
    assert (
        ast.unparse(entry.body[2].value)
        == "run_scanned_pdf(content_or_path, pipeline_id, page_start, page_end, namespace=globals())"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50


def test_imports_remain_lazy_and_single_close_owner_keeps_original_boundary():
    _, inputs = load_role("inputs")
    assert [n.module for n in inputs.body if isinstance(n, ast.ImportFrom)] == [
        "__future__",
        "app.features.pipeline_scanned_state",
    ]
    load = next(n for n in inputs.body if isinstance(n, ast.FunctionDef))
    modules = [n.module for n in load.body if isinstance(n, ast.ImportFrom)]
    assert modules == [
        "app.core.config",
        "app.core.deployment_profile",
        "app.core.ocr_profile",
        "app.services.ocr_service",
    ]
    _, execution = load_role("execution")
    run = next(n for n in execution.body if isinstance(n, ast.FunctionDef))
    assert isinstance(run.body[0], ast.Assign)
    assert isinstance(run.body[1], ast.Try)
    assert ast.unparse(run.body[1].finalbody[0]) == "state.doc.close()"
    assert isinstance(run.body[2], ast.Return)
    assert ast.unparse(run.body[2].value) == "finish_scanned_pdf(state)"
    close_calls = [
        n
        for n in ast.walk(execution)
        if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(".close")
    ]
    assert len(close_calls) == 1


def test_state_has_no_runtime_initializer_and_uses_original_namespace():
    _, tree = load_role("state")
    state = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    assert [n.name for n in state.body if isinstance(n, ast.FunctionDef)] == ["port"]
    port = next(n for n in state.body if isinstance(n, ast.FunctionDef))
    assert (
        ast.unparse(port.body[0])
        == "if name in self.namespace:\n    return self.namespace[name]"
    )
    assert (
        ast.unparse(port.body[1])
        == "if name in _bound_builtins:\n    return _bound_builtins[name]"
    )
    assert isinstance(port.body[2], ast.Raise)
