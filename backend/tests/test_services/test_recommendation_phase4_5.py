"""Phase 4.5 — 推荐系统上线前稳定性治理 + 灰度验证 单元测试。"""
import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

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
        elif method == "scalar_one_or_none":
            mock_result.scalar_one_or_none.return_value = value
        elif method == "all":
            mock_result.all.return_value = value
        elif method == "one":
            mock_result.one.return_value = value
        elif method == "scalar":
            mock_result.scalar.return_value = value
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


def _run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════
# Test 1: seed service — 幂等性（force=False 不覆盖已有值）
# ══════════════════════════════════════════════════════════════════


class TestSeedDefaultStrategies:
    def test_seed_creates_all_five_when_empty(self):
        """空库时 seed 创建 5 个默认策略。"""
        from app.services.recommendation_seed_service import (
            seed_default_recommendation_strategies,
        )

        db = _make_mock_db()
        # 所有 5 个查询都返回 None（不存在）
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        result = _run(seed_default_recommendation_strategies(db, force=False))

        assert result["created"] == 5
        assert result["updated"] == 0
        assert result["skipped"] == 0
        assert db.add.call_count == 5

    def test_seed_skips_when_all_exist_and_no_force(self):
        """所有策略已存在且字段完整时，force=False 全部 skip。"""
        from app.services.recommendation_seed_service import (
            _SEED_STRATEGIES,
            seed_default_recommendation_strategies,
        )

        db = _make_mock_db()

        # 构造已存在的 mock config，字段完整
        def _make_existing_config(seed):
            config = MagicMock()
            for key, value in seed.items():
                setattr(config, key, value)
            return config

        # 每次 execute 返回对应的已存在 config
        side_effects = []
        for seed in _SEED_STRATEGIES:
            existing = _make_existing_config(seed)
            side_effects.append(_make_execute_result(scalar_one_or_none=existing))

        db.execute.side_effect = side_effects

        result = _run(seed_default_recommendation_strategies(db, force=False))

        assert result["created"] == 0
        assert result["skipped"] == 5
        assert db.add.call_count == 0

    def test_seed_force_overwrites_existing(self):
        """force=True 覆盖已有配置。"""
        from app.services.recommendation_seed_service import (
            _SEED_STRATEGIES,
            seed_default_recommendation_strategies,
        )

        db = _make_mock_db()

        # 所有策略已存在但 display_name 被管理员修改
        side_effects = []
        for seed in _SEED_STRATEGIES:
            existing = MagicMock()
            for key, value in seed.items():
                setattr(existing, key, value)
            existing.display_name = "管理员自定义"  # 会被 force 覆盖
            side_effects.append(_make_execute_result(scalar_one_or_none=existing))

        db.execute.side_effect = side_effects

        result = _run(seed_default_recommendation_strategies(db, force=True))

        assert result["created"] == 0
        assert result["updated"] == 5
        assert result["skipped"] == 0


# ══════════════════════════════════════════════════════════════════
# Test 2: strategy config validation
# ══════════════════════════════════════════════════════════════════


class TestStrategyConfigValidation:
    def test_valid_config_passes(self):
        """合法配置通过校验。"""
        from app.services.recommendation_strategy_service import (
            validate_strategy_config,
        )

        payload = {
            "name": "test",
            "scene": "practice_smart",
            "strategy_type": "weakness_vector",
            "weight_vector_similarity": 0.5,
            "weight_knowledge_overlap": 0.2,
        }
        errors = validate_strategy_config(payload)
        assert errors == []

    def test_invalid_strategy_type_rejected(self):
        """非法 strategy_type 被拒绝。"""
        from app.services.recommendation_strategy_service import (
            validate_strategy_config,
        )

        payload = {
            "strategy_type": "nonexistent_strategy",
        }
        errors = validate_strategy_config(payload)
        assert len(errors) == 1
        assert "不在允许列表中" in errors[0]

    def test_negative_weight_rejected(self):
        """负权重被拒绝。"""
        from app.services.recommendation_strategy_service import (
            validate_strategy_config,
        )

        payload = {
            "weight_vector_similarity": -0.5,
        }
        errors = validate_strategy_config(payload)
        assert len(errors) == 1
        assert "不能为负数" in errors[0]

    def test_scene_not_validated_as_strategy_type(self):
        """scene 字段不被当作 strategy_type 校验。"""
        from app.services.recommendation_strategy_service import (
            validate_strategy_config,
        )

        payload = {
            "name": "test",
            "scene": "practice_smart",
            # 没有 strategy_type
        }
        errors = validate_strategy_config(payload)
        assert errors == []

    def test_no_strategy_type_passes(self):
        """不提供 strategy_type 时通过校验。"""
        from app.services.recommendation_strategy_service import (
            validate_strategy_config,
        )

        payload = {
            "name": "test",
            "scene": "practice_smart",
            "weight_vector_similarity": 0.5,
        }
        errors = validate_strategy_config(payload)
        assert errors == []


# ══════════════════════════════════════════════════════════════════
# Test 3: experiment safety valve — evaluate_experiment_safety
# ══════════════════════════════════════════════════════════════════


class TestExperimentSafetyValve:
    def test_auto_pause_on_high_error_rate(self):
        """错误率超阈值时自动暂停实验。"""
        from app.services.recommendation_experiment_service import (
            evaluate_experiment_safety,
        )

        db = _make_mock_db()

        mock_exp = MagicMock()
        mock_exp.id = 1
        mock_exp.status = "running"
        mock_exp.auto_pause_on_error_rate = 0.3
        mock_exp.min_sample_size = 10

        # 查实验
        # 查指标聚合
        mock_metric_row = MagicMock()
        mock_metric_row.__getitem__ = lambda self, i: ("A", 50, 20, 100)[i]
        # variant_key="A", answer_count=50, wrong_count=20, exposure_count=100

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=mock_exp),
            _make_execute_result(all=[mock_metric_row]),
        ]

        result = _run(evaluate_experiment_safety(
            db, experiment_id=1,
            date_from=date(2026, 6, 1), date_to=date(2026, 6, 28),
        ))

        assert result["paused"] is True
        assert mock_exp.status == "paused"

    def test_no_pause_when_sample_too_small(self):
        """样本量不足时不暂停。"""
        from app.services.recommendation_experiment_service import (
            evaluate_experiment_safety,
        )

        db = _make_mock_db()

        mock_exp = MagicMock()
        mock_exp.id = 1
        mock_exp.status = "running"
        mock_exp.auto_pause_on_error_rate = 0.3
        mock_exp.min_sample_size = 100  # 需要 100 样本

        # 只有 10 个回答（< 100）
        mock_metric_row = MagicMock()
        mock_metric_row.__getitem__ = lambda self, i: ("A", 10, 5, 50)[i]

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=mock_exp),
            _make_execute_result(all=[mock_metric_row]),
        ]

        result = _run(evaluate_experiment_safety(
            db, experiment_id=1,
            date_from=date(2026, 6, 1), date_to=date(2026, 6, 28),
        ))

        assert result["paused"] is False
        assert mock_exp.status == "running"

    def test_no_pause_when_error_rate_below_threshold(self):
        """错误率低于阈值时不暂停。"""
        from app.services.recommendation_experiment_service import (
            evaluate_experiment_safety,
        )

        db = _make_mock_db()

        mock_exp = MagicMock()
        mock_exp.id = 1
        mock_exp.status = "running"
        mock_exp.auto_pause_on_error_rate = 0.5  # 50% 阈值
        mock_exp.min_sample_size = 10

        # 错误率 10% (< 50%)
        mock_metric_row = MagicMock()
        mock_metric_row.__getitem__ = lambda self, i: ("A", 100, 10, 200)[i]

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=mock_exp),
            _make_execute_result(all=[mock_metric_row]),
        ]

        result = _run(evaluate_experiment_safety(
            db, experiment_id=1,
            date_from=date(2026, 6, 1), date_to=date(2026, 6, 28),
        ))

        assert result["paused"] is False


# ══════════════════════════════════════════════════════════════════
# Test 4: traffic cap — max_traffic_percent
# ══════════════════════════════════════════════════════════════════


class TestTrafficCap:
    def test_traffic_cap_excludes_users(self):
        """max_traffic_percent=0 排除所有用户。"""
        from app.services.recommendation_experiment_service import (
            assign_user_to_variant,
        )

        db = _make_mock_db()

        mock_exp = MagicMock()
        mock_exp.id = 1
        mock_exp.variants = [
            {"key": "A", "strategy": "random", "ratio": 0.5},
            {"key": "B", "strategy": "knowledge_path", "ratio": 0.5},
        ]
        mock_exp.max_traffic_percent = 0.0  # 0% 流量

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=None),  # 无已有分配
            _make_execute_result(scalar_one_or_none=mock_exp),  # 实验信息
        ]

        result = _run(assign_user_to_variant(db, user_id=42, experiment_id=1))

        assert result.get("excluded_by_traffic_limit") is True
        assert result["variant_key"] is None
        assert result["strategy"] is None

    def test_traffic_cap_100_percent_includes_all(self):
        """max_traffic_percent=100 不排除任何用户。"""
        from app.services.recommendation_experiment_service import (
            assign_user_to_variant,
        )

        db = _make_mock_db()

        mock_exp = MagicMock()
        mock_exp.id = 1
        mock_exp.variants = [
            {"key": "A", "strategy": "random", "ratio": 0.5},
            {"key": "B", "strategy": "knowledge_path", "ratio": 0.5},
        ]
        mock_exp.max_traffic_percent = 100.0

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=None),
            _make_execute_result(scalar_one_or_none=mock_exp),
        ]

        result = _run(assign_user_to_variant(db, user_id=42, experiment_id=1))

        assert result.get("excluded_by_traffic_limit") is None
        assert result["variant_key"] is not None
        assert result["strategy"] is not None


# ══════════════════════════════════════════════════════════════════
# Test 5: metrics backfill
# ══════════════════════════════════════════════════════════════════


class TestMetricsBackfill:
    def test_backfill_multi_day_range(self):
        """backfill_metrics 补跑多天指标。"""
        from app.services.recommendation_metrics_service import backfill_metrics

        db = _make_mock_db()

        call_count = 0

        async def mock_aggregate(db, target_date, subject=None):
            nonlocal call_count
            call_count += 1
            return {"aggregated_rows": 1, "target_date": str(target_date)}

        with patch(
            "app.services.recommendation_metrics_service.aggregate_recommendation_metrics_daily",
            side_effect=mock_aggregate,
        ):
            result = _run(backfill_metrics(
                db,
                date_from=date(2026, 6, 25),
                date_to=date(2026, 6, 28),
            ))

        assert len(result["success_dates"]) == 4  # 25, 26, 27, 28
        assert len(result["failed_dates"]) == 0
        assert call_count == 4

    def test_backfill_single_day_failure_does_not_stop_others(self):
        """单天补跑失败不影响其他天。"""
        from app.services.recommendation_metrics_service import backfill_metrics

        db = _make_mock_db()

        async def mock_aggregate(db, target_date, subject=None):
            if target_date == date(2026, 6, 27):
                raise RuntimeError("模拟失败")
            return {"aggregated_rows": 1, "target_date": str(target_date)}

        with patch(
            "app.services.recommendation_metrics_service.aggregate_recommendation_metrics_daily",
            side_effect=mock_aggregate,
        ):
            result = _run(backfill_metrics(
                db,
                date_from=date(2026, 6, 25),
                date_to=date(2026, 6, 28),
            ))

        assert len(result["success_dates"]) == 3
        assert len(result["failed_dates"]) == 1
        assert str(date(2026, 6, 27)) in result["failed_dates"]
        assert len(result["errors"]) == 1


# ══════════════════════════════════════════════════════════════════
# Test 6: health report
# ══════════════════════════════════════════════════════════════════


class TestHealthReport:
    def test_health_report_structure(self):
        """健康报告返回完整结构。"""
        from app.services.recommendation_health_service import (
            build_recommendation_health_report,
        )

        db = _make_mock_db()

        # 构造 fallback_row 和 low_sim_row 的 mock 对象
        fallback_row = MagicMock()
        fallback_row.__getitem__ = lambda self, i: (100, 10)[i]
        low_sim_row = MagicMock()
        low_sim_row.__getitem__ = lambda self, i: (80, 5)[i]

        mock_fallback_result = MagicMock()
        mock_fallback_result.one.return_value = fallback_row

        mock_low_sim_result = MagicMock()
        mock_low_sim_result.one.return_value = low_sim_row

        # 模拟各查询返回值
        db.execute.side_effect = [
            _make_execute_result(scalar=100),         # total_logs
            mock_fallback_result,                     # fallback
            mock_low_sim_result,                      # low_sim
            _make_execute_result(scalar=30),          # experiment_assignment_count
            _make_execute_result(all=[]),             # variant_distribution
            _make_execute_result(scalar=8),           # vector_recall_failure_count
            _make_execute_result(all=[]),             # top_fallback_scenes
            _make_execute_result(all=[]),             # top_error_strategies
        ]

        result = _run(build_recommendation_health_report(
            db, subject="exam408-ds",
        ))

        assert "total_recommendation_logs" in result
        assert "fallback_rate" in result
        assert "low_similarity_rate" in result
        assert "experiment_assignment_count" in result
        assert "experiment_variant_distribution" in result
        assert "vector_recall_failure_count" in result
        assert "top_fallback_scenes" in result
        assert "top_error_strategies" in result
        assert "warnings" in result
        assert isinstance(result["warnings"], list)


# ══════════════════════════════════════════════════════════════════
# Test 7: cache invalidation — 静默降级
# ══════════════════════════════════════════════════════════════════


class TestCacheInvalidation:
    def test_invalidate_strategy_cache_silent_on_error(self):
        """策略缓存失效在 Redis 不可用时不抛异常。"""
        from app.services.recommendation_cache_service import (
            invalidate_strategy_cache,
        )

        with patch("app.services.recommendation_cache_service.cache") as mock_cache:
            mock_cache.delete = AsyncMock(side_effect=RuntimeError("Redis 连接失败"))
            result = _run(invalidate_strategy_cache())

        assert result == 0  # 不抛异常，返回 0

    def test_invalidate_experiment_cache_with_id(self):
        """指定 experiment_id 时清理对应缓存。"""
        from app.services.recommendation_cache_service import (
            invalidate_experiment_cache,
        )

        with patch("app.services.recommendation_cache_service.cache") as mock_cache:
            mock_cache.delete = AsyncMock(return_value=3)
            result = _run(invalidate_experiment_cache(experiment_id=42))

        assert result == 3
        mock_cache.delete.assert_called_once_with("recommendation:experiment:42:*")

    def test_invalidate_knowledge_path_cache(self):
        """知识路径缓存失效调用 3 个 pattern。"""
        from app.services.recommendation_cache_service import (
            invalidate_knowledge_path_cache,
        )

        with patch("app.services.recommendation_cache_service.cache") as mock_cache:
            mock_cache.delete = AsyncMock(return_value=1)
            result = _run(invalidate_knowledge_path_cache(subject="exam408-ds"))

        assert result == 3  # 3 个 pattern 各返回 1
        assert mock_cache.delete.call_count == 3


# ══════════════════════════════════════════════════════════════════
# Test 8: 回归 — random/sequential 模式不受影响
# ══════════════════════════════════════════════════════════════════


class TestPhase45Regression:
    def test_random_mode_still_works(self):
        """random 模式不受 Phase 4.5 影响。"""
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        mock_q = MagicMock()
        mock_q.id = 1

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_q]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        questions = _run(get_practice_questions(
            db, user_id=1, subject="exam408-ds", count=5, mode="random",
        ))
        assert isinstance(questions, list)

    def test_sm2_service_not_modified(self):
        """SM-2 服务文件未被 Phase 4.5 修改。"""
        import os
        sm2_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "app", "services", "sm2_service.py"
        )
        if os.path.exists(sm2_path):
            with open(sm2_path, encoding="utf-8") as f:
                content = f.read()
            assert "recommendation_experiment" not in content
            assert "seed_default" not in content
            assert "health_report" not in content
