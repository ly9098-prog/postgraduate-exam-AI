"""VL rebuild stays synchronous, bounded, lazy and free of transaction ownership."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.test_pipeline_chunked_boundaries import RESOLVER
from tests.architecture.vl_rebuild_boundary_support import CALLS, ENTRY, POLICY, owner

FEATURES = Path(__file__).resolve().parents[2] / "app/features"
ROLES = ("guard", "source", "select", "merge", "publish", "state")
IMPORTS = {
    "__future__",
    "dataclasses",
    "typing",
    "app.features.pipeline_vl_rebuild_state",
    "app.features.ocr_fix.router",
    "app.core.deployment_profile",
    "app.features.ocr_correction_common",
    "app.features.question_type_classifier",
    "app.services.ocr_service",
    "app.features.option_recovery",
}
PORTS = {
    "Exception",
    "logger",
    "any",
    "len",
    "range",
    "open",
    "_run_coro_in_loop",
    "getattr",
    "isinstance",
    "dict",
    "str",
    "set",
    "list",
    "max",
    "re",
}
LAZY_IMPORTS = IMPORTS - {
    "__future__",
    "dataclasses",
    "typing",
    "app.features.pipeline_vl_rebuild_state",
}


def locked_resolver_nodes(tree):
    resolver = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "port"
        ),
        None,
    )
    if resolver is not None:
        assert ast.dump(resolver) == ast.dump(ast.parse(RESOLVER).body[0])
    return set(ast.walk(resolver)) if resolver is not None else set()


def inspect_helper(source):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    excluded = locked_resolver_nodes(tree)
    for node in ast.walk(tree):
        if node in excluded:
            continue
        assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await))
        if isinstance(node, (ast.FunctionDef, ast.Lambda)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in IMPORTS
            if node.module in LAZY_IMPORTS:
                parent = parents[node]
                while parent in parents and not isinstance(parent, ast.FunctionDef):
                    parent = parents[parent]
                assert isinstance(parent, ast.FunctionDef)
        if isinstance(node, ast.Import):
            assert all(alias.name in {"fitz", "os"} for alias in node.names)
            assert isinstance(parents[node], ast.FunctionDef)
        if isinstance(node, ast.Attribute):
            inspect_state_attribute(node, parents)
        if isinstance(node, ast.Name) and node.id == "state":
            parent = parents[node]
            if not isinstance(parent, ast.Attribute):
                assert isinstance(parent, ast.Call) and node in parent.args
                assert getattr(parent.func, "id", "") in CALLS.get(
                    owner(node, parents), set()
                )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            inspect_named_call(node, parents)
    return tree


def inspect_named_call(node, parents):
    if node.func.id == "field":
        assert ast.dump(node) == ast.dump(
            ast.parse("field(init=False)", mode="eval").body
        )
        declaration = parents[node]
        assert isinstance(declaration, ast.AnnAssign)
        assert isinstance(parents[declaration], ast.ClassDef)
        assert parents[declaration].name == "VlRebuildState"
        return
    assert node.func.id in CALLS.get(owner(node, parents), set())


def inspect_state_attribute(node, parents):
    assert node.attr not in {
        "commit",
        "rollback",
        "flush",
        "unlink",
        "write",
        "execute",
        "namespace",
    }
    if ast.unparse(node.value) != "state":
        return
    values, ports, fields = (set(item.split()) for item in POLICY[owner(node, parents)])
    assert node.attr in fields | {"port", "values"}
    parent = parents[node]
    if node.attr == "port":
        assert isinstance(parent, ast.Call) and parent.func is node
        assert len(parent.args) == 1 and isinstance(parent.args[0], ast.Constant)
        assert parent.args[0].value in ports & PORTS and not parent.keywords
    if node.attr == "values":
        assert isinstance(parent, ast.Subscript) and isinstance(parent.ctx, ast.Load)
        assert isinstance(parent.slice, ast.Constant) and parent.slice.value in values


@pytest.mark.parametrize("role", ROLES)
def test_vl_helpers_are_bounded_and_keep_runtime_dependencies_lazy(role):
    inspect_helper((FEATURES / f"pipeline_vl_rebuild_{role}.py").read_text())


def test_original_entry_retains_sync_signature_and_exception_scope():
    tree = ast.parse((FEATURES / "pipeline_orchestrator.py").read_text())
    entry = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run_vl_rebuild_blocks"
    )
    inspect_entry(entry)


def inspect_entry(entry):
    assert isinstance(entry, ast.FunctionDef)
    assert entry.end_lineno - entry.lineno + 1 <= 50
    expected = ast.parse(ENTRY).body[0]
    assert ast.dump(entry.args) == ast.dump(expected.args)
    assert ast.dump(entry.returns) == ast.dump(expected.returns)
    assert isinstance(entry.body[-1], ast.Try)
    assert ast.unparse(entry.body[-1].handlers[0].type) == "Exception"
    assert not any(isinstance(node, ast.Await) for node in ast.walk(entry))


@pytest.mark.parametrize(
    "source",
    [
        "async def rebuild():\n    pass\n",
        "def rebuild():\n" + "    pass\n" * 51,
        "from app.core.database import async_session\n",
        "from app.features.ocr_fix.router import OCRFixRouter\n",
        "def rebuild(state):\n    state.port(name)()\n",
        "def rebuild(state):\n    state.port('database')()\n",
        "def rebuild(db):\n    db.commit()\n",
        "def rebuild():\n    __import__('socket')\n",
    ],
)
def test_gate_rejects_interface_budget_runtime_and_transaction_regressions(source):
    with pytest.raises(AssertionError):
        inspect_helper(source)


@pytest.mark.parametrize(
    "role,method,statement",
    [
        ("guard", "rebuild_vl_input_guard", 'state.namespace["unexpected"] = True'),
        (
            "publish",
            "publish_vl_rebuild_block",
            'state.values["self"].db.execute(None)',
        ),
        ("publish", "publish_vl_rebuild_block", 'state.port("open")("unexpected")'),
        ("guard", "rebuild_vl_input_guard", 'state.values["vl_config"] = {}'),
        ("publish", "publish_vl_rebuild_block", "load_vl_rebuild_sources(state)"),
        (
            "publish",
            "publish_vl_rebuild_block",
            "from app.features.ocr_fix.router import OCRFixRouter\nOCRFixRouter()",
        ),
    ],
)
def test_gate_rejects_capability_injections_in_real_helpers(role, method, statement):
    source = (FEATURES / f"pipeline_vl_rebuild_{role}.py").read_text()
    tree = ast.parse(source)
    function = next(node for node in tree.body if getattr(node, "name", "") == method)
    function.body[1:1] = ast.parse(statement).body
    with pytest.raises(AssertionError):
        inspect_helper(ast.unparse(tree))


@pytest.mark.parametrize("mutation", ["kwargs", "kwonly", "returns"])
def test_full_signature_gate_rejects_optional_or_variadic_api_changes(mutation):
    tree = ast.parse((FEATURES / "pipeline_orchestrator.py").read_text())
    entry = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run_vl_rebuild_blocks"
    )
    if mutation == "kwargs":
        entry.args.kwarg = ast.arg(arg="ignored")
    elif mutation == "kwonly":
        entry.args.kwonlyargs = [ast.arg(arg="optional")]
        entry.args.kw_defaults = [ast.Constant(value=None)]
    else:
        entry.returns = ast.Name(id="dict", ctx=ast.Load())
    with pytest.raises(AssertionError):
        inspect_entry(entry)


def test_fresh_helpers_import_without_initializing_ocr_or_database():
    probe = """
import importlib
import sys
for role in ('guard', 'source', 'select', 'merge', 'publish', 'state'):
    importlib.import_module('app.features.pipeline_vl_rebuild_' + role)
for name in (
    'app.features.pipeline_orchestrator', 'app.core.config', 'app.core.database',
    'app.services.ocr_service', 'app.features.ocr_fix.router',
    'app.features.option_recovery', 'fitz', 'sqlalchemy', 'redis', 'httpx',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=FEATURES.parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
