"""Keep token policy local, bounded, synchronous and free of persistence IO."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "app/services/practice/batch_token.py"
IMPORTS = {
    "__future__": {"annotations"},
    "base64": None,
    "hashlib": None,
    "hmac": None,
    "json": None,
    "time": None,
    "datetime": {"datetime", "timedelta"},
    "uuid": {"uuid4"},
    "app.core.config": {"settings"},
    "app.core.time_utils": {"utcnow"},
    "app.services.practice.normalization": {
        "PRACTICE_ALLOWED_MODES",
        "normalize_practice_request_id",
        "parse_session_datetime",
    },
}


def inspect_boundary(source):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append(node.name)
            assert node.end_lineno - node.lineno + 1 <= 50
        assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await))
        if isinstance(node, ast.Import):
            assert all(
                a.name in IMPORTS and IMPORTS[a.name] is None for a in node.names
            )
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in IMPORTS
            assert IMPORTS[node.module] is not None
            assert all(a.name in IMPORTS[node.module] for a in node.names)
        if isinstance(node, ast.Call):
            assert getattr(node.func, "id", "") not in {
                "open",
                "exec",
                "eval",
                "__import__",
            }
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "commit",
                "rollback",
                "flush",
                "begin",
                "begin_nested",
                "open",
                "read_text",
                "write_text",
                "read_bytes",
                "write_bytes",
                "urlopen",
                "request",
                "socket",
                "connect",
                "send",
                "recv",
                "system",
                "popen",
                "Popen",
                "run",
            }
    assert functions
    return set(functions)


def test_token_module_budget_dependencies_and_no_database_or_network():
    assert {
        "create_practice_batch_token",
        "_decode_practice_batch_token",
        "_validate_practice_batch_token",
        "_collect_practice_batch_revisions",
        "_encode_practice_batch_payload",
        "_read_practice_batch_questions",
        "_validate_practice_batch_identity",
    } <= inspect_boundary(SOURCE.read_text())


@pytest.mark.parametrize(
    "source",
    [
        "def small():\n    pass\n" + "\n" * 299,
        "def outer():\n    def nested():\n" + "        pass\n" * 51,
        "from sqlalchemy import select\ndef small():\n    pass\n",
        "from app.core import database\ndef small():\n    pass\n",
        "from .normalization import parse_session_datetime\ndef small():\n    pass\n",
        "from app.services.practice_service import logger\ndef small():\n    pass\n",
        "import httpx\ndef small():\n    pass\n",
        "def small():\n    return open('payload').read()\n",
        "def small(db):\n    return db.commit()\n",
        "def small():\n    return __import__('socket')\n",
        "async def small():\n    pass\n",
    ],
)
def test_token_boundary_rejects_budget_dependencies_io_and_async(source):
    with pytest.raises(AssertionError):
        inspect_boundary(source)
