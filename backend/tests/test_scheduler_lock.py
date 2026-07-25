"""Pomodoro scheduler lock tests — verify lock semantics with DistributedLock."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _AsyncCM:
    """Simple async context manager for mocking."""
    def __init__(self, value: bool):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
async def test_tick_does_not_execute_without_lock():
    """When acquire returns False, _do_tick is not called."""
    from app.services import pomodoro_scheduler_service
    orig = pomodoro_scheduler_service.DistributedLock
    try:
        mock_cls = MagicMock()
        mock_cls.acquire_and_renew.return_value = _AsyncCM(False)
        pomodoro_scheduler_service.DistributedLock = MagicMock(return_value=mock_cls)

        scheduler = pomodoro_scheduler_service.PomodoroScheduler()
        with patch.object(scheduler, "_do_tick", new_callable=AsyncMock) as mock_do_tick:
            await scheduler.tick()
            mock_do_tick.assert_not_called()
    finally:
        pomodoro_scheduler_service.DistributedLock = orig


@pytest.mark.asyncio
async def test_tick_executes_with_lock():
    """When acquire returns True, _do_tick is called."""
    from app.services import pomodoro_scheduler_service
    orig = pomodoro_scheduler_service.DistributedLock
    try:
        mock_cls = MagicMock()
        mock_cls.acquire_and_renew.return_value = _AsyncCM(True)
        pomodoro_scheduler_service.DistributedLock = MagicMock(return_value=mock_cls)

        scheduler = pomodoro_scheduler_service.PomodoroScheduler()
        with patch.object(scheduler, "_do_tick", new_callable=AsyncMock) as mock_do_tick:
            await scheduler.tick()
            mock_do_tick.assert_called_once()
    finally:
        pomodoro_scheduler_service.DistributedLock = orig


@pytest.mark.asyncio
async def test_lock_released_after_tick():
    """_do_tick exception propagates through acquire_and_renew context."""
    from app.services import pomodoro_scheduler_service
    orig = pomodoro_scheduler_service.DistributedLock
    try:
        mock_cls = MagicMock()
        mock_cls.acquire_and_renew.return_value = _AsyncCM(True)
        pomodoro_scheduler_service.DistributedLock = MagicMock(return_value=mock_cls)

        scheduler = pomodoro_scheduler_service.PomodoroScheduler()
        scheduler._do_tick = AsyncMock(side_effect=RuntimeError("tick failed"))

        with pytest.raises(RuntimeError, match="tick failed"):
            await scheduler.tick()
    finally:
        pomodoro_scheduler_service.DistributedLock = orig
