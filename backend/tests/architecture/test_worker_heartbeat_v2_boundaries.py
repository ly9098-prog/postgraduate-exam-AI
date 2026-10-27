"""Guard v2 heartbeat delegation, lease-window arithmetic and owner-lost semantics."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
WORKER = APP / "services/task_queue_worker.py"
HELPERS = (
    "_v2_heartbeat_cancel_requested",
    "_abandon_v2_heartbeat",
    "_retry_v2_heartbeat_once",
    "_v2_heartbeat_tick",
)


def load():
    return ast.parse(WORKER.read_text())


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def source_of(tree, name):
    return ast.unparse(function(tree, name))


def check_budgets(tree):
    for name in ("_v2_heartbeat_loop_with_lease_window",) + HELPERS:
        node = function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= 50, name


def check_loop(tree):
    source = source_of(tree, "_v2_heartbeat_loop_with_lease_window")
    assert "interval = max(lease_sec // 3, 10)" in source
    assert "while _v2_worker_running:" in source
    assert "await _v2_heartbeat_tick(task, lease_sec, interval, owner_lost)" in source
    assert (
        "if not await _v2_heartbeat_tick(task, lease_sec, interval, owner_lost):\n            break"
        in source
    )
    assert "try:" not in source
    assert "queue_metrics" not in source
    assert "Once owner_lost is set, the heartbeat loop stops" in source


def check_cancel_predicate(tree):
    source = source_of(tree, "_v2_heartbeat_cancel_requested")
    assert "task_data = await task_queue.get_task_v2(task.task_id)" in source
    assert "except Exception:\n        return False" in source
    assert "task_data.get('cancel_requested') == '1'" in source
    assert source.index("logger.warning(") < source.index("owner_lost.set()")
    assert "owner_lost.set()\n        return True" in source
    assert source.rstrip().endswith("return False")
    assert "queue_metrics" not in source


def check_abandon(tree):
    node = function(tree, "_abandon_v2_heartbeat")
    params = [arg.arg for arg in node.args.args]
    assert params == ["owner_lost", "message"]
    assert node.args.vararg.arg == "args"
    source = ast.unparse(node)
    assert "logger.warning(message, *args)" in source
    assert "queue_metrics['lease_renewal_failure'] += 1" in source
    assert "if owner_lost is not None:\n        owner_lost.set()" in source
    assert source.index("logger.warning(message, *args)") < source.index(
        "queue_metrics['lease_renewal_failure'] += 1"
    )
    assert source.index("queue_metrics['lease_renewal_failure'] += 1") < source.index(
        "owner_lost.set()"
    )
    assert "return" not in source


def check_retry(tree):
    source = source_of(tree, "_retry_v2_heartbeat_once")
    assert "await asyncio.sleep(1)" in source
    assert "ok = await task_queue.heartbeat_v2(task, lease_sec=lease_sec)" in source
    assert (
        "if ok == 1:\n            await asyncio.sleep(interval)\n            return True"
        in source
    )
    assert "except Exception:\n        pass" in source
    assert "'v2 Heartbeat retry failed, owner lost: task_id=%s'" in source
    assert source.rstrip().endswith("return False")
    assert isinstance(function(tree, "_retry_v2_heartbeat_once"), ast.AsyncFunctionDef)


def check_tick(tree):
    source = source_of(tree, "_v2_heartbeat_tick")
    assert "queue_metrics" not in source
    assert "ok = await task_queue.heartbeat_v2(task, lease_sec=lease_sec)" in source
    assert "if ok == 1:" in source
    assert "if await _v2_heartbeat_cancel_requested(task, owner_lost):" in source
    assert source.index("if await _v2_heartbeat_cancel_requested(") < source.index(
        "await asyncio.sleep(interval)"
    )
    assert "'v2 Heartbeat rejected (code=%d), owner lost: task_id=%s'" in source
    assert "if lease_window_remaining < interval * 2:" in source
    assert "lease_window_remaining = task.lease_expires_at - time.time()" in source
    assert (
        "'v2 Heartbeat transient error, retrying once: task_id=%s error=%s'" in source
    )
    assert (
        "return await _retry_v2_heartbeat_once(task, lease_sec, interval, owner_lost)"
        in source
    )
    assert "'v2 Heartbeat unexpected error, owner lost: task_id=%s error=%s'" in source

    try_node = next(
        node
        for node in ast.walk(function(tree, "_v2_heartbeat_tick"))
        if isinstance(node, ast.Try)
    )
    handler_types = [ast.unparse(handler.type) for handler in try_node.handlers]
    assert handler_types == [
        "(redis_exc.ConnectionError, redis_exc.TimeoutError)",
        "asyncio.CancelledError",
        "Exception",
    ]
    cancelled_handler = try_node.handlers[1]
    assert [ast.unparse(statement) for statement in cancelled_handler.body] == [
        "return False"
    ]


def test_heartbeat_helpers_stay_within_budget():
    check_budgets(load())


def test_loop_and_predicates_keep_owner_lost_semantics():
    tree = load()
    check_loop(tree)
    check_cancel_predicate(tree)
    check_abandon(tree)
    check_retry(tree)
    check_tick(tree)


def test_gate_rejects_dropped_metric_and_widened_lease_window():
    tree = load()
    abandon = function(tree, "_abandon_v2_heartbeat")
    for node in ast.walk(abandon):
        if isinstance(node, ast.AugAssign) and "lease_renewal_failure" in ast.unparse(
            node
        ):
            node.value = ast.Constant(value=0)
            break
    with pytest.raises(AssertionError):
        check_abandon(tree)

    tree = load()
    tick = function(tree, "_v2_heartbeat_tick")
    for node in ast.walk(tick):
        if isinstance(node, ast.Compare) and "lease_window_remaining" in ast.unparse(
            node
        ):
            node.comparators = [ast.Name(id="interval", ctx=ast.Load())]
            break
    with pytest.raises(AssertionError):
        check_tick(tree)
