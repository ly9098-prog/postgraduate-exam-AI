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
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(loop_scope="module", scope="module")
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

        from app.models.pomodoro import (
            PomodoroPauseInterval,
            PomodoroSession,
            PomodoroSubjectAllocation,
        )
        from app.models.user import User

        await db.execute(delete(PomodoroPauseInterval))
        # SQLite does not enable the allocation table's FK cascade in this fixture.
        await db.execute(delete(PomodoroSubjectAllocation))
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
    from sqlalchemy import select

    from app.models.admin import Subject
    subj = await db.scalar(select(Subject).where(Subject.code == "advanced_math"))
    if subj is not None:
        return subj.id
    subj = Subject(
        code="advanced_math", name="高等数学", level=1, path="advanced_math",
        is_active=True, sort_order=0,
    )
    db.add(subj)
    await db.flush()
    return subj.id


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    from app.services import pomodoro_service as svc

    value = SimpleNamespace(now=datetime(2026, 8, 8, 0, 0))
    monkeypatch.setattr(svc, "utcnow", lambda: value.now)
    return value


class TestServiceLayer:
    @pytest.mark.asyncio
    async def test_complete_session_closes_notification_channel(self, isolated_db, clock):
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
            with pytest.raises(svc.PomodoroNotReadyError):
                await svc.complete_session(db, sid, uid)
            await db.rollback()

        clock.now += timedelta(minutes=25)
        async with isolated_db.async_session() as db:
            await svc.complete_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()

        assert row.status == "completed"
        assert row.actual_duration == 1500
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
            await svc.interrupt_session(db, sid, uid)
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
        assert delta == 1500
        assert row.openid_snapshot == "u_start"
        assert row.notification_enabled is True
        assert row.notification_sent is False

    @pytest.mark.asyncio
    async def test_pause_then_resume_extends_expected_end_time(self, isolated_db, clock):
        from sqlalchemy import select

        from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
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

        clock.now += timedelta(seconds=90)

        # 恢复
        async with isolated_db.async_session() as db:
            await svc.resume_session(db, sid, uid)
            await db.commit()

        async with isolated_db.async_session() as db:
            row = (await db.execute(select(PomodoroSession).where(PomodoroSession.id == sid))).scalar_one()
            interval = (await db.execute(
                select(PomodoroPauseInterval).where(PomodoroPauseInterval.session_id == sid)
            )).scalar_one()

        assert row.paused_at is None
        delta = (row.expected_end_time - paused_eet).total_seconds()
        assert delta == 90
        assert (interval.ended_at - interval.started_at).total_seconds() == 90
        assert row.total_paused_sec == 90

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
        assert row.expected_end_time == original_eet


class TestTimelineBoundaries:
    @pytest.mark.asyncio
    async def test_complete_terminal_without_end_time_keeps_not_ready_error(
        self, isolated_db, clock
    ):
        from app.models.pomodoro import PomodoroSession
        from app.services import pomodoro_service as svc

        start = datetime(2026, 8, 8, 0, 0)
        clock.now = start + timedelta(minutes=1)

        async with isolated_db.async_session() as db:
            uid = await _make_user(db, "u_terminal_missing_end")
            subj_id = await _make_subject(db)
            session = PomodoroSession(
                user_id=uid,
                subject_id=subj_id,
                preset="standard",
                work_duration=25,
                break_duration=5,
                start_time=start,
                expected_end_time=start + timedelta(minutes=25),
                end_time=None,
                actual_duration=5,
                status="completed",
                notification_enabled=False,
                notification_sent=True,
                total_paused_sec=0,
            )
            db.add(session)
            await db.flush()
            session_id = session.id
            await db.commit()

        async with isolated_db.async_session() as db:
            with pytest.raises(svc.PomodoroNotReadyError, match="POMODORO_NOT_READY"):
                await svc.complete_session(
                    db,
                    session_id=session_id,
                    user_id=uid,
                    client_action_at=start + timedelta(seconds=5),
                )

    def test_resolve_client_action_time_keeps_floor_ahead_of_server(self):
        from app.services import pomodoro_service as svc

        start = datetime(2026, 8, 8, 0, 0)
        server_now = start + timedelta(minutes=1)
        floor = server_now + timedelta(seconds=1)
        session = SimpleNamespace(start_time=start, pause_intervals=[])

        assert (
            svc._resolve_client_action_time(session, None, server_now, floor=floor)
            == floor
        )

    def test_delayed_resume_before_latest_pause_start_is_rejected(self):
        from app.services import pomodoro_service as svc

        start = datetime(2026, 8, 8, 0, 0)
        latest = SimpleNamespace(
            started_at=start + timedelta(seconds=10),
            ended_at=start + timedelta(seconds=20),
        )
        session = SimpleNamespace(start_time=start, pause_intervals=[latest])

        with pytest.raises(svc.PomodoroStaleActionError):
            svc._shorten_latest_closed_pause(
                session,
                latest,
                start + timedelta(seconds=5),
                start + timedelta(seconds=30),
            )

        assert latest.ended_at == start + timedelta(seconds=20)
