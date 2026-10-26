"""Resume helpers retain bounded responsibilities, captured imports and live ports."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.resume_boundary_support import (
    ENTRY,
    FUNCTIONS,
    PORTS,
    STATE_FIELDS,
    VALUES,
)
from tests.architecture.test_pipeline_chunked_boundaries import RESOLVER, bounded

FEATURES = Path(__file__).resolve().parents[2] / "app/features"


def owner(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    raise AssertionError("runtime calls must be inside a helper")


def check_import(node, role, parents):
    assert isinstance(node, ast.ImportFrom) and not node.level
    allowed = {"__future__": {"annotations"}}
    if role == "state":
        allowed.update({"dataclasses": {"dataclass", "field"}, "typing": {"Any"}})
    else:
        allowed["app.features.pipeline_resume_state"] = {"ResumeRunState"}
    if node.module == "app.services.watermark_service":
        assert role == "context" and owner(node, parents) == "resolve_resume_watermarks"
        allowed[node.module] = {"load_rules", "get_default_patterns"}
    assert node.module in allowed
    assert all(n.asname is None and n.name in allowed[node.module] for n in node.names)


def check_attribute(node, parents):
    assert not node.attr.startswith("__") and node.attr != "namespace"
    if isinstance(node.value, ast.Name) and node.value.id == "state":
        assert node.attr in STATE_FIELDS[owner(node, parents)] | {"port", "values"}
    if node.attr in {"port", "values"}:
        assert ast.unparse(node.value) == "state"
        parent = parents[node]
        name = owner(node, parents)
        if node.attr == "port":
            assert isinstance(parent, ast.Call) and parent.func is node
            assert len(parent.args) == 1 and not parent.keywords
            assert isinstance(parent.args[0], ast.Constant)
            assert parent.args[0].value in PORTS[name]
        else:
            assert isinstance(parent, ast.Subscript) and parent.value is node
            assert (
                isinstance(parent.slice, ast.Constant)
                and parent.slice.value in VALUES[name]
            )
    if node.attr == "session_factory":
        if isinstance(node.ctx, ast.Store):
            assert owner(node, parents) == "load_resume_pipeline"
        else:
            call = parents[node]
            assert isinstance(call, ast.Call) and call.func is node
            assert not call.args and not call.keywords
    if node.attr == "execute":
        assert owner(node, parents) in {"load_resume_pipeline", "load_resume_chunks"}
        assert ast.unparse(node.value) == "state.values['db']"
    assert node.attr not in {
        "commit",
        "rollback",
        "flush",
        "add",
        "connect",
        "read_text",
        "write_text",
        "read_bytes",
        "write_bytes",
    }


def inspect_helper(source, role):
    parsed = bounded(source)
    parents = {c: n for n in ast.walk(parsed) for c in ast.iter_child_nodes(n)}
    functions = [
        n
        for n in ast.walk(parsed)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert {n.name for n in functions} == FUNCTIONS[role]
    assert all(
        isinstance(n, ast.AsyncFunctionDef)
        == (n.name not in {"port", "resolve_resume_mode"})
        for n in functions
    )
    resolver = set()
    if role == "state":
        assert ast.dump(functions[0]) == ast.dump(ast.parse(RESOLVER).body[0])
        resolver = set(ast.walk(functions[0]))
    for node in ast.walk(parsed):
        if node in resolver:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            check_import(node, role, parents)
        if isinstance(node, ast.Name) and node.id == "state":
            parent = parents[node]
            if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name):
                assert parent.func.id == "start_resume_replay"
                assert owner(node, parents) == "execute_resume_replay"
                assert parent.args == [node] and not parent.keywords
            else:
                assert isinstance(parent, ast.Attribute) and parent.value is node
        if isinstance(node, ast.Attribute):
            check_attribute(node, parents)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if role == "state":
                assert node.func.id == "field"
            else:
                assert (owner(node, parents), node.func.id) in {
                    ("resolve_resume_watermarks", "load_rules"),
                    ("resolve_resume_watermarks", "get_default_patterns"),
                    ("execute_resume_replay", "start_resume_replay"),
                }
    return parsed


def inspect_entry(source):
    parsed = ast.parse(source)
    entry = next(
        n
        for n in parsed.body
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "resume_pipeline_background"
    )
    expected = ast.parse(ENTRY).body[0]
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert ast.dump(entry.args) == ast.dump(expected.args)
    assert ast.dump(entry.returns) == ast.dump(expected.returns)
    assert isinstance(entry.body[0], ast.Expr)
    assert isinstance(entry.body[0].value, ast.Constant)
    assert isinstance(entry.body[0].value.value, str)
    assert ast.dump(ast.Module(body=entry.body[1:], type_ignores=[])) == ast.dump(
        ast.Module(body=expected.body[1:], type_ignores=[])
    )


def test_resume_entry_signature_captured_imports_and_exact_delegation():
    inspect_entry((FEATURES / "pipeline_orchestrator.py").read_text())
    assert {
        p.stem.removeprefix("pipeline_resume_")
        for p in FEATURES.glob("pipeline_resume_*.py")
    } == set(FUNCTIONS)
    for role in FUNCTIONS:
        inspect_helper((FEATURES / f"pipeline_resume_{role}.py").read_text(), role)


@pytest.mark.parametrize(
    "injection",
    [
        '    state.namespace["escape"]()\n',
        "    alias = state.namespace\n",
        "    alias = state.port\n",
        "    alias = state.values\n",
        "    alias = state\n",
        '    alias = state.__dict__["namespace"]\n',
        '    state.port("database")()\n',
        "    state.port(name)()\n",
        "    globals()\n",
        '    open("payload")\n',
        "    state.shared.commit()\n",
        "    state.session_factory()\n",
        '    state.values["db"].execute(None)\n',
    ],
)
def test_mode_helper_rejects_dynamic_port_namespace_and_database_escape(injection):
    source = (FEATURES / "pipeline_resume_context.py").read_text()
    anchor = '    state.mode_str = state.opts.get("import_mode", "auto")\n'
    assert source.count(anchor) == 1
    with pytest.raises(AssertionError):
        inspect_helper(source.replace(anchor, injection + anchor), "context")


@pytest.mark.parametrize(
    "injection",
    [
        "    state.session_factory()\n",
        '    state.values["db"].execute(None)\n',
        '    state.port("_derive_session_factory")(None)\n',
        "    alias = state.port\n",
        "    from app.core.database import async_session\n",
    ],
)
def test_watermark_helper_cannot_acquire_sessions_or_write_database(injection):
    source = (FEATURES / "pipeline_resume_context.py").read_text()
    anchor = "    state.watermark_patterns = []\n"
    assert source.count(anchor) == 1
    with pytest.raises(AssertionError):
        inspect_helper(source.replace(anchor, injection + anchor), "context")


def test_helpers_fresh_import_does_not_boot_runtime():
    probe = """
import sys
from app.features import pipeline_resume_input, pipeline_resume_context
from app.features import pipeline_resume_execution, pipeline_resume_result
for name in ('app.features.pipeline_orchestrator', 'app.features.pipeline_checkpoint',
             'app.features.global_hash_index', 'app.services.watermark_service',
             'app.models', 'app.core.config', 'app.core.database', 'sqlalchemy', 'redis', 'httpx'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=FEATURES.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("statement", ["await db.commit()", "db.execute(None)", "None"])
def test_entry_cannot_hide_an_executable_first_statement(statement):
    source = (FEATURES / "pipeline_orchestrator.py").read_text()
    parsed = ast.parse(source)
    entry = next(
        n
        for n in parsed.body
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "resume_pipeline_background"
    )
    lines = source.splitlines(keepends=True)
    doc = entry.body[0]
    lines[doc.lineno - 1 : doc.end_lineno] = ["    " + statement + "\n"]
    with pytest.raises(AssertionError):
        inspect_entry("".join(lines))


@pytest.mark.parametrize(
    "injection",
    [
        "    state.cached_factory = state.session_factory\n",
        "    state.opts = state.session_factory\n",
    ],
)
def test_loading_helper_cannot_export_factory_through_derived_alias(injection):
    source = (FEATURES / "pipeline_resume_input.py").read_text()
    anchor = "    state.pipeline_row = (\n"
    assert source.count(anchor) == 1
    with pytest.raises(AssertionError):
        inspect_helper(source.replace(anchor, injection + anchor), "input")


def test_watermark_helper_cannot_call_a_derived_factory():
    source = (FEATURES / "pipeline_resume_context.py").read_text()
    anchor = "    state.watermark_patterns = []\n"
    injection = (
        "    async with state.cached_factory() as unexpected_db:\n        pass\n"
    )
    with pytest.raises(AssertionError):
        inspect_helper(source.replace(anchor, injection + anchor), "context")
