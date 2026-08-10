"""sync_merge_service 知识点修复测试：F2（KP 同步异常不静默丢包）、F6（仅改科目重建映射）。"""
import asyncio
import tempfile
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _Db:
    engine: object
    session_factory: sessionmaker


@pytest.fixture()
def db():
    f = tempfile.NamedTemporaryFile(prefix="sync_merge_kp_", suffix=".db", delete=False)
    f.close()

    import app.models  # noqa: F401 — register all tables
    from app.core.database import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{f.name}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    _run(_init())
    return _Db(engine=engine, session_factory=session_factory)


def _package_with_question(qid: str, **overrides) -> dict:
    base = {
        "sync_uuid": qid,
        "subject_id": 1,
        "question_type": "single_choice",
        "content": {"text": "q"},
        "answer": "A",
        "question_hash": "h" + qid,
        "updated_at": "2026-08-02T00:00:00",
    }
    base.update(overrides)
    return {"tags": [], "questions": [base]}


# ── F2：KP 同步抛 IntegrityError → 回滚整个 package 并记入 report ──


@pytest.mark.asyncio
async def test_kp_sync_error_rolls_back_and_records_report(db):
    from sqlalchemy.exc import IntegrityError

    from app.features.sync_merge_service import merge_sync_package

    async with db.session_factory() as s:
        pkg = _package_with_question("kp-err-1", knowledge_points=["线性表"])
        with patch(
            "app.services.knowledge_point_service.sync_question_knowledge_points",
            new=AsyncMock(
                side_effect=IntegrityError(
                    "INSERT ...", {}, Exception("UNIQUE constraint failed")
                )
            ),
        ):
            report = await merge_sync_package(s, pkg)

        assert report.questions_new == 1
        assert report.errors, "KP 同步异常必须记入 report"
        # 事务已回滚：题目行不应落库
        await s.rollback()
        q = (await s.execute(select(Question).where(Question.sync_uuid == "kp-err-1"))).scalar_one_or_none()
        assert q is None


# ── F6：仅改科目、未携带知识点 → 用旧展示名在新科目下重建映射 ──


@pytest.mark.asyncio
async def test_subject_only_change_remaps_kp_under_new_subject(db):
    from app.features.sync_merge_service import merge_sync_package
    from app.services.knowledge_point_service import (
        load_question_kps,
        sync_question_knowledge_points,
    )

    async with db.session_factory() as s:
        q = Question(subject_id=1, question_type="single_choice",
                     content={"text": "q"}, answer="A",
                     question_hash="h-subj", sync_uuid="subj-change-1",
                     updated_at=datetime(2026, 8, 1))
        s.add(q)
        await s.flush()
        await sync_question_knowledge_points(s, q, ["线性表", "顺序表"], source="test")
        await s.commit()

        # 云端只改 subject_id=2，不带 knowledge_points
        pkg = _package_with_question(
            "subj-change-1",
            subject_id=2,
            updated_at="2026-08-03T00:00:00",
        )
        report = await merge_sync_package(s, pkg)
        await s.commit()

        assert report.questions_updated == 1
        kp_map = await load_question_kps(s, [q.id])
        # 展示名保留
        assert kp_map[q.id] == ["线性表", "顺序表"]
        # 但知识点归属到 subject 2
        rows = (
            await s.execute(
                select(KnowledgePoint.subject_id, KnowledgePoint.name)
                .join(QuestionKnowledgePoint, QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id)
                .where(QuestionKnowledgePoint.question_id == q.id)
            )
        ).all()
        assert {(subj, name) for subj, name in rows} == {(2, "线性表"), (2, "顺序表")}
        # subject 不变量：无残留指向旧科目
        assert {subj for subj, _ in rows} == {2}
