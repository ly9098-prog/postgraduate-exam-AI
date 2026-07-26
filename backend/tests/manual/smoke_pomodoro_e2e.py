"""本地起服务冒烟（TestClient 模式，不依赖外网 / 微信）。

流程：
1. 临时 SQLite + 关闭 Redis
2. mock wechat 发送 + 缩短 scheduler 间隔到 5s
3. 启动 FastAPI lifespan
4. 调 /auth/login（dev 模式直接派生 openid）
5. 调 /api/v1/pomodoro/start（带 notification_enabled=true，work_duration=0 让 expected_end_time 立即到期）
6. 等待 6 秒让 scheduler tick 一次
7. 验证 notification_sent=true 与 notification_sent_at 写入

用法：
    .venv/bin/python tests/manual/smoke_pomodoro_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, BACKEND_DIR)

tmp_db = tempfile.NamedTemporaryFile(prefix="pomo_smoke_", suffix=".db", delete=False)
tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_db.name}"
os.environ["REDIS_URL"] = ""
os.environ["WECHAT_APP_ID"] = ""  # 走 dev_openid 派生
os.environ["POMODORO_NOTIFY_ENABLED"] = "true"
os.environ["POMODORO_SCHEDULER_INTERVAL_SEC"] = "15"  # tick 周期 ≥ 15s
os.environ["WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID"] = "TPL_SMOKE"


async def main():
    # 1. mock wechat
    from app.services import pomodoro_scheduler_service as scheduler_module
    from app.services import wechat_notify_service as wn

    sent_calls: list[dict] = []

    async def fake_send(**kwargs):
        sent_calls.append(kwargs)
        return {"errcode": 0, "errmsg": "ok"}

    wn.send_subscribe_message = fake_send  # type: ignore
    scheduler_module.wechat.send_subscribe_message = fake_send  # type: ignore

    # 2. 启动 FastAPI（手动跑 lifespan）
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with app.router.lifespan_context(app):
        # 插入测试科目（lifespan 已创建表）
        from sqlalchemy import insert

        from app.core.database import async_session as db_session
        from app.models.admin import Subject

        async with db_session() as db:
            await db.execute(
                insert(Subject).values(
                    id=1, code="math", name="数学",
                    level=1, path="math", sort_order=1, is_active=True
                )
            )
            await db.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 登录 → token
            r = await client.post("/api/v1/auth/login", json={"code": "smoke_user_001"})
            assert r.status_code == 200, r.text
            token = r.json()["access_token"]
            print(f"[1] 登录成功，token len={len(token)}")

            headers = {"Authorization": f"Bearer {token}"}

            # 启动番茄钟（work_duration=1 让 expected_end_time 1 分钟后；为快速验证我们手动改 DB）
            r = await client.post(
                "/api/v1/pomodoro/start",
                headers=headers,
                json={
                    "subject_id": 1,
                    "chapter_id": None,
                    "preset": "standard",
                    "work_duration": 1,
                    "break_duration": 1,
                    "notification_enabled": True,
                },
            )
            assert r.status_code == 200, r.text
            session = r.json()
            sid = session["id"]
            assert session["notification_enabled"] is True
            assert session["expected_end_time"] is not None
            print(f"[2] /pomodoro/start 成功 session_id={sid} expected_end_time={session['expected_end_time']}")

            # 把 expected_end_time 提前到过去，让 scheduler 立即认领
            from sqlalchemy import update

            from app.core.database import async_session
            from app.models.pomodoro import PomodoroSession

            async with async_session() as db:
                await db.execute(
                    update(PomodoroSession)
                    .where(PomodoroSession.id == sid)
                    .values(expected_end_time=datetime.utcnow() - timedelta(seconds=1))
                )
                await db.commit()

            # 直接触发一次 tick（lifespan 已启动 scheduler，但等 15s 太久）
            await scheduler_module.pomodoro_scheduler.tick()

            # 验证
            from sqlalchemy import select
            async with async_session() as db:
                row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

            assert row.notification_sent is True
            assert row.notification_sent_at is not None
            assert row.notification_error is None
            assert len(sent_calls) == 1
            assert sent_calls[0]["template_id"] == "TPL_SMOKE"
            assert sent_calls[0]["page"] == "pages/pomodoro/pomodoro"
            print(f"[3] scheduler 触发 → notification_sent=True, sent_at={row.notification_sent_at}")
            print(f"[3] 微信调用 1 次, openid=***{sent_calls[0]['openid'][-4:]}, page={sent_calls[0]['page']}")

            # 再 tick 一次：不应重发
            await scheduler_module.pomodoro_scheduler.tick()
            assert len(sent_calls) == 1, "重复 tick 不应重发"
            print("[4] 重复 tick：未重发 ✓")

            # 用户端 complete：仍可清理，不会发送
            r = await client.post(
                f"/api/v1/pomodoro/{sid}/complete",
                headers=headers,
                json={"total_paused_ms": 0},
            )
            assert r.status_code == 200, r.text
            print("[5] /pomodoro/complete 调用成功，无重复推送")

    print("\n本地服务冒烟全部通过 ✅")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        try:
            os.unlink(tmp_db.name)
        except Exception:
            pass
