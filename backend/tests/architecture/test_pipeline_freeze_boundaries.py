"""Freeze stays synchronous, lazy, bounded and limited to mode projection."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.pipeline_freeze_boundary_policy import (
    CALLS,
    ENTRY,
    FUNCTIONS,
    INJECTIONS,
    LAZY_IMPORTS,
    MODULE_IMPORTS,
    POLICY,
    RESULT_KEYS,
    STATE,
    bounded,
    normalized,
)

FEATURES = Path(__file__).resolve().parents[2] / "app/features"
ROLES = (*FUNCTIONS, "state")


def inspect_entry(entry):
    assert isinstance(entry, ast.FunctionDef)
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert ast.get_docstring(entry), "retain the public entry docstring"
    expected = ast.parse(ENTRY).body[0]
    assert normalized(entry) == normalized(expected)


def inspect_import(node, role, function=None):
    assert isinstance(node, ast.ImportFrom) and not node.level
    allowed = LAZY_IMPORTS.get(function, set()) if function else MODULE_IMPORTS[role]
    if not function:
        allowed = allowed | {("__future__", "annotations", None)}
    assert all((node.module, alias.name, alias.asname) in allowed for alias in node.names)


def inspect_attribute(node, parents, function):
    readable, writable, ports, _ = (set(value.split()) for value in POLICY[function])
    assert not node.attr.startswith("__") and node.attr != "namespace"
    if ast.unparse(node.value) == "state":
        assert node.attr in readable | {"port"}
        if isinstance(node.ctx, ast.Store):
            assert node.attr in writable
        if node.attr == "converter":
            assert isinstance(parents[node], ast.Call) and parents[node].func is node
            assert not parents[node].args and not parents[node].keywords
        if node.attr == "port":
            call = parents[node]
            assert isinstance(call, ast.Call) and call.func is node
            assert len(call.args) == 1 and not call.keywords
            assert isinstance(call.args[0], ast.Constant) and call.args[0].value in ports
    else:
        call = parents[node]
        assert isinstance(call, ast.Call) and call.func is node
        assert ast.unparse(node) in CALLS[function]


def inspect_reference(node, parents, function):
    parent = parents[node]
    if node.id == "state":
        if isinstance(node.ctx, ast.Store):
            assert isinstance(parent, ast.Assign)
            expected = (
                "FreezeState(namespace, None, None, None, None)"
                if function == "_load_freeze_inputs"
                else "_load_freeze_inputs(normalized_blocks, namespace=namespace)"
            )
            assert ast.unparse(parent.value) == expected
        elif isinstance(parent, ast.Return):
            assert function == "_load_freeze_inputs"
        elif not isinstance(parent, ast.Attribute):
            assert isinstance(parent, ast.Call) and node in parent.args
            assert isinstance(parent.func, ast.Name)
            assert parent.func.id in CALLS[function] and parent.func.id in POLICY
    if node.id == "namespace":
        assert isinstance(parent, (ast.keyword, ast.Call))
        call = parents[parent] if isinstance(parent, ast.keyword) else parent
        assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        assert call.func.id in {"_load_freeze_inputs", "FreezeState"}


def inspect_store(node, parents, function):
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        assert node.id in POLICY[function][3].split()
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
        assert ast.unparse(node.value) == "result"
        assert isinstance(node.slice, ast.Constant) and node.slice.value in RESULT_KEYS
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "result" for target in node.targets
    ):
        assert ast.unparse(node.value) in {
            "state.port('dict')(state.legacy_result)",
            "{**state.legacy_result}",
        }
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        assert ast.unparse(node.value) == "state"
    if isinstance(node, ast.Assign) and any(
        ast.unparse(target) == "state.ir_to_legacy" for target in node.targets
    ):
        assert ast.unparse(node.value) == "_ir_to_legacy"


def inspect_function(function, role):
    parents = {child: node for node in ast.walk(function) for child in ast.iter_child_nodes(node)}
    assert not function.decorator_list and not function.args.defaults
    locals_ = set(POLICY[function.name][3].split())
    names = {arg.arg for arg in ast.walk(function.args) if isinstance(arg, ast.arg)}
    imports = MODULE_IMPORTS[role] | LAZY_IMPORTS.get(function.name, set())
    names |= {alias or name for _, name, alias in imports}
    names |= locals_ | FUNCTIONS[role] | {"list", "dict", "FreezeState"}
    for node in ast.walk(function):
        assert not isinstance(node, (ast.Delete, ast.Global, ast.Nonlocal, ast.NamedExpr))
        assert not isinstance(node, ast.FunctionDef) or node is function
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            inspect_import(node, role, function.name)
        if isinstance(node, ast.Call):
            assert ast.unparse(node.func) in CALLS[function.name]
        if isinstance(node, ast.Attribute):
            inspect_attribute(node, parents, function.name)
        if isinstance(node, ast.Name):
            assert not isinstance(node.ctx, ast.Load) or node.id in names
            inspect_reference(node, parents, function.name)
        inspect_store(node, parents, function.name)


def inspect_helper(source, role):
    tree = bounded(source)
    if role == "state":
        assert normalized(tree) == normalized(ast.parse(STATE))
        return
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert {node.name for node in functions} == FUNCTIONS[role]
    assert len(functions) == len(FUNCTIONS[role])
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            inspect_function(node, role)
        elif not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            inspect_import(node, role)


@pytest.mark.parametrize("role", ROLES)
def test_helpers_keep_budgets_and_explicit_capabilities(role):
    inspect_helper((FEATURES / f"pipeline_freeze_{role}.py").read_text(), role)


def test_gate_and_policy_keep_the_same_budgets():
    for name in ("pipeline_freeze_boundary_policy.py", "test_pipeline_freeze_boundaries.py"):
        bounded(Path(__file__).with_name(name).read_text())


def test_entry_keeps_full_signature_docstring_and_thin_sync_delegate():
    tree = ast.parse((FEATURES / "pipeline_orchestrator.py").read_text())
    entry = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_run_structure_freeze"
    )
    inspect_entry(entry)
    bindings = [
        alias
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.features.pipeline_freeze_orchestration"
        for alias in node.names
    ]
    assert len(bindings) == 1
    assert bindings[0].name == "run_structure_freeze_mode" and bindings[0].asname is None


@pytest.mark.parametrize("mutation", ["kwargs", "kwonly", "returns", "docstring", "extra", "async"])
def test_entry_gate_rejects_signature_and_hidden_work(mutation):
    entry = ast.parse(ENTRY).body[0]
    entry.body.insert(0, ast.Expr(value=ast.Constant(value="Public stage.")))
    if mutation == "kwargs":
        entry.args.kwarg.arg = "ignored"
    elif mutation == "kwonly":
        entry.args.kwonlyargs = [ast.arg(arg="extra")]
        entry.args.kw_defaults = [ast.Constant(value=None)]
    elif mutation == "returns":
        entry.returns = ast.Name(id="object", ctx=ast.Load())
    elif mutation == "docstring":
        entry.body.pop(0)
    elif mutation == "extra":
        entry.body[1:1] = ast.parse("side_effect()").body
    else:
        entry = ast.AsyncFunctionDef(**entry.__dict__)
    with pytest.raises(AssertionError):
        inspect_entry(ast.parse(ast.unparse(entry)).body[0])


@pytest.mark.parametrize("role,function,statement", INJECTIONS)
def test_actual_helpers_reject_capability_injections(role, function, statement):
    tree = ast.parse((FEATURES / f"pipeline_freeze_{role}.py").read_text())
    target = next(node for node in tree.body if getattr(node, "name", None) == function)
    target.body[0:0] = ast.parse(statement).body
    with pytest.raises(AssertionError):
        inspect_helper(ast.unparse(tree), role)


@pytest.mark.parametrize(
    "mutation", ["module_builtins", "copy", "field", "async", "budget", "eager", "converter"]
)
def test_state_resolver_and_lazy_imports_are_locked(mutation):
    source = (FEATURES / "pipeline_freeze_state.py").read_text()
    if mutation == "module_builtins":
        source = source.replace("_bound_builtins[name]", "self.namespace['__builtins__'][name]")
    elif mutation == "copy":
        source += "\n_bound_builtins = dict(_bound_builtins)\n"
    elif mutation == "field":
        source = source.replace("field(init=False)", "field(default_factory=dict)")
    elif mutation == "async":
        source = source.replace("def port(", "async def port(")
    elif mutation == "budget":
        source += "\n" * 301
    elif mutation == "converter":
        source = source.replace("raise _UnboundLocalError(", "raise _NameError(")
    else:
        source += "\nfrom app.core.config import settings\n"
    with pytest.raises(AssertionError):
        inspect_helper(source, "state")


@pytest.mark.parametrize("mutation", ["eager", "function_budget", "async"])
def test_real_helper_rejects_eager_import_and_function_budget(mutation):
    tree = ast.parse((FEATURES / "pipeline_freeze_projection.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    if mutation == "eager":
        imported = next(node for node in function.body if isinstance(node, ast.ImportFrom))
        function.body.remove(imported)
        tree.body.append(imported)
    elif mutation == "function_budget":
        function.body[:0] = ast.parse("pass\n" * 51).body
    else:
        tree.body[tree.body.index(function)] = ast.AsyncFunctionDef(**function.__dict__)
    with pytest.raises(AssertionError):
        inspect_helper(ast.unparse(tree), "projection")


def test_resolver_uses_live_canonical_builtins_and_global_precedence(monkeypatch):
    from builtins import __dict__ as canonical

    from app.features.pipeline_freeze_state import FreezeState

    namespace = {"__builtins__": {"_freeze_gate_probe": "wrong"}}
    state = FreezeState(namespace, None, None, None, None)
    for value in (object(), object()):
        monkeypatch.setitem(canonical, "_freeze_gate_probe", value)
        assert state.port("_freeze_gate_probe") is value
    namespace["_freeze_gate_probe"] = None
    assert state.port("_freeze_gate_probe") is None
    del namespace["__builtins__"]
    assert state.port("_freeze_gate_probe") is None
    with pytest.raises(NameError) as caught:
        state.port("_freeze_gate_missing")
    assert caught.value.name == "_freeze_gate_missing"


def test_fresh_import_never_attempts_runtime_initialization(tmp_path):
    probe = """
import importlib, sys
attempts = []
blocked = ('app.core.config', 'app.core.database', 'app.features.pipeline_orchestrator',
           'app.features.pipeline_stages', 'app.features.ocr_canary',
           'app.services', 'sqlalchemy', 'redis', 'httpx', 'fitz', 'paddleocr')
class BlockRuntime:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('app.features.ocr') or any(
            fullname == n or fullname.startswith(n + '.') for n in blocked
        ):
            attempts.append(fullname)
            raise AssertionError(fullname)
sys.meta_path.insert(0, BlockRuntime())
for role in ('orchestration', 'projection', 'canary', 'dual', 'state'):
    importlib.import_module('app.features.pipeline_freeze_' + role)
assert not any(n == b or n.startswith(b + '.') for n in sys.modules for b in blocked)
assert not attempts, attempts
"""
    env = {"PATH": os.defpath, "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=FEATURES.parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
