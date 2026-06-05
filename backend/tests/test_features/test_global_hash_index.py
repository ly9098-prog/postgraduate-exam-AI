"""P2-4 GlobalHashIndex 单测。

覆盖：
- recent_days 过滤（仅加载窗口内题目）
- 当前 batch_id 的 import 记录加载
- 阈值降级（fallback_to_sql=True）下 lookup 走单条 SQL
- chunk 间 dedup 通过 add_import → 后续 lookup_import 命中
- env override：HASH_INDEX_RECENT_DAYS / HASH_INDEX_MAX_SIZE
- subject/hash 缺失保护
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.features.global_hash_index import (
    GlobalHashIndex,
    _resolve_max_size,
    _resolve_recent_days,
)
from app.models.question import Question
from app.models.question_import import QuestionImport


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _make_session(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'p2_4_hash.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


def _run(coro):
    return asyncio.run(coro)


def _make_question(
    *,
    qid: int,
    subject: str,
    qhash: str,
    is_active: bool = True,
    created_at: datetime | None = None,
) -> Question:
    return Question(
        id=qid,
        subject=subject,
        question_type="single_choice",
        content={"text": f"stem-{qhash}"},
        options={"A": "a", "B": "b"},
        answer="A",
        question_hash=qhash,
        is_active=is_active,
        created_at=created_at or datetime.now(timezone.utc),
    )


def _make_import(
    *,
    iid: int,
    batch_id: str,
    subject: str,
    qhash: str,
    status: str = "pending",
) -> QuestionImport:
    return QuestionImport(
        id=iid,
        batch_id=batch_id,
        source_type="pdf",
        subject=subject,
        question_type="single_choice",
        raw_data={"stem": f"raw-{qhash}"},
        parsed_content={"text": f"stem-{qhash}"},
        parsed_options={"A": "a"},
        parsed_answer="A",
        question_hash=qhash,
        status=status,
        duplicate_status="normal",
    )


# ---------------------------------------------------------------------------
# env helpers
# ---------------------------------------------------------------------------


class TestResolveRecentDays:
    def test_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HASH_INDEX_RECENT_DAYS", None)
            assert _resolve_recent_days(None) == 30

    def test_env_override(self):
        with patch.dict(os.environ, {"HASH_INDEX_RECENT_DAYS": "7"}):
            assert _resolve_recent_days(None) == 7

    def test_explicit_override_wins_over_env(self):
        with patch.dict(os.environ, {"HASH_INDEX_RECENT_DAYS": "7"}):
            assert _resolve_recent_days(15) == 15

    def test_zero_means_unlimited(self):
        assert _resolve_recent_days(0) == 0

    def test_negative_clamps_to_zero(self):
        assert _resolve_recent_days(-5) == 0

    def test_invalid_env_falls_back_to_default(self):
        with patch.dict(os.environ, {"HASH_INDEX_RECENT_DAYS": "abc"}):
            assert _resolve_recent_days(None) == 30


class TestResolveMaxSize:
    def test_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HASH_INDEX_MAX_SIZE", None)
            assert _resolve_max_size() == 500_000

    def test_env_override(self):
        with patch.dict(os.environ, {"HASH_INDEX_MAX_SIZE": "100"}):
            assert _resolve_max_size() == 100

    def test_zero_or_negative_falls_back_to_default(self):
        with patch.dict(os.environ, {"HASH_INDEX_MAX_SIZE": "0"}):
            assert _resolve_max_size() == 500_000


# ---------------------------------------------------------------------------
# load + lookup
# ---------------------------------------------------------------------------


class TestLoadRecentDays:
    """recent_days 过滤：超过窗口的历史题不加载。"""

    def test_only_recent_loaded(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            now = datetime.now(timezone.utc)
            async with sm() as db:
                # 60 条最近 30 天（hash hh000..hh059）
                for i in range(60):
                    db.add(_make_question(
                        qid=1000 + i,
                        subject="exam408",
                        qhash=f"hh{i:03d}",
                        created_at=now - timedelta(days=5),
                    ))
                # 40 条更早的（hash old000..old039）
                for i in range(40):
                    db.add(_make_question(
                        qid=2000 + i,
                        subject="exam408",
                        qhash=f"old{i:03d}",
                        created_at=now - timedelta(days=120),
                    ))
                await db.commit()

            async with sm() as db:
                index = GlobalHashIndex()
                await index.load(db, recent_days=30)

                # 60 条最近的应入索引
                assert index.stats["question_count"] == 60
                assert index.is_fallback is False

                # 命中：最近的 hash 找得到
                hit = await index.lookup_question(db, "exam408", "hh000")
                assert hit == 1000

                # 历史 hash 不在内存中（不走 SQL fallback）
                miss = await index.lookup_question(db, "exam408", "old000")
                assert miss is None

        _run(_go())

    def test_unlimited_window_loads_everything(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            now = datetime.now(timezone.utc)
            async with sm() as db:
                db.add(_make_question(
                    qid=1, subject="math2", qhash="recent",
                    created_at=now - timedelta(days=3),
                ))
                db.add(_make_question(
                    qid=2, subject="math2", qhash="ancient",
                    created_at=now - timedelta(days=999),
                ))
                await db.commit()

            async with sm() as db:
                index = GlobalHashIndex()
                await index.load(db, recent_days=0)
                assert index.stats["question_count"] == 2
                assert (await index.lookup_question(db, "math2", "ancient")) == 2

        _run(_go())


class TestInactiveExcluded:
    def test_inactive_questions_not_loaded(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            now = datetime.now(timezone.utc)
            async with sm() as db:
                db.add(_make_question(
                    qid=1, subject="math2", qhash="active",
                    is_active=True, created_at=now,
                ))
                db.add(_make_question(
                    qid=2, subject="math2", qhash="inactive",
                    is_active=False, created_at=now,
                ))
                await db.commit()

            async with sm() as db:
                index = GlobalHashIndex()
                await index.load(db, recent_days=30)
                assert index.stats["question_count"] == 1
                assert (await index.lookup_question(db, "math2", "active")) == 1
                assert (await index.lookup_question(db, "math2", "inactive")) is None

        _run(_go())


class TestBatchImportLoad:
    """batch_id 注入时同时加载当前批次的 QuestionImport。"""

    def test_batch_imports_loaded(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                db.add(_make_import(
                    iid=11, batch_id="REVIEW_B1",
                    subject="exam408", qhash="imp001",
                ))
                db.add(_make_import(
                    iid=12, batch_id="REVIEW_B1",
                    subject="exam408", qhash="imp002",
                ))
                # different batch — should NOT load
                db.add(_make_import(
                    iid=99, batch_id="REVIEW_B2",
                    subject="exam408", qhash="other",
                ))
                # rejected — should NOT load
                db.add(_make_import(
                    iid=13, batch_id="REVIEW_B1",
                    subject="exam408", qhash="rej001",
                    status="rejected",
                ))
                await db.commit()

            async with sm() as db:
                index = GlobalHashIndex()
                await index.load(db, recent_days=30, batch_id="REVIEW_B1")
                assert index.stats["import_count"] == 2
                assert (await index.lookup_import(db, "exam408", "imp001")) == 11
                assert (await index.lookup_import(db, "exam408", "imp002")) == 12
                assert (await index.lookup_import(db, "exam408", "other")) is None
                assert (await index.lookup_import(db, "exam408", "rej001")) is None

        _run(_go())


class TestFallbackToSql:
    """超过 max_size 时不真正加载，lookup 改走单条 SQL。"""

    def test_threshold_triggers_fallback(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            now = datetime.now(timezone.utc)
            async with sm() as db:
                # 5 条 active
                for i in range(5):
                    db.add(_make_question(
                        qid=100 + i, subject="exam408",
                        qhash=f"big{i:03d}",
                        created_at=now,
                    ))
                await db.commit()

            async with sm() as db:
                # 把 max_size 调到 3，5 条直接进 fallback
                with patch.dict(os.environ, {"HASH_INDEX_MAX_SIZE": "3"}):
                    index = GlobalHashIndex()
                    await index.load(db, recent_days=30)

                assert index.is_fallback is True
                assert index.stats["fallback_to_sql"] is True
                # 内存里没东西
                assert len(index._question_index) == 0
                # 但 SQL 仍然能命中
                assert (await index.lookup_question(db, "exam408", "big001")) == 101
                # 不存在的 hash 仍然 None
                assert (await index.lookup_question(db, "exam408", "missing")) is None

        _run(_go())


class TestAddImportCrossChunk:
    """chunk[0] add 后 chunk[1] 能命中。"""

    def test_add_then_lookup_in_memory(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                # 空库，让 index 进入 in-memory 模式
                pass

            async with sm() as db:
                index = GlobalHashIndex()
                await index.load(db, recent_days=30)
                assert index.is_fallback is False

                # 模拟 chunk 0 写完
                index.add_import("exam408", "chunk0_h", 7001)
                # chunk 1 lookup 应命中
                hit = await index.lookup_import(db, "exam408", "chunk0_h")
                assert hit == 7001

                # 重复 add 不覆盖（保留首条 import_id）
                index.add_import("exam408", "chunk0_h", 9999)
                hit2 = await index.lookup_import(db, "exam408", "chunk0_h")
                assert hit2 == 7001

        _run(_go())

    def test_add_is_noop_in_fallback_mode(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            now = datetime.now(timezone.utc)
            async with sm() as db:
                for i in range(5):
                    db.add(_make_question(
                        qid=200 + i, subject="exam408",
                        qhash=f"f{i}", created_at=now,
                    ))
                await db.commit()

            async with sm() as db:
                with patch.dict(os.environ, {"HASH_INDEX_MAX_SIZE": "1"}):
                    index = GlobalHashIndex()
                    await index.load(db, recent_days=30)
                assert index.is_fallback is True

                # add 在 fallback 下是 no-op，不污染内存 index
                index.add_import("exam408", "ghost", 12345)
                assert len(index._import_index) == 0
                # 但 lookup_import 仍走 SQL 兜底
                assert (await index.lookup_import(db, "exam408", "ghost")) is None

        _run(_go())


class TestNullSafety:
    def test_lookup_with_missing_subject_or_hash(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                index = GlobalHashIndex()
                await index.load(db, recent_days=30)

                assert (await index.lookup_question(db, None, "h")) is None
                assert (await index.lookup_question(db, "math2", None)) is None
                assert (await index.lookup_question(db, "", "h")) is None

                index.add_import("", "h", 1)
                index.add_import("math2", "", 1)
                index.add_import("math2", "h", 0)  # falsy id ignored
                assert len(index._import_index) == 0

        _run(_go())
