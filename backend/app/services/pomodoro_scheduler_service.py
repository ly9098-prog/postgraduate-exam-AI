"""番茄钟到期扫描调度器。

每分钟扫一次：
- 状态=running
- notification_enabled=true
- notification_sent=false
- expected_end_time <= now
- openid_snapshot 非空

扫到的任务会调用微信订阅消息发送，并标记 notification_sent。

容错：
- 进程重启后第一次 tick 自然吸收停机期间漏发的提醒。
- Redis 锁防止多 worker 同时扫描；Redis 不可用时降级为单进程串行。
- PostgreSQL 用 FOR UPDATE SKIP LOCKED 行级互斥；SQLite 自动降级为普通 select（开发环境）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload

from app.core.time_utils import utcnow
from app.core.cache import cache
from app.core.config import settings
from app.core.database import async_session
from app.models.pomodoro import PomodoroSession
from app.services import wechat_notify_service as wechat

logger = logging.getLogger("2240ai.pomodoro_scheduler")

_TICK_LOCK_KEY = "pomodoro:scheduler:tick"
_TICK_LOCK_TTL = 70  # 大于扫描间隔，防止重叠

_SUBJECT_LABELS = {
    "data_structure": "数据结构",
    "computer_organization": "组成原理",
    "operating_system": "操作系统",
    "computer_network": "计算机网络",
    "english": "英语",
    "math": "数学",
    "politics": "政治",
}


class PomodoroScheduler:
    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        if not settings.POMODORO_NOTIFY_ENABLED:
            logger.info("番茄钟通知调度器未启用 (POMODORO_NOTIFY_ENABLED=false)")
            return
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._scheduler.add_job(
            self._safe_tick,
            "interval",
            seconds=max(15, settings.POMODORO_SCHEDULER_INTERVAL_SEC),
            id="pomodoro_tick",
            max_instances=1,
            coalesce=True,
            next_run_time=utcnow(),  # 启动后立即跑一次，吸收停机期间的漏发
        )
        self._scheduler.start()
        self._running = True
        logger.info(
            "番茄钟调度器已启动: interval=%ds, template=%s",
            settings.POMODORO_SCHEDULER_INTERVAL_SEC,
            settings.WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID or "<未配置>",
        )

    async def stop(self) -> None:
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("番茄钟调度器已停止")

    async def _safe_tick(self) -> None:
        try:
            await self.tick()
        except Exception:
            logger.exception("番茄钟调度器 tick 失败")

    async def tick(self) -> None:
        # Redis 锁：多 worker / 多实例下同一时刻只允许一个 tick
        lock_value = f"{os.getpid()}-{int(time.time())}"
        got_lock = await cache.acquire_lock(_TICK_LOCK_KEY, lock_value, ttl=_TICK_LOCK_TTL)
        if not got_lock:
            return  # Another instance holds the lock — skip this tick entirely

        # Background lease renewal: extend lock TTL every 30s while tick runs
        renew_stop = asyncio.Event()

        async def _renew_loop():
            while not renew_stop.is_set():
                try:
                    await asyncio.sleep(30)
                    await cache.expire(_TICK_LOCK_KEY, _TICK_LOCK_TTL)
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass  # best-effort renewal

        renew_task = asyncio.create_task(_renew_loop())

        try:
            await self._do_tick()
        finally:
            renew_stop.set()
            renew_task.cancel()
            try:
                await renew_task
            except asyncio.CancelledError:
                pass
            await cache.release_lock(_TICK_LOCK_KEY, lock_value)

    async def _do_tick(self) -> None:
        now = utcnow()
        async with async_session() as db:
            sessions = await self._claim_due_sessions(db, now)
            if not sessions:
                await db.commit()
                return

            logger.info("番茄钟调度器认领到 %d 个待通知任务", len(sessions))

        # 释放认领事务后，逐个发通知（避免长事务）
        for sess_data in sessions:
            await self._send_one(sess_data)

    async def _claim_due_sessions(self, db, now: datetime) -> list[dict[str, Any]]:
        """认领到期任务：标记 notification_sent=true 并返回快照。

        失败发送时 _send_one 会写回 notification_error，但 notification_sent 不再回滚——
        这是有意的"至多一次"语义：宁可少发，不能重复打扰用户。
        """
        stmt = (
            select(PomodoroSession)
            .options(joinedload(PomodoroSession.subject_ref))
            .where(
                PomodoroSession.status == "running",
                PomodoroSession.notification_enabled.is_(True),
                PomodoroSession.notification_sent.is_(False),
                PomodoroSession.expected_end_time.isnot(None),
                PomodoroSession.expected_end_time <= now,
                PomodoroSession.openid_snapshot.isnot(None),
                PomodoroSession.paused_at.is_(None),
            )
            .order_by(PomodoroSession.expected_end_time.asc())
            .limit(50)
        )
        # PostgreSQL: FOR UPDATE SKIP LOCKED；SQLite 静默忽略
        try:
            stmt = stmt.with_for_update(skip_locked=True)
        except Exception:
            pass

        try:
            result = await db.execute(stmt)
        except OperationalError:
            # SQLite 不支持 SKIP LOCKED，降级为普通 select
            stmt = stmt.with_for_update(skip_locked=False)
            try:
                result = await db.execute(stmt)
            except OperationalError:
                result = await db.execute(
                    select(PomodoroSession).where(
                        PomodoroSession.status == "running",
                        PomodoroSession.notification_enabled.is_(True),
                        PomodoroSession.notification_sent.is_(False),
                        PomodoroSession.expected_end_time.isnot(None),
                        PomodoroSession.expected_end_time <= now,
                        PomodoroSession.openid_snapshot.isnot(None),
                        PomodoroSession.paused_at.is_(None),
                    )
                )

        rows = result.scalars().all()
        if not rows:
            return []

        snapshots: list[dict[str, Any]] = []
        ids: list[int] = []
        for s in rows:
            ids.append(s.id)
            snapshots.append({
                "id": s.id,
                "user_id": s.user_id,
                "subject": (s.subject_ref.code if s.subject_ref else "") or "",
                "work_duration": s.work_duration,
                "expected_end_time": s.expected_end_time,
                "openid": s.openid_snapshot,
            })

        await db.execute(
            update(PomodoroSession)
            .where(PomodoroSession.id.in_(ids))
            .values(notification_sent=True, notification_sent_at=now)
        )
        await db.commit()
        return snapshots

    async def _send_one(self, sess: dict[str, Any]) -> None:
        sid = sess["id"]
        openid = sess["openid"]
        work = int(sess["work_duration"] or 0)
        subject_key = sess["subject"] or ""
        subject_label = _SUBJECT_LABELS.get(subject_key, subject_key or "学习")
        template_id = settings.WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID

        if not template_id:
            await self._record_error(sid, "skipped: template_id not configured")
            logger.warning("番茄钟通知未发送：未配置 WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID (session_id=%s)", sid)
            return

        # 模板 ID Dc2tD7nbZn4FQi9nYOXZCtpmK3KUbcG_vrJ57UokMUQ：
        #   thing1.DATA            打卡活动（中文/数字，20 字内，禁止符号）
        #   character_string2.DATA 打卡进度（字母+数字，20 字内）
        data = {
            "thing1": {"value": f"{subject_label}番茄钟"},
            "character_string2": {"value": f"{work}min"},
        }

        try:
            await wechat.send_subscribe_message(
                openid=openid,
                template_id=template_id,
                data=data,
                page=settings.POMODORO_NOTIFY_PAGE,
            )
            logger.info("番茄钟通知已发送 session_id=%s openid=***%s", sid, openid[-4:] if openid else "")
        except wechat.WeChatNotifyError as e:
            await self._record_error(sid, f"wechat error: errcode={e.errcode} {e.errmsg}")
            logger.warning("番茄钟通知发送失败 session_id=%s errcode=%s msg=%s", sid, e.errcode, e.errmsg)
        except Exception as e:
            await self._record_error(sid, f"unexpected: {type(e).__name__}: {e}")
            logger.exception("番茄钟通知发送异常 session_id=%s", sid)

    async def _record_error(self, session_id: int, message: str) -> None:
        try:
            async with async_session() as db:
                await db.execute(
                    update(PomodoroSession)
                    .where(PomodoroSession.id == session_id)
                    .values(notification_error=message)
                )
                await db.commit()
        except Exception:
            logger.exception("写入 notification_error 失败 session_id=%s", session_id)


pomodoro_scheduler = PomodoroScheduler()
