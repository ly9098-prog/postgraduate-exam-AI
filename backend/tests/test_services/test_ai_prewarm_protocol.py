"""Exercise actual revision validation and durable producer/consumer handoff."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.prewarm_revision import build_prewarm_revision
from app.core import database
from app.core.background_tasks import _background_tasks
from app.core.cache import CacheClient
from app.services import ai_prewarm_worker as worker
from app.services import ai_service as service
from app.services.ai import analysis_availability, connection_probe, model_health
from app.services.task_queue_contract import Task
from app.services.task_queue_v2_dead_retry_contract import build_v2_dead_retry_payload


@pytest.fixture
def analysis_context(monkeypatch):
    wrong = SimpleNamespace(review_count=2, wrong_answer="AB", ai_analysis=None)
    result = MagicMock()
    result.scalar_one_or_none.return_value = wrong
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(database, "async_session", lambda: context)
    analyze = AsyncMock(return_value={"model": "synthetic-model", "duration_ms": 12})
    monkeypatch.setattr(service, "analyze_error", analyze)
    return SimpleNamespace(wrong=wrong, result=result, db=db, analyze=analyze)


@pytest.mark.asyncio
async def test_superseded_revision_skips_provider_and_retains_user_filter(analysis_context):
    ctx = analysis_context
    stale = build_prewarm_revision(review_count=1, wrong_answer="AB")
    result = await service.prewarm_wrong_question_analysis(7, 8, expected_revision=stale)
    assert result == {"status": "superseded", "reason": "revision_changed", "from_cache": False}
    ctx.analyze.assert_not_awaited()
    statement = ctx.db.execute.call_args.args[0]
    filters = {clause.left.key: clause.right.value for clause in statement.whereclause.clauses}
    assert filters == {"id": 7, "user_id": 8}


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
async def test_matching_revision_preserves_success_or_cache_outcome(analysis_context, cached):
    ctx = analysis_context
    ctx.analyze.return_value["from_cache"] = cached
    revision = build_prewarm_revision(review_count=2, wrong_answer="AB")
    result = await service.prewarm_wrong_question_analysis(7, 8, expected_revision=revision)
    assert result == {
        "status": "cache_hit" if cached else "success", "reason": None,
        "from_cache": cached, "model": "synthetic-model", "duration_ms": 12,
    }
    ctx.analyze.assert_awaited_once_with(ctx.db, 8, 7, force_regenerate=False)


@pytest.mark.asyncio
async def test_missing_wrong_question_never_calls_provider(analysis_context):
    analysis_context.result.scalar_one_or_none.return_value = None
    result = await service.prewarm_wrong_question_analysis(7, 8, expected_revision="stale")
    assert result == {"status": "skipped", "reason": "wrong_question_not_found", "from_cache": False}
    analysis_context.analyze.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_baseline_skips_an_already_regenerated_analysis(analysis_context, monkeypatch):
    monkeypatch.setattr(service, "ai_analysis_generated_at", lambda value: "new-generation")
    result = await service.prewarm_wrong_question_analysis(
        7, 8, force_regenerate=True, baseline_generated_at="old-generation",
    )
    assert result == {
        "status": "superseded", "reason": "analysis_already_regenerated", "from_cache": True,
    }
    analysis_context.analyze.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("retryable", [False, True])
async def test_fallback_is_a_typed_worker_failure(analysis_context, retryable):
    analysis_context.analyze.return_value = {
        "from_fallback": True, "error_code": "synthetic-failure", "retryable": retryable,
    }
    with pytest.raises(service.PrewarmAnalysisError) as failure:
        await service.prewarm_wrong_question_analysis(7, 8)
    assert failure.value.error_code == "synthetic-failure"
    assert failure.value.retryable is retryable


@pytest.mark.parametrize(
    "reason,retryable",
    [("checking", True), ("transient", True), ("status_unavailable", True),
     ("configuration", False), ("quota", False), ("unconfigured", False),
     ("user_quota", False)],
)
def test_shared_availability_controls_prewarm_retry_policy(reason, retryable):
    error = service._prewarm_failure_from_result({
        "model": "fallback", "from_fallback": True,
        "error_code": "ai_service_unavailable", "retryable": False,
        "availability": {"reason": reason, "retry_after_ms": 60000},
    })
    assert error.retryable is retryable
    assert error.retry_after == (65 if reason == "checking" else 60 if retryable else 0)
    assert error.detail == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("retryable", [True, False])
async def test_worker_preserves_transient_budget_and_passes_cooldown(monkeypatch, retryable):
    task = Task(
        task_id="test-prewarm", task_type="prewarm_analysis",
        payload={"wq_id": 7, "user_id": 8}, max_retries=3,
    )
    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(
        "app.core.worker_concurrency.get_worker_semaphore",
        AsyncMock(return_value=semaphore),
    )
    monkeypatch.setattr(worker.task_queue, "dequeue_v2", AsyncMock(return_value=task))
    monkeypatch.setattr(worker.task_queue, "heartbeat_v2", AsyncMock(return_value=True))
    error = service.PrewarmAnalysisError(
        "ai_service_unavailable", retryable=retryable,
        detail="checking" if retryable else "configuration", retry_after=65,
    )
    monkeypatch.setattr(worker, "_process_task", AsyncMock(side_effect=error))

    async def fail(*args, **kwargs):
        worker._worker_running = False
        return 1 if retryable else 2

    failed = AsyncMock(side_effect=fail)
    monkeypatch.setattr(worker.task_queue, "fail_v2", failed)
    await worker.run_prewarm_worker()
    assert task.max_retries == (3 if retryable else 1)
    failed.assert_awaited_once_with(
        task, f"ai_service_unavailable: {error.detail}", retry_delay=65,
    )
    assert not semaphore.locked()


@pytest.mark.asyncio
async def test_cold_shared_probe_then_manual_retry_reaches_prewarm_success(
    analysis_context, monkeypatch
):
    store = CacheClient()
    store._enabled = False
    runtime = SimpleNamespace(
        model_config_id=11, config_fingerprint="test-revision",
        base_url="https://model.invalid/v1", api_key="test-key",
        model_name="test-model", provider="openai_compatible",
    )
    probe = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(model_health, "cache", store)
    monkeypatch.setattr(connection_probe, "probe_chat_connection", probe)
    monkeypatch.setattr(
        analysis_availability, "list_analysis_candidates", AsyncMock(return_value=[runtime]),
    )

    async def analyze(*args, **kwargs):
        selected, state = await analysis_availability.resolve_available_runtime("db")
        if selected is None:
            return {
                "from_fallback": True, "error_code": "ai_service_unavailable",
                "retryable": True, "availability": state,
            }
        return {"model": "test-model", "duration_ms": 1}

    analysis_context.analyze.side_effect = analyze
    task = Task(task_id="cold-prewarm", task_type="prewarm_analysis",
                payload={"wq_id": 7, "user_id": 8}, max_retries=1,
                error="ai_service_unavailable: fallback")
    with pytest.raises(service.PrewarmAnalysisError) as failure:
        await worker._process_task(task)
    assert failure.value.retryable and failure.value.retry_after == 65
    await asyncio.gather(*[
        task for task in _background_tasks if task.get_name() == "analysis-model-probe"
    ])
    retried = Task.from_dict(json.loads(build_v2_dead_retry_payload(
        task.to_dict(), task_type="prewarm_analysis",
    )))
    assert retried.max_retries == 3 and retried.retry_count == 0
    assert (await worker._process_task(retried))["status"] == "success"
    assert probe.await_count == 1


@pytest.mark.asyncio
async def test_durable_payload_and_task_id_reach_actual_revision_validator(analysis_context, monkeypatch):
    enqueue = AsyncMock(return_value=SimpleNamespace(accepted=True))
    monkeypatch.setattr(worker.task_queue, "enqueue_v2", enqueue)
    revision = build_prewarm_revision(review_count=2, wrong_answer="AB")
    assert await worker.enqueue_prewarm(7, 8, revision=revision)
    args = enqueue.call_args
    assert args.args == (worker.TASK_TYPE_PREWARM, {"wq_id": 7, "user_id": 8, "revision": revision})
    assert args.kwargs == {
        "task_id": f"prewarm:7:{revision}", "max_retries": 3, "idempotent": True,
    }
    task = SimpleNamespace(payload=args.args[1], created_at=time.time())
    outcome = await worker._process_task(task)
    assert outcome["status"] == "success"
    analysis_context.analyze.assert_awaited_once_with(
        analysis_context.db, 8, 7, force_regenerate=False,
    )


@pytest.mark.asyncio
async def test_worker_entry_starts_once_and_shutdown_cancels_owned_tasks(monkeypatch):
    entered = asyncio.Event()

    async def loop():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "_worker_task", None)
    monkeypatch.setattr(worker, "_worker_running", False)
    monkeypatch.setattr(worker, "_local_fallback_tasks", {})
    monkeypatch.setattr(worker, "run_prewarm_worker", loop)
    local = asyncio.create_task(asyncio.Event().wait())
    worker._local_fallback_tasks["synthetic-local"] = local
    try:
        await worker.start_worker()
        task = worker._worker_task
        await entered.wait()
        await worker.start_worker()
        assert worker._worker_task is task
        await worker.stop_worker()
        assert worker._worker_task is None
        assert worker._worker_running is False
        assert not worker._local_fallback_tasks
        assert task.cancelled()
        assert local.cancelled()
    finally:
        await worker.stop_worker()
