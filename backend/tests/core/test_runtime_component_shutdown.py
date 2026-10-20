"""Characterize role stop protocols and formula pool timeout fallback."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import runtime_resource_shutdown, runtime_role_shutdown


@pytest.fixture
def components(monkeypatch):
    events = []
    failures = {}

    def asynchronous(name):
        async def call():
            events.append(name)
            if name in failures:
                raise failures[name]
        return call

    def formula(*, wait, cancel_futures):
        events.append(("formula", wait, cancel_futures))
        key = "formula" if wait else "forced"
        if key in failures:
            raise failures[key]

    modules = {
        "task_queue_worker": SimpleNamespace(
            graceful_shutdown_v2=asynchronous("drain"),
            stop_reaper_v2=asynchronous("reaper"),
            set_draining_v2=asynchronous("set_draining"),
        ),
        "audit_cleanup_scheduler": SimpleNamespace(
            audit_log_cleanup_scheduler=SimpleNamespace(stop=asynchronous("audit")),
        ),
        "recommendation_metrics_scheduler": SimpleNamespace(
            recommendation_metrics_scheduler=SimpleNamespace(stop=asynchronous("recommendation")),
        ),
        "ai_prewarm_worker": SimpleNamespace(stop_worker=asynchronous("prewarm")),
        "formula_graph_spec_renderer": SimpleNamespace(shutdown_formula_render_pool=formula),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, f"app.services.{name}", module)

    async def to_thread(fn, **kwargs):
        events.append("to_thread")
        return fn(**kwargs)

    async def wait_for(coro, *, timeout):
        events.append(("wait_for", timeout))
        if "wait" in failures:
            coro.close()
            raise failures["wait"]
        return await coro

    runtime = SimpleNamespace(to_thread=to_thread, wait_for=wait_for)
    logger = SimpleNamespace(info=Mock(), warning=Mock(), exception=Mock())
    return SimpleNamespace(events=events, failures=failures, runtime=runtime, logger=logger)


@pytest.fixture
def protocols(components, monkeypatch):
    monkeypatch.setattr(runtime_role_shutdown, "logger", components.logger)
    monkeypatch.setattr(runtime_resource_shutdown, "logger", components.logger)
    monkeypatch.setattr(runtime_resource_shutdown, "asyncio", components.runtime)

    async def formula(_role):
        await runtime_resource_shutdown.shutdown_formula_pool()

    return SimpleNamespace(
        drain=runtime_role_shutdown.drain_queue_for_role,
        stop=runtime_role_shutdown.stop_role_services,
        formula=formula,
    )


ROLE_CALLS = {
    "web": ["set_draining"], "worker": ["drain", "reaper", "prewarm"],
    "scheduler": ["set_draining", "audit", "recommendation"],
    "all": ["drain", "reaper", "audit", "recommendation", "prewarm"],
    "unknown": ["set_draining"],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLE_CALLS)
@pytest.mark.parametrize("failure", [None, "drain", "reaper", "set_draining", "audit", "recommendation", "prewarm"])
async def test_role_selection_order_and_ordinary_error_continuation(protocols, components, role, failure):
    if failure:
        components.failures[failure] = RuntimeError("synthetic stop failure")
    await protocols.drain(role)
    await protocols.stop(role)
    assert components.events == ROLE_CALLS[role]
    assert components.logger.warning.call_count == int(failure in ROLE_CALLS[role])


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLE_CALLS)
@pytest.mark.parametrize("failure", ["drain", "reaper", "set_draining", "audit", "recommendation", "prewarm"])
async def test_role_cancellation_stops_following_protocols(protocols, components, role, failure):
    cancelled = asyncio.CancelledError()
    components.failures[failure] = cancelled

    async def run():
        await protocols.drain(role)
        await protocols.stop(role)

    expected = ROLE_CALLS[role]
    if failure in expected:
        with pytest.raises(asyncio.CancelledError) as caught:
            await run()
        assert caught.value is cancelled
        expected = expected[:expected.index(failure) + 1]
    else:
        await run()
    assert components.events == expected
    components.logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "wait_error", "timeout", "forced_error", "cancel", "thread_error", "thread_timeout"])
async def test_formula_pool_shared_timeout_and_force_flags(protocols, components, failure):
    if failure in {"timeout", "forced_error"}:
        components.failures["wait"] = TimeoutError()
    elif failure == "wait_error":
        components.failures["wait"] = RuntimeError("synthetic wait error")
    elif failure == "cancel":
        components.failures["wait"] = asyncio.CancelledError()
    elif failure in {"thread_error", "thread_timeout"}:
        components.failures["formula"] = TimeoutError() if failure == "thread_timeout" else RuntimeError("synthetic pool error")
    if failure == "forced_error":
        components.failures["forced"] = RuntimeError("synthetic forced error")
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await protocols.formula("web")
    else:
        await protocols.formula("web")
    expected = [("wait_for", 30)]
    if failure in {None, "thread_error", "thread_timeout"}:
        expected += ["to_thread", ("formula", True, False)]
    if failure in {"timeout", "forced_error", "thread_timeout"}:
        expected += [("formula", False, True)]
    assert components.events == expected
    assert components.logger.warning.call_count == int(failure in {"timeout", "forced_error", "thread_timeout"})
    assert components.logger.exception.call_count == int(failure in {"wait_error", "thread_error", "forced_error"})
    assert components.logger.info.call_count == int(failure is None)
