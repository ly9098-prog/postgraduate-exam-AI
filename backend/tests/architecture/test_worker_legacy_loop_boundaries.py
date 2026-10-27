"""Guard legacy v1 worker loop delegation, ordering and cleanup ownership."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
WORKER = APP / "services/task_queue_worker.py"
HELPERS = (
    "_process_supervised_task",
    "_settle_supervised_task",
    "_dispatch_supervised_outcome",
    "_complete_supervised_task",
    "_fail_supervised_task",
    "_cancel_supervised_tasks",
)


def load():
    return ast.parse(WORKER.read_text())


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def check_budgets(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name


def check_loop(tree):
    source = ast.unparse(function(tree, "run_pipeline_worker"))
    assert "task_types = DISPATCHER_TASK_TYPES" in source
    assert "while _worker_running:" in source
    assert "if _worker_draining:" in source
    assert source.index("if _worker_draining:") < source.index("await asyncio.sleep(1)")
    assert source.index("await asyncio.sleep(1)") < source.index(
        "await task_queue.dequeue("
    )
    assert "task = await task_queue.dequeue(task_type, lease_sec=lease_sec)" in source
    assert "await _process_supervised_task(task, task_type, lease_sec)" in source
    assert "if not processed:" in source
    assert "await asyncio.sleep(poll_interval)" in source
    assert "Processing cancelled (owner lost)" not in source
    assert "cancel_monitor.cancel()" not in source
    assert "queue_metrics[" not in source
    assert "except asyncio.CancelledError:\n        logger.info(" in source
    assert "logger.info('Pipeline worker cancelled')" in source
    assert source.index("_worker_running = False") < source.index(
        "logger.info('Pipeline worker stopped')"
    )


def check_supervision_order(tree):
    source = ast.unparse(function(tree, "_process_supervised_task"))
    heartbeat = source.index("_heartbeat_loop(task, lease_sec, owner_lost)")
    processing = source.index("asyncio.create_task(_process_task(task))")
    monitor = source.index("_cancel_on_owner_loss(processing_task, owner_lost)")
    assert heartbeat < processing < monitor
    assert "await _settle_supervised_task(" in source
    assert "owner_lost," in source and "cancel_monitor," in source


def check_settle(tree):
    source = ast.unparse(function(tree, "_settle_supervised_task"))
    assert "await processing_task" in source
    assert (
        "await _dispatch_supervised_outcome(task, processing_task, owner_lost)"
        in source
    )
    assert "except asyncio.CancelledError:\n        raise" in source
    assert "await _fail_supervised_task(task, e, owner_lost)" in source
    assert source.index("await _dispatch_supervised_outcome") < source.index(
        "await _fail_supervised_task"
    )
    assert "finally:\n        await _cancel_supervised_tasks(" in source
    assert "heartbeat_task," in source and "processing_task," in source


def check_cleanup_order(tree):
    source = ast.unparse(function(tree, "_cancel_supervised_tasks"))
    positions = [
        source.index("cancel_monitor.cancel()"),
        source.index("await cancel_monitor"),
        source.index("heartbeat_task.cancel()"),
        source.index("await heartbeat_task"),
        source.index("logger.warning('Heartbeat task raised after cancel: %s', e)"),
        source.index("if not processing_task.done():"),
        source.index("processing_task.cancel()"),
        source.index("await processing_task"),
    ]
    assert positions == sorted(positions)


def test_loop_and_helpers_stay_within_budget():
    tree = load()
    check_budgets(
        ast.Module(
            body=[function(tree, "run_pipeline_worker")]
            + [function(tree, name) for name in HELPERS],
            type_ignores=[],
        )
    )


def test_loop_delegates_supervision_and_keeps_claim_shape():
    check_loop(load())


def test_supervision_creation_order_and_settlement_ownership():
    tree = load()
    check_supervision_order(tree)
    check_settle(tree)
    check_cleanup_order(tree)


def test_gate_rejects_inline_settlement_and_swapped_creation_order():
    tree = load()
    loop = function(tree, "run_pipeline_worker")
    for node in ast.walk(loop):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Await):
            call = node.value.value
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == (
                "_process_supervised_task"
            ):
                node.value.value = ast.parse("_process_task(task)").body[0].value
                break
    with pytest.raises(AssertionError):
        check_loop(tree)

    tree = load()
    process = function(tree, "_process_supervised_task")
    body = process.body
    heartbeat_index = next(
        index
        for index, node in enumerate(body)
        if "_heartbeat_loop" in ast.unparse(node)
    )
    processing_index = next(
        index
        for index, node in enumerate(body)
        if "processing_task = " in ast.unparse(node)
    )
    body[heartbeat_index], body[processing_index] = (
        body[processing_index],
        body[heartbeat_index],
    )
    with pytest.raises(AssertionError):
        check_supervision_order(tree)
