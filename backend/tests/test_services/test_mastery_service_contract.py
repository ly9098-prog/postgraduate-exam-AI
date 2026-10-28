"""Behavioral contract for the mastery-service answer update and projections.

These cases pin the current observable behavior of ``mastery_service`` before
the function-budget convergence: query coverage, integrity-claim semantics,
per-knowledge-point statistics, four-decimal averages and the weak-point
projections backed by real SQLite rows (no service-internal mocks).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every relationship before create_all
from app.core.database import Base
from app.core.time_utils import serialize_utc_datetime, utcnow
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.syllabus import SyllabusKnowledgePoint
from app.models.user import User
from app.models.user_knowledge_state import UserKnowledgeState
from app.services.mastery_service import (
    get_user_knowledge_states,
    get_user_weak_knowledge_points,
    update_user_knowledge_state_after_answer,
)


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'mastery-contract.db'}",
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
                User(id=1, openid="mastery-contract-user"),
                Subject(id=1, code="mastery", name="掌握度科目", path="mastery"),
                Subject(id=2, code="other", name="其他科目", path="other"),
            ]
        )
        await db.commit()


async def _seed_knowledge_points(session_factory, count: int, *, subject_id: int = 1):
    async with session_factory() as db:
        db.add_all(
            [
                KnowledgePoint(
                    id=index,
                    subject_id=subject_id,
                    name=f"知识点{index}",
                    normalized_name=f"知识点{index}",
                    aliases=[],
                    is_active=True,
                )
                for index in range(1, count + 1)
            ]
        )
        await db.commit()


async def _seed_version(
    session_factory, *, version_id: int = 1, difficulty: int | None = 3
):
    async with session_factory() as db:
        db.add(
            QuestionVersion(
                id=version_id,
                question_id=1,
                version=version_id,
                subject_id=1,
                question_type="single_choice",
                content={"text": "1"},
                options={"A": "A"},
                answer="A",
                difficulty=difficulty,
                is_active=True,
            )
        )
        await db.commit()


async def _seed_version_mappings(
    session_factory,
    knowledge_point_ids,
    *,
    version_id: int = 1,
    syllabus_by_kp: dict[int, int] | None = None,
):
    syllabus_by_kp = syllabus_by_kp or {}
    async with session_factory() as db:
        db.add_all(
            [
                QuestionVersionKnowledgePoint(
                    question_version_id=version_id,
                    knowledge_point_id=kp_id,
                    position=position,
                    syllabus_knowledge_point_id=syllabus_by_kp.get(kp_id),
                )
                for position, kp_id in enumerate(knowledge_point_ids)
            ]
        )
        await db.commit()


def _state_row(
    *, knowledge_point_id: int, mastery: float, attempts: int = 0, **overrides
):
    values = {
        "user_id": 1,
        "subject_id": 1,
        "knowledge_point_id": knowledge_point_id,
        "attempt_count": attempts,
        "correct_count": 0,
        "wrong_count": 0,
        "accuracy": 0.0,
        "mastery_score": mastery,
        "weakness_level": "observing",
        "confidence": 0.0,
        "recent_answer_count": 0,
        "recent_correct_count": 0,
        "recent_wrong_count": 0,
    }
    values.update(overrides)
    return UserKnowledgeState(**values)


EMPTY_SUMMARY = {
    "updated": 0,
    "created": 0,
    "mastery_before": None,
    "mastery_after": None,
    "mastery_delta": None,
}


class TestAnswerUpdateQueries:
    @pytest.mark.asyncio
    async def test_version_difficulty_is_read_even_when_mappings_are_missing(
        self, tmp_path
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_knowledge_points(session_factory, 1)
            await _seed_version(session_factory)
            statements = _record_statements(engine)

            async with session_factory() as db:
                result = await update_user_knowledge_state_after_answer(
                    db, user_id=1, question_id=1, is_correct=True, question_version_id=1
                )

            assert result == EMPTY_SUMMARY
            assert any(
                "question_versions" in statement and "difficulty" in statement
                for statement in statements
            ), statements
            assert not any(
                "user_knowledge_states" in statement for statement in statements
            )
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_dangling_version_row_returns_empty_summary_without_state_writes(
        self, tmp_path
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_knowledge_points(session_factory, 1)
            await _seed_version_mappings(session_factory, [1], version_id=999)

            async with session_factory() as db:
                result = await update_user_knowledge_state_after_answer(
                    db,
                    user_id=1,
                    question_id=1,
                    is_correct=True,
                    question_version_id=999,
                )
                await db.commit()

            assert result == EMPTY_SUMMARY
            async with session_factory() as db:
                count = await db.scalar(select(func.count(UserKnowledgeState.id)))
            assert count == 0
        finally:
            await engine.dispose()


class TestAnswerUpdateStateMachine:
    @pytest.mark.asyncio
    async def test_first_wrong_answer_claims_state_and_fills_recent_statistics(
        self, tmp_path
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_knowledge_points(session_factory, 1)
            await _seed_version(session_factory, difficulty=3)
            await _seed_version_mappings(session_factory, [1])

            async with session_factory() as db:
                result = await update_user_knowledge_state_after_answer(
                    db,
                    user_id=1,
                    question_id=1,
                    is_correct=False,
                    question_version_id=1,
                    used_time=42,
                )
                await db.commit()

            assert result == {
                "updated": 1,
                "created": 1,
                "mastery_before": 50.0,
                "mastery_after": 38.0,
                "mastery_delta": -12.0,
            }
            async with session_factory() as db:
                state = await db.scalar(select(UserKnowledgeState))
            assert state.id is not None
            assert (state.attempt_count, state.correct_count, state.wrong_count) == (
                1,
                0,
                1,
            )
            assert (state.recent_answer_count, state.recent_correct_count) == (1, 0)
            assert state.recent_wrong_count == 1
            assert state.accuracy == 0.0
            assert state.confidence == 0.1
            assert state.mastery_score == 38.0
            assert state.weakness_level == "possible_weak"
            assert state.last_is_correct is False
            assert state.last_answer_time_seconds == 42
            assert state.last_wrong_at is not None
            assert state.last_practiced_at is not None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_existing_and_missing_states_share_one_version_update(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_knowledge_points(session_factory, 2)
            await _seed_version(session_factory, difficulty=5)
            await _seed_version_mappings(session_factory, [1, 2])
            previous_wrong_at = datetime(2026, 9, 1, 12, 0, 0)
            async with session_factory() as db:
                db.add(
                    _state_row(
                        knowledge_point_id=1,
                        mastery=40.0,
                        attempts=5,
                        correct_count=3,
                        wrong_count=2,
                        accuracy=0.6,
                        confidence=0.5,
                        weakness_level="normal",
                        recent_answer_count=2,
                        recent_correct_count=0,
                        recent_wrong_count=2,
                        last_wrong_at=previous_wrong_at,
                    )
                )
                await db.commit()

            async with session_factory() as db:
                result = await update_user_knowledge_state_after_answer(
                    db,
                    user_id=1,
                    question_id=1,
                    is_correct=True,
                    question_version_id=1,
                    used_time=90,
                )
                await db.commit()

            assert result == {
                "updated": 2,
                "created": 1,
                "mastery_before": 45.0,
                "mastery_after": 54.0,
                "mastery_delta": 9.0,
            }
            async with session_factory() as db:
                states = (
                    (
                        await db.execute(
                            select(UserKnowledgeState).order_by(
                                UserKnowledgeState.knowledge_point_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            updated, claimed = states
            assert updated.attempt_count == 6
            assert updated.correct_count == 4
            assert updated.recent_correct_count == 1
            assert updated.recent_wrong_count == 0
            assert updated.recent_answer_count == 3
            assert updated.mastery_score == 49.0
            assert updated.confidence == 0.6
            assert updated.weakness_level == "normal"
            assert updated.last_is_correct is True
            assert updated.last_wrong_at == previous_wrong_at
            assert updated.last_answer_time_seconds == 90
            assert claimed.attempt_count == 1
            assert claimed.mastery_score == 59.0
            assert claimed.last_wrong_at is None
            assert claimed.weakness_level == "observing"
            assert round(claimed.accuracy, 4) == 1.0
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_three_point_averages_round_to_four_decimals(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_knowledge_points(session_factory, 3)
            await _seed_version(session_factory, difficulty=3)
            await _seed_version_mappings(session_factory, [1, 2, 3])
            async with session_factory() as db:
                db.add_all(
                    [
                        _state_row(knowledge_point_id=1, mastery=10.0, attempts=3),
                        _state_row(knowledge_point_id=2, mastery=20.0, attempts=3),
                        _state_row(knowledge_point_id=3, mastery=40.0, attempts=3),
                    ]
                )
                await db.commit()

            async with session_factory() as db:
                result = await update_user_knowledge_state_after_answer(
                    db, user_id=1, question_id=1, is_correct=True, question_version_id=1
                )

            assert result["updated"] == 3
            assert result["created"] == 0
            assert result["mastery_before"] == 23.3333
            assert result["mastery_after"] == 29.3333
            assert result["mastery_delta"] == 6.0
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_wrong_answers_clamp_mastery_and_report_clamped_delta(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_knowledge_points(session_factory, 1)
            await _seed_version(session_factory, difficulty=1)
            await _seed_version_mappings(session_factory, [1])
            async with session_factory() as db:
                db.add(
                    _state_row(
                        knowledge_point_id=1,
                        mastery=2.0,
                        attempts=4,
                        correct_count=2,
                        wrong_count=2,
                        accuracy=0.5,
                        confidence=0.4,
                        recent_answer_count=3,
                        recent_correct_count=2,
                        recent_wrong_count=1,
                    )
                )
                await db.commit()

            async with session_factory() as db:
                result = await update_user_knowledge_state_after_answer(
                    db,
                    user_id=1,
                    question_id=1,
                    is_correct=False,
                    question_version_id=1,
                )
                await db.commit()

            assert result["mastery_after"] == 0.0
            assert result["mastery_delta"] == -2.0
            async with session_factory() as db:
                state = await db.scalar(select(UserKnowledgeState))
            assert state.mastery_score == 0.0
            assert state.recent_wrong_count == 2
            assert state.recent_correct_count == 0
            assert state.wrong_count == 3
            assert state.accuracy == 0.4
        finally:
            await engine.dispose()


class TestWeakPointProjection:
    @pytest.mark.asyncio
    async def test_state_projection_orders_truncates_and_skips_untouched_points(
        self, tmp_path
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_knowledge_points(session_factory, 6)
            async with session_factory() as db:
                db.add_all(
                    [
                        _state_row(
                            knowledge_point_id=1, mastery=20.0, attempts=5, accuracy=0.4
                        ),
                        _state_row(
                            knowledge_point_id=2, mastery=65.0, attempts=2, accuracy=0.5
                        ),
                        _state_row(
                            knowledge_point_id=3, mastery=69.0, attempts=9, accuracy=0.6
                        ),
                        _state_row(
                            knowledge_point_id=4, mastery=69.0, attempts=1, accuracy=0.5
                        ),
                        _state_row(knowledge_point_id=5, mastery=30.0, attempts=0),
                        _state_row(
                            knowledge_point_id=6, mastery=80.0, attempts=4, accuracy=0.9
                        ),
                    ]
                )
                await db.commit()

            async with session_factory() as db:
                weak = await get_user_weak_knowledge_points(
                    db, user_id=1, subject=1, limit=3
                )

            assert [item["knowledge_point_id"] for item in weak] == [1, 2, 3]
            assert weak[0] == {
                "knowledge_point_id": 1,
                "name": "知识点1",
                "subject_id": 1,
                "mastery_score": 20.0,
                "confidence": 0.0,
                "accuracy": 0.4,
                "attempt_count": 5,
                "weakness_level": "observing",
            }
            assert [item["attempt_count"] for item in weak] == [5, 2, 9]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_fallback_projection_uses_recent_practice_records(
        self, tmp_path, caplog
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_knowledge_points(session_factory, 3)
            for version_id in (1, 2, 3):
                await _seed_version(
                    session_factory, version_id=version_id, difficulty=3
                )
            async with session_factory() as db:
                db.add(
                    SyllabusKnowledgePoint(
                        id=1,
                        syllabus_version_id=1,
                        knowledge_point_id=3,
                        subject_id=1,
                        name_snapshot="快照知识点3",
                        normalized_name_snapshot="快照知识点3",
                    )
                )
                await db.commit()
            await _seed_version_mappings(session_factory, [1], version_id=1)
            await _seed_version_mappings(session_factory, [2], version_id=2)
            await _seed_version_mappings(
                session_factory, [3], version_id=3, syllabus_by_kp={3: 1}
            )
            now = utcnow()
            recent = [
                (1, True),
                (1, False),
                (3, False),
                (3, False),
                (3, False),
            ]
            async with session_factory() as db:
                db.add_all(
                    [
                        PracticeRecord(
                            user_id=1,
                            question_id=1,
                            question_version_id=version_id,
                            subject_id=1,
                            question_type="single_choice",
                            user_answer="A",
                            is_correct=is_correct,
                            answered_at=now - timedelta(days=1),
                            projection_state="completed",
                        )
                        for version_id, is_correct in recent
                    ]
                    + [
                        PracticeRecord(
                            user_id=1,
                            question_id=1,
                            question_version_id=2,
                            subject_id=1,
                            question_type="single_choice",
                            user_answer="A",
                            is_correct=True,
                            answered_at=now - timedelta(days=45),
                            projection_state="completed",
                        )
                    ]
                )
                await db.commit()

            with caplog.at_level(logging.INFO, logger="app.services.mastery_service"):
                async with session_factory() as db:
                    weak = await get_user_weak_knowledge_points(
                        db, user_id=1, subject=1, limit=5
                    )

            assert "fallback 到 PracticeRecord 统计" in caplog.text
            assert weak == [
                {
                    "knowledge_point_id": 3,
                    "name": "快照知识点3",
                    "mastery_score": 0.0,
                    "confidence": 0.3,
                    "accuracy": 0.0,
                    "attempt_count": 3,
                    "weakness_level": "weak",
                },
                {
                    "knowledge_point_id": 1,
                    "name": "知识点1",
                    "mastery_score": 50.0,
                    "confidence": 0.2,
                    "accuracy": 0.5,
                    "attempt_count": 2,
                    "weakness_level": "normal",
                },
            ]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_fallback_limit_truncates_after_sorting(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            await _seed_knowledge_points(session_factory, 3)
            for version_id in (1, 2, 3):
                await _seed_version(
                    session_factory, version_id=version_id, difficulty=3
                )
            await _seed_version_mappings(session_factory, [1], version_id=1)
            await _seed_version_mappings(session_factory, [2], version_id=2)
            await _seed_version_mappings(session_factory, [3], version_id=3)
            now = utcnow()
            async with session_factory() as db:
                db.add_all(
                    [
                        PracticeRecord(
                            user_id=1,
                            question_id=1,
                            question_version_id=1,
                            subject_id=1,
                            question_type="single_choice",
                            user_answer="A",
                            is_correct=False,
                            answered_at=now - timedelta(days=1),
                            projection_state="completed",
                        )
                        for _ in range(2)
                    ]
                    + [
                        PracticeRecord(
                            user_id=1,
                            question_id=1,
                            question_version_id=3,
                            subject_id=1,
                            question_type="single_choice",
                            user_answer="A",
                            is_correct=is_correct,
                            answered_at=now - timedelta(days=1),
                            projection_state="completed",
                        )
                        for is_correct in (True, False)
                    ]
                )
                await db.commit()

            async with session_factory() as db:
                weak = await get_user_weak_knowledge_points(
                    db, user_id=1, subject=1, limit=1
                )

            assert len(weak) == 1
            assert weak[0]["knowledge_point_id"] == 1
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_unresolved_subject_short_circuits_both_projections(
        self, tmp_path, caplog
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            with caplog.at_level(logging.INFO, logger="app.services.mastery_service"):
                async with session_factory() as db:
                    assert (
                        await get_user_weak_knowledge_points(
                            db, user_id=1, subject="missing", limit=5
                        )
                        == []
                    )
                    assert (
                        await get_user_knowledge_states(db, user_id=1, subject=99) == []
                    )
            assert "fallback 到 PracticeRecord 统计" not in caplog.text
        finally:
            await engine.dispose()


class TestKnowledgeStateProjection:
    @pytest.mark.asyncio
    async def test_state_view_rounds_serializes_and_labels_subjects(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            async with session_factory() as db:
                db.add_all(
                    [
                        KnowledgePoint(
                            id=1,
                            subject_id=1,
                            name="A知识点",
                            normalized_name="A知识点",
                            aliases=[],
                            is_active=True,
                        ),
                        KnowledgePoint(
                            id=2,
                            subject_id=2,
                            name="B知识点",
                            normalized_name="B知识点",
                            aliases=[],
                            is_active=True,
                        ),
                        KnowledgePoint(
                            id=3,
                            subject_id=1,
                            name="C知识点",
                            normalized_name="C知识点",
                            aliases=[],
                            is_active=True,
                        ),
                    ]
                )
                await db.commit()
            practiced_at = datetime(2026, 8, 1, 4, 30, 0)
            async with session_factory() as db:
                db.add_all(
                    [
                        _state_row(
                            knowledge_point_id=1,
                            mastery=33.333333,
                            attempts=3,
                            correct_count=1,
                            wrong_count=2,
                            accuracy=1 / 3,
                            confidence=0.25,
                            weakness_level="normal",
                            recent_wrong_count=1,
                            last_practiced_at=practiced_at,
                            last_wrong_at=practiced_at,
                        ),
                        _state_row(
                            knowledge_point_id=2,
                            subject_id=2,
                            mastery=90.0,
                            attempts=10,
                            correct_count=10,
                            accuracy=1.0,
                            confidence=1.0,
                        ),
                        _state_row(
                            knowledge_point_id=3,
                            mastery=60.0,
                            attempts=2,
                            correct_count=1,
                            wrong_count=1,
                            accuracy=0.5,
                            confidence=0.2,
                            weakness_level="observing",
                        ),
                    ]
                )
                await db.commit()

            async with session_factory() as db:
                items = await get_user_knowledge_states(db, user_id=1, subject=1)
            async with session_factory() as db:
                other_items = await get_user_knowledge_states(db, user_id=1, subject=2)

            assert [item["knowledge_point_id"] for item in items] == [1, 3]
            assert [item["knowledge_point_id"] for item in other_items] == [2]
            first, third = items
            assert first == {
                "knowledge_point_id": 1,
                "name": "A知识点",
                "subject_id": 1,
                "subject_name": "掌握度科目",
                "attempt_count": 3,
                "correct_count": 1,
                "wrong_count": 2,
                "accuracy": 0.3333,
                "mastery_score": 33.33,
                "confidence": 0.25,
                "weakness_level": "normal",
                "recent_wrong_count": 1,
                "last_practiced_at": serialize_utc_datetime(practiced_at),
                "last_wrong_at": serialize_utc_datetime(practiced_at),
            }
            assert third["mastery_score"] == 60.0
            assert third["accuracy"] == 0.5
            assert third["weakness_level"] == "observing"
            assert third["last_practiced_at"] is None
            second = other_items[0]
            assert second["subject_name"] == "其他科目"
            assert second["last_practiced_at"] is None
            assert second["last_wrong_at"] is None
            assert second["accuracy"] == 1.0
            assert second["confidence"] == 1.0
        finally:
            await engine.dispose()
