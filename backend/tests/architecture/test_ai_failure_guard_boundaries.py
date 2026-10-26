"""Provider predicates are pure; revision query ownership stays at its entrypoint."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

AI = Path(__file__).resolve().parents[2] / "app/services/ai"
CALLS = {
    "classify_ai_provider_exception": {
        "str",
        "str(exc or '').lower",
        "getattr",
        "_typed_status",
        "_is_auth_failure",
        "_is_rate_limit_failure",
        "_is_transient_failure",
        "_looks_like_vision_rejection",
        "bool",
    },
    "_is_auth_failure": {"_contains_any"},
    "_is_rate_limit_failure": {"_contains_any"},
    "_is_transient_failure": {"_contains_any"},
    "_contains_any": {"any"},
    "_typed_status": {"getattr", "int", "re.search", "match.group"},
    "_looks_like_vision_rejection": {"_contains_any"},
    "check_analysis_revision_drift": {
        "logging.getLogger",
        "build_answer_grounding",
        "getattr",
        "int",
        "db.scalar",
        "select",
        "select(QuestionVersion).where",
        "logger.warning",
        "_revision_semantics_match",
        "_revision_guard_response",
    },
    "_revision_semantics_match": {
        "build_answer_grounding",
        "getattr",
        "grounding_fact_signature",
    },
    "_revision_guard_response": {
        "build_revision_drift_analysis",
        "datetime.now",
        "datetime.now(UTC).isoformat",
    },
}
LOCALS = {
    "classify_ai_provider_exception": {
        "text",
        "error_kind",
        "typed_retryable",
        "status",
        "retryable",
    },
    "_is_auth_failure": set(),
    "_is_rate_limit_failure": set(),
    "_is_transient_failure": set(),
    "_typed_status": {"raw", "status", "match"},
    "_contains_any": {"token"},
    "_looks_like_vision_rejection": set(),
    "check_analysis_revision_drift": {
        "logger",
        "current_grounding",
        "current_version_id",
        "wrong_version_id",
        "revision",
    },
    "_revision_semantics_match": {"revision_semantics_match", "historical_grounding"},
    "_revision_guard_response": set(),
}
FUNCTIONS = {
    "provider_exception": set(CALLS)
    - {
        "check_analysis_revision_drift",
        "_revision_semantics_match",
        "_revision_guard_response",
    },
    "revision_guard": {
        "check_analysis_revision_drift",
        "_revision_semantics_match",
        "_revision_guard_response",
    },
}
IMPORTS = {
    "provider_exception": {"__future__": {"annotations"}, "re": {None}},
    "revision_guard": {
        "__future__": {"annotations"},
        "datetime": {"UTC", "datetime"},
        "typing": {"Any"},
        "sqlalchemy": {"select"},
        "sqlalchemy.ext.asyncio": {"AsyncSession"},
        "app.ai.answer_grounding": {
            "build_answer_grounding",
            "build_revision_drift_analysis",
            "grounding_fact_signature",
        },
        "app.models.admin": {"QuestionVersion"},
        "logging": {None},
    },
}
SIGNATURES = {
    "classify_ai_provider_exception": "def classify_ai_provider_exception(exc: Exception, *, visual: bool) -> tuple[str, bool, str]: pass",
    "check_analysis_revision_drift": "async def check_analysis_revision_drift(db: AsyncSession, *, wrong_question: Any, question: Any) -> dict | None: pass",
}


def owning_function(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    raise AssertionError("runtime calls belong inside a guard helper")


def inspect_module(source, role):
    assert len(source.splitlines()) <= 300
    parsed = ast.parse(source, feature_version=(3, 11))
    parents = {
        child: parent
        for parent in ast.walk(parsed)
        for child in ast.iter_child_nodes(parent)
    }
    functions = [
        n
        for n in ast.walk(parsed)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert (
        len(functions) == len(FUNCTIONS[role])
        and {n.name for n in functions} == FUNCTIONS[role]
    )
    for function in functions:
        assert function.end_lineno - function.lineno + 1 <= 50
        assert not function.decorator_list
        assert isinstance(function, ast.AsyncFunctionDef) == (
            function.name == "check_analysis_revision_drift"
        )
        if function.name in SIGNATURES:
            expected = ast.parse(SIGNATURES[function.name]).body[0]
            assert ast.dump(function.args) == ast.dump(expected.args)
            assert ast.dump(function.returns) == ast.dump(expected.returns)
    for node in ast.walk(parsed):
        inspect_node(node, parents, role)
    return parsed


def inspect_node(node, parents, role):
    assert not isinstance(
        node, (ast.Global, ast.Nonlocal, ast.Lambda, ast.ClassDef, ast.Delete)
    )
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        aliases = (
            [(a.name, None, a.asname) for a in node.names]
            if isinstance(node, ast.Import)
            else [(node.module, a.name, a.asname) for a in node.names]
        )
        assert not isinstance(node, ast.ImportFrom) or node.level == 0
        for module, name, alias in aliases:
            assert alias is None and name in IMPORTS[role].get(module, set())
            if module == "logging":
                assert owning_function(node, parents) == "check_analysis_revision_drift"
    if isinstance(node, ast.Call):
        assert ast.unparse(node.func) in CALLS[owning_function(node, parents)]
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        if node.id != "__all__":
            assert node.id in LOCALS[owning_function(node, parents)]
    if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(
        node.ctx, ast.Store
    ):
        raise AssertionError("these guards must not mutate caller objects")
    if isinstance(node, ast.Attribute):
        assert not node.attr.startswith("__")


@pytest.mark.parametrize("role", FUNCTIONS)
def test_guards_keep_bounded_helpers_original_signatures_and_owned_dependencies(role):
    inspect_module((AI / f"{role}.py").read_text(), role)


@pytest.mark.parametrize(
    "injection",
    [
        "    db.scalar(None)\n",
        "    globals()\n",
        '    __import__("os")\n',
        "    callback = _contains_any\n",
        "    status = lambda: None\n",
        "    from app.core.database import async_session\n",
        "    text.value = 1\n",
    ],
)
def test_auth_predicate_cannot_acquire_database_dynamic_code_or_write_ports(injection):
    source = (AI / "provider_exception.py").read_text()
    anchor = '    if (\n        error_kind == "auth"\n'
    assert source.count(anchor) == 1
    with pytest.raises(AssertionError):
        inspect_module(source.replace(anchor, injection + anchor), "provider_exception")


@pytest.mark.parametrize(
    "injection",
    [
        "    db.commit()\n",
        "    db.scalar(None)\n",
        "    wrong_question.ai_analysis = {}\n",
        "    logger.warning('unexpected')\n",
        "    clock = datetime.now\n",
    ],
)
def test_response_builder_cannot_query_write_mutate_or_acquire_logger(injection):
    source = (AI / "revision_guard.py").read_text()
    anchor = "def _revision_guard_response() -> dict:\n"
    assert source.count(anchor) == 1
    with pytest.raises(AssertionError):
        inspect_module(source.replace(anchor, anchor + injection), "revision_guard")


@pytest.mark.parametrize(
    "source",
    [
        "pass\n" * 301,
        "def extra():\n" + "    pass\n" * 51,
        "async def extra():\n" + "    pass\n" * 51,
    ],
)
def test_module_and_function_budget_injections_are_rejected(source):
    with pytest.raises(AssertionError):
        inspect_module(source, "provider_exception")


def test_provider_classifier_import_does_not_initialize_models_database_or_services():
    probe = """
import sys
from app.services.ai import provider_exception
for name in ('app.models', 'app.core.config', 'app.core.database',
             'app.services.ai_service', 'app.workers', 'sqlalchemy', 'httpx', 'redis'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=AI.parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("target", ["question", "revision"])
def test_historical_comparison_cannot_delete_input_options(target):
    source = (AI / "revision_guard.py").read_text()
    anchor = "    revision_semantics_match = False\n"
    assert source.count(anchor) == 1
    with pytest.raises(AssertionError):
        inspect_module(
            source.replace(anchor, f'    del {target}.options["A"]\n' + anchor),
            "revision_guard",
        )
