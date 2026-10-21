"""Startup cleanup keeps the original failure even when cleanup logging fails."""

import asyncio
from types import SimpleNamespace

import pytest

from app.core import runtime_startup_cleanup


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_kind", ["error", "cancel"])
@pytest.mark.parametrize("logger_failure", ["warning", "critical"])
async def test_cleanup_coordinator_never_replaces_original_failure(
    cleanup_kind, logger_failure,
):
    original = RuntimeError("synthetic startup failure")
    cleanup_error = {
        "error": RuntimeError("synthetic cleanup failure"),
        "cancel": asyncio.CancelledError("synthetic cleanup cancellation"),
    }[cleanup_kind]

    async def cleanup():
        raise cleanup_error

    async def shutdown(resources):
        await cleanup()

    def fail_warning(*args, **kwargs):
        raise RuntimeError(f"synthetic {logger_failure} log failure")

    logger = SimpleNamespace(
        warning=fail_warning if logger_failure == "warning" else lambda *args, **kwargs: None,
        critical=fail_warning if logger_failure == "critical" else lambda *args, **kwargs: None,
    )
    resources = SimpleNamespace(role="worker")
    with pytest.raises(SystemError) as caught:
        await runtime_startup_cleanup.rethrow_startup_failure(
            original, resources, shutdown, logger=logger,
        )
    assert caught.value.__cause__ is original


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_kind", ["error", "cancel"])
async def test_cleanup_does_not_replace_plain_startup_error(cleanup_kind):
    original = RuntimeError("synthetic startup failure")
    cleanup_error = {
        "error": RuntimeError("synthetic cleanup failure"),
        "cancel": asyncio.CancelledError("synthetic cleanup cancellation"),
    }[cleanup_kind]

    async def cleanup():
        raise cleanup_error

    async def shutdown(resources):
        await cleanup()

    with pytest.raises(SystemError) as caught:
        await runtime_startup_cleanup.rethrow_startup_failure(
            original,
            SimpleNamespace(role="worker"),
            shutdown,
            logger=SimpleNamespace(
                warning=lambda *args, **kwargs: None,
                critical=lambda *args, **kwargs: None,
            ),
        )
    assert caught.value.__cause__ is original


@pytest.mark.asyncio
async def test_existing_startup_system_error_is_preserved_by_coordinator():
    original = SystemError("synthetic startup system error")
    calls = []

    async def shutdown(resources):
        calls.append(resources)

    with pytest.raises(SystemError) as caught:
        await runtime_startup_cleanup.rethrow_startup_failure(
            original,
            SimpleNamespace(role="worker"),
            shutdown,
            logger=SimpleNamespace(
                warning=lambda *args, **kwargs: None,
                critical=lambda *args, **kwargs: None,
            ),
        )
    assert caught.value is original
    assert calls == []


@pytest.mark.asyncio
async def test_logger_failure_does_not_replace_startup_cancellation():
    original = asyncio.CancelledError("synthetic startup cancellation")
    logger = SimpleNamespace(
        warning=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("warning")),
        critical=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("critical")),
    )

    async def cleanup():
        raise asyncio.CancelledError("synthetic cleanup cancellation")

    async def shutdown(resources):
        await cleanup()

    with pytest.raises(SystemError) as caught:
        await runtime_startup_cleanup.rethrow_startup_failure(
            original, SimpleNamespace(role="worker"), shutdown, logger=logger,
        )
    assert caught.value.__cause__ is original
