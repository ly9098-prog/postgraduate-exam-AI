"""Pomodoro 统计快照性能基准（synthetic，非 CI gate）。

对比组合统计接口（一次 snapshot：stats + trends + daily_summary 一次 load + 一次归因）
与逐接口（/stats + /trends + /daily-summary 各自 load + attribution）的
DB query 数量与计算耗时；并单独测 90 天趋势窗口下的扩展性。

生成 90 天 synthetic 数据，每天 20 / 50 / 100 sessions、每 session 0~5 pauses。

用法:
    cd backend
    .venv/bin/python tests/benchmarks/bench_pomodoro_snapshot.py

注意：90 天 × 100 sessions 是极端合成量（≈41h/天），用于观察 query 是否有界，
不反映真实用户规模。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./_bench_pomodoro.db")
os.environ.setdefault("REDIS_URL", "")

import sqlalchemy as sa

import app.models  # noqa: F401 — registers all models on Base
from app.core import time_utils
from app.core.database import Base
from app.models.admin import Subject
from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession
from app.models.user import User

FIXED_NOW = datetime(2026, 8, 8, 10, 0, 0)  # UTC；today = 08-08 (dsm=0)


class _QueryCounter:
    def __init__(self, engine):
        self.statements: list[str] = []
        sa.event.listen(engine.sync_engine, "before_cursor_execute", self._hook)

    def _hook(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(str(statement))

    def clear(self):
        self.statements.clear()

    def detach(self, engine):
        sa.event.remove(engine.sync_engine, "before_cursor_execute", self._hook)


async def _seed(session_factory, *, days, per_day, max_pauses, openid) -> int:
    """Seed ``days`` × ``per_day`` completed sessions, 0..max_pauses pauses each."""
    start_date = date(2026, 5, 11)  # 90 天窗口起点，相对 FIXED_NOW=08-08
    n_pauses_total = 0
    code = f"bench_{openid}"
    async with session_factory() as db:
        u = User(openid=openid)
        db.add(u)
        await db.flush()
        uid = u.id
        subj = Subject(
            code=code, name="数学二", level=1,
            path=code, is_active=True, sort_order=0,
        )
        db.add(subj)
        await db.flush()
        for d in range(days):
            day = start_date + timedelta(days=d)
            for i in range(per_day):
                start = datetime(day.year, day.month, day.day, 8, 0, 0) + timedelta(minutes=i * 6)
                end = start + timedelta(minutes=25)
                s = PomodoroSession(
                    user_id=uid, subject_id=subj.id, preset="standard",
                    work_duration=25, break_duration=5,
                    start_time=start, end_time=end,
                    actual_duration=1500, status="completed",
                )
                db.add(s)
                await db.flush()
                n_pauses = (i % (max_pauses + 1)) if max_pauses else 0
                for p in range(n_pauses):
                    db.add(PomodoroPauseInterval(
                        session_id=s.id,
                        started_at=start + timedelta(minutes=1 + p),
                        ended_at=start + timedelta(minutes=2 + p),
                    ))
                n_pauses_total += n_pauses
        await db.commit()
        return uid, n_pauses_total


async def _combined(session_factory, uid, *, trends_days, counter):
    from app.services import pomodoro_service as svc

    counter.clear()
    t0 = time.perf_counter()
    async with session_factory() as db:
        snap = await svc.build_pomodoro_statistics_snapshot(
            db, uid, trends_days=trends_days,
            need_stats=True, need_trends=True, need_daily_summary=True,
        )
    dt = time.perf_counter() - t0
    return snap, dt, len(counter.statements)


async def _naive(session_factory, uid, counter):
    """Before-口径：统计页逐接口各 load + attribution。"""
    from app.services import pomodoro_service as svc

    counter.clear()
    t0 = time.perf_counter()
    async with session_factory() as db:
        stats = await svc.get_stats(db, uid)
        trends = await svc.get_trends(db, uid, 7)
        summary = await svc.get_daily_summary(db, uid)
    dt = time.perf_counter() - t0
    return (stats, trends, summary), dt, len(counter.statements)


async def _main() -> None:
    tmp = tempfile.NamedTemporaryFile(prefix="bench_pomo_", suffix=".db", delete=False)
    tmp.close()
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}", connect_args={"check_same_thread": False})
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    time_utils.utcnow = lambda: FIXED_NOW

    counter = _QueryCounter(engine)
    header = (
        f"{'per_day':>8} {'sessions':>9} {'pauses':>7} | "
        f"{'combined_q':>10} {'combined_ms':>11} | "
        f"{'trend90_q':>10} {'trend90_ms':>11} | "
        f"{'naive_q':>8} {'naive_ms':>10}"
    )
    print(header)
    print("-" * len(header))
    try:
        for per_day in (20, 50, 100):
            uid, n_pauses = await _seed(
                session_factory, days=90, per_day=per_day, max_pauses=5,
                openid=f"bench_{per_day}",
            )
            n_sessions = 90 * per_day

            # warm-up：SQLite 页缓存 / 首条 SQL 编译，不计入耗时
            await _combined(session_factory, uid, trends_days=7, counter=counter)
            await _combined(session_factory, uid, trends_days=90, counter=counter)
            await _naive(session_factory, uid, counter)

            _, c_dt, c_q = await _combined(session_factory, uid, trends_days=7, counter=counter)
            _, t_dt, t_q = await _combined(session_factory, uid, trends_days=90, counter=counter)
            _, n_dt, n_q = await _naive(session_factory, uid, counter)

            print(
                f"{per_day:>8} {n_sessions:>9} {n_pauses:>7} | "
                f"{c_q:>10} {c_dt * 1000:>9.2f} | "
                f"{t_q:>10} {t_dt * 1000:>9.2f} | "
                f"{n_q:>8} {n_dt * 1000:>8.2f}"
            )
    finally:
        counter.detach(engine)
        await engine.dispose()
        os.unlink(tmp.name)


if __name__ == "__main__":
    asyncio.run(_main())
