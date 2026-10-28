"""Behavioral contract for the learning statistics service.

Real SQLite rows back all aggregate queries; provider ports stay stubbed only
for the AI-facing paths.  The cases pin the public dashboard/statistics shapes
and the fallback decisions that existing clients rely on.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register relationships before create_all
from app.core.database import Base
from app.models.admin import (
    QuestionVersion,
    QuestionVersionKnowledgePoint,
    Subject,
)
from app.models.answer_behavior import AnswerBehavior
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.review_scheduler import ReviewSchedule
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.services import stats_service

TODAY = date(2026, 10, 22)
NOW = datetime(2026, 10, 22, 10, 0, 0)


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'stats-contract.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_subjects(session_factory) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, openid="stats-contract-user"),
                Subject(
                    id=1,
                    code="exam408",
                    name="计算机学科专业基础",
                    path="exam408",
                    level=1,
                ),
                Subject(
                    id=2,
                    parent_id=1,
                    code="data_structure",
                    name="数据结构",
                    path="exam408/data-structure",
                    level=2,
                ),
                Question(
                    id=10,
                    subject_id=2,
                    question_type="single_choice",
                    content={},
                    answer="A",
                    difficulty=3,
                    is_active=True,
                ),
                Question(
                    id=11,
                    subject_id=2,
                    question_type="single_choice",
                    content={},
                    answer="A",
                    difficulty=3,
                    is_active=True,
                ),
                QuestionVersion(
                    id=1,
                    question_id=10,
                    version=1,
                    subject_id=2,
                    question_type="single_choice",
                    content={},
                    answer="A",
                    difficulty=3,
                    is_active=True,
                ),
                QuestionVersion(
                    id=2,
                    question_id=11,
                    version=1,
                    subject_id=2,
                    question_type="single_choice",
                    content={},
                    answer="A",
                    difficulty=3,
                    is_active=True,
                ),
            ]
        )
        await db.commit()


def _practice(*, question_id: int, answered_at: datetime, correct: bool, seconds: int):
    return PracticeRecord(
        user_id=1,
        question_id=question_id,
        question_version_id=1,
        subject_id=2,
        question_type="single_choice",
        user_answer="A",
        is_correct=correct,
        used_time=seconds,
        answered_at=answered_at,
    )


class TestOverviewContract:
    @pytest.mark.asyncio
    async def test_overview_counts_scope_and_today_window(self, tmp_path, monkeypatch):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            async with session_factory() as db:
                db.add_all(
                    [
                        _practice(
                            question_id=10,
                            answered_at=datetime(2026, 10, 22, 9),
                            correct=True,
                            seconds=10,
                        ),
                        _practice(
                            question_id=10,
                            answered_at=datetime(2026, 10, 21, 9),
                            correct=False,
                            seconds=20,
                        ),
                        WrongQuestion(
                            user_id=1,
                            question_id=10,
                            question_version_id=1,
                            error_type="concept",
                            review_count=1,
                            mastered=False,
                            is_active=True,
                        ),
                        WrongQuestion(
                            user_id=1,
                            question_id=11,
                            question_version_id=2,
                            error_type="logic",
                            review_count=0,
                            mastered=True,
                            is_active=True,
                        ),
                        ReviewSchedule(
                            user_id=1,
                            question_id=10,
                            question_version_id=1,
                            subject_id=2,
                            interval=1,
                            next_review_at=datetime(2026, 10, 22, 8),
                            mastered=False,
                            is_active=True,
                        ),
                    ]
                )
                await db.commit()

            monkeypatch.setattr(stats_service, "shanghai_today", lambda: TODAY)
            monkeypatch.setattr(
                stats_service, "_today_utc", lambda: datetime(2026, 10, 22)
            )
            monkeypatch.setattr(stats_service, "utcnow", lambda: NOW)

            async with session_factory() as db:
                result = await stats_service.get_overview(db, user_id=1)

            assert result == {
                "total_questions": 2,
                "total_correct": 1,
                "total_wrong": 1,
                "accuracy": 0.5,
                "total_duration_sec": 30,
                "consecutive_days": 2,
                "today_questions": 1,
                "today_correct": 1,
                "today_duration_sec": 10,
                "mastered_count": 1,
                "due_review_count": 1,
                "wrong_question_count": 2,
            }
        finally:
            await engine.dispose()


class TestBehaviorContract:
    @pytest.mark.asyncio
    async def test_behavior_rates_distribution_and_hourly_window(self, tmp_path):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            async with session_factory() as db:
                db.add_all(
                    [
                        AnswerBehavior(
                            user_id=1,
                            question_id=10,
                            question_version_id=1,
                            subject_id=2,
                            time_spent_sec=20,
                            view_answer_count=2,
                            is_abandoned=False,
                            created_at=datetime(2026, 10, 22, 0),
                        ),
                        AnswerBehavior(
                            user_id=1,
                            question_id=10,
                            question_version_id=1,
                            subject_id=2,
                            time_spent_sec=40,
                            view_answer_count=0,
                            is_abandoned=True,
                            created_at=datetime(2026, 10, 22, 0),
                        ),
                        AnswerBehavior(
                            user_id=1,
                            question_id=10,
                            question_version_id=1,
                            subject_id=2,
                            time_spent_sec=0,
                            view_answer_count=9,
                            is_abandoned=True,
                            created_at=datetime(2026, 10, 22, 1),
                        ),
                        WrongQuestion(
                            user_id=1,
                            question_id=10,
                            question_version_id=1,
                            error_type="concept",
                            review_count=2,
                            mastered=False,
                            is_active=True,
                        ),
                        WrongQuestion(
                            user_id=1,
                            question_id=11,
                            question_version_id=2,
                            error_type="logic",
                            review_count=1,
                            mastered=False,
                            is_active=True,
                        ),
                    ]
                )
                await db.commit()

            async with session_factory() as db:
                result = await stats_service.get_behavior_stats(db, user_id=1)

            assert result["avg_time_sec"] == 30.0
            assert result["total_answers"] == 2
            assert result["view_answer_rate"] == 1.0
            assert result["abandon_rate"] == 0.5
            assert result["error_type_distribution"][0]["count"] == 1
            assert result["hourly_activity"] == [
                {"hour": 8, "count": 2},
                {"hour": 9, "count": 1},
            ]
        finally:
            await engine.dispose()


class TestForgettingContract:
    @pytest.mark.asyncio
    async def test_forgetting_pseudo_mastered_and_topic_ranking(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            async with session_factory() as db:
                db.add_all(
                    [
                        KnowledgePoint(
                            id=100,
                            subject_id=2,
                            name="链表",
                            normalized_name="链表",
                            aliases=[],
                            is_active=True,
                        ),
                        QuestionVersionKnowledgePoint(
                            question_version_id=1,
                            knowledge_point_id=100,
                            role="main",
                            weight=1.0,
                            source="imported",
                            position=0,
                        ),
                        WrongQuestion(
                            user_id=1,
                            question_id=10,
                            question_version_id=1,
                            error_type="concept",
                            review_count=3,
                            mastered=False,
                            is_active=True,
                        ),
                        WrongQuestion(
                            user_id=1,
                            question_id=11,
                            question_version_id=2,
                            error_type="logic",
                            review_count=1,
                            mastered=True,
                            is_active=True,
                        ),
                        ReviewSchedule(
                            user_id=1,
                            question_id=11,
                            question_version_id=2,
                            subject_id=2,
                            interval=2,
                            ease_factor=2.5,
                            next_review_at=datetime(2026, 10, 23),
                            mastered=True,
                            is_active=True,
                        ),
                        ReviewSchedule(
                            user_id=1,
                            question_id=10,
                            question_version_id=1,
                            subject_id=2,
                            interval=5,
                            ease_factor=2.2,
                            next_review_at=datetime(2026, 10, 10),
                            mastered=False,
                            is_active=True,
                        ),
                    ]
                )
                await db.commit()

            monkeypatch.setattr(stats_service, "shanghai_today", lambda: TODAY)
            async with session_factory() as db:
                result = await stats_service.get_forgetting_trends(db, user_id=1)

            assert result["high_forget_count"] == 1
            assert result["stuck_questions"] == 1
            assert result["pseudo_mastered"][0]["question_id"] == 11
            assert result["pseudo_mastered"][0]["next_review_date"] == "2026-10-23"
            assert result["top_forgotten_topics"] == [{"topic": "链表", "count": 1}]
        finally:
            await engine.dispose()


class TestGrowthContract:
    @pytest.mark.asyncio
    async def test_growth_formula_and_badge_progress(self):
        result = await stats_service.get_growth_profile(
            None,
            user_id=1,
            overview={
                "total_questions": 100,
                "accuracy": 0.8,
                "consecutive_days": 8,
                "mastered_count": 50,
                "today_questions": 5,
                "due_review_count": 4,
            },
        )

        assert result["total_exp"] == 100 * 10 + 50 * 20 + 8 * 5 + int(100 * 0.8 * 5)
        assert result["level"] == 4
        assert result["level_title"] == "Lv4 高效进阶"
        assert result["exp_current"] == 940
        assert result["exp_to_next"] == 2000
        assert result["level_progress_pct"] == 47
        assert result["streak_title"] == "连续学习 7 天，势头正盛"
        assert result["daily_boost"] == "今日已练 5 题，连续 8 天，累计 100 题"
        assert len(result["badges"]) == 9
        assert next(b for b in result["badges"] if b["key"] == "hundred")["unlocked"]
        assert not next(b for b in result["badges"] if b["key"] == "five_hundred")[
            "unlocked"
        ]
        assert (
            next(b for b in result["badges"] if b["key"] == "accuracy_90")[
                "progress_text"
            ]
            == "80%"
        )


class TestAiDiagnosisContract:
    @pytest.mark.asyncio
    async def test_ai_diagnosis_uses_provider_shape_and_falls_back_on_invalid_json(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            async with session_factory() as db:
                db.add(
                    WrongQuestion(
                        user_id=1,
                        question_id=10,
                        question_version_id=1,
                        error_type="concept",
                        review_count=1,
                        mastered=False,
                        is_active=True,
                    )
                )
                db.add(
                    PracticeRecord(
                        user_id=1,
                        question_id=10,
                        question_version_id=1,
                        subject_id=2,
                        question_type="single_choice",
                        user_answer="A",
                        is_correct=True,
                        used_time=10,
                        answered_at=datetime(2026, 10, 22, 9),
                    )
                )
                await db.commit()

            runtime = SimpleNamespace(
                model_name="contract-model",
                api_key="synthetic",
                base_url="https://example.invalid",
                provider="openai",
            )
            monkeypatch.setattr(
                "app.ai.gateway.resolve_llm_runtime_config",
                AsyncMock(return_value=runtime),
            )
            chat = AsyncMock(
                return_value={
                    "content": (
                        '{"weak_points":[{"knowledge_point":"链表","accuracy":0.2}],'
                        '"strong_points":[],"learning_suggestions":["复盘链表"]}'
                    )
                }
            )
            monkeypatch.setattr("app.ai.client.llm.chat", chat)

            monkeypatch.setattr(stats_service, "shanghai_today", lambda: TODAY)
            monkeypatch.setattr(
                stats_service, "_today_utc", lambda: datetime(2026, 10, 22)
            )
            monkeypatch.setattr(stats_service, "utcnow", lambda: NOW)

            async with session_factory() as db:
                result = await stats_service.get_ai_diagnosis(db, user_id=1)

            assert result["generated"] is True
            assert result["weak_points"][0]["knowledge_point"] == "链表"
            assert result["learning_suggestions"] == ["复盘链表"]
            assert (
                chat.await_args.kwargs["timeout"]
                == stats_service._SYNC_AI_PROVIDER_TIMEOUT_SEC
            )
            assert (
                chat.await_args.kwargs["max_tokens"]
                == stats_service._AI_DIAGNOSIS_MAX_TOKENS
            )

            chat.return_value = {"content": "not json"}
            async with session_factory() as db:
                fallback = await stats_service.get_ai_diagnosis(db, user_id=1)
            assert fallback["generated"] is False
            assert "AI 模型响应较慢" in fallback["summary"]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_runtime_config_failure_uses_local_diagnosis(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            async with session_factory() as db:
                db.add(
                    WrongQuestion(
                        user_id=1,
                        question_id=10,
                        question_version_id=1,
                        error_type="concept",
                        review_count=1,
                        mastered=False,
                        is_active=True,
                    )
                )
                await db.commit()

            monkeypatch.setattr(
                "app.ai.gateway.resolve_llm_runtime_config",
                AsyncMock(side_effect=RuntimeError("config down")),
            )
            monkeypatch.setattr(stats_service, "shanghai_today", lambda: TODAY)
            monkeypatch.setattr(
                stats_service, "_today_utc", lambda: datetime(2026, 10, 22)
            )
            monkeypatch.setattr(stats_service, "utcnow", lambda: NOW)

            async with session_factory() as db:
                result = await stats_service.get_ai_diagnosis(db, user_id=1)

            assert result["generated"] is False
            assert "AI 模型响应较慢" in result["summary"]
        finally:
            await engine.dispose()


class TestDashboardLlmContract:
    @pytest.mark.asyncio
    async def test_unavailable_provider_returns_rule_based_dashboard(
        self, tmp_path, monkeypatch
    ):
        engine, session_factory = await _make_database(tmp_path)
        try:
            await _seed_subjects(session_factory)
            monkeypatch.setattr(
                "app.ai.gateway.chat_with_db_model",
                AsyncMock(return_value=None),
            )
            monkeypatch.setattr(stats_service, "shanghai_today", lambda: TODAY)
            monkeypatch.setattr(
                stats_service, "_today_utc", lambda: datetime(2026, 10, 22)
            )
            monkeypatch.setattr(stats_service, "utcnow", lambda: NOW)

            async with session_factory() as db:
                result = await stats_service.get_dashboard_llm_analysis(
                    db, user_id=1, trend_days=7
                )

            assert result["model"] == "rule-based"
            assert result["generated"] is False
            assert result["summary"] == "数据不足，无法生成分析。"
        finally:
            await engine.dispose()
