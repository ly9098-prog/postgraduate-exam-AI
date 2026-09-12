"""Phase 4 — 推荐效果评估 + 策略调参 + 质量治理 单元测试。"""
import asyncio
import hashlib
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure all ORM models are registered so Subject's string relationships
# (practice_records, answer_behaviors, review_schedules, ...) resolve at
# mapper configuration time (see app/models/admin.py Subject).
from app.models.answer_behavior import AnswerBehavior  # noqa: F401
from app.models.import_batch_job import ImportBatchJob  # noqa: F401
from app.models.knowledge_edge import KnowledgeEdge  # noqa: F401
from app.models.knowledge_point import KnowledgePoint  # noqa: F401
from app.models.pomodoro import PomodoroSession  # noqa: F401
from app.models.practice_record import PracticeRecord  # noqa: F401
from app.models.recommendation_log import RecommendationLog  # noqa: F401
from app.models.recommendation_metrics_daily import (
    RecommendationMetricsDaily,  # noqa: F401
)
from app.models.review_scheduler import ReviewSchedule  # noqa: F401
from app.models.tag import Tag  # noqa: F401
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


# ── Test 1: get_strategy_config 无数据库配置时返回默认配置 ──


class TestGetStrategyConfig:
    def test_returns_default_when_no_db_config(self):
        """get_strategy_config 无数据库配置时返回内置默认配置。"""
        from app.services.recommendation_strategy_service import get_strategy_config

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        result = _run(get_strategy_config(db, scene="practice_smart"))

        assert result["name"] == "default"
        assert result["scene"] == "practice_smart"
        assert result["weight_vector_similarity"] == 0.5
        assert result["weight_knowledge_overlap"] == 0.2
        assert result["is_default"] is True

    def test_returns_db_config_when_exists(self):
        """get_strategy_config 有数据库配置时返回数据库值。"""
        from app.services.recommendation_strategy_service import get_strategy_config

        db = _make_mock_db()
        mock_config = MagicMock()
        mock_config.id = 1
        mock_config.name = "custom_v1"
        mock_config.display_name = "自定义V1"
        mock_config.description = "test"
        mock_config.scene = "practice_smart"
        mock_config.is_active = True
        mock_config.is_default = True
        mock_config.weight_vector_similarity = 0.6
        mock_config.weight_knowledge_overlap = 0.15
        mock_config.weight_difficulty_match = 0.1
        mock_config.weight_mastery_gap = 0.1
        mock_config.weight_path_priority = 0.05
        mock_config.exploration_ratio = 0.2
        mock_config.config_json = None

        db.execute.return_value = _make_execute_result(scalar_one_or_none=mock_config)

        result = _run(get_strategy_config(db, scene="practice_smart"))

        assert result["name"] == "custom_v1"
        assert result["weight_vector_similarity"] == 0.6


# ── Test 2: create_or_update_strategy_config 能创建和更新 ──


class TestCreateOrUpdateStrategyConfig:
    def test_create_new_config(self):
        """create_or_update_strategy_config 能创建新配置。"""
        from app.services.recommendation_strategy_service import (
            create_or_update_strategy_config,
        )

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        payload = {
            "name": "test_config",
            "display_name": "测试配置",
            "scene": "practice_smart",
            "weight_vector_similarity": 0.7,
        }

        _run(create_or_update_strategy_config(db, payload))

        db.add.assert_called_once()
        db.flush.assert_called_once()

    def test_update_existing_config(self):
        """create_or_update_strategy_config 能更新已有配置。"""
        from app.services.recommendation_strategy_service import (
            create_or_update_strategy_config,
        )

        db = _make_mock_db()
        mock_config = MagicMock()
        mock_config.id = 1
        mock_config.name = "test_config"
        mock_config.display_name = "旧名称"
        mock_config.description = None
        mock_config.scene = "practice_smart"
        mock_config.is_active = True
        mock_config.is_default = False
        mock_config.weight_vector_similarity = 0.5
        mock_config.weight_knowledge_overlap = 0.2
        mock_config.weight_difficulty_match = 0.1
        mock_config.weight_mastery_gap = 0.1
        mock_config.weight_path_priority = 0.1
        mock_config.exploration_ratio = 0.1
        mock_config.config_json = None

        db.execute.return_value = _make_execute_result(scalar_one_or_none=mock_config)

        payload = {"name": "test_config", "display_name": "新名称"}
        _run(create_or_update_strategy_config(db, payload))

        assert mock_config.display_name == "新名称"
        db.add.assert_not_called()  # 不应新增


# ── Test 3: apply_strategy_weights 计算结果在 0~1 ──


class TestApplyStrategyWeights:
    def test_weighted_score_in_range(self):
        """apply_strategy_weights 计算结果在 0~1 之间。"""
        from app.services.recommendation_strategy_service import apply_strategy_weights

        config = {
            "weight_vector_similarity": 0.5,
            "weight_knowledge_overlap": 0.2,
            "weight_difficulty_match": 0.1,
            "weight_mastery_gap": 0.1,
            "weight_path_priority": 0.1,
        }
        base_scores = {
            "vector_similarity": 0.8,
            "knowledge_overlap": 1.0,
            "difficulty_match": 0.5,
            "mastery_gap": 0.7,
            "path_priority": 0.9,
        }

        result = apply_strategy_weights(base_scores, config)
        assert 0.0 <= result <= 1.0

    def test_clamp_to_zero(self):
        """apply_strategy_weights 负分 clamp 到 0。"""
        from app.services.recommendation_strategy_service import apply_strategy_weights

        config = {
            "weight_vector_similarity": 0.5,
            "weight_knowledge_overlap": 0.2,
            "weight_difficulty_match": 0.1,
            "weight_mastery_gap": 0.1,
            "weight_path_priority": 0.1,
        }
        base_scores = {
            "vector_similarity": -1.0,
            "knowledge_overlap": -1.0,
        }

        result = apply_strategy_weights(base_scores, config)
        assert result == 0.0

    def test_clamp_to_one(self):
        """apply_strategy_weights 超高分 clamp 到 1。"""
        from app.services.recommendation_strategy_service import apply_strategy_weights

        config = {
            "weight_vector_similarity": 0.5,
            "weight_knowledge_overlap": 0.2,
            "weight_difficulty_match": 0.1,
            "weight_mastery_gap": 0.1,
            "weight_path_priority": 0.1,
        }
        base_scores = {
            "vector_similarity": 2.0,
            "knowledge_overlap": 2.0,
        }

        result = apply_strategy_weights(base_scores, config)
        assert result == 1.0


# ── Test 4: assign_user_to_variant 对同一用户稳定分组 ──


class TestAssignUserToVariant:
    def test_stable_assignment(self):
        """assign_user_to_variant 对同一用户返回稳定分组。"""
        from app.services.recommendation_experiment_service import (
            assign_user_to_variant,
        )

        db = _make_mock_db()

        # 模拟实验
        mock_exp = MagicMock()
        mock_exp.id = 1
        mock_exp.variants = [
            {"key": "A", "strategy": "random", "ratio": 0.25},
            {"key": "B", "strategy": "weakness_vector", "ratio": 0.25},
            {"key": "C", "strategy": "knowledge_path", "ratio": 0.25},
            {"key": "D", "strategy": "similar_vector", "ratio": 0.25},
        ]

        # 第一次查: 无已有分配
        # 第二次查: 获取实验信息
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=None),  # 无已有分配
            _make_execute_result(scalar_one_or_none=mock_exp),  # 实验信息
        ]

        result1 = _run(assign_user_to_variant(db, user_id=42, experiment_id=1))

        # 再次调用（模拟第二次请求，已有分配）
        mock_assignment = MagicMock()
        mock_assignment.experiment_id = 1
        mock_assignment.user_id = 42
        mock_assignment.variant_key = result1["variant_key"]
        mock_assignment.strategy = result1["strategy"]

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=mock_assignment),
        ]

        result2 = _run(assign_user_to_variant(db, user_id=42, experiment_id=1))

        assert result1["variant_key"] == result2["variant_key"]
        assert result1["strategy"] == result2["strategy"]

    def test_hash_deterministic(self):
        """hash(f"{experiment_id}:{user_id}") 结果确定。"""
        hash_input = "1:42"
        h1 = int(hashlib.md5(hash_input.encode()).hexdigest(), 16) % 10000 / 10000.0
        h2 = int(hashlib.md5(hash_input.encode()).hexdigest(), 16) % 10000 / 10000.0
        assert h1 == h2


# ── Test 5: resolve_strategy_for_user 能返回实验策略 ──


class TestResolveStrategyForUser:
    def test_returns_experiment_strategy(self):
        """resolve_strategy_for_user 有活跃实验时返回实验策略。"""
        from app.services.recommendation_experiment_service import (
            resolve_strategy_for_user,
        )

        db = _make_mock_db()

        mock_exp = MagicMock()
        mock_exp.id = 1
        mock_exp.start_at = None
        mock_exp.end_at = None
        mock_exp.variants = [
            {"key": "A", "strategy": "random", "ratio": 0.5},
            {"key": "B", "strategy": "knowledge_path", "ratio": 0.5},
        ]

        mock_assignment = MagicMock()
        mock_assignment.experiment_id = 1
        mock_assignment.user_id = 42
        mock_assignment.variant_key = "B"
        mock_assignment.strategy = "knowledge_path"

        # get_active_experiment: scalars().all() → [mock_exp]
        # assign: 1) 查已有分配 → None, 2) 查实验 → mock_exp
        mock_scalars_result = MagicMock()
        mock_scalars_result.all.return_value = [mock_exp]
        mock_exp_query_result = MagicMock()
        mock_exp_query_result.scalars.return_value = mock_scalars_result

        db.execute.side_effect = [
            mock_exp_query_result,  # get_active_experiment
            _make_execute_result(scalar_one_or_none=None),  # 无已有分配
            _make_execute_result(scalar_one_or_none=mock_exp),  # 获取实验信息
        ]

        result = _run(resolve_strategy_for_user(db, user_id=42, scene="practice_smart",
                                                 default_strategy="weakness_vector"))

        assert result["source"] == "experiment"
        assert result["experiment_id"] == 1
        # 策略应该来自实验分组（不是默认值）
        assert result["strategy"] in ["random", "knowledge_path"]
        assert result["variant_key"] is not None

    def test_returns_default_when_no_experiment(self):
        """resolve_strategy_for_user 无活跃实验时返回默认策略。"""
        from app.services.recommendation_experiment_service import (
            resolve_strategy_for_user,
        )

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        result = _run(resolve_strategy_for_user(db, user_id=42, scene="practice_smart",
                                                 default_strategy="weakness_vector"))

        assert result["source"] == "default"
        assert result["strategy"] == "weakness_vector"
        assert result["experiment_id"] is None


# ── Test 6: recommendation_logs 能写入 experiment_id / variant_key ──


class TestRecommendationLogsWithExperiment:
    def test_create_logs_with_experiment_fields(self):
        """create_recommendation_logs 能写入 experiment_id / variant_key。"""
        from app.services.recommendation_log_service import create_recommendation_logs

        db = _make_mock_db()

        recommendations = [
            {"question_id": 100, "subject_id": 5},
            {"question_id": 101, "subject_id": 5},
        ]

        _run(create_recommendation_logs(
            db=db,
            user_id=1,
            recommendations=recommendations,
            scene="practice_smart",
            strategy="knowledge_path",
            experiment_id=42,
            variant_key="B",
            strategy_config_id=7,
            mastery_before=0.3,
        ))

        assert db.add.call_count == 2
        # 检查第一个 log 的字段
        first_log = db.add.call_args_list[0][0][0]
        assert first_log.experiment_id == 42
        assert first_log.variant_key == "B"
        assert first_log.strategy_config_id == 7
        assert first_log.mastery_before == 0.3

    def test_mark_answered_with_mastery(self):
        """mark_recommendation_answered 能写入 mastery_after / mastery_delta。"""
        from app.services.recommendation_log_service import mark_recommendation_answered

        db = _make_mock_db()
        mock_log = MagicMock()
        mock_log.answered_at = None

        db.execute.return_value = _make_execute_result(scalar_one_or_none=mock_log)

        result = _run(mark_recommendation_answered(
            db=db, user_id=1, question_id=100, is_correct=True,
            mastery_after=0.6, mastery_delta=0.3,
        ))

        assert result is True
        assert mock_log.mastery_after == 0.6
        assert mock_log.mastery_delta == 0.3

    def test_create_logs_commits(self):
        """create_recommendation_logs 必须 commit，否则日志随 get_db 会话关闭回滚而丢失。"""
        from app.services.recommendation_log_service import create_recommendation_logs

        db = _make_mock_db()
        _run(create_recommendation_logs(
            db=db,
            user_id=1,
            recommendations=[{"question_id": 100, "subject_id": 5}],
            scene="practice_smart",
            strategy="weakness_vector",
        ))

        db.commit.assert_called_once()


# ── Test 7: aggregate_recommendation_metrics_daily 能正确聚合 ──


class TestAggregateMetricsDaily:
    def test_aggregate_basic(self):
        """aggregate_recommendation_metrics_daily 能聚合曝光、答题、正确率。"""
        from app.services.recommendation_metrics_service import (
            aggregate_recommendation_metrics_daily,
        )

        db = _make_mock_db()

        # 模拟聚合查询结果
        mock_row = MagicMock()
        mock_row.date = date(2026, 6, 28)
        mock_row.subject_id = 5
        mock_row.scene = "practice_smart"
        mock_row.strategy = "knowledge_path"
        mock_row.variant_key = None
        mock_row.exposure_count = 100
        mock_row.click_count = 50
        mock_row.answer_count = 40
        mock_row.correct_count = 30
        mock_row.wrong_count = 10
        mock_row.avg_recommend_score = 0.75
        mock_row.avg_similarity = 0.6
        mock_row.avg_mastery_before = 0.4
        mock_row.avg_mastery_after = 0.55
        mock_row.avg_mastery_delta = 0.15

        # 第一次 execute: 聚合查询
        # 第二次 execute: 查已有 daily（不存在）
        db.execute.side_effect = [
            _make_execute_result(all=[mock_row]),
            _make_execute_result(scalar_one_or_none=None),
        ]

        with patch(
            "app.services.recommendation_metrics_service.resolve_subject_ids",
            new_callable=AsyncMock, return_value=[5],
        ):
            result = _run(aggregate_recommendation_metrics_daily(
                db, target_date=date(2026, 6, 28), subject_id=5,
            ))

        assert result["aggregated_rows"] == 1
        db.add.assert_called_once()


# ── Test 8: get_recommendation_metrics 优先读取 daily 表 ──


class TestGetRecommendationMetrics:
    def test_reads_daily_table(self):
        """get_recommendation_metrics 从 daily 表读取。"""
        from app.services.recommendation_metrics_service import (
            get_recommendation_metrics,
        )

        db = _make_mock_db()
        mock_daily = MagicMock()
        mock_daily.date = date(2026, 6, 28)
        mock_daily.subject_id = 5
        mock_daily.scene = "practice_smart"
        mock_daily.strategy = "knowledge_path"
        mock_daily.variant_key = None
        mock_daily.exposure_count = 100
        mock_daily.click_count = 50
        mock_daily.answer_count = 40
        mock_daily.correct_count = 30
        mock_daily.wrong_count = 10
        mock_daily.avg_recommend_score = 0.75
        mock_daily.avg_similarity = 0.6
        mock_daily.avg_mastery_before = 0.4
        mock_daily.avg_mastery_after = 0.55
        mock_daily.avg_mastery_delta = 0.15
        mock_daily.completion_rate = 0.4
        mock_daily.accuracy = 0.75
        mock_daily.ctr = 0.5

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_daily]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        result = _run(get_recommendation_metrics(
            db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 28),
        ))

        assert len(result) == 1
        assert result[0]["exposure_count"] == 100


# ── Test 9: compare_experiment_variants 返回各组指标 ──


class TestCompareExperimentVariants:
    def test_compare_variants(self):
        """compare_experiment_variants 返回各分组指标（GROUP BY 单次查询）。"""
        from app.services.recommendation_metrics_service import (
            compare_experiment_variants,
        )

        db = _make_mock_db()

        mock_exp = MagicMock()
        mock_exp.id = 1
        mock_exp.name = "test_exp"

        # 查实验 → scalar_one_or_none
        # 查 variant_keys → all
        # GROUP BY 聚合 → all (一次查询所有 variant)
        mock_group_row_a = MagicMock()
        mock_group_row_a.__getitem__ = lambda self, i: ("A", 100, 40, 30, 0.75, 0.4, 0.1, 0.5)[i]
        mock_group_row_b = MagicMock()
        mock_group_row_b.__getitem__ = lambda self, i: ("B", 120, 50, 40, 0.8, 0.5, 0.15, 0.6)[i]

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=mock_exp),
            _make_execute_result(all=[
                MagicMock(variant_key="A", strategy="random"),
                MagicMock(variant_key="B", strategy="knowledge_path"),
            ]),
            _make_execute_result(all=[mock_group_row_a, mock_group_row_b]),
        ]

        result = _run(compare_experiment_variants(
            db, experiment_id=1,
            date_from=date(2026, 6, 1), date_to=date(2026, 6, 28),
        ))

        assert result["experiment_id"] == 1
        assert len(result["variants"]) == 2
        assert result["variants"][0]["variant_key"] == "A"
        assert result["variants"][1]["variant_key"] == "B"


# ── Test 10: build_recommendation_quality_report 能识别 fallback 比例过高 ──


class TestRecommendationQualityReport:
    def test_returns_correct_structure(self):
        """build_recommendation_quality_report 返回完整结构。"""
        from app.services.recommendation_quality_service import (
            build_recommendation_quality_report,
        )

        db = _make_mock_db()

        # 模拟各查询:
        # 1. recent_count (scalar)
        # 2. hot_q_result (all)
        # 3. scene_strategy_result (all)
        # 4. avg_sim_result (scalar)
        # 5. total_count (scalar)
        mock_hot_row = (100, 50)  # (question_id, rec_count)

        mock_scene_row = ("practice_smart", "weakness_vector", 30)  # (scene, strategy, cnt)

        db.execute.side_effect = [
            _make_execute_result(scalar=10),        # recent_count
            _make_execute_result(all=[mock_hot_row]),  # hot questions
            _make_execute_result(scalars=[SimpleNamespace(id=100, content={"stem": "求极限"})]),  # hot question texts
            _make_execute_result(all=[mock_scene_row]),  # scene/strategy breakdown
            _make_execute_result(scalar=0.65),       # avg_similarity
            _make_execute_result(scalar=30),         # total_count
        ]

        result = _run(build_recommendation_quality_report(db, subject_id=5))

        assert "summary" in result
        assert "warnings" in result
        assert "hot_questions" in result
        assert "high_fallback_scenes" in result
        assert "low_similarity_samples" in result
        assert result["summary"]["total_logs_30d"] == 30
        assert len(result["hot_questions"]) == 1
        assert result["hot_questions"][0]["question_id"] == 100
        assert result["hot_questions"][0]["question_title"] == "求极限"


# ── Test 11: build_knowledge_quality_report 能识别孤立知识点和无题知识点 ──


class TestKnowledgeQualityReport:
    def test_identifies_isolated_and_no_question_kps(self):
        """build_knowledge_quality_report 能识别孤立知识点和无题知识点。"""
        from app.services.recommendation_quality_service import (
            build_knowledge_quality_report,
        )

        db = _make_mock_db()

        mock_kp1 = MagicMock()
        mock_kp1.id = 1
        mock_kp1.name = "链表"
        mock_kp1.subject_id = 5

        mock_kp2 = MagicMock()
        mock_kp2.id = 2
        mock_kp2.name = "孤立知识点"
        mock_kp2.subject_id = 5

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_kp1, mock_kp2]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        db.execute.side_effect = [
            mock_result,  # 所有知识点
            _make_execute_result(scalars=[]),  # 科目标签 (subject labels)
            _make_execute_result(all=[(1, 5)]),  # kp1 有 5 题，kp2 无题
            _make_execute_result(all=[(1, 1)]),  # 边：只有 kp1 连接
            _make_execute_result(scalar=0),  # low_conf_count
            _make_execute_result(scalar=1),  # total_edges
            _make_execute_result(all=[]),  # prerequisite edges (no cycles)
        ]

        result = _run(build_knowledge_quality_report(db, subject_id=5))

        assert result["summary"]["total_knowledge_points"] == 2
        # kp2 无题
        assert len(result["low_question_count_points"]) >= 1 or result["summary"]["no_question_count"] >= 1


# ── Test 12: smart 推荐在实验服务失败时 fallback 原逻辑 ──


class TestSmartFallbackOnExperimentFailure:
    def test_fallback_when_experiment_service_fails(self):
        """smart 推荐在实验服务抛异常时 fallback 到原逻辑。"""
        from app.services.practice_service import get_smart_practice_questions

        db = _make_mock_db()

        # 模拟 mastery_service 返回空（退化为随机）
        mock_mastery = MagicMock()
        mock_mastery.get_user_weak_knowledge_points = AsyncMock(return_value=[])

        mock_q = MagicMock()
        mock_q.id = 1
        mock_q.subject_id = 5

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_q]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        # patch resolve_strategy_for_user 使其抛异常
        with patch(
            "app.services.recommendation_experiment_service.resolve_strategy_for_user",
            side_effect=Exception("实验服务崩溃"),
        ):
            with patch(
                "app.services.mastery_service.get_user_weak_knowledge_points",
                new=mock_mastery.get_user_weak_knowledge_points,
            ):
                # 即使实验服务失败，也不应抛异常
                questions, meta = _run(get_smart_practice_questions(
                    db, user_id=1, subject_code="exam408-ds", count=5,
                    smart_strategy="weakness_vector",
                ))

        # 应该能正常返回（可能为空列表，但不应崩溃）
        assert isinstance(questions, list)
        assert isinstance(meta, dict)


# ── Test 13: random / sequential 原模式不受影响 ──


class TestOriginalModesUnaffected:
    def test_random_mode_works(self):
        """random 模式不受 Phase 4 影响。"""
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
            db, user_id=1, subject_code="exam408-ds", count=5, mode="random",
        ))

        assert isinstance(questions, list)

    def test_sequential_mode_works(self):
        """sequential 模式不受 Phase 4 影响。"""
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
            db, user_id=1, subject_code="exam408-ds", count=5, mode="sequential",
        ))

        assert isinstance(questions, list)


# ── Test 14: ReviewSchedule / SM-2 相关测试不受影响 ──


class TestSM2Unaffected:
    def test_sm2_service_not_modified(self):
        """SM-2 服务文件未被 Phase 4 修改。"""
        import os
        sm2_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "app", "services", "sm2_service.py"
        )
        if os.path.exists(sm2_path):
            with open(sm2_path, encoding="utf-8") as f:
                content = f.read()
            # SM-2 服务不应包含 Phase 4 相关引用
            assert "recommendation_experiment" not in content
            assert "RecommendationStrategyConfig" not in content
