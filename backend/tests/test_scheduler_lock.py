"""Pomodoro scheduler lock tests — verify lock semantics."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSchedulerLock:
    """Scheduler tick only executes with the lock."""

    @pytest.mark.asyncio
    async def test_tick_does_not_execute_without_lock(self):
        """When cache.acquire_lock returns False, _do_tick is not called."""
        from app.services.pomodoro_scheduler_service import PomodoroScheduler

        scheduler = PomodoroScheduler()
        scheduler._do_tick = AsyncMock()

        with patch.object(
            scheduler, "_do_tick", new_callable=AsyncMock
        ) as mock_do_tick:
            with patch("app.services.pomodoro_scheduler_service.cache") as mock_cache:
                mock_cache.acquire_lock = AsyncMock(return_value=False)

                await scheduler.tick()

                mock_do_tick.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_executes_with_lock(self):
        """When cache.acquire_lock returns True, _do_tick is called."""
        from app.services.pomodoro_scheduler_service import PomodoroScheduler

        scheduler = PomodoroScheduler()
        scheduler._do_tick = AsyncMock()

        with patch.object(
            scheduler, "_do_tick", new_callable=AsyncMock
        ) as mock_do_tick:
            with patch("app.services.pomodoro_scheduler_service.cache") as mock_cache:
                mock_cache.acquire_lock = AsyncMock(return_value=True)
                mock_cache.release_lock = AsyncMock()

                await scheduler.tick()

                mock_do_tick.assert_called_once()
                mock_cache.release_lock.assert_called_once()

    @pytest.mark.asyncio
    async def test_lock_released_after_tick(self):
        """Lock is released in finally block even if _do_tick raises."""
        from app.services.pomodoro_scheduler_service import PomodoroScheduler

        scheduler = PomodoroScheduler()
        scheduler._do_tick = AsyncMock(side_effect=RuntimeError("tick failed"))

        with patch("app.services.pomodoro_scheduler_service.cache") as mock_cache:
            mock_cache.acquire_lock = AsyncMock(return_value=True)
            mock_cache.release_lock = AsyncMock()

            with pytest.raises(RuntimeError, match="tick failed"):
                await scheduler.tick()

            mock_cache.release_lock.assert_called_once()
