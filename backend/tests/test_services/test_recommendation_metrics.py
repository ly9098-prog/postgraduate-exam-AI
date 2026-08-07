"""Phase 4.6 — 推荐指标调度器 + 日志保留清理 + 策略权重重排 单元测试。"""
import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure all ORM models are registered so string relationships resolve
# (see app/models/admin.py Subject).
from app.models.knowledge_point import KnowledgePoint  # noqa: F401
from app.models.recommendation_log import RecommendationLog  # noqa: F401
from app.models.recommendation_metrics_daily import RecommendationMetricsDaily  # noqa: F401
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
    q.knowledge_points = kps or []
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

    def test_safe_run_aggregates_yesterday(self):
        from app.services.recommendation_metrics_scheduler import (
            RecommendationMetricsScheduler,
        )

        sched = RecommendationMetricsScheduler.__new__(RecommendationMetricsScheduler)
        handle = MagicMock()
        handle.is_still_held.return_value = True
        lock_cm = AsyncMock()
        lock_cm.__aenter__.return_value = handle
        lock_cm.__aexit__.return_value = False
        sched._lock = MagicMock()
        sched._lock.acquire_and_renew.return_value = lock_cm

        mock_db = _make_mock_db()
        session_cm = AsyncMock()
        session_cm.__aenter__.return_value = mock_db
        session_cm.__aexit__.return_value = False

        yesterday = date.today() - timedelta(days=1)

        with patch(
            "app.services.recommendation_metrics_scheduler.async_session",
            return_value=session_cm,
        ), patch(
            "app.services.recommendation_metrics_scheduler.aggregate_recommendation_metrics_daily",
            new=AsyncMock(return_value={"aggregated_rows": 3}),
        ) as agg, patch(
            "app.services.recommendation_metrics_scheduler.cleanup_expired_recommendation_logs",
            new=AsyncMock(return_value=0),
        ) as cleanup:
            _run(sched._safe_run())

            agg.assert_awaited_once()
            assert agg.await_args.kwargs["target_date"] == yesterday
            cleanup.assert_awaited_once()
            mock_db.commit.assert_awaited()

    def test_safe_run_skips_when_lock_held(self):
        from app.services.recommendation_metrics_scheduler import (
            RecommendationMetricsScheduler,
        )

        sched = RecommendationMetricsScheduler.__new__(RecommendationMetricsScheduler)
        handle = MagicMock()
        handle.is_still_held.return_value = False
        lock_cm = AsyncMock()
        lock_cm.__aenter__.return_value = handle
        lock_cm.__aexit__.return_value = False
        sched._lock = MagicMock()
        sched._lock.acquire_and_renew.return_value = lock_cm

        with patch(
            "app.services.recommendation_metrics_scheduler.aggregate_recommendation_metrics_daily",
            new=AsyncMock(),
        ) as agg:
            _run(sched._safe_run())
            agg.assert_not_awaited()


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
        # KP 查询 → [(10, "KP_A")], 掌握度查询 → 空
        db.execute.side_effect = [
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
        assert db.execute.await_count == 2  # 固定 2 次查询，无 N+1
