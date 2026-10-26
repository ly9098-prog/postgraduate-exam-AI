"""Chunked helpers keep bounded responsibilities and historical live ports."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

FEATURES = Path(__file__).resolve().parents[2] / "app/features"
FUNCTIONS = {
    "state": {"port"},
    "input": {"prepare_chunked_run", "initialize_chunked_checkpoints",
              "load_chunked_hash_index", "start_chunked_run"},
    "execution": {"execute_chunked_loop"},
    "result": {"finalize_chunked_checkpoint", "aggregate_chunked_result",
               "log_chunked_result", "project_chunked_result"},
}
PORTS = {
    "prepare_chunked_run": {"_resolve_chunk_size", "_resolve_chunk_overlap",
                            "_derive_session_factory", "_serialize_watermark_patterns"},
    "initialize_chunked_checkpoints": set(),
    "load_chunked_hash_index": {"Exception", "logger"},
    "start_chunked_run": {"set", "logging", "time", "log_event", "len"},
    "execute_chunked_loop": {"enumerate", "len"},
    "finalize_chunked_checkpoint": set(),
    "aggregate_chunked_result": {"len", "sum", "_merge_risk_flag_counts",
                                 "serialize_utc_datetime", "utcnow", "next"},
    "log_chunked_result": {"log_event", "len", "round", "time"},
    "project_chunked_result": {"dict"},
}
VALUES = {
    "input": {"shared", "chunk_ranges", "db", "ckpt", "self", "source_type",
              "source_file", "GlobalHashIndex"},
    "execution": {"chunk_ranges", "self", "file_content", "file_path", "source_type",
                  "source_file", "subject", "subject_id", "opts", "progress_callback",
                  "started_at", "page_images", "page_image_refs"},
    "result": {"ckpt", "self", "chunk_ranges", "started_at"},
}
RESOLVER = '''
def port(self, name: str) -> Any:
    """Resolve the original global or builtin at each expression site."""
    if name in self.namespace:
        return self.namespace[name]
    builtins = self.namespace["__builtins__"]
    if not isinstance(builtins, dict):
        builtins = vars(builtins)
    if name in builtins:
        return builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)
'''
ENTRY = '''
async def _run_chunked(
    self, *, file_content: bytes | None, file_path: str | None,
    source_type: str, source_file: str, subject: str | None,
    subject_id: int | None = None, opts: dict, db, shared: dict,
    progress_callback, chunk_ranges: list[tuple[int, int]], started_at: str,
    page_images: dict[int, bytes] | None = None,
    page_image_refs: dict[int, str] | None = None,
) -> dict:
    """Entry documentation."""
    from app.features import pipeline_checkpoint as ckpt
    from app.features.global_hash_index import GlobalHashIndex
    state = ChunkedRunState(locals(), globals())
    prepare_chunked_run(state)
    await initialize_chunked_checkpoints(state)
    await load_chunked_hash_index(state)
    start_chunked_run(state)
    await execute_chunked_loop(state)
    await finalize_chunked_checkpoint(state)
    aggregate_chunked_result(state)
    log_chunked_result(state)
    return project_chunked_result(state)
'''


def bounded(source):
    assert len(source.splitlines()) <= 300
    parsed = ast.parse(source, feature_version=(3, 11))
    for node in ast.walk(parsed):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            assert node.end_lineno - node.lineno + 1 <= 50
    return parsed


def resolver_nodes(parsed, role):
    if role != "state":
        return set()
    resolver = next(n for n in ast.walk(parsed) if isinstance(n, ast.FunctionDef))
    assert ast.dump(resolver) == ast.dump(ast.parse(RESOLVER).body[0])
    return set(ast.walk(resolver))


def owning_function(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    raise AssertionError("runtime expressions must belong to a helper")


def check_attribute(node, parents, role):
    assert not node.attr.startswith("__")
    if node.attr == "namespace":
        raise AssertionError("namespace access must stay inside the exact resolver")
    if node.attr == "port":
        call = parents[node]
        assert ast.unparse(node.value) == "state"
        assert isinstance(call, ast.Call) and call.func is node
        assert len(call.args) == 1 and not call.keywords
        assert isinstance(call.args[0], ast.Constant)
        assert call.args[0].value in PORTS[owning_function(node, parents)]
    if node.attr == "values":
        assert ast.unparse(node.value) == "state"
        subscript = parents[node]
        assert isinstance(subscript, ast.Subscript) and subscript.value is node
        assert isinstance(subscript.slice, ast.Constant)
        assert subscript.slice.value in VALUES[role]
        if subscript.slice.value == "self":
            access = parents[subscript]
            assert isinstance(access, ast.Attribute) and access.value is subscript
            allowed = {"input": {"pipeline_id", "created_by", "source_sha256"},
                       "execution": {"_execute_chunk"}, "result": {"pipeline_id"}}
            assert access.attr in allowed[role]
        if subscript.slice.value == "ckpt":
            assert owning_function(node, parents) in {
                "initialize_chunked_checkpoints", "finalize_chunked_checkpoint",
            }
        if subscript.slice.value == "db":
            call = parents[subscript]
            assert isinstance(call, ast.Call) and call.args == [subscript]
            assert ast.unparse(call.func) == "state.port('_derive_session_factory')"
    if node.attr == "session_factory":
        assert owning_function(node, parents) in {
            "prepare_chunked_run", "initialize_chunked_checkpoints",
            "load_chunked_hash_index", "execute_chunked_loop", "finalize_chunked_checkpoint",
        }


def check_import(node, role):
    assert isinstance(node, ast.ImportFrom) and not node.level
    allowed = {"__future__": {"annotations"}}
    if role == "state":
        allowed.update({"dataclasses": {"dataclass", "field"}, "typing": {"Any"}})
    else:
        allowed["app.features.pipeline_chunked_state"] = {"ChunkedRunState"}
    assert node.module in allowed
    assert all(n.asname is None and n.name in allowed[node.module] for n in node.names)


def inspect_helper(source, role):
    parsed = bounded(source)
    parents = {c: n for n in ast.walk(parsed) for c in ast.iter_child_nodes(n)}
    functions = {n.name for n in ast.walk(parsed)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert functions == FUNCTIONS[role]
    asynchronous = {"initialize_chunked_checkpoints", "load_chunked_hash_index",
                    "execute_chunked_loop", "finalize_chunked_checkpoint"}
    assert all(isinstance(n, ast.AsyncFunctionDef) == (n.name in asynchronous)
               for n in ast.walk(parsed)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    resolver = resolver_nodes(parsed, role)
    for node in ast.walk(parsed):
        if node in resolver:
            continue
        if isinstance(node, ast.Name) and node.id == "state":
            parent = parents[node]
            assert isinstance(parent, ast.Attribute) and parent.value is node
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            check_import(node, role)
        if isinstance(node, ast.Attribute):
            check_attribute(node, parents, role)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert role == "state" and node.func.id == "field"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                "commit", "rollback", "execute", "flush", "add", "connect",
                "read_text", "write_text", "read_bytes", "write_bytes",
            }
    return parsed


def test_chunked_entry_keeps_full_signature_imports_and_ordered_ownership():
    parsed = ast.parse((FEATURES / "pipeline_orchestrator.py").read_text())
    entry = next(n for n in ast.walk(parsed)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_chunked")
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
    actual = {p.stem.removeprefix("pipeline_chunked_")
              for p in FEATURES.glob("pipeline_chunked_*.py")}
    assert actual == set(FUNCTIONS)
    for role in FUNCTIONS:
        inspect_helper((FEATURES / f"pipeline_chunked_{role}.py").read_text(), role)


@pytest.mark.parametrize("injection", [
    '    state.namespace["escape"]()\n',
    "    lookup = state.namespace\n",
    "    lookup = state.port\n",
    "    lookup = state.values\n",
    "    lookup = state\n",
    '    lookup = state.__dict__["namespace"]\n',
    '    database = state.values["db"]\n',
    '    state.port("database")()\n',
    "    state.port(name)()\n",
    "    globals()\n",
    '    open("payload")\n',
    "    state.shared.commit()\n",
])
def test_actual_input_helper_rejects_namespace_database_and_port_escape(injection):
    source = (FEATURES / "pipeline_chunked_input.py").read_text()
    anchor = '    state.shared = state.values["shared"]\n'
    assert source.count(anchor) == 1
    with pytest.raises(AssertionError):
        inspect_helper(source.replace(anchor, injection + anchor), "input")


@pytest.mark.parametrize("mutation", ["body", "docstring"])
def test_exact_resolver_cannot_hide_additional_runtime_calls(mutation):
    source = (FEATURES / "pipeline_chunked_state.py").read_text()
    anchor = ('        if name in self.namespace:' if mutation == "body"
              else '        """Resolve the original global or builtin at each expression site."""')
    assert anchor in source
    with pytest.raises(AssertionError):
        inspect_helper(source.replace(anchor, '        self.namespace["escape"]()\n' + anchor), "state")


@pytest.mark.parametrize("injection", [
    '    checkpoint = state.values["ckpt"]\n',
    "    session = state.session_factory()\n",
    '    session = state.port("_derive_session_factory")(None)()\n',
    '    lookup = state.__dict__["namespace"]\n',
    '    lookup = state.__dict__["values"]["db"]\n',
    '    run = state.values["self"]._execute_chunk\n',
])
def test_result_projection_cannot_acquire_checkpoint_or_session_ports(injection):
    source = (FEATURES / "pipeline_chunked_result.py").read_text()
    anchor = '    return {\n'
    assert source.count(anchor) == 1
    with pytest.raises(AssertionError):
        inspect_helper(source.replace(anchor, injection + anchor), "result")


@pytest.mark.parametrize("source", [
    "void\n" * 301,
    "def f():\n" + "    pass\n" * 51,
    "def f():\n    def inner():\n" + "        pass\n" * 51,
    "value = lambda: (\n" + "    1,\n" * 51 + ")\n",
])
def test_helper_gate_rejects_module_and_nested_function_budget_injections(source):
    with pytest.raises(AssertionError):
        bounded(source)


def test_fresh_helpers_do_not_import_runtime_database_or_orchestrator():
    probe = """
import sys
from app.features import pipeline_chunked_input, pipeline_chunked_execution, pipeline_chunked_result
for name in ('app.features.pipeline_orchestrator', 'app.features.pipeline_checkpoint',
             'app.features.global_hash_index', 'app.models', 'app.core.config',
             'app.core.database', 'sqlalchemy', 'redis', 'httpx'):
    assert name not in sys.modules, name
"""
    result = subprocess.run([sys.executable, "-B", "-c", probe],
                            cwd=FEATURES.parent.parent, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
