"""Characterize startup seeding sessions, commits, logging and failure boundaries."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import runtime_startup_checks

STAGES = ["admin", "seed", "ai"]
FAILURES = [f"{name}.{phase}" for name in STAGES for phase in ["factory", "enter", "call", "exit"]] + ["admin.commit", "seed.commit"]


@pytest.fixture
def startup_ports(monkeypatch):
    events = []
    failures = {}
    calls = {}
    state = SimpleNamespace(
        events=events, failures=failures, calls=calls, sessions=[], created=True,
        seed_result={"created": 1, "updated": 0, "skipped": 0},
        ai_result=SimpleNamespace(severity="ok", enabled_count=1, default_count=1, providers=[], features=[]),
        config=SimpleNamespace(APP_ENV=" TeSt "), enter_hook=None,
    )

    def event(name):
        events.append(name)
        if name in failures:
            raise failures[name]

    def factory():
        label = STAGES[len(state.sessions)]
        session = SimpleNamespace(label=label)
        state.sessions.append(session)
        event(f"{label}.factory")

        async def commit():
            event(f"{label}.commit")
        session.commit = commit

        class Context:
            async def __aenter__(self):
                event(f"{label}.enter")
                if state.enter_hook:
                    state.enter_hook(label)
                return session

            async def __aexit__(self, error_type, error, traceback):
                events.append((f"{label}.exit_type", error_type))
                event(f"{label}.exit")
                return False

        return Context()

    async def admin(session, env):
        calls["admin"] = (session, env)
        event("admin.call")
        return state.created

    async def seed(session, *, force):
        calls["seed"] = (session, force)
        event("seed.call")
        return state.seed_result

    async def ai(session):
        calls["ai"] = (session,)
        event("ai.call")
        return state.ai_result

    logger = SimpleNamespace(info=Mock(), warning=Mock(), error=Mock())
    state.factory, state.admin, state.logger = factory, admin, logger
    monkeypatch.setitem(sys.modules, "app.services.recommendation_seed_service", SimpleNamespace(seed_default_recommendation_strategies=seed))
    monkeypatch.setitem(sys.modules, "app.services.health_check_service", SimpleNamespace(check_ai_model_config=ai))
    return state


@pytest.fixture
def startup(startup_ports, monkeypatch):
    monkeypatch.setattr(runtime_startup_checks, "logger", startup_ports.logger)

    async def run():
        await runtime_startup_checks.initialize_dev_admin(
            startup_ports.factory, startup_ports.admin, startup_ports.config,
        )
        await runtime_startup_checks.seed_recommendation_strategies(startup_ports.factory)
        await runtime_startup_checks.log_ai_model_configuration(startup_ports.factory)
    return run


@pytest.mark.asyncio
@pytest.mark.parametrize("created", [False, True])
@pytest.mark.parametrize("seed_result", [{}, {"created": 0, "updated": 0, "skipped": 0}, {"skipped": 2}])
@pytest.mark.parametrize("severity", ["error", "warning", "ok"])
async def test_startup_check_sessions_parameters_and_conditional_logs(startup, startup_ports, created, seed_result, severity):
    ports = startup_ports
    ports.created = created
    ports.seed_result = seed_result
    ports.ai_result.severity = severity
    await startup()
    assert ports.events == [
        "admin.factory", "admin.enter", "admin.call", "admin.commit", ("admin.exit_type", None), "admin.exit",
        "seed.factory", "seed.enter", "seed.call", "seed.commit", ("seed.exit_type", None), "seed.exit",
        "ai.factory", "ai.enter", "ai.call", ("ai.exit_type", None), "ai.exit",
    ]
    assert ports.calls["admin"] == (ports.sessions[0], ports.config.APP_ENV)
    assert ports.calls["seed"] == (ports.sessions[1], False)
    assert ports.calls["ai"] == (ports.sessions[2],)
    assert ports.logger.info.call_count == int(created) + int(any(seed_result.values())) + int(severity == "ok")
    assert ports.logger.warning.call_count == int(severity == "warning")
    assert ports.logger.error.call_count == int(severity == "error")


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", FAILURES)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_original_session_failure_boundary_and_cancellation(startup, startup_ports, failed, error_type):
    error = error_type("synthetic startup check failure")
    startup_ports.failures[failed] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await startup()
        assert caught.value is error
        assert startup_ports.events[-1] in {failed, failed.split(".")[0] + ".exit"}
        startup_ports.logger.warning.assert_not_called()
    else:
        await startup()
        expected = failed if failed in {"ai.factory", "ai.enter"} else "ai.exit"
        assert startup_ports.events[-1] == expected
        startup_ports.logger.warning.assert_called_once()
    label, phase = failed.split(".")
    if phase in {"call", "commit"}:
        assert (f"{label}.exit_type", error_type) in startup_ports.events
    elif phase == "enter":
        assert f"{label}.exit" not in startup_ports.events
    if phase in {"factory", "enter", "call"}:
        assert f"{label}.commit" not in startup_ports.events


@pytest.mark.asyncio
async def test_admin_environment_is_read_after_session_entry(startup, startup_ports):
    def entered(label):
        if label == "admin":
            startup_ports.config.APP_ENV = "synthetic-after-entry"
    startup_ports.enter_hook = entered
    await startup()
    assert startup_ports.calls["admin"][1] == "synthetic-after-entry"
