"""Real SQLite compatibility baseline for the 408 knowledge map."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all relationships before create_all
from app.core.database import Base
from app.core.subject_scope import EXAM408_CORE_CODES
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint, SyllabusVersion
from app.models.user import User
from app.models.user_knowledge_state import UserKnowledgeState
from app.services import knowledge_map_service


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'knowledge-map.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory) -> dict[str, int]:
    async with session_factory() as db:
        root = Subject(
            id=1,
            code="exam408",
            name="408",
            path="exam408",
            sort_order=0,
            is_active=True,
        )
        core_ids = {code: 10 + index for index, code in enumerate(EXAM408_CORE_CODES)}
        db.add_all(
            [
                root,
                *(
                    Subject(
                        id=subject_id,
                        parent_id=1,
                        code=code,
                        name=code,
                        path=f"exam408/{code}",
                        sort_order=10 + index,
                        is_active=True,
                    )
                    for index, (code, subject_id) in enumerate(core_ids.items())
                ),
            ]
        )
        await db.flush()

        version = SyllabusVersion(
            code="active-2026",
            name="2026 408",
            root_subject_id=1,
            effective_year=2026,
            status="active",
            activated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        db.add(version)
        await db.flush()

        ds_id = core_ids["data_structure"]
        kp_root = KnowledgePoint(
            id=1,
            subject_id=ds_id,
            name="线性表",
            normalized_name="线性表",
            aliases=[],
            is_active=True,
        )
        kp_child = KnowledgePoint(
            id=2,
            subject_id=ds_id,
            name="链表",
            normalized_name="链表",
            aliases=[],
            is_active=True,
        )
        kp_outside = KnowledgePoint(
            id=3,
            subject_id=core_ids["operating_system"],
            name="进程",
            normalized_name="进程",
            aliases=[],
            is_active=True,
        )
        db.add_all([kp_root, kp_child, kp_outside])
        await db.flush()

        db.add_all(
            [
                SyllabusKnowledgePoint(
                    syllabus_version_id=version.id,
                    knowledge_point_id=1,
                    subject_id=ds_id,
                    name_snapshot="线性表",
                    normalized_name_snapshot="线性表",
                    sort_order=10,
                ),
                SyllabusKnowledgePoint(
                    syllabus_version_id=version.id,
                    knowledge_point_id=2,
                    subject_id=ds_id,
                    name_snapshot="链表",
                    normalized_name_snapshot="链表",
                    sort_order=20,
                ),
                SyllabusKnowledgePoint(
                    syllabus_version_id=version.id,
                    knowledge_point_id=3,
                    subject_id=core_ids["operating_system"],
                    name_snapshot="进程",
                    normalized_name_snapshot="进程",
                    sort_order=10,
                ),
            ]
        )
        await db.flush()

        question = Question(
            subject_id=ds_id,
            question_type="single_choice",
            content={"text": "链表题"},
            options={"A": "A", "B": "B"},
            answer="A",
            difficulty=3,
            review_status="approved",
            is_active=True,
        )
        db.add(question)
        await db.flush()
        version_row = QuestionVersion(
            question_id=question.id,
            version=1,
            subject_id=ds_id,
            question_type="single_choice",
            content={"text": "链表题"},
            options={"A": "A", "B": "B"},
            answer="A",
            difficulty=3,
            is_active=True,
        )
        db.add(version_row)
        await db.flush()
        question.current_version_id = version_row.id
        db.add(
            QuestionKnowledgePoint(
                question_id=question.id,
                knowledge_point_id=2,
                position=0,
            )
        )
        db.add(
            QuestionVersionKnowledgePoint(
                question_version_id=version_row.id,
                knowledge_point_id=2,
                position=0,
            )
        )
        db.add(
            KnowledgeEdge(
                subject_id=ds_id,
                source_knowledge_point_id=1,
                target_knowledge_point_id=2,
                relation_type="parent",
                weight=0.8,
                confidence=0.7,
                source="manual",
                is_active=True,
            )
        )
        db.add(User(id=9, openid="knowledge-map-user"))
        await db.commit()
        return {
            "version": version.id,
            "ds": ds_id,
            "os": core_ids["operating_system"],
            "question": question.id,
            "question_version": version_row.id,
        }


@pytest.mark.asyncio
async def test_overview_is_fail_closed_without_active_syllabus(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        async with session_factory() as db:
            result = await knowledge_map_service.get_overview(db, 9)
        assert result == {
            "scope": "exam408",
            "syllabus_version": None,
            "scope_ready": False,
            "subjects": [],
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_overview_only_uses_active_canonical_408_scope(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        ids = await _seed(session_factory)
        async with session_factory() as db:
            result = await knowledge_map_service.get_overview(db, 9)

        assert result["scope_ready"] is True
        assert result["syllabus_version"]["code"] == "active-2026"
        assert [subject["subject_code"] for subject in result["subjects"]] == list(
            EXAM408_CORE_CODES
        )
        ds_summary = result["subjects"][0]
        assert ds_summary["subject_id"] == ids["ds"]
        assert ds_summary["total_knowledge_points"] == 2
        assert ds_summary["trainable_knowledge_points"] == 1
        assert ds_summary["status"] == "no_data"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_subject_map_builds_parented_tree_and_keeps_state_semantics(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        ids = await _seed(session_factory)
        async with session_factory() as db:
            db.add(
                UserKnowledgeState(
                    user_id=9,
                    subject_id=ids["ds"],
                    knowledge_point_id=2,
                    attempt_count=4,
                    correct_count=1,
                    wrong_count=3,
                    accuracy=0.25,
                    mastery_score=30.0,
                    weakness_level="weak",
                    confidence=0.8,
                    recent_answer_count=4,
                    recent_correct_count=1,
                    recent_wrong_count=3,
                )
            )
            await db.commit()

        async with session_factory() as db:
            result = await knowledge_map_service.get_subject_map(db, 9, ids["ds"])
        assert result is not None
        assert result["subject"]["status"] == "weak"
        assert result["root_count"] == 1
        assert result["parented_knowledge_points"] == 1
        nodes = {node["knowledge_point_id"]: node for node in result["nodes"]}
        assert nodes[1]["depth"] == 0
        assert nodes[2]["parent_id"] == 1
        assert nodes[2]["depth"] == 1
        assert nodes[2]["status"] == "weak"
        assert nodes[2]["trainable_question_count"] == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_point_detail_uses_recent_answers_and_syllabus_relations(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        ids = await _seed(session_factory)
        async with session_factory() as db:
            db.add(
                PracticeRecord(
                    user_id=9,
                    question_id=ids["question"],
                    question_version_id=ids["question_version"],
                    subject_id=ids["ds"],
                    question_type="single_choice",
                    user_answer="A",
                    is_correct=True,
                    used_time=12,
                    projection_state="completed",
                )
            )
            await db.commit()

        async with session_factory() as db:
            result = await knowledge_map_service.get_point_detail(db, 9, 2)
        assert result is not None
        assert result["knowledge_point_id"] == 2
        assert result["parent_id"] == 1
        assert result["ancestors"] == [
            {"knowledge_point_id": 1, "name": "线性表", "depth": 0}
        ]
        assert result["recent_answers"][0]["is_correct"] is True
        assert result["practice_route_params"] == {
            "subject_id": ids["ds"],
            "mode": "random",
            "count": 1,
            "knowledge_point": "链表",
            "knowledge_point_id": 2,
            "include_descendants": 0,
            "allow_repeat": 1,
            "autostart": 1,
            "source": "knowledge_map",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_point_detail_rejects_points_outside_active_408_scope(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    try:
        ids = await _seed(session_factory)
        async with session_factory() as db:
            point = (
                await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == 3))
            ).scalar_one()
            await db.delete(point)
            await db.commit()

        async with session_factory() as db:
            detail = await knowledge_map_service.get_point_detail(db, 9, 3)
            os_map = await knowledge_map_service.get_subject_map(db, 9, ids["os"])
        assert detail is None
        assert os_map is not None
    finally:
        await engine.dispose()
