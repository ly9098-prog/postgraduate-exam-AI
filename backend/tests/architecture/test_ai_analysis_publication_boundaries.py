"""Publication helpers are pure synchronous ports after persistence succeeds."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
OUTCOMES = APP / "services/ai/analysis_outcomes.py"
PUBLICATION = APP / "services/ai/analysis_publication.py"
PORTS = {"bool", "len", "grounding_repaired_response", "valid_analysis_response"}
EXPECTED = {
    "grounding_repair_outcome": [
        "wrong_question",
        "user_id",
        "context",
        "result",
        "grounding",
        "usage",
        "image_data_urls",
        "input_signature",
        "model_signature",
        "expected_answer_check",
        "effective_force",
        "runtime",
        "logger",
        "persist",
    ],
    "valid_analysis_outcome": [
        "wrong_question",
        "user_id",
        "context",
        "result",
        "parsed",
        "grounding",
        "usage",
        "image_data_urls",
        "input_signature",
        "model_signature",
        "expected_answer_check",
        "effective_force",
        "visual_evidence_is_valid",
        "max_tokens",
        "runtime",
        "logger",
        "persist",
    ],
}


def tree(source):
    result = ast.parse(source, feature_version=(3, 11))
    assert len(source.splitlines()) <= 300
    for node in ast.walk(result):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            assert node.end_lineno - node.lineno + 1 <= 50
    return result


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


def checked_resolver(parsed):
    resolvers = [n for n in parsed.body if getattr(n, "name", "") == "_port"]
    assert len(resolvers) <= 1
    if not resolvers:
        return set()
    resolver = resolvers[0]
    expected = ast.parse(RESOLVER).body[0]
    assert ast.dump(resolver.args) == ast.dump(expected.args)
    first = resolver.body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    assert isinstance(first.value.value, str)
    assert ast.dump(ast.Module(body=resolver.body[1:], type_ignores=[])) == ast.dump(
        ast.Module(body=expected.body, type_ignores=[])
    )
    return set(ast.walk(resolver))


def assert_port_call(call):
    assert isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_port"
    assert len(call.args) == 2 and not call.keywords
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "namespace"
    assert isinstance(call.args[1], ast.Constant) and call.args[1].value in PORTS


def assert_publication(source):
    parsed = tree(source)
    parents = {
        child: node for node in ast.walk(parsed) for child in ast.iter_child_nodes(node)
    }
    resolver_nodes = checked_resolver(parsed)
    for node in ast.walk(parsed):
        if isinstance(node, ast.Name) and node.id in {"namespace", "_port"}:
            if node not in resolver_nodes:
                call = parents[node]
                assert_port_call(call)
                if node.id == "namespace":
                    assert call.args[0] is node
                else:
                    assert call.func is node
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id == "values":
                assert isinstance(node.slice, ast.Constant) and node.slice.value != "db"
        assert not isinstance(
            node, (ast.Import, ast.ImportFrom, ast.AsyncFunctionDef, ast.Await)
        )
        if isinstance(node, ast.Call):
            assert getattr(node.func, "id", "") not in {
                "open", "eval", "exec", "__import__",
            }
            assert getattr(node.func, "attr", "") not in {
                "commit", "rollback", "execute", "flush", "add", "begin",
                "begin_nested", "connect", "read_text", "write_text",
                "read_bytes", "write_bytes",
            }
    return parsed


def test_outcome_entries_keep_signatures_and_delegate_once_after_persistence():
    parsed = tree(OUTCOMES.read_text())
    for name, keywords in EXPECTED.items():
        entry = next(node for node in parsed.body if getattr(node, "name", "") == name)
        assert isinstance(entry, ast.AsyncFunctionDef)
        assert [arg.arg for arg in entry.args.args] == ["db"]
        assert [arg.arg for arg in entry.args.kwonlyargs] == keywords
        assert entry.args.kw_defaults[:-1] == [None] * (len(keywords) - 1)
        persist_name = "persist_repaired_analysis" if "repair" in name else "persist_valid_analysis"
        assert ast.unparse(entry.args.kw_defaults[-1]) == persist_name
        assert not entry.args.defaults and not entry.args.posonlyargs
        assert entry.args.vararg is None and entry.args.kwarg is None
        assert ast.unparse(entry.args.args[0].annotation) == "AsyncSession"
        assert ast.unparse(entry.returns) == "dict"
        annotations = {
            "wrong_question": "Any", "user_id": "int", "context": "dict",
            "result": "dict", "parsed": "dict", "grounding": "GroundingValidation",
            "usage": "AnalysisUsage", "image_data_urls": "list[str]",
            "input_signature": "str", "model_signature": "str",
            "expected_answer_check": "Any", "effective_force": "bool",
            "runtime": "Any", "logger": "Logger", "max_tokens": "int",
            "visual_evidence_is_valid": "Callable[[str], bool]",
        }
        assert all(
            (arg.annotation is None if arg.arg == "persist"
             else ast.unparse(arg.annotation) == annotations[arg.arg])
            for arg in entry.args.kwonlyargs
        )
        awaits = [node for node in ast.walk(entry) if isinstance(node, ast.Await)]
        assert len(awaits) == 1
        assert ast.unparse(awaits[0].value).startswith("persist(")
        returns = [node for node in entry.body if isinstance(node, ast.Return)]
        assert len(returns) == 1 and "publish_" in ast.unparse(returns[0].value)
    assert_publication(PUBLICATION.read_text())


@pytest.mark.parametrize(
    "source",
    [
        "def f(): pass\n" + "\n" * 300,
        "def f():\n    def inner():\n" + "        pass\n" * 51,
        "async def f(): pass\n",
        "from app.models import User\n",
        "def f(values):\n    return values['db'].commit()\n",
        "def f(values):\n    return values['db'].add(None)\n",
        "def f(namespace):\n    return namespace['unexpected']()\n",
        "def f(namespace):\n    return _port(namespace, 'database')\n",
        "def f(namespace, name):\n    return _port(namespace, name)\n",
        "def f(namespace):\n    lookup = _port\n",
        "value = lambda: (\n" + "    1,\n" * 51 + ")\n",
    ],
)
def test_publication_gate_rejects_runtime_io_and_port_mutations(source):
    with pytest.raises(AssertionError):
        assert_publication(source)


def test_fresh_publication_import_has_no_service_or_runtime_side_effects():
    probe = """
import sys
from app.services.ai.analysis_publication import publish_valid_analysis
assert callable(publish_valid_analysis)
for name in ('app.services.ai.analysis_outcomes', 'app.services.ai_service',
             'app.models', 'app.core.config', 'app.core.database', 'sqlalchemy',
             'redis', 'httpx'):
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


@pytest.mark.parametrize("mutation", ["db", "namespace", "alias", "port_alias"])
def test_actual_publication_helpers_reject_namespace_and_database_escape(mutation):
    injection = {
        "db": '    database = values["db"]\n',
        "namespace": '    namespace["unexpected"]()\n',
        "alias": "    lookup = namespace\n",
        "port_alias": "    lookup = _port\n",
    }[mutation]
    source = PUBLICATION.read_text().replace(
        '    values["logger"].warning(', injection + '    values["logger"].warning(', 1
    )
    with pytest.raises(AssertionError):
        assert_publication(source)


@pytest.mark.parametrize("replace_docstring", [False, True])
def test_resolver_cannot_hide_runtime_io_in_exception_or_first_statement(replace_docstring):
    source = PUBLICATION.read_text()
    anchor = ('    """Resolve original module globals and builtins at each expression site."""'
              if replace_docstring else "    if name in namespace:")
    source = source.replace(anchor, '    namespace["unexpected"]()\n' + anchor, 1)
    with pytest.raises(AssertionError):
        assert_publication(source)
