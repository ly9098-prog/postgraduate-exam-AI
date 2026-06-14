"""番茄钟通知调度器单元测试。

使用临时 SQLite，覆盖：
- 到期任务被认领并发送
- 未到期任务不被认领
- notification_enabled=false 不被认领
- notification_sent=true 不重复发送
- 模板未配置时写入 notification_error
- complete_session/interrupt_session 关闭通知通道
- access_token 失效时强刷重发
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta

import pytest
import pytest_asyncio


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def isolated_db(monkeypatch_module):
    tmp = tempfile.NamedTemporaryFile(prefix="pomo_test_", suffix=".db", delete=False)
    tmp.close()

    monkeypatch_module.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    monkeypatch_module.setenv("REDIS_URL", "")
    monkeypatch_module.setenv("POMODORO_NOTIFY_ENABLED", "true")

    # 强制重新加载 settings + database 以应用 env
    import importlib
    from app.core import config as config_mod
    from app.core import database as db_mod

    importlib.reload(config_mod)
    importlib.reload(db_mod)

    # 显式导入所有模型让外键能解析
    import app.models  # noqa: F401
    from app.models import admin as _admin  # noqa: F401
    from app.models import app_user_admin_binding as _aub  # noqa: F401
    from app.models.user import User  # noqa: F401
    from app.models.pomodoro import PomodoroSession  # noqa: F401

    async with db_mod.engine.begin() as conn:
        await conn.run_sync(db_mod.Base.metadata.create_all)

    yield db_mod

    try:
        await db_mod.engine.dispose()
        os.unlink(tmp.name)
    except Exception:
        pass


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest_asyncio.fixture()
async def db_session(isolated_db):
    async with isolated_db.async_session() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def reset_tables(isolated_db):
    async with isolated_db.async_session() as db:
        from app.models.pomodoro import PomodoroSession
        from app.models.user import User
        from sqlalchemy import delete

        await db.execute(delete(PomodoroSession))
        await db.execute(delete(User))
        await db.commit()


async def _make_user(db, openid: str = "openid_test") -> int:
    from app.models.user import User
    u = User(openid=openid, session_key="t")
    db.add(u)
    await db.flush()
    return u.id


async def _insert(db, *, user_id: int, openid: str, due_offset_sec: int,
                 enabled: bool = True, sent: bool = False,
                 status: str = "running", work: int = 25):
    from app.models.pomodoro import PomodoroSession
    now = datetime.utcnow()
    s = PomodoroSession(
        user_id=user_id, subject="math", chapter_id=None, preset="standard",
        work_duration=work, break_duration=5,
        start_time=now - timedelta(minutes=work),
        expected_end_time=now + timedelta(seconds=due_offset_sec),
        status=status,
        notification_enabled=enabled,
        notification_sent=sent,
        openid_snapshot=openid,
    )
    db.add(s)
    await db.flush()
    return s.id


# ============================================================
# 测试用例
# ============================================================

class TestSchedulerClaiming:
    @pytest.mark.asyncio
    async def test_due_session_is_claimed_and_sent(self, isolated_db, monkeypatch):
        from app.services import pomodoro_scheduler_service as ssvc
        from app.core.config import settings as s

        sent: list[dict] = []

        async def _fake_send(**kwargs):
            sent.append(kwargs)
            return {"errcode": 0}

        monkeypatch.setattr(ssvc.wechat, "send_subscribe_message", _fake_send)
        monkeypatch.setattr(s, "WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID", "TPL_X")

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_due")
            sid = await _insert(db, user_id=uid, openid="u_due", due_offset_sec=-30)
            await db.commit()

        await ssvc.PomodoroScheduler().tick()

        async with isolated_db.async_session() as db:
            from sqlalchemy import select
            from app.models.pomodoro import PomodoroSession
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.notification_sent is True
        assert row.notification_sent_at is not None
        assert row.notification_error is None
        assert len(sent) == 1
        assert sent[0]["template_id"] == "TPL_X"
        assert sent[0]["openid"] == "u_due"

    @pytest.mark.asyncio
    async def test_future_session_not_claimed(self, isolated_db, monkeypatch):
        from app.services import pomodoro_scheduler_service as ssvc
        from app.core.config import settings as s

        sent: list[dict] = []
        monkeypatch.setattr(ssvc.wechat, "send_subscribe_message",
                            lambda **kw: sent.append(kw) or {"errcode": 0})
        monkeypatch.setattr(s, "WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID", "TPL_X")

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_future")
            sid = await _insert(db, user_id=uid, openid="u_future", due_offset_sec=300)
            await db.commit()

        await ssvc.PomodoroScheduler().tick()

        async with isolated_db.async_session() as db:
            from sqlalchemy import select
            from app.models.pomodoro import PomodoroSession
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.notification_sent is False
        assert sent == []

    @pytest.mark.asyncio
    async def test_disabled_session_not_claimed(self, isolated_db, monkeypatch):
        from app.services import pomodoro_scheduler_service as ssvc
        from app.core.config import settings as s

        sent: list[dict] = []

        async def _fake_send(**kwargs):
            sent.append(kwargs)
            return {"errcode": 0}

        monkeypatch.setattr(ssvc.wechat, "send_subscribe_message", _fake_send)
        monkeypatch.setattr(s, "WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID", "TPL_X")

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_disabled")
            sid = await _insert(db, user_id=uid, openid="u_disabled", due_offset_sec=-30, enabled=False)
            await db.commit()

        await ssvc.PomodoroScheduler().tick()

        async with isolated_db.async_session() as db:
            from sqlalchemy import select
            from app.models.pomodoro import PomodoroSession
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.notification_sent is False
        assert sent == []

    @pytest.mark.asyncio
    async def test_already_sent_not_resent(self, isolated_db, monkeypatch):
        from app.services import pomodoro_scheduler_service as ssvc
        from app.core.config import settings as s

        sent: list[dict] = []

        async def _fake_send(**kwargs):
            sent.append(kwargs)
            return {"errcode": 0}

        monkeypatch.setattr(ssvc.wechat, "send_subscribe_message", _fake_send)
        monkeypatch.setattr(s, "WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID", "TPL_X")

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_sent")
            await _insert(db, user_id=uid, openid="u_sent", due_offset_sec=-30, sent=True)
            await db.commit()

        await ssvc.PomodoroScheduler().tick()
        assert sent == []

    @pytest.mark.asyncio
    async def test_template_missing_marks_error_and_skips_send(self, isolated_db, monkeypatch):
        from app.services import pomodoro_scheduler_service as ssvc
        from app.core.config import settings as s

        sent: list[dict] = []

        async def _fake_send(**kwargs):
            sent.append(kwargs)
            return {"errcode": 0}

        monkeypatch.setattr(ssvc.wechat, "send_subscribe_message", _fake_send)
        monkeypatch.setattr(s, "WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID", "")

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_no_tpl")
            sid = await _insert(db, user_id=uid, openid="u_no_tpl", due_offset_sec=-30)
            await db.commit()

        await ssvc.PomodoroScheduler().tick()

        async with isolated_db.async_session() as db:
            from sqlalchemy import select
            from app.models.pomodoro import PomodoroSession
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.notification_sent is True  # 至多一次：仍置位
        assert "template_id not configured" in (row.notification_error or "")
        assert sent == []


class TestServiceLayer:
    @pytest.mark.asyncio
    async def test_complete_session_closes_notification_channel(self, isolated_db):
        from app.services import pomodoro_service as svc
        from sqlalchemy import select
        from app.models.pomodoro import PomodoroSession

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_complete")
            session = await svc.start_session(
                db, uid, "math", None, "standard", 25, 5, notification_enabled=True
            )
            sid = session.id
            await db.commit()

        async with isolated_db.async_session() as db:
            await svc.complete_session(db, sid, uid, total_paused_ms=0)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.status == "completed"
        assert row.notification_sent is True
        assert "user completed" in (row.notification_error or "")

    @pytest.mark.asyncio
    async def test_interrupt_session_closes_notification_channel(self, isolated_db):
        from app.services import pomodoro_service as svc
        from sqlalchemy import select
        from app.models.pomodoro import PomodoroSession

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_interrupt")
            session = await svc.start_session(
                db, uid, "math", None, "standard", 25, 5, notification_enabled=True
            )
            sid = session.id
            await db.commit()

        async with isolated_db.async_session() as db:
            await svc.interrupt_session(db, sid, uid, total_paused_ms=0)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.status == "interrupted"
        assert row.notification_sent is True
        assert "user interrupted" in (row.notification_error or "")

    @pytest.mark.asyncio
    async def test_start_session_writes_expected_end_time_and_openid(self, isolated_db):
        from app.services import pomodoro_service as svc
        from sqlalchemy import select
        from app.models.pomodoro import PomodoroSession

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_start")
            session = await svc.start_session(
                db, uid, "english", None, "standard", 25, 5, notification_enabled=True
            )
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == session.id))).scalar_one()

        assert row.expected_end_time is not None
        delta = (row.expected_end_time - row.start_time).total_seconds()
        assert 1499 <= delta <= 1501  # 25 min ±1s
        assert row.openid_snapshot == "u_start"
        assert row.notification_enabled is True
        assert row.notification_sent is False


class TestWechatTokenRetry:
    @pytest.mark.asyncio
    async def test_send_retries_on_token_invalid(self, monkeypatch):
        from app.services import wechat_notify_service as wn

        token_calls = {"n": 0}
        send_calls: list[str] = []

        async def fake_get_token(force_refresh: bool = False) -> str:
            token_calls["n"] += 1
            return f"tok-{token_calls['n']}"

        monkeypatch.setattr(wn, "get_access_token", fake_get_token)

        # 第一次调用返回 40001，第二次成功
        responses = iter([
            {"errcode": 40001, "errmsg": "invalid credential"},
            {"errcode": 0, "errmsg": "ok"},
        ])

        class _Resp:
            def __init__(self, payload):
                self._p = payload
            def json(self):
                return self._p

        class _Client:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def post(self, url, params, json, timeout):
                send_calls.append(params["access_token"])
                return _Resp(next(responses))

        monkeypatch.setattr(wn.httpx, "AsyncClient", lambda: _Client())

        result = await wn.send_subscribe_message(
            openid="o", template_id="t", data={"thing1": {"value": "x"}}, page="p"
        )
        assert result["errcode"] == 0
        assert send_calls == ["tok-1", "tok-2"]
        assert token_calls["n"] == 2  # 第二次是 force_refresh
