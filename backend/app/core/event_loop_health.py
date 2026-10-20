"""Process-local lag sample shared by monitoring, admission and HTTP diagnostics."""

import asyncio
import time
from dataclasses import dataclass


@dataclass
class EventLoopHealth:
    lag_ms: float = 0.0


event_loop_health = EventLoopHealth()


async def monitor_event_loop_lag(state: EventLoopHealth, interval: float = 1.0) -> None:
    """Publish scheduling delay after each sleep; caller owns task start and stop."""
    while True:
        scheduled = time.perf_counter()
        await asyncio.sleep(interval)
        actual = time.perf_counter()
        state.lag_ms = round((actual - scheduled - interval) * 1000, 2)
