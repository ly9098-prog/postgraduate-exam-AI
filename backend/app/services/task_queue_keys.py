"""Redis key namespace for the durable task queue.

The key strings are a compatibility contract: producers and workers can be
deployed independently, so builders must not silently change namespaces.
"""

# v1 Redis key prefixes (legacy, used only for drain/migration).
_QUEUE_PREFIX = "taskq:queue"
_PROCESSING_PREFIX = "taskq:processing"
_DEAD_PREFIX = "taskq:dead"
_RETRY_PREFIX = "taskq:retry"
_CORRUPT_PREFIX = "taskq:corrupt"
_TASK_PREFIX = "taskq:task"
_IDEMPOTENCY_PREFIX = "taskq:idempotent"
_HEARTBEAT_PREFIX = "taskq:heartbeat"

# v2 Redis key namespace used by production.
_V2_QUEUE_PREFIX = "taskq:v2:ready"
_V2_PROCESSING_PREFIX = "taskq:v2:processing"
_V2_DEAD_PREFIX = "taskq:v2:dead"
_V2_RETRY_PREFIX = "taskq:v2:retry"
_V2_CORRUPT_PREFIX = "taskq:v2:corrupt"
_V2_TASK_PREFIX = "taskq:v2:task"
_V2_IDEMPOTENCY_PREFIX = "taskq:v2:idempotent"
_V2_HEARTBEAT_PREFIX = "taskq:v2:heartbeat"
_V2_FENCING_PREFIX = "taskq:v2:fencing"


def _task_hash_key(task_id: str) -> str:
    return f"{_TASK_PREFIX}:{task_id}"


def _heartbeat_key(task_id: str) -> str:
    return f"{_HEARTBEAT_PREFIX}:{task_id}"


def _idempotent_key(task_id: str) -> str:
    return f"{_IDEMPOTENCY_PREFIX}:{task_id}"


def _q_key(task_type: str) -> str:
    return f"{_QUEUE_PREFIX}:{task_type}"


def _p_key(task_type: str) -> str:
    return f"{_PROCESSING_PREFIX}:{task_type}"


def _dead_key(task_type: str) -> str:
    return f"{_DEAD_PREFIX}:{task_type}"


def _retry_key(task_type: str) -> str:
    return f"{_RETRY_PREFIX}:{task_type}"


def _corrupt_key(task_type: str) -> str:
    return f"{_CORRUPT_PREFIX}:{task_type}"


def _v2_q_key(task_type: str) -> str:
    return f"{_V2_QUEUE_PREFIX}:{task_type}"


def _v2_p_key(task_type: str) -> str:
    return f"{_V2_PROCESSING_PREFIX}:{task_type}"


def _v2_dead_key(task_type: str) -> str:
    return f"{_V2_DEAD_PREFIX}:{task_type}"


def _v2_retry_key(task_type: str) -> str:
    return f"{_V2_RETRY_PREFIX}:{task_type}"


def _v2_corrupt_key(task_type: str) -> str:
    return f"{_V2_CORRUPT_PREFIX}:{task_type}"


def _v2_task_hash_key(task_id: str) -> str:
    return f"{_V2_TASK_PREFIX}:{task_id}"


def _v2_heartbeat_key(task_id: str) -> str:
    return f"{_V2_HEARTBEAT_PREFIX}:{task_id}"


def _v2_fencing_key(task_id: str) -> str:
    return f"{_V2_FENCING_PREFIX}:{task_id}"


def _v2_idempotent_key(task_id: str) -> str:
    return f"{_V2_IDEMPOTENCY_PREFIX}:{task_id}"
