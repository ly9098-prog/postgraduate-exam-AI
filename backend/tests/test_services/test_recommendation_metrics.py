"""Phase 4.6 — 推荐指标调度器 + 日志保留清理 + 策略权重重排 单元测试。"""
import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure all ORM models are registered so string relationships resolve
# (see app/models/admin.py Subject).
from app.models.knowledge_point import KnowledgePoint  # noqa: F401
from app.models.recommendation_log import RecommendationLog  # noqa: F401
from app.models.recommendation_metrics_daily import (
    RecommendationMetricsDaily,  # noqa: F401
)
from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401

# ── helpers ──


def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_execute_result(**methods):
    mock_result = MagicMock()
    for method, value in methods.items():
        if method == "scalars":
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = value
            mock_result.scalars.return_value = mock_scalars
        elif method == "all":
            mock_result.all.return_value = value
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


def _run(coro):
    return asyncio.run(coro)


def _make_question(qid: int, difficulty: int = 3, kps: list[str] | None = None):
    q = MagicMock()
    q.id = qid
    q.difficulty = difficulty
    return q


def _make_config(**overrides):
    config = {
        "id": 1,
        "is_active": True,
        "config_json": {"strategy_type": "weakness_vector"},
        "exploration_ratio": 0.0,
        "weight_vector_similarity": 1.0,
        "weight_knowledge_overlap": 0.0,
        "weight_difficulty_match": 0.0,
        "weight_mastery_gap": 0.0,
        "weight_path_priority": 0.0,
    }
    config.update(overrides)
    return config


# ── Test 1: cleanup_expired_recommendation_logs 保留清理 ──


class TestCleanupExpiredRecommendationLogs:
    def test_deletes_batched_old_rows(self):
        from app.services.recommendation_log_service import (
            cleanup_expired_recommendation_logs,
        )

        db = _make_mock_db()
        # execute 调用顺序: select ids → [1,2]; delete → unused; select ids → []
        db.execute.side_effect = [
            _make_execute_result(scalars=[1, 2]),
            _make_execute_result(scalars=[]),
            _make_execute_result(scalars=[]),
        ]

        deleted = _run(cleanup_expired_recommendation_logs(db, retention_days=90))

        assert deleted == 2
        assert db.commit.await_count == 1

    def test_no_rows_skips_commit(self):
        from app.services.recommendation_log_service import (
            cleanup_expired_recommendation_logs,
        )

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalars=[])

        deleted = _run(cleanup_expired_recommendation_logs(db, retention_days=90))

        assert deleted == 0
        db.commit.assert_not_awaited()


# ── Test 2: 调度器聚合昨日指标 ──


class TestRecommendationMetricsScheduler:
    def test_module_singleton_exists(self):
        """模块必须导出 recommendation_metrics_scheduler 单例（bootstrap import 依赖）。"""
        from app.services.recommendation_metrics_scheduler import (
            RecommendationMetricsScheduler,
            recommendation_metrics_scheduler,
        )

        assert isinstance(recommendation_metrics_scheduler, RecommendationMetricsScheduler)

    def test_safe_run_delegates_to_system_task_service(self):
        from app.services.recommendation_metrics_scheduler import (
            RecommendationMetricsScheduler,
        )

        sched = RecommendationMetricsScheduler()
        outcome = MagicMock(status="success", message="completed")

        with patch(
            "app.services.system_task_service.execute_scheduled_task",
            new=AsyncMock(return_value=outcome),
        ) as execute:
            _run(sched._safe_run())

        execute.assert_awaited_once_with(
            "recommendation_metrics_daily", source="scheduler"
        )

    def test_safe_run_logs_skipped_outcome(self, caplog):
        import logging

        from app.services.recommendation_metrics_scheduler import (
            RecommendationMetricsScheduler,
        )

        sched = RecommendationMetricsScheduler()
        outcome = MagicMock(status="skipped", message="already run")

        with (
            patch(
                "app.services.system_task_service.execute_scheduled_task",
                new=AsyncMock(return_value=outcome),
            ),
            caplog.at_level(logging.INFO, logger="2240ai.recommendation_metrics"),
        ):
            _run(sched._safe_run())

        assert "推荐指标聚合跳过: already run" in caplog.text

    def test_system_task_backfills_rolling_window_then_cleans(self):
        from app.services import system_task_service as service

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=db)
        session_cm.__aexit__ = AsyncMock(return_value=False)
        aggregate = AsyncMock(return_value={"aggregated_rows": 2})
        cleanup = AsyncMock(return_value=3)

        async def run_work(task_id, source, lock_name, work, *, ttl=600):
            assert (task_id, source, lock_name, ttl) == (
                "recommendation_metrics_daily",
                "scheduler",
                "recommendation:metrics:daily",
                600,
            )
            return await work()

        with (
            patch.object(service, "_run_with_lock", new=run_work),
            patch("app.core.database.async_session", return_value=session_cm),
            patch(
                "app.services.recommendation_metrics_service.aggregate_recommendation_metrics_daily",
                new=aggregate,
            ),
            patch(
                "app.services.recommendation_log_service.cleanup_expired_recommendation_logs",
                new=cleanup,
            ),
            patch.object(service, "shanghai_today", return_value=date(2026, 10, 23)),
        ):
            result = _run(service._run_recommendation_metrics("scheduler"))

        target_dates = [call.kwargs["target_date"] for call in aggregate.await_args_list]
        assert target_dates == [date(2026, 10, day) for day in range(16, 23)]
        assert db.commit.await_count == 7
        db.rollback.assert_not_awaited()
        cleanup.assert_awaited_once()
        assert result == "回补最近 7 天，聚合 14 行，清理 3 条推荐日志"

    def test_system_task_failure_blocks_log_cleanup(self):
        from app.services import system_task_service as service

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=db)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        async def aggregate(_db, *, target_date):
            if target_date == date(2026, 10, 20):
                raise RuntimeError("aggregate failed")
            return {"aggregated_rows": 1}

        cleanup = AsyncMock(return_value=9)

        async def run_work(_task_id, _source, _lock_name, work, *, ttl=600):
            assert ttl == 600
            return await work()

        with (
            patch.object(service, "_run_with_lock", new=run_work),
            patch("app.core.database.async_session", return_value=session_cm),
            patch(
                "app.services.recommendation_metrics_service.aggregate_recommendation_metrics_daily",
                new=AsyncMock(side_effect=aggregate),
            ),
            patch(
                "app.services.recommendation_log_service.cleanup_expired_recommendation_logs",
                new=cleanup,
            ),
            patch.object(service, "shanghai_today", return_value=date(2026, 10, 23)),
        ):
            result = _run(service._run_recommendation_metrics("scheduler"))

        assert result.status == "failed"
        assert "失败日期：2026-10-20" in result.message
        assert "本轮未执行推荐日志清理" in result.message
        db.rollback.assert_awaited_once()
        cleanup.assert_not_awaited()


# ── Test 3: _apply_strategy_weight_rerank 守卫与排序 ──


class TestApplyStrategyWeightRerank:
    def test_no_config_returns_unchanged(self):
        from app.services.practice_service import _apply_strategy_weight_rerank

        db = _make_mock_db()
        q1, q2 = _make_question(1), _make_question(2)
        questions = [q1, q2]
        metadata = {1: {"similarity": 0.9}, 2: {"similarity": 0.3}}

        result_qs, result_meta = _run(_apply_strategy_weight_rerank(
            db, 1, questions, metadata, None, ["KP_A"],
        ))

        assert result_qs is questions
        assert result_meta is metadata
        db.execute.assert_not_awaited()

    def test_inactive_or_no_db_id_returns_unchanged(self):
        from app.services.practice_service import _apply_strategy_weight_rerank

        db = _make_mock_db()
        questions = [_make_question(1), _make_question(2)]
        metadata = {1: {"similarity": 0.9}, 2: {"similarity": 0.3}}

        for config in (
            _make_config(id=None),
            _make_config(is_active=False),
            _make_config(config_json={"strategy_type": "knowledge_path"}),
        ):
            result_qs, _ = _run(_apply_strategy_weight_rerank(
                db, 1, questions, metadata, config, ["KP_A"],
            ))
            assert result_qs is questions

    def test_orders_by_weighted_similarity_deterministically(self):
        from app.services.practice_service import _apply_strategy_weight_rerank

        db = _make_mock_db()
        # 1) load_question_kps → [(qid, name)]，2) KP id 查询，3) 掌握度查询 → 空
        db.execute.side_effect = [
            _make_execute_result(all=[(1, "KP_A"), (2, "KP_A")]),
            _make_execute_result(all=[(10, "KP_A")]),
            _make_execute_result(all=[]),
        ]

        q1 = _make_question(1, kps=["KP_A"])
        q2 = _make_question(2, kps=["KP_A"])
        questions = [q1, q2]
        metadata = {1: {"similarity": 0.9}, 2: {"similarity": 0.3}}
        # 只有 vector_similarity 权重非 0 → final 即 similarity，确定性
        config = _make_config()

        result_qs, result_meta = _run(_apply_strategy_weight_rerank(
            db, 1, questions, metadata, config, ["KP_A"],
        ))

        assert result_qs[0].id == 1
        assert result_qs[1].id == 2
        assert result_meta[1]["recommend_score"] == 0.9
        assert result_meta[2]["recommend_score"] == 0.3
        assert db.execute.await_count == 3  # load_question_kps + KP id + mastery，固定次数无 N+1
