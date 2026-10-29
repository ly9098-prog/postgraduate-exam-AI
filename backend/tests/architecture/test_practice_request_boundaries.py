"""Practice request ownership, route declarations and import isolation."""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "backend/app/services/practice/request_submission.py"
ROUTE = ROOT / "backend/app/api/v1/practice.py"
PORTS = {
    "str",
    "len",
    "get_log_context",
    "normalize_trace_id",
    "debug_log",
    "save_debug_snapshot",
    "svc",
    "HTTPException",
    "logger",
    "cache",
    "ValueError",
    "AnswerResult",
    "BatchSubmitResponse",
}
ATTRIBUTE_CALLS = {
    ast.dump(ast.parse(expression, mode="eval").body)
    for expression in (
        'ports("get_log_context")().get',
        'ports("svc").batch_submit_answers',
        "a.model_dump",
        "data.session.model_dump",
        'ports("logger").warning',
        'ports("cache").delete',
        "result.get",
    )
}


def validate_service(source):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source)
    functions = []
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef):
            functions.append(node.name)
            assert node.end_lineno - node.lineno + 1 <= 50
            assert not node.decorator_list
            assert [arg.arg for arg in node.args.kwonlyargs] == ["ports"]
        elif isinstance(node, ast.ImportFrom):
            assert node.module == "__future__"
        else:
            assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    assert functions == ["batch_submit", "_submit_answers"]
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            raise AssertionError("Submission requests must not import dependencies")
        if isinstance(node, ast.ImportFrom):
            assert node in tree.body and node.module == "__future__"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id in {"ports", "_submit_answers"}
            if node.func.id == "ports":
                assert len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
                used.add(node.args[0].value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert ast.dump(node.func) in ATTRIBUTE_CALLS
    assert used == PORTS


def validate_entry(source):
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    route = functions["batch_submit"]
    expected = ast.parse(
        "async def batch_submit():\n"
        "    return await _request_submission.batch_submit(\n"
        "        data, x_trace_id, db, current_user, ports=_practice_request_port\n"
        "    )"
    ).body[0]
    assert ast.dump(ast.Module(body=route.body, type_ignores=[])) == ast.dump(
        ast.Module(body=expected.body, type_ignores=[])
    )
    resolver = functions["_practice_request_port"]
    assert resolver.end_lineno - resolver.lineno + 1 <= 50
    return functions


def test_submission_responsibility_stays_bounded_and_has_no_transport_imports():
    validate_service(SERVICE.read_text())


def test_submission_route_is_a_single_live_dependency_delegate():
    validate_entry(ROUTE.read_text())


def test_request_module_import_does_not_load_routes_database_or_settings():
    script = (
        "import sys\n"
        "from app.services.practice import request_submission\n"
        "assert 'app.api.v1.practice' not in sys.modules\n"
        "assert 'app.core.database' not in sys.modules\n"
        "assert 'app.core.config' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", script], cwd=ROOT / "backend", check=True)


@pytest.mark.parametrize(
    "extra",
    [
        "\nimport app.api.v1.practice\n",
        "\nfrom app.core.database import get_db\n",
        "\nasync def extra(*, ports):\n    pass\n",
        "\n" * 301,
    ],
)
def test_module_gate_rejects_added_dependencies_owners_or_budget(extra):
    with pytest.raises(AssertionError):
        validate_service(SERVICE.read_text() + extra)


@pytest.mark.parametrize(
    "statement",
    [
        "from app.api.v1 import practice",
        "import app.api.v1.practice",
        "await db.commit()",
        "await db.rollback()",
        "await db.flush()",
        "db.add(data)",
        "await db.delete(data)",
    ],
)
def test_module_gate_rejects_function_local_imports_and_database_mutations(statement):
    tree = ast.parse(SERVICE.read_text())
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_submit_answers"
    )
    helper.body.insert(0, ast.parse(statement).body[0])
    with pytest.raises(AssertionError):
        validate_service(ast.unparse(tree))


def test_route_gate_rejects_business_work_added_before_delegation():
    tree = ast.parse(ROUTE.read_text())
    route = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "batch_submit"
    )
    route.body.insert(0, ast.parse("await db.commit()").body[0])
    with pytest.raises(AssertionError):
        validate_entry(ast.unparse(tree))


def digest(node):
    return hashlib.sha256(ast.dump(node).encode()).hexdigest()


DECLARATIONS = {
    "get_practice_subjects": "83d376973cbcafa925e87db51f3ff9850ef3fe2663af8be8a28a863b56ec4a2f",
    "get_practice_questions": "de2ddda73239c4f31371669e6da6738d107050cd8416f58d25bdb2cded0a6585",
    "_issue_questions_response": "ff990efb7e96f9031da665b8e59ab07a0697b0c17dbf470552a4a82aa2a52289",
    "reset_sequential_practice": "54be870a050d8a9aef2d3647348d6e2609ee03099b3d1eceb5c74ce652b89126",
    "batch_submit": "2dda2f19918b2f38260558f327392ddd7d820fce764a0ad1da1444d5e2e2071a",
    "get_practice_session_scope_snapshot": "03bffe2e9f9230ce33a0085bd30fd17b897b185bf474896eb74b0ab6b24133a0",
    "get_practice_session_knowledge_summary": "c969c56d514c0d5c734449005181f680dfc36492a23f0339782d16ad94541a8e",
    "get_practice_stats": "5bc6e2ed96fbbf4940da5bc1ec3e1fd6e61ca13083c9ee524b4efe06db916f5d",
    "list_records": "db81f80ed9eaf574649cc2e9ae6825c059827b1e8d55a09c66ba77269e1a64de",
    "get_knowledge_states": "8981f7fcb5eaa552d615418cb57f073ad2999b3fdcc6d6bc8e6fd87706c9af7b",
    "get_weak_knowledge_points": "a4d8f803d27997ecfb0b16694113c9f06c7af9c0a284a6a8bb91653e47666c85",
}

RETAINED_BODIES = {
    "get_practice_subjects": "416364a78da286c4edddda2cd297cc0ca213356f29d8463595af39936c2cc27d",
    "get_practice_questions": "d184ed011e596aab6af881accf4afb32c092973dce4d08b114b4f8dcc04b7d08",
    "_issue_questions_response": "d94ea8aed3baf511477b27b0a82c592fe156f60ce3605140be418b5d8674eb7e",
    "reset_sequential_practice": "1e74ee63bb01604ab0656b00b54dd69e6b520037ecb1c5525923362b8c070ff7",
    "get_practice_session_scope_snapshot": "9e699ee973bbe19e3421fde98d6b4bbe4a1d207f47e002322887ce4238ee5ea3",
    "get_practice_session_knowledge_summary": "6f51b8bc52fe244b81d8bd663b320745f2999ddc470ad70733d22fc19cb5e038",
    "get_practice_stats": "54c0d810edfe2847bc9eae5a04104ed92248e5b4601befc3fc8e53a5e2093195",
    "list_records": "f14f07ca2ed79c1064a0e05253a18aaf02fbb9f991fe703491d846513221ed29",
    "get_knowledge_states": "da76c6cf0cfe22b606d68827189f437f55b422082f0d4105c525be787e70a42c",
    "get_weak_knowledge_points": "f96a4186ce483dcf940c4728978a88605b2a4f62488d37583433e99929c7b6a4",
}


def test_original_declarations_and_retained_request_bodies_are_preserved():
    functions = validate_entry(ROUTE.read_text())
    assert set(functions) == set(DECLARATIONS) | {"_practice_request_port"}
    assert [name for name in functions if name != "_practice_request_port"] == list(
        DECLARATIONS
    )
    for name, expected in DECLARATIONS.items():
        node = functions[name]
        declaration = ast.Tuple(
            elts=[
                node.args,
                node.returns or ast.Constant(None),
                *node.decorator_list,
                ast.Constant(ast.get_docstring(node)),
            ],
            ctx=ast.Load(),
        )
        assert digest(declaration) == expected, name
    for name, expected in RETAINED_BODIES.items():
        assert (
            digest(ast.Module(body=functions[name].body, type_ignores=[])) == expected
        ), name
