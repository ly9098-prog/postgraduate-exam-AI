"""Architecture guards for the durable task-queue protocol modules."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from app.services import (
    task_queue_lua_v1,
    task_queue_lua_v1_recovery,
    task_queue_lua_v1_to_v2,
    task_queue_lua_v2_claim,
    task_queue_lua_v2_transitions,
)
from app.services.task_queue_keys import (
    _corrupt_key,
    _dead_key,
    _heartbeat_key,
    _idempotent_key,
    _p_key,
    _q_key,
    _retry_key,
    _task_hash_key,
    _v2_corrupt_key,
    _v2_dead_key,
    _v2_fencing_key,
    _v2_heartbeat_key,
    _v2_idempotent_key,
    _v2_p_key,
    _v2_q_key,
    _v2_retry_key,
    _v2_task_hash_key,
)
from app.services.task_queue_script_bindings import SCRIPT_BINDINGS

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
SERVICE_PATH = APP_ROOT / "services" / "task_queue_service.py"
PROTOCOL_MODULES = (
    APP_ROOT / "services" / "task_queue_keys.py",
    APP_ROOT / "services" / "task_queue_lua_v1.py",
    APP_ROOT / "services" / "task_queue_lua_v1_recovery.py",
    APP_ROOT / "services" / "task_queue_lua_v1_to_v2.py",
    APP_ROOT / "services" / "task_queue_lua_v2_claim.py",
    APP_ROOT / "services" / "task_queue_lua_v2_transitions.py",
    APP_ROOT / "services" / "task_queue_script_bindings.py",
)

# These hashes are the wire-level Lua contract. Updating a script requires an
# explicit protocol change and a new hash.
EXPECTED_SCRIPT_SHA256 = {
    "_LUA_ENQUEUE": "9edc7a1ebee19c56e1db9174ce1d777f797e7475c91ec7d3de7de0db7a1c424f",
    "_LUA_ENQUEUE_NON_IDEMPOTENT": (
        "994912bfbd3e6588c1114742ef863dff798d59be72b374c1237e873bb8a62286"
    ),
    "_LUA_CLAIM": "926183b65e0ae09b40264e01260ea59229f4b9118057d3453b4ba6536023a443",
    "_LUA_HEARTBEAT": (
        "efa4f00d4c80a7a4ba649821c90c789ea52b957d032eede59ab1917d6b02cf9b"
    ),
    "_LUA_COMPLETE": (
        "340b58a2c14099a6a5421e7a025e5fc6c0f96ac5c79e2c3c066ec3426a64e538"
    ),
    "_LUA_FAIL_RETRY": (
        "bc5d1abc9d61f175098aa281aed6b5d90c768b356c6d1116d9015b87abddb71d"
    ),
    "_LUA_FAIL_DEAD": (
        "2c3f21926f3298b6bbd15dd6ba824b6a12f6206133b5528c884f0fdfd846b72f"
    ),
    "_LUA_REAPER": "20395e94a6fbaac50f1ef53a05d5b2f7ab9d4254f305dd760cfda6aab3901c22",
    "_LUA_RETRY_CLAIM": (
        "3c44c77584f930d2e071d7460492de2fd9f075edda51bab2b8ac4525f1bbe112"
    ),
    "_LUA_ENQUEUE_V2": (
        "7746e6dfd1e7667903b818d4a4150e5e081c448537c3c6de7a8f3e8b6fa2d558"
    ),
    "_LUA_ENQUEUE_NON_IDEMPOTENT_V2": (
        "9f4d1ecdf2745a91caa22492bfecaaa9297f7253afaf1424d3c0f077ad6abc53"
    ),
    "_LUA_CLAIM_V2": (
        "c9f7717da14fdd23ffc9786369b23099b630649b4e9f9dffe567c6f9522d64dd"
    ),
    "_LUA_HEARTBEAT_V2": (
        "1bd719cba0f3edde61086596f5fbceb7d5bb6ff37ed9d0481a49f58b07b3b54b"
    ),
    "_LUA_COMPLETE_V2": (
        "bee5b1099209eed29b5683ced7334ee95800c1eb5f075153b54ac2f0a7be064e"
    ),
    "_LUA_FAIL_RETRY_V2": (
        "54bbc35c1f383b34df2a56bf1735007807653713e7f2ccf79f6be7409d95df2e"
    ),
    "_LUA_FAIL_DEAD_V2": (
        "7617a54f758a23c7115cb13263963d05ca1c02884540e3ae0565c17ef39e6e69"
    ),
    "_LUA_REAPER_V2": (
        "59c199c6d000a8b1ab9a9e546c98135993f5da45b35e234fc82ee7840a456f8a"
    ),
    "_LUA_RETRY_CLAIM_V2": (
        "fd6e97fc1cfa1ed47fe009c5904d1b96f96f7fa1236e2700f0cd431f33b5bb4b"
    ),
    "_LUA_MARK_CORRUPT_V2": (
        "5375e3a4dbd624f348916b1aa60c9a1aef15db1153eef98f51e7b248f0f3929e"
    ),
    "_LUA_CANCEL_V2": (
        "75bb2d8adff2a648dbbf48aa9cd647db74b4615ac71bd508331d16921f87c775"
    ),
    "_LUA_DRAIN_ONE_V1_TO_V2": (
        "527da83d9a77ddb7db7b574750d347769d39021d1a40ff8484a3e0f5c0632f89"
    ),
}


def test_lua_script_payloads_match_wire_contract() -> None:
    modules = (
        task_queue_lua_v1,
        task_queue_lua_v1_recovery,
        task_queue_lua_v1_to_v2,
        task_queue_lua_v2_claim,
        task_queue_lua_v2_transitions,
    )
    actual = {
        name: hashlib.sha256(getattr(module, name).encode()).hexdigest()
        for module in modules
        for name in EXPECTED_SCRIPT_SHA256
        if hasattr(module, name)
    }

    assert actual == EXPECTED_SCRIPT_SHA256


def test_service_delegates_lua_text_to_protocol_modules() -> None:
    tree = ast.parse(SERVICE_PATH.read_text())
    assignments = {
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and node.targets
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("_LUA_")
    }

    assert assignments == set()


def test_script_bindings_preserve_attribute_order_and_protocol_sources() -> None:
    protocol = {
        name: value
        for module in (
            task_queue_lua_v1,
            task_queue_lua_v1_recovery,
            task_queue_lua_v1_to_v2,
            task_queue_lua_v2_claim,
            task_queue_lua_v2_transitions,
        )
        for name in EXPECTED_SCRIPT_SHA256
        if hasattr(module, name)
        for value in (getattr(module, name),)
    }
    expected_attributes = (
        "_lua_enqueue",
        "_lua_enqueue_non_idempotent",
        "_lua_claim",
        "_lua_heartbeat",
        "_lua_complete",
        "_lua_fail_retry",
        "_lua_fail_dead",
        "_lua_reaper",
        "_lua_retry_claim",
        "_lua_enqueue_v2",
        "_lua_enqueue_non_idempotent_v2",
        "_lua_claim_v2",
        "_lua_heartbeat_v2",
        "_lua_complete_v2",
        "_lua_fail_retry_v2",
        "_lua_fail_dead_v2",
        "_lua_reaper_v2",
        "_lua_retry_claim_v2",
        "_lua_mark_corrupt_v2",
        "_lua_cancel_v2",
        "_lua_drain_one_v1_to_v2",
    )

    assert tuple(attribute for attribute, _ in SCRIPT_BINDINGS) == expected_attributes
    assert [script for _, script in SCRIPT_BINDINGS] == [
        protocol[name] for name in EXPECTED_SCRIPT_SHA256
    ]


def test_protocol_modules_are_data_only_and_below_line_budget() -> None:
    for path in PROTOCOL_MODULES:
        tree = ast.parse(path.read_text())
        definitions = [
            node
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if path.name != "task_queue_keys.py":
            assert definitions == [], path
        assert len(path.read_text().splitlines()) <= 300, path


def test_queue_service_stays_below_extraction_baseline() -> None:
    assert len(SERVICE_PATH.read_text().splitlines()) <= 2438


def test_redis_key_builders_preserve_namespaces() -> None:
    assert _task_hash_key("t1") == "taskq:task:t1"
    assert _heartbeat_key("t1") == "taskq:heartbeat:t1"
    assert _idempotent_key("t1") == "taskq:idempotent:t1"
    assert _q_key("ocr") == "taskq:queue:ocr"
    assert _p_key("ocr") == "taskq:processing:ocr"
    assert _dead_key("ocr") == "taskq:dead:ocr"
    assert _retry_key("ocr") == "taskq:retry:ocr"
    assert _corrupt_key("ocr") == "taskq:corrupt:ocr"

    assert _v2_q_key("ocr") == "taskq:v2:ready:ocr"
    assert _v2_p_key("ocr") == "taskq:v2:processing:ocr"
    assert _v2_dead_key("ocr") == "taskq:v2:dead:ocr"
    assert _v2_retry_key("ocr") == "taskq:v2:retry:ocr"
    assert _v2_corrupt_key("ocr") == "taskq:v2:corrupt:ocr"
    assert _v2_task_hash_key("t1") == "taskq:v2:task:t1"
    assert _v2_heartbeat_key("t1") == "taskq:v2:heartbeat:t1"
    assert _v2_fencing_key("t1") == "taskq:v2:fencing:t1"
    assert _v2_idempotent_key("t1") == "taskq:v2:idempotent:t1"
