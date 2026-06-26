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
from datetime import timezone, datetime, timedelta

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

    # 强制重新加载 settings 以应用 env
    import importlib
    from app.core import config as config_mod
    importlib.reload(config_mod)

    # 重新加载 pomodoro 调度服务模块，确保引用最新的 settings 单例。
    # 若此前其他测试已导入该模块，其 settings 引用仍指向旧单例，
    # 导致后续 test function 的 monkeypatch 无法生效。
    import app.services.pomodoro_scheduler_service as _ssvc_for_reload
    importlib.reload(_ssvc_for_reload)

    # 使用全局 Base — 导入所有模型让其注册到 Base.metadata
    from app.core.database import Base
    import app.models  # noqa: F401 — registers all models on Base
    from app.models import admin as _admin  # noqa: F401
    from app.models import app_user_admin_binding as _aub  # noqa: F401
    from app.models.user import User  # noqa: F401
    from app.models.pomodoro import PomodoroSession  # noqa: F401

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp.name}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 构建一个类似 db_mod 的命名空间让下游 fixture 正常工作
    import types
    fake_db = types.SimpleNamespace(
        engine=engine,
        async_session=session_factory,
        Base=Base,
    )

    yield fake_db

    try:
        await engine.dispose()
        os.unlink(tmp.name)
    except Exception:
        pass


@pytest.fixture(scope="module", autouse=True)
def patch_async_session(isolated_db):
    """Patch async_session in modules used by PomodoroScheduler to use the isolated DB."""
    from app.core import database
    import app.services.pomodoro_scheduler_service as ssvc

    orig_db = database.async_session
    orig_ssvc = ssvc.async_session

    try:
        database.async_session = isolated_db.async_session
        ssvc.async_session = isolated_db.async_session
        yield
    finally:
        database.async_session = orig_db
        ssvc.async_session = orig_ssvc


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
                 status: str = "running", work: int = 25,
                 paused_at: datetime | None = None):
    from app.models.pomodoro import PomodoroSession
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    s = PomodoroSession(
        user_id=user_id, subject="math", chapter_id=None, preset="standard",
        work_duration=work, break_duration=5,
        start_time=now - timedelta(minutes=work),
        expected_end_time=now + timedelta(seconds=due_offset_sec),
        status=status,
        notification_enabled=enabled,
        notification_sent=sent,
        openid_snapshot=openid,
        paused_at=paused_at,
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

    @pytest.mark.asyncio
    async def test_paused_session_not_claimed(self, isolated_db, monkeypatch):
        from app.services import pomodoro_scheduler_service as ssvc
        from app.core.config import settings as s

        sent: list[dict] = []

        async def _fake_send(**kwargs):
            sent.append(kwargs)
            return {"errcode": 0}

        monkeypatch.setattr(ssvc.wechat, "send_subscribe_message", _fake_send)
        monkeypatch.setattr(s, "WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID", "TPL_X")

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_paused")
            sid = await _insert(
                db, user_id=uid, openid="u_paused",
                due_offset_sec=-30, paused_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=60),
            )
            await db.commit()

        await ssvc.PomodoroScheduler().tick()

        async with isolated_db.async_session() as db:
            from sqlalchemy import select
            from app.models.pomodoro import PomodoroSession
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.notification_sent is False, "paused session must not be claimed"
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

    @pytest.mark.asyncio
    async def test_pause_then_resume_extends_expected_end_time(self, isolated_db):
        from app.services import pomodoro_service as svc
        from sqlalchemy import select, update
        from app.models.pomodoro import PomodoroSession

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_pause")
            session = await svc.start_session(
                db, uid, "math", None, "standard", 25, 5, notification_enabled=True
            )
            sid = session.id
            await db.commit()

        # 暂停
        async with isolated_db.async_session() as db:
            await svc.pause_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()
            paused_eet = row.expected_end_time
            assert row.paused_at is not None, "暂停后 paused_at 必须有值"

        # 把 paused_at 倒推 90 秒模拟"暂停了 90 秒"
        async with isolated_db.async_session() as db:
            await db.execute(
                update(PomodoroSession)
                .where(PomodoroSession.id == sid)
                .values(paused_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=90))
            )
            await db.commit()

        # 恢复
        async with isolated_db.async_session() as db:
            await svc.resume_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.paused_at is None
        # expected_end_time 应延后 ~90 秒（容忍 ±2 秒处理时延）
        delta = (row.expected_end_time - paused_eet).total_seconds()
        assert 88 <= delta <= 92, f"expected ~90s shift, got {delta}s"

    @pytest.mark.asyncio
    async def test_pause_is_idempotent(self, isolated_db):
        from app.services import pomodoro_service as svc
        from sqlalchemy import select
        from app.models.pomodoro import PomodoroSession

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_pause_idem")
            session = await svc.start_session(
                db, uid, "math", None, "standard", 25, 5, notification_enabled=True
            )
            sid = session.id
            await db.commit()

        async with isolated_db.async_session() as db:
            await svc.pause_session(db, sid, uid)
            await db.commit()
        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()
            first_paused_at = row.paused_at

        # 第二次 pause 不应改变 paused_at
        async with isolated_db.async_session() as db:
            await svc.pause_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.paused_at == first_paused_at, "重复暂停不应推后 paused_at"

    @pytest.mark.asyncio
    async def test_resume_without_pause_is_noop(self, isolated_db):
        from app.services import pomodoro_service as svc
        from sqlalchemy import select
        from app.models.pomodoro import PomodoroSession

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_resume_noop")
            session = await svc.start_session(
                db, uid, "math", None, "standard", 25, 5, notification_enabled=True
            )
            sid = session.id
            original_eet = session.expected_end_time
            await db.commit()

        async with isolated_db.async_session() as db:
            await svc.resume_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.paused_at is None
        # 未暂停的 resume 不应改 expected_end_time
        assert abs((row.expected_end_time - original_eet).total_seconds()) < 1


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


class TestAsyncSessionIsolation:
    """Regression: verify patch_async_session fixture isolates the scheduler."""

    @pytest.mark.asyncio
    async def test_async_session_patched_to_isolated_db(self, isolated_db):
        """patch_async_session must point ssvc.async_session to isolated_db."""
        import app.services.pomodoro_scheduler_service as ssvc
        from app.core import database

        assert ssvc.async_session is isolated_db.async_session, (
            "ssvc.async_session must be isolated_db.async_session"
        )
        assert database.async_session is isolated_db.async_session, (
            "database.async_session must be isolated_db.async_session"
        )

    @pytest.mark.asyncio
    async def test_scheduler_tick_finds_data_in_isolated_db(self, isolated_db, monkeypatch):
        """Tick must find sessions in the isolated DB (not the global test DB)."""
        from app.services import pomodoro_scheduler_service as ssvc
        from app.core.config import settings as s

        sent: list[dict] = []

        async def _fake_send(**kwargs):
            sent.append(kwargs)
            return {"errcode": 0}

        monkeypatch.setattr(ssvc.wechat, "send_subscribe_message", _fake_send)
        monkeypatch.setattr(s, "WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID", "TPL_ISO")

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_iso_check")
            await _insert(db, user_id=uid, openid="u_iso_check", due_offset_sec=-30)
            await db.commit()

        await ssvc.PomodoroScheduler().tick()

        async with isolated_db.async_session() as db:
            from sqlalchemy import select
            from app.models.pomodoro import PomodoroSession
            rows = (await db.execute(select(PomodoroSession))).scalars().all()

        assert len(rows) == 1
        assert rows[0].notification_sent is True, (
            "Scheduler must claim the session via patched async_session"
        )
