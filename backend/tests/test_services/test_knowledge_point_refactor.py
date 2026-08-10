"""知识点关联表重构新增测试：load_question_kps / 过滤 helper / subject 不变量。"""
import asyncio
import tempfile
from dataclasses import dataclass
from datetime import datetime

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
    f = tempfile.NamedTemporaryFile(prefix="kp_refactor_", suffix=".db", delete=False)
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


async def _seed(db: AsyncSession, subject_id=1):
    """造题目 + 知识点 + 映射。"""
    from app.services.knowledge_point_service import sync_question_knowledge_points

    now = datetime(2026, 8, 1)
    q1 = Question(subject_id=subject_id, question_type="single_choice",
                  content={"text": "q1"}, answer="A", difficulty=2, created_at=now)
    q2 = Question(subject_id=subject_id, question_type="single_choice",
                  content={"text": "q2"}, answer="B", difficulty=3, created_at=now)
    db.add_all([q1, q2])
    await db.flush()
    await sync_question_knowledge_points(db, q1, ["线性表", "顺序表"], source="test")
    await sync_question_knowledge_points(db, q2, ["二叉树", "树"], source="test")
    await db.commit()
    return q1.id, q2.id


# ── load_question_kps ──

@pytest.mark.asyncio
async def test_load_question_kps_batch_and_order(db):
    from app.services.knowledge_point_service import load_question_kps

    async with db.session_factory() as s:
        q1, q2 = await _seed(s)
        kp_map = await load_question_kps(s, [q1, q2, q1, 99999, 0])
        assert kp_map[q1] == ["线性表", "顺序表"]  # 顺序按 position
        assert kp_map[q2] == ["二叉树", "树"]
        assert kp_map[99999] == []  # 无映射的题返回 []
        assert kp_map[0] == []  # 请求的 id 都返回键


@pytest.mark.asyncio
async def test_load_question_kps_empty_ids(db):
    from app.services.knowledge_point_service import load_question_kps

    async with db.session_factory() as s:
        assert await load_question_kps(s, []) == {}


@pytest.mark.asyncio
async def test_load_question_kps_no_n1(db):
    """一次 execute 完成批量加载（无 N+1）。"""
    from app.services.knowledge_point_service import load_question_kps

    async with db.session_factory() as s:
        q1, q2 = await _seed(s)
        executed = []

        class _Spy:
            def __init__(self, inner):
                self.inner = inner

            async def execute(self, *a, **k):
                executed.append(1)
                return await self.inner.execute(*a, **k)

        spy = _Spy(s)
        await load_question_kps(spy, [q1, q2])
        assert len(executed) == 1


# ── 过滤 helper ──

@pytest.mark.asyncio
async def test_kp_filter_and_any_fuzzy(db):
    from sqlalchemy import and_, select

    from app.services.knowledge_point_service import (
        kp_any_condition,
        kp_exact_conditions,
        kp_fuzzy_condition,
    )

    async with db.session_factory() as s:
        q1, q2 = await _seed(s)
        # AND 语义：同时命中"线性表"和"顺序表" → q1
        and_conds = kp_exact_conditions([" 线性表 ", "顺序表"])
        r1 = (await s.execute(select(Question.id).where(and_(*and_conds)))).scalars().all()
        assert r1 == [q1]
        # OR 语义：命中"线性表"或"二叉树" → q1, q2
        any_cond = kp_any_condition(["线性表", "二叉树"])
        r2 = (await s.execute(select(Question.id).where(any_cond))).scalars().all()
        assert set(r2) == {q1, q2}
        # 模糊：contains "树" → q2（二叉树/树）
        fuzzy = kp_fuzzy_condition("树")
        r3 = (await s.execute(select(Question.id).where(fuzzy))).scalars().all()
        assert set(r3) == {q2}


@pytest.mark.asyncio
async def test_kp_filter_normalization(db):
    """大小写/全角/空格归一化匹配。"""
    from sqlalchemy import select

    from app.services.knowledge_point_service import (
        kp_exact_conditions,
        sync_question_knowledge_points,
    )

    async with db.session_factory() as s:
        now = datetime(2026, 8, 1)
        q = Question(subject_id=2, question_type="single_choice",
                     content={"text": "q"}, answer="A", difficulty=2, created_at=now)
        s.add(q)
        await s.flush()
        await sync_question_knowledge_points(s, q, ["CPU 调度"], source="test")
        await s.commit()
        # 全角空格 + 英文大小写归一化后应命中
        cond = kp_exact_conditions(["ＣＰＵ　调度"])
        r = (await s.execute(select(Question.id).where(*cond))).scalars().all()
        assert r == [q.id]


# ── subject 不变量（Case B：只改 subject 时用旧名重建映射）──

@pytest.mark.asyncio
async def test_replace_respects_subject_invariant(db):
    from app.services.knowledge_point_service import (
        load_question_kps,
        replace_question_knowledge_points,
    )

    async with db.session_factory() as s:
        q1, _q2 = await _seed(s, subject_id=1)
        q = (await s.execute(select(Question).where(Question.id == q1))).scalar_one()
        # 先把题迁移到 subject 2，再 replace（Case B：subject 变、KP 名不变）
        q.subject_id = 2
        await s.flush()
        await replace_question_knowledge_points(s, q, ["线性表", "顺序表"], source="admin")
        await s.commit()
        # 新映射都挂在 subject 2 下
        kp_map = await load_question_kps(s, [q1])
        assert kp_map[q1] == ["线性表", "顺序表"]
        kp_rows = (await s.execute(
            select(KnowledgePoint).join(
                QuestionKnowledgePoint, QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id
            ).where(QuestionKnowledgePoint.question_id == q1)
        )).scalars().all()
        assert {kp.subject_id for kp in kp_rows} == {2}


# ── 版本历史快照：当前值变更不改变历史（service 层快照）──

@pytest.mark.asyncio
async def test_sync_replace_keeps_position_order(db):
    """replace 后 position 仍按输入顺序。"""
    from app.services.knowledge_point_service import (
        load_question_kps,
        replace_question_knowledge_points,
    )

    async with db.session_factory() as s:
        q1, _q2 = await _seed(s)
        q = (await s.execute(select(Question).where(Question.id == q1))).scalar_one()
        await replace_question_knowledge_points(s, q, ["栈", "队列", "线性表"], source="admin")
        await s.commit()
        kp_map = await load_question_kps(s, [q1])
        assert kp_map[q1] == ["栈", "队列", "线性表"]


@pytest.mark.asyncio
async def test_sync_replace_swap_and_shrink_respect_position_constraint(db):
    """F1: replace 重排/删补在 uq_qkp_question_position 下不触发瞬时冲突。

    SQLite 的 create_all 不会建该约束，测试内手动建 UNIQUE INDEX 模拟生产 A2
    迁移后的约束；旧实现（同表 flush 按 UPDATE→INSERT→DELETE 排序）在 swap
    场景会抛 IntegrityError，两阶段 position 更新后正常。
    """
    from sqlalchemy import text

    from app.services.knowledge_point_service import (
        load_question_kps,
        replace_question_knowledge_points,
    )

    async with db.session_factory() as s:
        await s.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_qkp_question_position "
                "ON question_knowledge_points (question_id, position)"
            )
        )
        await s.commit()

        q1, _q2 = await _seed(s)
        q = (await s.execute(select(Question).where(Question.id == q1))).scalar_one()

        # swap：A↔B 互换位置
        await replace_question_knowledge_points(s, q, ["顺序表", "线性表"], source="admin")
        await s.commit()
        kp_map = await load_question_kps(s, [q1])
        assert kp_map[q1] == ["顺序表", "线性表"]

        # 删一个 + 增一个 + 保留一个（先删后 flush 再 insert 路径）
        await replace_question_knowledge_points(s, q, ["线性表", "栈"], source="admin")
        await s.commit()
        kp_map = await load_question_kps(s, [q1])
        assert kp_map[q1] == ["线性表", "栈"]


# ── 题库 keyword 搜索增强：命中知识点名 / aliases ──

@pytest.mark.asyncio
async def test_list_admin_questions_keyword_matches_kp_name(db):
    from app.services.admin_question_service import list_admin_questions

    async with db.session_factory() as s:
        q1, _q2 = await _seed(s)
        questions, total = await list_admin_questions(s, page=1, page_size=20, keyword="线性表")
        assert total == 1
        assert questions[0].id == q1


@pytest.mark.asyncio
async def test_list_admin_questions_keyword_matches_kp_aliases(db):
    from app.services.admin_question_service import list_admin_questions

    async with db.session_factory() as s:
        q1, _q2 = await _seed(s)
        kp = (await s.execute(select(KnowledgePoint).where(KnowledgePoint.name == "线性表"))).scalar_one()
        kp.aliases = ["顺序存储结构的实现", "SeqList"]
        await s.commit()

        # 别名英文子串命中
        questions, total = await list_admin_questions(s, page=1, page_size=20, keyword="SeqList")
        assert total == 1
        assert questions[0].id == q1
        # 别名中文子串命中（JSON 文本 contains）
        questions, total = await list_admin_questions(s, page=1, page_size=20, keyword="存储结构")
        assert total == 1
        assert questions[0].id == q1
        # 无关词不命中
        _questions, total = await list_admin_questions(s, page=1, page_size=20, keyword="完全无关")
        assert total == 0


@pytest.mark.asyncio
async def test_list_admin_questions_keyword_keeps_content_or_semantics(db):
    """keyword 仍同时匹配 answer/analysis/raw_content（OR 语义不回归）。"""
    from app.services.admin_question_service import list_admin_questions

    async with db.session_factory() as s:
        q1, _q2 = await _seed(s)
        questions, total = await list_admin_questions(s, page=1, page_size=20, keyword="A")
        assert total == 1
        assert questions[0].id == q1


@pytest.mark.asyncio
async def test_list_admin_questions_keyword_escapes_like_wildcards(db):
    """用户输入中的 %/_ 必须按字面匹配，不能当 LIKE 通配符用（转义回归）。"""
    from app.services.admin_question_service import list_admin_questions

    now = datetime(2026, 8, 1)
    async with db.session_factory() as s:
        q1 = Question(subject_id=1, question_type="single_choice",
                      content={"text": "q1"}, raw_content="含 50% 折扣", answer="A",
                      difficulty=2, created_at=now)
        q2 = Question(subject_id=1, question_type="single_choice",
                      content={"text": "q2"}, raw_content="含 50 折扣", answer="B",
                      difficulty=3, created_at=now)
        q3 = Question(subject_id=1, question_type="single_choice",
                      content={"text": "q3"}, raw_content="a_b 下划线", answer="C",
                      difficulty=2, created_at=now)
        s.add_all([q1, q2, q3])
        await s.commit()

        # "%" 不能当通配符：只命中字面含 "50%" 的题，而非所有含 "50" 的题
        _qs, total = await list_admin_questions(s, page=1, page_size=20, keyword="50%")
        assert total == 1
        assert _qs[0].id == q1.id
        # "_" 不能匹配任意单字符：只命中字面含下划线的题
        _qs, total = await list_admin_questions(s, page=1, page_size=20, keyword="_")
        assert total == 1
        assert _qs[0].id == q3.id
        # 反斜杠关键字按字面匹配（LaTeX 关键词不被损坏）
        q4 = Question(subject_id=1, question_type="single_choice",
                      content={"text": "q4"}, raw_content="\\frac{a}{b}", answer="D",
                      difficulty=2, created_at=now)
        s.add(q4)
        await s.commit()
        _qs, total = await list_admin_questions(s, page=1, page_size=20, keyword="\\frac")
        assert total == 1
        assert _qs[0].id == q4.id
