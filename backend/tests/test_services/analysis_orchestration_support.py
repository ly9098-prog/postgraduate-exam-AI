"""Trace the orchestration without a provider, Redis, or database."""

import asyncio
from dataclasses import fields
from types import SimpleNamespace

import pytest

from app.services.ai import analysis_orchestration as module


def harness(monkeypatch, *, fail_at=None, failure=None):
    request = SimpleNamespace(
        **{field.name: object() for field in fields(module.AnalysisOrchestrationRequest)}
    )
    request.wrong_question = SimpleNamespace(id=7)
    request.generating = {7}
    request.user_id = 8
    lease = object()
    cache = SimpleNamespace(input_signature="refreshed", response=None)
    context = {"question": object()}
    inputs = SimpleNamespace(
        response=None, context=context, prompt_grounding=object(), image_data_urls=[]
    )
    invocation, review, response = object(), object(), {"model": "done"}
    events, context_snapshots = [], []
    results = dict(
        begin=lease, cache=cache, inputs=inputs, invoke=(invocation, review),
        resolve=response, finish=None,
    )

    def callback(name):
        async def call(*args, **kwargs):
            events.append((name, args, kwargs))
            if name in {"invoke", "resolve"}:
                context_snapshots.append((name, dict(kwargs["context"])))
            if name == fail_at:
                raise failure
            return results[name]

        return call

    for name, target in {
        "begin": "begin_analysis_generation",
        "cache": "review_locked_analysis_cache",
        "inputs": "prepare_locked_analysis_inputs",
        "invoke": "invoke_and_review_analysis",
        "resolve": "resolve_reviewed_analysis_outcome",
        "finish": "finish_analysis_generation",
    }.items():
        monkeypatch.setattr(module, target, callback(name))
    return SimpleNamespace(
        request=request, lease=lease, cache=cache, inputs=inputs, events=events,
        results=results, invocation=invocation, review=review, response=response,
        context_snapshots=context_snapshots,
    )


def expected_calls(h):
    r = h.request
    return [
        ("begin", (), dict(
            wrong_question_id=7, user_id=8, timeout_sec=r.timeout_sec,
            lock_grace_sec=r.lock_grace_sec, generating=r.generating, cache=r.cache,
        )),
        ("cache", (r.db, r.wrong_question, r.question), dict(
            user_id=8, force=r.effective_force, requires_visual=r.requires_visual,
            stored_visual_sources=r.stored_visual_sources,
            knowledge_points=r.knowledge_points, model_signature=r.model_signature,
            input_signature=r.input_signature_builder, cached_response=r.cached_response,
            cache_age=r.cache_age, logger=r.logger,
        )),
        ("inputs", (r.wrong_question, r.question), dict(
            current_answer_grounding=r.answer_grounding, requires_visual=r.requires_visual,
            runtime=r.runtime, knowledge_points=r.knowledge_points, timeout_sec=r.timeout_sec,
            logger=r.logger, prepare_visual_inputs=r.prepare_visual_inputs,
            build_context=r.build_context, build_prompt_grounding=r.build_prompt_grounding,
            build_expected_answer_check=r.build_expected_answer_check,
        )),
        ("invoke", (), dict(
            db=r.db, request=r, context=h.inputs.context, image_data_urls=h.inputs.image_data_urls,
            input_signature="refreshed", inputs=h.inputs,
        )),
        ("resolve", (), dict(
            request=r, context=h.inputs.context, input_signature="refreshed",
            image_data_urls=h.inputs.image_data_urls, inputs=h.inputs,
            invocation=h.invocation, review=h.review,
        )),
        ("finish", (), dict(
            wrong_question_id=7, generating=r.generating, lease=h.lease, cache=r.cache,
        )),
    ]


async def assert_task_cancellation(task, entered):
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        assert task in done, "cancelled task did not finish within deadline"
        with pytest.raises(asyncio.CancelledError):
            task.result()
    finally:
        if not task.done():
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=1)
            assert task in done, "task cleanup did not finish within deadline"
        await asyncio.gather(task, return_exceptions=True)
