"""番茄钟 service 层单元测试。

使用临时 SQLite，覆盖 pomodoro_service 的核心生命周期：
- start_session 写 expected_end_time / openid_snapshot / notification 状态
- pause / resume 对 expected_end_time 与 paused_at 的影响（含幂等、noop）
- complete_session / interrupt_session 关闭通知通道（置 notification_sent）

注：原 PomodoroScheduler 认领发送链路与 wechat_notify_service 已随
订阅消息功能一并移除，相关测试一并删除。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime, timedelta

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

    # 强制重新加载 settings 以应用 env
    import importlib

    from app.core import config as config_mod
    importlib.reload(config_mod)

    # 使用全局 Base — 导入所有模型让其注册到 Base.metadata
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import app.models  # noqa: F401 — registers all models on Base
    from app.core.database import Base
    from app.models import admin as _admin  # noqa: F401
    from app.models.pomodoro import PomodoroSession  # noqa: F401
    from app.models.user import User  # noqa: F401

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
        from sqlalchemy import delete

        from app.models.pomodoro import PomodoroSession
        from app.models.user import User

        await db.execute(delete(PomodoroSession))
        await db.execute(delete(User))
        await db.commit()


async def _make_user(db, openid: str = "openid_test") -> int:
    from app.models.user import User
    u = User(openid=openid)
    db.add(u)
    await db.flush()
    return u.id


async def _make_subject(db) -> int:
    import uuid

    from app.models.admin import Subject
    code = f"test_subject_{uuid.uuid4().hex[:8]}"
    subj = Subject(code=code, name="测试科目", level=1, path="test", is_active=True, sort_order=0)
    db.add(subj)
    await db.flush()
    return subj.id


class TestServiceLayer:
    @pytest.mark.asyncio
    async def test_complete_session_closes_notification_channel(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_complete")
            subj_id = await _make_subject(db)
            session = await svc.start_session(
                db, uid, subj_id, None, "standard", 25, 5, notification_enabled=True
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
        assert "skipped: user completed" in (row.notification_error or "")

    @pytest.mark.asyncio
    async def test_interrupt_session_closes_notification_channel(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_interrupt")
            subj_id = await _make_subject(db)
            session = await svc.start_session(
                db, uid, subj_id, None, "standard", 25, 5, notification_enabled=True
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
        assert "skipped: user interrupted" in (row.notification_error or "")

    @pytest.mark.asyncio
    async def test_start_session_writes_expected_end_time_and_openid(self, isolated_db):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_start")
            subj_id = await _make_subject(db)
            session = await svc.start_session(
                db, uid, subj_id, None, "standard", 25, 5, notification_enabled=True
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
        from sqlalchemy import select, update

        from app.models.pomodoro import PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_pause")
            subj_id = await _make_subject(db)
            session = await svc.start_session(
                db, uid, subj_id, None, "standard", 25, 5, notification_enabled=True
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
                .values(paused_at=datetime.now(UTC) - timedelta(seconds=90))
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
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_pause_idem")
            subj_id = await _make_subject(db)
            session = await svc.start_session(
                db, uid, subj_id, None, "standard", 25, 5, notification_enabled=True
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
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroSession
        from app.services import pomodoro_service as svc

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_resume_noop")
            subj_id = await _make_subject(db)
            session = await svc.start_session(
                db, uid, subj_id, None, "standard", 25, 5, notification_enabled=True
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
