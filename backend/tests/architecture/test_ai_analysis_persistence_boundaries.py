"""AI persistence owns transactions; projection helpers cannot acquire runtime IO."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = APP / "services/ai/analysis_persistence.py"
PROJECTION = MODULE.with_name("analysis_persistence_projection.py")
PORTS = {
    "datetime",
    "UTC",
    "_base_meta",
    "merge_grounded_diagnosis",
    "build_context_snapshot",
}
SIGNATURES = {
    "persist_repaired_analysis": [
        "wrong_question",
        "user_id",
        "context",
        "result",
        "answer_grounding",
        "visual_evidence",
        "visual_ack_retried",
        "visual_ack_retry_ms",
        "image_count",
        "input_signature",
        "model_signature",
        "expected_answer_check",
        "grounding_guard_reason",
        "actual_answer_check",
        "tokens_used",
        "duration_ms",
        "effective_force",
        "runtime",
    ],
    "persist_valid_analysis": [
        "wrong_question",
        "user_id",
        "context",
        "result",
        "parsed",
        "answer_grounding",
        "visual_evidence",
        "visual_ack_retried",
        "visual_ack_retry_ms",
        "image_count",
        "input_signature",
        "model_signature",
        "expected_answer_check",
        "effective_force",
        "tokens_used",
        "duration_ms",
        "runtime",
    ],
}


def bounded_tree(source):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    functions = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    assert functions
    assert all(n.end_lineno - n.lineno + 1 <= 50 for n in functions)
    return tree


RESOLVER = """def _port(namespace: dict, name: str):
    if name in namespace:
        return namespace[name]
    builtins = namespace["__builtins__"]
    if not isinstance(builtins, dict):
        builtins = vars(builtins)
    if name in builtins:
        return builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)
"""


def assert_namespace_access(node, parents, resolver):
    if node in set(ast.walk(resolver)):
        return
    parent = parents[node]
    assert isinstance(parent, ast.Call)
    assert getattr(parent.func, "id", "") == "_port"
    assert len(parent.args) == 2 and parent.args[0] is node


def checked_resolver(tree):
    resolvers = [n for n in tree.body if getattr(n, "name", "") == "_port"]
    assert len(resolvers) <= 1
    resolver = resolvers[0] if resolvers else ast.Module(body=[], type_ignores=[])
    if resolvers:
        expected = ast.parse(RESOLVER).body[0]
        assert ast.dump(resolver.args) == ast.dump(expected.args)
        first = resolver.body[0]
        assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
        assert isinstance(first.value.value, str)
        assert ast.dump(
            ast.Module(body=resolver.body[1:], type_ignores=[])
        ) == ast.dump(ast.Module(body=expected.body, type_ignores=[]))
    return resolver


def assert_projection(source):
    tree = bounded_tree(source)
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    resolver = checked_resolver(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "namespace":
            assert_namespace_access(node, parents, resolver)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id == "values":
                assert isinstance(node.slice, ast.Constant) and node.slice.value != "db"
        assert not isinstance(node, (ast.Import, ast.AsyncFunctionDef, ast.Await))
        if isinstance(node, ast.ImportFrom):
            assert node.module == "app.ai.answer_grounding" and not node.level
            assert [(n.name, n.asname) for n in node.names] == [
                ("build_safe_grounded_analysis", None)
            ]
        if isinstance(node, ast.Name) and node.id == "_port":
            call = parents[node]
            assert isinstance(call, ast.Call) and call.func is node
            assert len(call.args) == 2 and not call.keywords
            assert ast.unparse(call.args[0]) == "namespace"
            assert (
                isinstance(call.args[1], ast.Constant) and call.args[1].value in PORTS
            )
        if isinstance(node, ast.Call):
            assert getattr(node.func, "id", "") not in {
                "open",
                "exec",
                "eval",
                "__import__",
            }
            assert getattr(node.func, "attr", "") not in {
                "add",
                "commit",
                "rollback",
                "execute",
                "flush",
                "begin",
                "begin_nested",
                "connect",
                "read_text",
                "write_text",
                "read_bytes",
                "write_bytes",
            }
    return tree


def test_persistence_and_projection_keep_budgets_and_stable_entry_signatures():
    tree = bounded_tree(MODULE.read_text())
    assert_projection(PROJECTION.read_text())
    for name, keywords in SIGNATURES.items():
        entry = next(n for n in tree.body if getattr(n, "name", "") == name)
        assert isinstance(entry, ast.AsyncFunctionDef)
        assert [arg.arg for arg in entry.args.args] == ["db"]
        assert [arg.arg for arg in entry.args.kwonlyargs] == keywords
        assert entry.args.kw_defaults == [None] * len(keywords)
        assert not entry.args.defaults and entry.args.vararg is None
        assert entry.args.kwarg is None
        commits = [
            n
            for n in ast.walk(entry)
            if isinstance(n, ast.Await) and ast.unparse(n.value) == "db.commit()"
        ]
        assert len(commits) == 1
        append = [
            n
            for n in ast.walk(entry)
            if isinstance(n, ast.Await)
            and isinstance(n.value, ast.Call)
            and getattr(n.value.func, "id", "") == "_append_analysis_chat"
        ]
        assert len(append) == 1 and commits[0].lineno < append[0].lineno


@pytest.mark.parametrize(
    "source",
    [
        "def f(): pass\n" + "\n" * 300,
        "def f():\n    def inner():\n" + "        pass\n" * 51,
        "async def f(): pass\n",
        "def f():\n    return open('payload')\n",
        "from app.core.config import settings\n",
        "from app.ai.answer_grounding import build_safe_grounded_analysis as other\n",
        "def f(db):\n    return db.commit()\n",
        "def f(db):\n    return db.rollback()\n",
        "def f(namespace):\n    return _port(namespace, 'database')\n",
        "def f(namespace, name):\n    return _port(namespace, name)\n",
        "def f(namespace):\n    lookup = _port\n",
        "def f(namespace):\n    return other(_port)\n",
        "value = lambda: (\n" + "    1,\n" * 51 + ")\n",
    ],
)
def test_projection_gate_rejects_io_budget_and_port_mutations(source):
    with pytest.raises(AssertionError):
        assert_projection(source)


def test_fresh_projection_import_does_not_initialize_models_runtime_or_ai():
    probe = """
import sys
from app.services.ai.analysis_persistence_projection import prepare_valid_result
assert callable(prepare_valid_result)
for name in (
    'app.services.ai.analysis_persistence', 'app.services.ai_service',
    'app.ai.answer_grounding', 'app.models', 'app.core.config', 'app.core.database',
    'sqlalchemy', 'redis', 'httpx',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation", ["add", "db_alias", "namespace", "namespace_alias"]
)
def test_actual_projection_helpers_reject_orm_and_namespace_bypasses(mutation):
    source = PROJECTION.read_text()
    line = {
        "add": '    values["db"].add(None)\n',
        "db_alias": '    database = values["db"]\n',
        "namespace": '    namespace["unexpected_port"]()\n',
        "namespace_alias": "    lookup = namespace\n",
    }[mutation]
    anchor = "    from app.ai.answer_grounding import build_safe_grounded_analysis\n"
    assert source.count(anchor) == 1
    source = source.replace(anchor, anchor + line)
    with pytest.raises(AssertionError):
        assert_projection(source)


def test_resolver_exception_does_not_allow_arbitrary_namespace_calls():
    source = PROJECTION.read_text().replace(
        "    if name in namespace:",
        '    namespace["unexpected_port"]()\n    if name in namespace:',
    )
    with pytest.raises(AssertionError):
        assert_projection(source)


def test_resolver_docstring_cannot_be_replaced_with_runtime_call():
    tree = ast.parse(PROJECTION.read_text())
    resolver = next(node for node in tree.body if getattr(node, "name", "") == "_port")
    resolver.body[0] = ast.parse('namespace["unexpected_port"]()').body[0]
    with pytest.raises(AssertionError):
        assert_projection(ast.unparse(tree))
