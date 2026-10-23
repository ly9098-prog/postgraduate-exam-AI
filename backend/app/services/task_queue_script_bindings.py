"""Canonical Lua script bindings for the durable task queue.

The first entries preserve the pre-extraction load sequence; the atomic v1→v2
migration script is appended. The queue service uses these attribute names for
its per-instance SHA cache; protocol modules remain the only owners of Lua
source text.
"""

from app.services.task_queue_lua_v1 import (
    _LUA_CLAIM,
    _LUA_COMPLETE,
    _LUA_ENQUEUE,
    _LUA_ENQUEUE_NON_IDEMPOTENT,
    _LUA_HEARTBEAT,
)
from app.services.task_queue_lua_v1_recovery import (
    _LUA_FAIL_DEAD,
    _LUA_FAIL_RETRY,
    _LUA_REAPER,
    _LUA_RETRY_CLAIM,
)
from app.services.task_queue_lua_v1_to_v2 import _LUA_DRAIN_ONE_V1_TO_V2
from app.services.task_queue_lua_v2_claim import (
    _LUA_CLAIM_V2,
    _LUA_ENQUEUE_NON_IDEMPOTENT_V2,
    _LUA_ENQUEUE_V2,
    _LUA_HEARTBEAT_V2,
    _LUA_REAPER_V2,
    _LUA_RETRY_CLAIM_V2,
)
from app.services.task_queue_lua_v2_transitions import (
    _LUA_CANCEL_V2,
    _LUA_COMPLETE_V2,
    _LUA_FAIL_DEAD_V2,
    _LUA_FAIL_RETRY_V2,
    _LUA_MARK_CORRUPT_V2,
)

SCRIPT_BINDINGS: tuple[tuple[str, str], ...] = (
    ("_lua_enqueue", _LUA_ENQUEUE),
    ("_lua_enqueue_non_idempotent", _LUA_ENQUEUE_NON_IDEMPOTENT),
    ("_lua_claim", _LUA_CLAIM),
    ("_lua_heartbeat", _LUA_HEARTBEAT),
    ("_lua_complete", _LUA_COMPLETE),
    ("_lua_fail_retry", _LUA_FAIL_RETRY),
    ("_lua_fail_dead", _LUA_FAIL_DEAD),
    ("_lua_reaper", _LUA_REAPER),
    ("_lua_retry_claim", _LUA_RETRY_CLAIM),
    ("_lua_enqueue_v2", _LUA_ENQUEUE_V2),
    ("_lua_enqueue_non_idempotent_v2", _LUA_ENQUEUE_NON_IDEMPOTENT_V2),
    ("_lua_claim_v2", _LUA_CLAIM_V2),
    ("_lua_heartbeat_v2", _LUA_HEARTBEAT_V2),
    ("_lua_complete_v2", _LUA_COMPLETE_V2),
    ("_lua_fail_retry_v2", _LUA_FAIL_RETRY_V2),
    ("_lua_fail_dead_v2", _LUA_FAIL_DEAD_V2),
    ("_lua_reaper_v2", _LUA_REAPER_V2),
    ("_lua_retry_claim_v2", _LUA_RETRY_CLAIM_V2),
    ("_lua_mark_corrupt_v2", _LUA_MARK_CORRUPT_V2),
    ("_lua_cancel_v2", _LUA_CANCEL_V2),
    ("_lua_drain_one_v1_to_v2", _LUA_DRAIN_ONE_V1_TO_V2),
)
