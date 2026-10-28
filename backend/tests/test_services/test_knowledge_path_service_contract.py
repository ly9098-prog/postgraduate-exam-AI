"""Behavioral contract for the knowledge-path recommendation service.

Real SQLite rows back the knowledge-point/mastery/subject queries; the graph and
vector ports stay stubbed.  These cases pin start-point resolution, neighbor
collection and roles, priority math, per-node question attachment, and the
endpoint payload (including the practice-entry ``write_logs=False`` contract).
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
import app.services
from app.core.database import Base
from app.models.admin import Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user import User
from app.models.user_knowledge_state import UserKnowledgeState
from app.services.knowledge_path_service import (
    _compute_priorities,
    attach_recommended_questions_to_path,
    build_user_knowledge_path,
    get_user_path_recommendations,
)


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'knowledge-path-contract.db'}",
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
                User(id=1, openid="knowledge-path-user"),
                Subject(id=5, code="exam408-ds", name="数据结构", path="ds"),
                Subject(id=6, code="exam408-os", name="操作系统", path="os"),
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
                    aliases=[],
                    is_active=is_active,
                )
                for point_id, subject_id, name, is_active in points
            ]
        )
        await db.commit()


async def _seed_mastery(session_factory, states) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                UserKnowledgeState(
                    user_id=1,
                    subject_id=5,
                    knowledge_point_id=kp_id,
                    attempt_count=attempt_count,
                    correct_count=0,
                    wrong_count=attempt_count,
                    accuracy=0.0,
                    mastery_score=mastery,
                    weakness_level=weakness_level,
                    confidence=0.5,
                    recent_answer_count=attempt_count,
                    recent_correct_count=0,
                    recent_wrong_count=attempt_count,
                )
                for kp_id, mastery, weakness_level, attempt_count in states
            ]
        )
        await db.commit()


def _graph_stub(*, prerequisites=None, nexts=None, relateds=None, errors=()):
    def _maybe(direction, value):
        if direction in errors:
            raise RuntimeError(f"{direction} failed")
        return value or []

    return SimpleNamespace(
        get_prerequisites=AsyncMock(
            side_effect=lambda *args, **kwargs: _maybe("prerequisites", prerequisites)
        ),
        get_next_nodes=AsyncMock(
            side_effect=lambda *args, **kwargs: _maybe("next", nexts)
        ),
        get_related_nodes=AsyncMock(
            side_effect=lambda *args, **kwargs: _maybe("related", relateds)
        ),
    )


def _neighbor(
    kp_id, *, name, relation_type="next", weight=0.6, confidence=0.9, depth=1
):
    return {
        "knowledge_point_id": kp_id,
        "name": name,
        "subject_id": 5,
        "relation_type": relation_type,
        "weight": weight,
        "confidence": confidence,
        "depth": depth,
        "edge_id": kp_id * 10,
    }


class TestBuildUserKnowledgePath:
    @pytest.mark.asyncio
    async def test_explicit_active_start_point_wins_over_mastery_path(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory,
                [
                    (10, 5, "指针基础", True),
                    (20, 5, "链表", True),
                    (30, 5, "栈", False),
                ],
            )
            await _seed_mastery(session_factory, [(20, 30.0, "weak", 5)])
            graph = _graph_stub(
                prerequisites=[
                    _neighbor(10, name="指针基础", relation_type="prerequisite")
                ],
                nexts=[_neighbor(30, name="栈", relation_type="next")],
                relateds=[_neighbor(40, name="队列", relation_type="related")],
            )
            monkeypatch.setattr(
                app.services, "knowledge_graph_service", graph, raising=False
            )
            monkeypatch.setattr(random, "shuffle", lambda items: None)

            async with session_factory() as db:
                result = await build_user_knowledge_path(
                    db, user_id=1, subject_id=5, start_knowledge_point_id=10, limit=8
                )

            assert result["strategy"] == "knowledge_path"
            assert result["start_kp"]["knowledge_point_id"] == 10
            assert result["start_kp"]["name"] == "指针基础"
            roles = {node["path_role"] for node in result["nodes"]}
            assert "current" in roles
            # 40 is not a stored KnowledgePoint row, so mastery/subject lookups skip it.
            ids = [node["knowledge_point_id"] for node in result["nodes"]]
            assert ids[0] == 10
            assert set(ids) <= {10, 20, 30, 40}
            current = next(
                node for node in result["nodes"] if node["path_role"] == "current"
            )
            assert (current["subject_code"], current["subject_name"]) == (
                "exam408-ds",
                "数据结构",
            )
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_inactive_or_unknown_start_falls_back_to_weakest_point(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory,
                [
                    (10, 5, "指针基础", True),
                    (20, 5, "链表", True),
                    (30, 5, "栈", False),
                ],
            )
            await _seed_mastery(
                session_factory,
                [(10, 65.0, "normal", 3), (20, 25.0, "weak", 5)],
            )
            graph = _graph_stub()
            monkeypatch.setattr(
                app.services, "knowledge_graph_service", graph, raising=False
            )

            async with session_factory() as db:
                inactive = await build_user_knowledge_path(
                    db, user_id=1, subject_id=5, start_knowledge_point_id=30
                )
                unknown = await build_user_knowledge_path(
                    db, user_id=1, subject_id=5, start_knowledge_point_id=999
                )

            assert inactive["start_kp"]["knowledge_point_id"] == 20
            assert unknown["start_kp"]["knowledge_point_id"] == 20
            assert inactive["start_kp"]["mastery_score"] == 25.0
            assert inactive["start_kp"]["weakness_level"] == "weak"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_random_start_is_used_when_no_mastery_evidence_exists(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory,
                [(10, 5, "指针基础", True), (20, 5, "链表", True), (30, 5, "栈", True)],
            )
            monkeypatch.setattr(
                app.services, "knowledge_graph_service", _graph_stub(), raising=False
            )
            monkeypatch.setattr(random, "randint", lambda low, high: 1)
            statements = _record_statements(engine)

            async with session_factory() as db:
                result = await build_user_knowledge_path(db, user_id=1, subject_id=5)

            assert result["start_kp"]["knowledge_point_id"] == 20
            assert result["start_kp"]["mastery_score"] is None
            assert result["start_kp"]["weakness_level"] == "unknown"
            assert any("practice_records" in statement for statement in statements)
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_empty_catalogue_returns_empty_strategy(self, tmp_path, monkeypatch):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            monkeypatch.setattr(
                app.services, "knowledge_graph_service", _graph_stub(), raising=False
            )

            async with session_factory() as db:
                result = await build_user_knowledge_path(db, user_id=1, subject_id=6)

            assert result == {"start_kp": None, "nodes": [], "strategy": "empty"}
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_direction_roles_and_failures_keep_the_other_directions(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory,
                [
                    (10, 5, "指针基础", True),
                    (20, 5, "链表", True),
                    (40, 5, "队列", True),
                    (50, 5, "树", True),
                ],
            )
            await _seed_mastery(session_factory, [(20, 40.0, "weak", 4)])
            graph = _graph_stub(
                # get_next_nodes may fall back to related when no explicit next edge
                # exists; the role must follow relation_type, not the port name.
                nexts=[_neighbor(40, name="队列", relation_type="related")],
                relateds=[_neighbor(50, name="树", relation_type="related")],
                errors=("prerequisites",),
            )
            monkeypatch.setattr(
                app.services, "knowledge_graph_service", graph, raising=False
            )

            async with session_factory() as db:
                result = await build_user_knowledge_path(db, user_id=1, subject_id=5)

            roles = {
                node["knowledge_point_id"]: node["path_role"]
                for node in result["nodes"]
            }
            assert roles[20] == "current"
            assert roles[40] == "related"
            assert roles[50] == "related"
            assert 10 not in roles
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_priority_order_dedupes_and_applies_limit(
        self, tmp_path, monkeypatch, caplog
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory,
                [
                    (10, 5, "指针基础", True),
                    (20, 5, "链表", True),
                    (40, 5, "队列", True),
                    (50, 5, "树", True),
                ],
            )
            await _seed_mastery(session_factory, [(20, 40.0, "weak", 4)])
            graph = _graph_stub(
                prerequisites=[
                    _neighbor(10, name="指针基础", relation_type="prerequisite")
                ],
                nexts=[_neighbor(20, name="链表", relation_type="next")],
                relateds=[
                    _neighbor(40, name="队列", relation_type="related"),
                    _neighbor(10, name="指针基础", relation_type="related"),
                ],
            )
            monkeypatch.setattr(
                app.services, "knowledge_graph_service", graph, raising=False
            )

            with caplog.at_level(
                logging.WARNING, logger="app.services.knowledge_path_service"
            ):
                async with session_factory() as db:
                    limited = await build_user_knowledge_path(
                        db, user_id=1, subject_id=5, limit=2
                    )
                    full = await build_user_knowledge_path(
                        db, user_id=1, subject_id=5, limit=8
                    )

            assert len(limited["nodes"]) == 2
            priorities = [node["priority"] for node in full["nodes"]]
            assert priorities == sorted(priorities, reverse=True)
            ids = [node["knowledge_point_id"] for node in full["nodes"]]
            assert len(ids) == len(set(ids))
            # 10 arrives as both prerequisite and related; the higher priority wins.
            node10 = next(
                node for node in full["nodes"] if node["knowledge_point_id"] == 10
            )
            assert node10["path_role"] == "prerequisite"
        finally:
            await engine.dispose()


class TestComputePriorities:
    def test_exact_priority_math_and_reasons(self):
        nodes = [
            {
                "knowledge_point_id": 20,
                "name": "链表",
                "mastery_score": 30,
                "weakness_level": "weak",
                "path_role": "current",
                "priority": 0.0,
                "reason": "",
            },
            {
                "knowledge_point_id": 10,
                "name": "指针基础",
                "mastery_score": 30,
                "weakness_level": "weak",
                "path_role": "prerequisite",
                "edge_weight": 0.6,
                "edge_confidence": 0.9,
                "priority": 0.0,
                "reason": "",
            },
            {
                "knowledge_point_id": 40,
                "name": "队列",
                "mastery_score": 70,
                "weakness_level": "unknown",
                "path_role": "next",
                "edge_weight": 1.5,
                "priority": 0.0,
                "reason": "",
            },
            {
                "knowledge_point_id": 50,
                "name": "树",
                "mastery_score": 80,
                "weakness_level": "unknown",
                "path_role": "related",
                "priority": 0.0,
                "reason": "",
            },
        ]
        _compute_priorities(nodes, start_kp={"knowledge_point_id": 20, "name": "链表"})
        by_id = {node["knowledge_point_id"]: node for node in nodes}

        assert by_id[10]["priority"] == 0.854
        assert by_id[40]["priority"] == 0.147
        assert by_id[50]["priority"] == 0.11
        # A weak prerequisite demotes the current node: 0.545 * 1.1 * 0.85.
        assert by_id[20]["priority"] == 0.5096
        assert by_id[20]["reason"] == "知识路径推荐：你在『链表』上较薄弱，建议重点练习"
        assert by_id[10]["reason"] == "前置知识：掌握『指针基础』有助于理解当前知识点"
        assert by_id[40]["reason"] == "下一步：掌握『队列』是当前的进阶方向"
        assert by_id[50]["reason"] == "相关知识：『树』与当前知识点相关"

    def test_missing_edge_signals_use_defaults_and_unknown_role_reason(self):
        nodes = [
            {
                "knowledge_point_id": 60,
                "name": "图",
                "mastery_score": None,
                "weakness_level": "unknown",
                "path_role": "current",
                "priority": 0.0,
                "reason": "",
            }
        ]
        _compute_priorities(nodes, start_kp={"knowledge_point_id": 60, "name": "图"})
        # mastery None -> 50 (0.5); edge defaults 0.5 weight, confidence 1.0
        assert nodes[0]["priority"] == round(
            (0.8 * 0.4 + 0.0 * 0.25 + 0.5 * 0.25 + 0.5 * 0.10) * 1.1, 4
        )
        assert nodes[0]["reason"] == "知识路径推荐：你在『图』上较薄弱，建议重点练习"


class TestAttachRecommendedQuestions:
    @pytest.mark.asyncio
    async def test_prefetched_candidates_are_sorted_by_difficulty_distance(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory,
                [(20, 5, "链表", True), (21, 5, "栈", True)],
            )
            async with session_factory() as db:
                db.add_all(
                    [
                        Question(
                            id=100,
                            subject_id=5,
                            question_type="single_choice",
                            content={},
                            answer="A",
                            difficulty=3,
                            is_active=True,
                        ),
                        Question(
                            id=101,
                            subject_id=5,
                            question_type="single_choice",
                            content={},
                            answer="A",
                            difficulty=1,
                            is_active=True,
                        ),
                        Question(
                            id=102,
                            subject_id=5,
                            question_type="single_choice",
                            content={},
                            answer="A",
                            difficulty=5,
                            is_active=True,
                        ),
                        Question(
                            id=103,
                            subject_id=5,
                            question_type="single_choice",
                            content={},
                            answer="A",
                            difficulty=2,
                            is_active=False,
                        ),
                        QuestionKnowledgePoint(
                            question_id=100, knowledge_point_id=20, position=0
                        ),
                        QuestionKnowledgePoint(
                            question_id=101, knowledge_point_id=20, position=1
                        ),
                        QuestionKnowledgePoint(
                            question_id=102, knowledge_point_id=20, position=2
                        ),
                        QuestionKnowledgePoint(
                            question_id=103, knowledge_point_id=20, position=3
                        ),
                        QuestionKnowledgePoint(
                            question_id=101, knowledge_point_id=21, position=0
                        ),
                    ]
                )
                await db.commit()
            monkeypatch.setattr(random, "shuffle", lambda items: None)
            vector = SimpleNamespace(vector_recall_by_text=AsyncMock(return_value=[]))
            monkeypatch.setattr(
                app.services, "vector_retrieval_service", vector, raising=False
            )

            nodes = [
                {
                    "knowledge_point_id": 20,
                    "name": "链表",
                    "mastery_score": 50.0,
                    "recommended_question_ids": [],
                },
                {
                    "knowledge_point_id": 21,
                    "name": "栈",
                    "mastery_score": 50.0,
                    "recommended_question_ids": [],
                },
            ]
            async with session_factory() as db:
                result = await attach_recommended_questions_to_path(
                    db,
                    user_id=1,
                    subject_code="exam408-ds",
                    nodes=nodes,
                    questions_per_node=2,
                )

            # target difficulty = 1 + 4 * 0.5 = 3 -> |3-3|=0, |1-3|=2, |5-3|=2 and the
            # inactive question 103 never enters the候选池.
            assert result[0]["recommended_question_ids"] == [100, 101]
            # 101 is already taken globally, so node 21 falls back to the vector port.
            assert result[1]["recommended_question_ids"] == []
            vector.vector_recall_by_text.assert_awaited()
            assert vector.vector_recall_by_text.await_args.kwargs["count"] == 2
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_excluded_answered_questions_and_vector_fallback(
        self, tmp_path, monkeypatch, caplog
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(session_factory, [(20, 5, "链表", True)])
            async with session_factory() as db:
                db.add_all(
                    [
                        Question(
                            id=100,
                            subject_id=5,
                            question_type="single_choice",
                            content={},
                            answer="A",
                            difficulty=3,
                            is_active=True,
                        ),
                        Question(
                            id=101,
                            subject_id=5,
                            question_type="single_choice",
                            content={},
                            answer="A",
                            difficulty=3,
                            is_active=True,
                        ),
                        QuestionKnowledgePoint(
                            question_id=100, knowledge_point_id=20, position=0
                        ),
                        QuestionKnowledgePoint(
                            question_id=101, knowledge_point_id=20, position=1
                        ),
                        PracticeRecord(
                            user_id=1,
                            question_id=100,
                            question_version_id=1,
                            subject_id=5,
                            question_type="single_choice",
                            user_answer="A",
                            is_correct=False,
                            answered_at=datetime(2026, 8, 1),
                            projection_state="completed",
                        ),
                    ]
                )
                await db.commit()
            monkeypatch.setattr(random, "shuffle", lambda items: None)
            vector = SimpleNamespace(
                vector_recall_by_text=AsyncMock(side_effect=RuntimeError("vector down"))
            )
            monkeypatch.setattr(
                app.services, "vector_retrieval_service", vector, raising=False
            )
            nodes = [
                {
                    "knowledge_point_id": 20,
                    "name": "链表",
                    "mastery_score": 50.0,
                    "recommended_question_ids": [],
                }
            ]
            with caplog.at_level(
                logging.WARNING, logger="app.services.knowledge_path_service"
            ):
                async with session_factory() as db:
                    result = await attach_recommended_questions_to_path(
                        db,
                        user_id=1,
                        subject_code="exam408-ds",
                        nodes=nodes,
                        questions_per_node=2,
                        exclude_answered=True,
                    )
            assert result[0]["recommended_question_ids"] == [101]
            assert "vector_recall_by_text 补齐失败" in caplog.text
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_nodes_without_knowledge_point_ids_return_untouched(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            statements = _record_statements(engine)
            async with session_factory() as db:
                result = await attach_recommended_questions_to_path(
                    db, user_id=1, subject_code="exam408-ds", nodes=[{"name": "无 KP"}]
                )
            assert result == [{"name": "无 KP"}]
            assert statements == []
        finally:
            await engine.dispose()


class TestGetUserPathRecommendations:
    @pytest.mark.asyncio
    async def test_payload_deduplicates_ids_and_writes_endpoint_logs(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_points(
                session_factory, [(20, 5, "链表", True), (21, 5, "栈", True)]
            )

            async def fake_build(_db, _user_id, _subject_id, **_kwargs):
                return {
                    "start_kp": {"knowledge_point_id": 20, "name": "链表"},
                    "strategy": "knowledge_path",
                    "nodes": [
                        {
                            "knowledge_point_id": 20,
                            "name": "链表",
                            "priority": 0.8,
                            "reason": "reason-20",
                            "recommended_question_ids": [100, 101],
                        },
                        {
                            "knowledge_point_id": 21,
                            "name": "栈",
                            "priority": 0.5,
                            "reason": "reason-21",
                            "recommended_question_ids": [101, 102],
                        },
                    ],
                }

            monkeypatch.setattr(
                "app.services.knowledge_path_service.build_user_knowledge_path",
                fake_build,
            )
            monkeypatch.setattr(
                "app.services.knowledge_path_service.attach_recommended_questions_to_path",
                AsyncMock(side_effect=lambda _db, _uid, _code, nodes, **_kw: nodes),
            )
            logs = AsyncMock(return_value=[1, 2, 3])
            monkeypatch.setattr(
                "app.services.recommendation_log_service.create_recommendation_logs",
                logs,
                raising=False,
            )

            async with session_factory() as db:
                result = await get_user_path_recommendations(db, user_id=1, subject=5)

            assert result["subject_code"] == "exam408-ds"
            assert result["subject_name"] == "数据结构"
            assert result["start_knowledge_point_id"] == 20
            assert result["fallback_used"] is False
            assert result["recommended_question_ids"] == [100, 101, 102]
            logs.assert_awaited_once()
            kwargs = logs.await_args.kwargs
            assert kwargs["scene"] == "knowledge_path"
            assert kwargs["strategy"] == "knowledge_path"
            assert [rec["question_id"] for rec in kwargs["recommendations"]] == [
                100,
                101,
                101,
                102,
            ]
            assert kwargs["recommendations"][0]["recommend_score"] == 0.8
            assert kwargs["recommendations"][0]["reason"] == "reason-20"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_empty_path_returns_early_without_attaching_or_logging(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            monkeypatch.setattr(
                "app.services.knowledge_path_service.build_user_knowledge_path",
                AsyncMock(
                    return_value={"start_kp": None, "nodes": [], "strategy": "empty"}
                ),
            )
            attach = AsyncMock()
            monkeypatch.setattr(
                "app.services.knowledge_path_service.attach_recommended_questions_to_path",
                attach,
            )
            logs = AsyncMock()
            monkeypatch.setattr(
                "app.services.recommendation_log_service.create_recommendation_logs",
                logs,
                raising=False,
            )

            async with session_factory() as db:
                result = await get_user_path_recommendations(db, user_id=1, subject=5)

            assert result == {
                "subject_id": 5,
                "subject_code": "exam408-ds",
                "subject_name": "数据结构",
                "user_id": 1,
                "start_knowledge_point_id": None,
                "strategy": "empty",
                "nodes": [],
                "recommended_question_ids": [],
                "fallback_used": True,
            }
            attach.assert_not_awaited()
            logs.assert_not_awaited()
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_write_logs_false_skips_logs_and_log_failures_are_swallowed(
        self, tmp_path, monkeypatch, caplog
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            node = {
                "knowledge_point_id": 20,
                "name": "链表",
                "priority": 0.8,
                "reason": "reason-20",
                "recommended_question_ids": [100],
            }
            monkeypatch.setattr(
                "app.services.knowledge_path_service.build_user_knowledge_path",
                AsyncMock(
                    return_value={
                        "start_kp": node,
                        "strategy": "knowledge_path",
                        "nodes": [node],
                    }
                ),
            )
            monkeypatch.setattr(
                "app.services.knowledge_path_service.attach_recommended_questions_to_path",
                AsyncMock(side_effect=lambda _db, _uid, _code, nodes, **_kw: nodes),
            )
            logs = AsyncMock(return_value=[])
            monkeypatch.setattr(
                "app.services.recommendation_log_service.create_recommendation_logs",
                logs,
                raising=False,
            )

            async with session_factory() as db:
                silent = await get_user_path_recommendations(
                    db, user_id=1, subject=5, write_logs=False
                )
            logs.assert_not_awaited()
            assert silent["recommended_question_ids"] == [100]

            logs.side_effect = RuntimeError("log down")
            with caplog.at_level(
                logging.WARNING, logger="app.services.knowledge_path_service"
            ):
                async with session_factory() as db:
                    failed = await get_user_path_recommendations(
                        db, user_id=1, subject=5
                    )
            assert failed["recommended_question_ids"] == [100]
            assert "推荐日志写入失败" in caplog.text
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_unknown_subject_uses_empty_labels_and_empty_strategy(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            monkeypatch.setattr(
                "app.services.knowledge_path_service.build_user_knowledge_path",
                AsyncMock(
                    return_value={"start_kp": None, "nodes": [], "strategy": "empty"}
                ),
            )
            async with session_factory() as db:
                result = await get_user_path_recommendations(
                    db, user_id=1, subject="missing-code"
                )
            assert result["subject_id"] is None
            assert result["subject_code"] == ""
            assert result["subject_name"] == ""
            assert result["fallback_used"] is True
        finally:
            await engine.dispose()
