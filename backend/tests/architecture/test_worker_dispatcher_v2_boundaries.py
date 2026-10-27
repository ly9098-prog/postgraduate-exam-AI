"""Guard v2 dispatcher delegation, backoff arithmetic and slot ownership."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
WORKER = APP / "services/task_queue_worker.py"
HELPERS = (
    "_run_dispatcher_v2_loop",
    "_probe_v2_redis_recovery",
    "_handle_v2_redis_failure",
    "_spawn_v2_processing",
)


def load():
    return ast.parse(WORKER.read_text())


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def source_of(tree, name):
    return ast.unparse(function(tree, name))


def check_budgets(tree):
    for name in ("run_dispatcher_v2",) + HELPERS:
        node = function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= 50, name


def check_entry(tree):
    source = source_of(tree, "run_dispatcher_v2")
    assert "_v2_worker_running = True" in source
    assert "from app.core.worker_concurrency import get_worker_semaphore" in source
    assert "await get_worker_semaphore()" in source
    assert "task_types = DISPATCHER_TASK_TYPES" in source
    assert "settings.WORKER_CONCURRENCY" in source
    assert "await _run_dispatcher_v2_loop(" in source
    assert (
        "except asyncio.CancelledError:\n        logger.info('v2 Dispatcher cancelled')\n        raise"
        in source
    )
    assert (
        "finally:\n        _v2_worker_running = False\n        logger.info('v2 Dispatcher stopped')"
        in source
    )


def check_loop(tree):
    source = source_of(tree, "_run_dispatcher_v2_loop")
    assert "while _v2_worker_running and (not _v2_worker_draining):" in source
    assert "await semaphore.acquire()" in source
    assert "if _v2_worker_draining or not _v2_worker_running:" in source
    assert "semaphore.release()\n            break" in source
    assert "task = await _try_claim_any_v2(task_types, lease_sec)" in source
    assert "except TaskQueueUnavailableError as e:" in source
    assert (
        "_redis_failure_count = await _handle_v2_redis_failure("
        "e, _redis_failure_count, _max_redis_failures)"
    ) in source
    assert "_redis_failure_count = 0" in source
    assert "if task is None:" in source
    assert (
        "semaphore.release()\n            await asyncio.sleep(poll_interval)" in source
    )
    assert "_spawn_v2_processing(task, lease_sec, semaphore)" in source
    assert source.index("_spawn_v2_processing(") < source.index(
        "await asyncio.sleep(0)"
    )
    assert "processing_task" not in source


def check_backoff(tree):
    source = source_of(tree, "_handle_v2_redis_failure")
    assert "failure_count += 1" in source
    assert "queue_metrics['queue_redis_failure'] += 1" in source
    assert "error.retry_after * (1 << min(failure_count - 1, 4)), 300" in source
    assert (
        "'v2 Dispatcher Redis unavailable (failure #%d): %s — backing off %ds'"
        in source
    )
    assert "if failure_count >= max_failures:" in source
    assert "circuit breaker OPEN after %d Redis failures" in source
    assert "await _probe_v2_redis_recovery(backoff)" in source
    assert "else:\n        await asyncio.sleep(backoff)" in source
    assert source.index("await _probe_v2_redis_recovery") < source.index("else:")


def check_probe(tree):
    source = source_of(tree, "_probe_v2_redis_recovery")
    assert "_probe_target = min(backoff * 2, 300)" in source
    assert "_probe_step = 5" in source
    assert "_probe_waited = 0" in source
    assert (
        "while _probe_waited < _probe_target and _v2_worker_running "
        "and (not _v2_worker_draining):"
    ) in source
    assert (
        "await asyncio.sleep(min(_probe_step, _probe_target - _probe_waited))" in source
    )
    assert "_probe_waited += _probe_step" in source


def check_spawn(tree):
    source = source_of(tree, "_spawn_v2_processing")
    assert "asyncio.create_task(" in source
    assert "name=f'proc:{task.task_id}'" in source
    assert "_v2_active_processing.add(proc_task)" in source
    assert "proc_task.add_done_callback(_v2_active_processing.discard)" in source
    assert "semaphore.release()" not in source


def test_dispatcher_and_helpers_stay_within_budget():
    check_budgets(load())


def test_dispatcher_entry_and_loop_keep_slot_ownership():
    tree = load()
    check_entry(tree)
    check_loop(tree)


def test_backoff_probe_and_spawn_arithmetic():
    tree = load()
    check_backoff(tree)
    check_probe(tree)
    check_spawn(tree)


def test_gate_rejects_dropped_release_and_metric():
    tree = load()
    loop = function(tree, "_run_dispatcher_v2_loop")
    for node in ast.walk(loop):
        if isinstance(node, ast.If) and "semaphore.release()" in ast.unparse(node):
            node.body = [
                statement
                for statement in node.body
                if "semaphore.release()" not in ast.unparse(statement)
            ]
            break
    with pytest.raises(AssertionError):
        check_loop(tree)

    tree = load()
    backoff = function(tree, "_handle_v2_redis_failure")
    for node in ast.walk(backoff):
        if isinstance(node, ast.AugAssign) and "queue_redis_failure" in ast.unparse(
            node
        ):
            node.target = ast.parse("failure_count").body[0].value
            break
    with pytest.raises(AssertionError):
        check_backoff(tree)
