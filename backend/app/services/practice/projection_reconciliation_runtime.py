"""Reconciliation limits and lease-owned polling with late-bound service ports."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ReconcileCyclePorts:
    reconcile: Callable[..., Awaitable[dict[str, int]]]
    sleep: Callable[[float], Awaitable[None]]
    log_info: Callable[..., Any]
    log_exception: Callable[..., Any]


def reconciliation_limits(
    batch_size: int | None,
    grace_sec: int | None,
    get_settings: Callable[[], Any],
) -> tuple[int, int]:
    effective_batch = max(
        1,
        int(
            batch_size
            if batch_size is not None
            else get_settings().ANSWER_PROJECTION_RECONCILE_BATCH_SIZE
        ),
    )
    effective_grace = max(
        0,
        int(
            grace_sec
            if grace_sec is not None
            else get_settings().ANSWER_PROJECTION_RECONCILE_GRACE_SEC
        ),
    )
    return effective_batch, effective_grace


def reconciler_parameters(
    poll_interval: float | None,
    grace_sec: int | None,
    batch_size: int | None,
    get_settings: Callable[[], Any],
) -> tuple[float, int, int]:
    interval = max(
        30.0,
        float(
            poll_interval
            if poll_interval is not None
            else get_settings().ANSWER_PROJECTION_RECONCILE_INTERVAL_SEC
        ),
    )
    effective_grace = (
        int(grace_sec)
        if grace_sec is not None
        else get_settings().ANSWER_PROJECTION_RECONCILE_GRACE_SEC
    )
    effective_batch = (
        int(batch_size)
        if batch_size is not None
        else get_settings().ANSWER_PROJECTION_RECONCILE_BATCH_SIZE
    )
    return interval, effective_grace, effective_batch


async def run_projection_reconcile_cycles(
    ports: ReconcileCyclePorts,
    async_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    lock: Any,
    interval: float,
    effective_grace: int,
    effective_batch: int,
) -> None:
    while True:
        try:
            lock_ttl = max(60, int(interval * 0.9))
            renew_interval = max(20, min(60, lock_ttl // 3))
            async with lock.acquire_and_renew(
                ttl=lock_ttl, renew_interval=renew_interval
            ) as handle:
                if handle.is_still_held():
                    async with async_session() as db:
                        stats = await ports.reconcile(
                            db,
                            batch_size=effective_batch,
                            grace_sec=effective_grace,
                        )
                    if stats["checked"] or stats["errors"]:
                        ports.log_info("Answer projection reconcile cycle: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:
            ports.log_exception("Answer projection reconcile cycle failed")
        await ports.sleep(interval)
