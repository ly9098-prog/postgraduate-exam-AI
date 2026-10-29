"""Keep chapter-diagnosis SQL in the service and projections free of persistence."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[2] / "app/services"
SERVICE = SERVICES / "knowledge_diagnosis_service.py"
PROJECTION = SERVICES / "knowledge_diagnosis_projection.py"
SIGNATURES = {
    "_load_chapter_sessions": "1d2aa67cdeeffbe003ef9ec6582aed39d512e2507977c8f0ba404bf7273ec0b5",
    "_root_chapter_reports": "6462b23643651384e7b1182ab6bd0f1aa6a754b33aa50542d93f4502eff18d55",
    "get_knowledge_diagnosis": "b798e633a8227b12cff8fec44b9ef0bb9afb46b378fb7f4dbf3ae00d647b599d",
}
QUERY_SHA256 = "f79d295fe6b0ce67ebb14145a6a897841072b0558c6f37175793a546649cc636"
PORTS = {
    "_int",
    "_float",
    "_accuracy",
    "_scope_coverage",
    "datetime",
    "public_practice_session_scope",
    "serialize_utc_datetime",
    "_MAX_RECENT_SESSIONS",
}
DB_CALLS = {
    "execute",
    "scalar",
    "scalars",
    "commit",
    "rollback",
    "flush",
    "add",
    "add_all",
    "delete",
    "begin",
    "begin_nested",
}


def functions(tree):
    return {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def check_budgets(source, limit):
    assert len(source.splitlines()) <= limit
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            assert node.end_lineno - node.lineno + 1 <= 50


def check_projection(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module in {"__future__", "typing"}
        if isinstance(node, ast.Import):
            assert all(n.name == "typing" for n in node.names)
        if isinstance(node, ast.Name):
            assert node.id != "db"
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in DB_CALLS
            if isinstance(node.func, ast.Name) and node.func.id == "ports":
                assert len(node.args) == 1 and not node.keywords
                assert isinstance(node.args[0], ast.Constant)
                assert node.args[0].value in PORTS


def check_service(source):
    tree = ast.parse(source)
    funcs = functions(tree)
    assert list(funcs) == ["_diagnosis_port", *SIGNATURES]
    assert ast.unparse(funcs["_diagnosis_port"].body[0]) == "return globals()[name]"
    for name, expected in SIGNATURES.items():
        node = funcs[name]
        declaration = (
            ast.dump(node.args)
            + ast.dump(node.returns)
            + repr([ast.dump(d) for d in node.decorator_list])
            + str(ast.get_docstring(node))
        )
        assert hashlib.sha256(declaration.encode()).hexdigest() == expected
    loader = funcs["_load_chapter_sessions"]
    assert len(loader.body) == 2
    assert hashlib.sha256(ast.dump(loader.body[0]).encode()).hexdigest() == QUERY_SHA256
    assert ast.unparse(loader.body[1]) == (
        "return _projection.project_chapter_sessions(rows, ports=_diagnosis_port)"
    )
    wrapper = funcs["_root_chapter_reports"]
    assert len(wrapper.body) == 1
    assert ast.unparse(wrapper.body[0]) == (
        "return _projection._root_chapter_reports(nodes, chapter_stats, ports=_diagnosis_port)"
    )
    calls = []
    for node in ast.walk(funcs["get_knowledge_diagnosis"]):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if ast.unparse(node.func.value) == "_projection":
                calls.append(node.func.attr)
                assert ast.unparse(node.keywords[-1]) == "ports=_diagnosis_port"
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in DB_CALLS
    assert calls == ["recent_session_reports", "diagnosis_report", "diagnosis_response"]


def test_projection_and_service_budgets():
    check_budgets(PROJECTION.read_text(), 300)
    check_budgets(SERVICE.read_text(), 125)


def test_projection_has_no_database_config_or_service_imports():
    check_projection(PROJECTION.read_text())


def test_historical_declarations_sql_and_projection_delegation():
    check_service(SERVICE.read_text())


@pytest.mark.parametrize(
    "leak",
    [
        "import sqlalchemy",
        "from app.core.config import settings",
        "def local():\n    from app.models.user import User",
        "def local(db):\n    return db",
        "def local(session):\n    session.commit()",
        'def local(ports):\n    return ports("select")',
    ],
)
def test_projection_gate_rejects_persistence_and_hidden_imports(leak):
    with pytest.raises(AssertionError):
        check_projection(PROJECTION.read_text() + "\n" + leak)


@pytest.mark.parametrize("mutation", ["query", "signature", "ports", "write", "bypass"])
def test_service_gate_rejects_query_or_delegation_drift(mutation):
    tree = ast.parse(SERVICE.read_text())
    funcs = functions(tree)
    if mutation == "query":
        funcs["_load_chapter_sessions"].body[0] = ast.parse("rows = []").body[0]
    elif mutation == "signature":
        funcs["get_knowledge_diagnosis"].args.kw_defaults[0] = ast.Constant(60)
    elif mutation == "ports":
        funcs["_load_chapter_sessions"].body[1].value.keywords[0].value.id = "globals"
    elif mutation == "write":
        funcs["get_knowledge_diagnosis"].body.insert(
            0, ast.parse("db.commit()").body[0]
        )
    else:
        funcs["_root_chapter_reports"].body = ast.parse("return []").body
    with pytest.raises(AssertionError):
        check_service(ast.unparse(ast.fix_missing_locations(tree)))


def test_budget_gate_rejects_oversized_function():
    source = "def oversized():\n" + "    pass\n" * 50
    with pytest.raises(AssertionError):
        check_budgets(source, 300)
