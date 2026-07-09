"""端到端验证：番茄钟通知调度器

不需要真实微信 access_token / 真实 Redis：
- 临时 SQLite（独立文件，跑完即删）
- mock wechat_notify_service.send_subscribe_message
- mock cache.acquire_lock 返回 True
- 直接 await scheduler.tick() 一次

覆盖：
1. 模板 ID 已配置 + openid 存在 → 发送成功，notification_sent_at 写入
2. 模板 ID 未配置 → notification_error="skipped: template_id not configured"
3. notification_sent=true 不重复扫描
4. notification_enabled=false 不被认领
5. expected_end_time 还没到不被认领

用法：
    python tests/manual/verify_pomodoro_scheduler.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta

# 切到 backend 目录确保 import 路径正确
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, BACKEND_DIR)

# 用临时 SQLite，避免污染 dev.db
tmp_db = tempfile.NamedTemporaryFile(prefix="pomo_e2e_", suffix=".db", delete=False)
tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_db.name}"
os.environ["REDIS_URL"] = ""  # 关闭 Redis，走进程内兜底
os.environ["POMODORO_NOTIFY_ENABLED"] = "true"

from app.core.config import settings  # noqa: E402
from app.core.database import Base, engine, async_session  # noqa: E402

# 显式导入所有模型，确保外键能解析（User.banned_by → admin_users.id 等）
import app.models  # noqa: E402,F401
from app.models import admin as _admin_models  # noqa: E402,F401
from app.models import app_user_admin_binding as _binding_models  # noqa: E402,F401
from app.models.pomodoro import PomodoroSession  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import pomodoro_scheduler_service as scheduler_module  # noqa: E402
from app.services import wechat_notify_service  # noqa: E402


# 替换 wechat 发送为 mock
sent_calls: list[dict] = []


async def fake_send(*, openid, template_id, data, page=None, miniprogram_state=None, lang="zh_CN"):
    sent_calls.append({"openid": openid, "template_id": template_id, "data": data, "page": page})
    return {"errcode": 0, "errmsg": "ok"}


wechat_notify_service.send_subscribe_message = fake_send  # type: ignore
scheduler_module.wechat.send_subscribe_message = fake_send  # type: ignore


async def setup_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def make_user(db, openid: str) -> int:
    u = User(openid=openid, session_key="test")
    db.add(u)
    await db.flush()
    return u.id


async def insert_session(
    db,
    *,
    user_id: int,
    openid: str,
    expected_end_time: datetime | None,
    notification_enabled: bool,
    notification_sent: bool = False,
    status: str = "running",
    work_duration: int = 25,
) -> int:
    s = PomodoroSession(
        user_id=user_id,
        chapter_id=None,
        preset="standard",
        work_duration=work_duration,
        break_duration=5,
        start_time=datetime.utcnow() - timedelta(minutes=work_duration),
        expected_end_time=expected_end_time,
        status=status,
        notification_enabled=notification_enabled,
        notification_sent=notification_sent,
        openid_snapshot=openid,
    )
    db.add(s)
    await db.flush()
    return s.id


async def reset_send_counters() -> None:
    sent_calls.clear()


async def fetch(db, sid: int) -> PomodoroSession:
    from sqlalchemy import select
    res = await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))
    return res.scalar_one()


async def run() -> None:
    await setup_db()
    print(f"DB: {tmp_db.name}")

    async with async_session() as db:
        u_id = await make_user(db, "openid_e2e")
        await db.commit()

    now = datetime.utcnow()

    # 用例 1：到期 + 启用 + 未发送 → 应该认领并发送
    async with async_session() as db:
        sid_due = await insert_session(
            db,
            user_id=u_id,
            openid="openid_e2e",
            expected_end_time=now - timedelta(seconds=10),
            notification_enabled=True,
        )
        # 用例 2：未到期 → 不应该被认领
        sid_future = await insert_session(
            db,
            user_id=u_id,
            openid="openid_e2e",
            expected_end_time=now + timedelta(minutes=5),
            notification_enabled=True,
        )
        # 用例 3：未授权 → 不应该被认领
        sid_disabled = await insert_session(
            db,
            user_id=u_id,
            openid="openid_e2e",
            expected_end_time=now - timedelta(seconds=10),
            notification_enabled=False,
        )
        # 用例 4：已发送 → 不重复
        sid_sent = await insert_session(
            db,
            user_id=u_id,
            openid="openid_e2e",
            expected_end_time=now - timedelta(seconds=10),
            notification_enabled=True,
            notification_sent=True,
        )
        await db.commit()

    # ---- 场景 A：模板已配置 ----
    settings.WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID = "TPL_FAKE_123"
    await reset_send_counters()
    sched = scheduler_module.PomodoroScheduler()
    await sched.tick()

    async with async_session() as db:
        s_due = await fetch(db, sid_due)
        s_future = await fetch(db, sid_future)
        s_disabled = await fetch(db, sid_disabled)
        s_sent = await fetch(db, sid_sent)

    assert s_due.notification_sent is True, "due session should be sent"
    assert s_due.notification_sent_at is not None
    assert s_due.notification_error is None
    assert s_future.notification_sent is False, "future session must not be claimed"
    assert s_disabled.notification_sent is False, "disabled session must not be claimed"
    assert s_sent.notification_sent is True
    assert len(sent_calls) == 1, f"expected exactly 1 wechat call, got {len(sent_calls)}"
    assert sent_calls[0]["template_id"] == "TPL_FAKE_123"
    assert sent_calls[0]["page"] == settings.POMODORO_NOTIFY_PAGE
    assert sent_calls[0]["openid"] == "openid_e2e"
    print("[A] 模板已配置：发送 1 次 ✓ 误扫 0 次 ✓ notification_sent_at 已写入 ✓")

    # 再 tick 一次：不应重复发送
    await reset_send_counters()
    await sched.tick()
    assert len(sent_calls) == 0, "second tick should not resend"
    print("[A] 重复 tick：未重发 ✓")

    # ---- 场景 B：模板未配置 ----
    settings.WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID = ""
    async with async_session() as db:
        sid_no_tpl = await insert_session(
            db,
            user_id=u_id,
            openid="openid_e2e",
            expected_end_time=now - timedelta(seconds=10),
            notification_enabled=True,
        )
        await db.commit()

    await reset_send_counters()
    await sched.tick()

    async with async_session() as db:
        s_no_tpl = await fetch(db, sid_no_tpl)
    assert s_no_tpl.notification_sent is True, "no-template still marked sent (at-most-once)"
    assert "template_id not configured" in (s_no_tpl.notification_error or "")
    assert len(sent_calls) == 0, "no wechat call expected when template missing"
    print("[B] 模板未配置：notification_error 标记为 skipped ✓ 未调微信 ✓")

    print("\n端到端验证全部通过 ✅")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    finally:
        try:
            os.unlink(tmp_db.name)
        except Exception:
            pass
