"""Behavioral contract for canonical knowledge-point resolution and mapping sync.

These cases pin the current observable behavior of ``knowledge_point_service``
before the function-budget convergence: resolution order and tombstones, alias
collapsing, create-if-missing idempotence, and the mapping sync payload plus
mapping rows for the no-op/additive/replace/no-subject branches.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.models.admin import Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.services.knowledge_point_resolution import KnowledgePointResolutionError
from app.services.knowledge_point_service import (
    get_or_create_knowledge_point,
    resolve_knowledge_point,
    resolve_knowledge_points,
    sync_question_knowledge_points,
)

ZERO_SUMMARY = {
    "changed": False,
    "created": 0,
    "updated": 0,
    "deleted": 0,
    "total": 0,
}


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'knowledge-point-contract.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _record_statements(engine) -> list[str]:
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    return statements


async def _seed_subjects(session_factory) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                Subject(id=1, code="ds", name="数据结构", path="ds"),
                Subject(id=2, code="os", name="操作系统", path="os"),
            ]
        )
        await db.commit()


async def _seed_points(session_factory, points) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                KnowledgePoint(
                    id=point_id,
                    subject_id=subject_id,
                    name=name,
                    normalized_name=name,
                    aliases=aliases,
                    is_active=is_active,
                )
                for point_id, subject_id, name, aliases, is_active in points
            ]
        )
        await db.commit()


async def _seed_question(
    session_factory, *, question_id: int | None = None, subject_id: int = 1
):
    async with session_factory() as db:
        question = Question(
            subject_id=subject_id,
            question_type="single_choice",
            content={"text": "q"},
            answer="A",
            difficulty=2,
        )
        if question_id is not None:
            question.id = question_id
        db.add(question)
        await db.commit()
        return question.id


async def _mappings(
    session_factory, question_id: int
) -> list[tuple[int, int, str, float, str]]:
    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(QuestionKnowledgePoint)
                    .where(QuestionKnowledgePoint.question_id == question_id)
                    .order_by(QuestionKnowledgePoint.position)
                )
            )
            .scalars()
            .all()
        )
        return [
            (row.knowledge_point_id, row.position, row.role, row.weight, row.source)
            for row in rows
        ]


class TestKnowledgePointResolution:
    @pytest.mark.asyncio
    async def test_empty_input_and_falsy_subject_boundaries(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            statements = _record_statements(engine)
            async with session_factory() as db:
                assert await resolve_knowledge_points(db, 1, []) == []
                assert await resolve_knowledge_points(db, 1, None) == []
                with pytest.raises(ValueError, match="subject_id"):
                    await resolve_knowledge_points(db, 0, ["线性表"])
            assert statements == []
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_exact_alias_dedup_order_and_inactive_tombstone(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory,
                [
                    (1, 1, "线性表", [], True),
                    (2, 1, "顺序表", ["顺序存储"], True),
                    (3, 1, "废弃知识点", ["废弃别名"], False),
                ],
            )
            async with session_factory() as db:
                resolved = await resolve_knowledge_points(
                    db, 1, ["线性表", "顺序存储", "线性表"]
                )
                assert [point.id for point in resolved] == [1, 2]

                assert await resolve_knowledge_points(db, 1, ["废弃别名"]) == []
                with pytest.raises(KnowledgePointResolutionError) as err:
                    await resolve_knowledge_points(
                        db, 1, ["废弃别名"], create_if_missing=True
                    )
                assert "inactive" in str(err.value)
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_ambiguous_alias_is_rejected_with_sorted_ids(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory,
                [
                    (7, 1, "知识点甲", ["共享别名"], True),
                    (3, 1, "知识点乙", ["共享别名"], True),
                ],
            )
            async with session_factory() as db:
                with pytest.raises(KnowledgePointResolutionError) as err:
                    await resolve_knowledge_points(db, 1, ["共享别名"])
            assert "[3, 7]" in str(err.value)
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_create_if_missing_is_idempotent_and_visible_afterwards(
        self, tmp_path
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            async with session_factory() as db:
                created = await resolve_knowledge_points(
                    db, 1, ["新算法", " 新算法 "], create_if_missing=True
                )
                await db.commit()
            assert len(created) == 1
            point = created[0]
            assert (point.id, point.name, point.subject_id) == (point.id, "新算法", 1)
            assert point.aliases == []
            assert point.is_active is True

            async with session_factory() as db:
                rows = (
                    (
                        await db.execute(
                            select(KnowledgePoint).where(
                                KnowledgePoint.subject_id == 1,
                                KnowledgePoint.normalized_name == "新算法",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert [row.id for row in rows] == [point.id]

                again = await resolve_knowledge_points(db, 1, ["新算法"])
            assert [item.id for item in again] == [point.id]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_single_and_get_or_create_wrappers(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory, [(1, 1, "线性表", ["list alias"], True)]
            )
            async with session_factory() as db:
                assert (await resolve_knowledge_point(db, 1, "list alias")).id == 1
                assert await resolve_knowledge_point(db, 1, "未登记知识点") is None
                created = await get_or_create_knowledge_point(db, 1, "另一个新点")
                await db.commit()
            assert created.name == "另一个新点"
            assert created.subject_id == 1
        finally:
            await engine.dispose()


class TestSyncQuestionKnowledgePoints:
    @pytest.mark.asyncio
    async def test_none_input_is_noop_before_locking_the_question(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            question_id = await _seed_question(session_factory)
            async with session_factory() as db:
                assert (
                    await sync_question_knowledge_points(
                        db, SimpleNamespace(id=question_id), None
                    )
                    == ZERO_SUMMARY
                )
                question = await db.get(Question, question_id)
            statements = _record_statements(engine)
            async with session_factory() as db:
                assert (
                    await sync_question_knowledge_points(db, question, None)
                    == ZERO_SUMMARY
                )
            assert statements == []
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_additive_creates_positions_and_stays_idempotent(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            question_id = await _seed_question(session_factory)
            await _seed_points(
                session_factory,
                [(1, 1, "线性表", [], True), (2, 1, "顺序表", [], True)],
            )
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                first = await sync_question_knowledge_points(
                    db, question, ["线性表", "顺序表"], source="contract"
                )
                await db.commit()
            assert first == {
                "changed": True,
                "created": 2,
                "updated": 0,
                "deleted": 0,
                "total": 2,
            }
            assert await _mappings(session_factory, question_id) == [
                (1, 0, "main", 1.0, "contract"),
                (2, 1, "main", 1.0, "contract"),
            ]
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                second = await sync_question_knowledge_points(
                    db, question, ["线性表", "顺序表"], source="contract"
                )
                await db.commit()
            assert second == {
                "changed": False,
                "created": 0,
                "updated": 0,
                "deleted": 0,
                "total": 2,
            }
            assert len(await _mappings(session_factory, question_id)) == 2
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_additive_appends_after_existing_positions(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            question_id = await _seed_question(session_factory)
            await _seed_points(
                session_factory,
                [(1, 1, "线性表", [], True), (2, 1, "顺序表", [], True)],
            )
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                await sync_question_knowledge_points(db, question, ["线性表"])
                result = await sync_question_knowledge_points(db, question, ["顺序表"])
                await db.commit()
            assert result["created"] == 1
            assert result["total"] == 1
            assert await _mappings(session_factory, question_id) == [
                (1, 0, "main", 1.0, "imported"),
                (2, 1, "main", 1.0, "imported"),
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_replace_with_empty_list_clears_every_mapping(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            question_id = await _seed_question(session_factory)
            await _seed_points(
                session_factory,
                [(1, 1, "线性表", [], True), (2, 1, "顺序表", [], True)],
            )
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                await sync_question_knowledge_points(db, question, ["线性表", "顺序表"])
                cleared = await sync_question_knowledge_points(
                    db, question, [], replace=True
                )
                await db.commit()
            assert cleared == {
                "changed": True,
                "created": 0,
                "updated": 0,
                "deleted": 2,
                "total": 0,
            }
            assert await _mappings(session_factory, question_id) == []
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_replace_reorders_deletes_and_reports_revision_counts(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            question_id = await _seed_question(session_factory)
            await _seed_points(
                session_factory,
                [
                    (1, 1, "知识点一", [], True),
                    (2, 1, "知识点二", [], True),
                    (3, 1, "知识点三", [], True),
                ],
            )
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                await sync_question_knowledge_points(
                    db, question, ["知识点一", "知识点二", "知识点三"]
                )
                replaced = await sync_question_knowledge_points(
                    db, question, ["知识点三", "知识点一"], replace=True
                )
                await db.commit()
            assert replaced == {
                "changed": True,
                "created": 0,
                "updated": 2,
                "deleted": 1,
                "total": 2,
            }
            assert await _mappings(session_factory, question_id) == [
                (3, 0, "main", 1.0, "imported"),
                (1, 1, "main", 1.0, "imported"),
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_replace_swap_survives_unique_position_constraint(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            question_id = await _seed_question(session_factory)
            await _seed_points(
                session_factory,
                [(1, 1, "知识点一", [], True), (2, 1, "知识点二", [], True)],
            )
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                await sync_question_knowledge_points(
                    db, question, ["知识点一", "知识点二"]
                )
                swapped = await sync_question_knowledge_points(
                    db, question, ["知识点二", "知识点一"], replace=True
                )
                await db.commit()
            assert swapped == {
                "changed": True,
                "created": 0,
                "updated": 2,
                "deleted": 0,
                "total": 2,
            }
            assert await _mappings(session_factory, question_id) == [
                (2, 0, "main", 1.0, "imported"),
                (1, 1, "main", 1.0, "imported"),
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_alias_spellings_collapse_into_one_mapping_but_count_as_entries(
        self, tmp_path
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            question_id = await _seed_question(session_factory)
            await _seed_points(
                session_factory, [(9, 1, "卡特兰数", ["Catalan数"], True)]
            )
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                result = await sync_question_knowledge_points(
                    db, question, ["Catalan数", "卡特兰数"], replace=True
                )
                await db.commit()
            assert result == {
                "changed": True,
                "created": 1,
                "updated": 0,
                "deleted": 0,
                "total": 2,
            }
            assert await _mappings(session_factory, question_id) == [
                (9, 0, "main", 1.0, "imported")
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_new_points_inherit_question_subject_and_source(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            question_id = await _seed_question(session_factory, subject_id=2)
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                result = await sync_question_knowledge_points(
                    db, question, ["操作系统新点"], source="admin_import"
                )
                await db.commit()
                created = (
                    await db.execute(
                        select(KnowledgePoint).where(
                            KnowledgePoint.normalized_name == "操作系统新点"
                        )
                    )
                ).scalar_one()
            assert result["created"] == 1
            assert (created.subject_id, created.name, created.aliases) == (
                2,
                "操作系统新点",
                [],
            )
            assert await _mappings(session_factory, question_id) == [
                (created.id, 0, "main", 1.0, "admin_import")
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_locked_question_without_subject_clears_or_warns(
        self, tmp_path, monkeypatch, caplog
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            question_id = await _seed_question(session_factory)
            await _seed_points(session_factory, [(1, 1, "线性表", [], True)])
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                await sync_question_knowledge_points(db, question, ["线性表"])
                await db.commit()

            async def fake_lock(_db, locked_id):
                return SimpleNamespace(id=locked_id, subject_id=None)

            monkeypatch.setattr(
                "app.services.question_revision_service.lock_question_for_revision",
                fake_lock,
            )
            async with session_factory() as db:
                question = await db.get(Question, question_id)
                cleared = await sync_question_knowledge_points(
                    db, question, [], replace=True
                )
                await db.commit()
            assert cleared == {
                "changed": True,
                "created": 0,
                "updated": 0,
                "deleted": 1,
                "total": 0,
            }
            assert await _mappings(session_factory, question_id) == []

            with caplog.at_level(
                logging.WARNING, logger="app.services.knowledge_point_service"
            ):
                async with session_factory() as db:
                    question = await db.get(Question, question_id)
                    skipped = await sync_question_knowledge_points(
                        db, question, ["线性表"]
                    )
            assert skipped == ZERO_SUMMARY
            assert "has no subject, skip" in caplog.text
            assert await _mappings(session_factory, question_id) == []
        finally:
            await engine.dispose()
