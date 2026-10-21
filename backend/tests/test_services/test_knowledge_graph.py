"""Phase 3 — 知识图谱 + 知识路径推荐 单元测试。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    db.scalar = AsyncMock(return_value=0)
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


def _make_kp(id=1, name="链表", subject_id=5, normalized_name=None, is_active=True):
    kp = MagicMock()
    kp.id = id
    kp.name = name
    kp.subject_id = subject_id
    kp.normalized_name = normalized_name or name
    kp.is_active = is_active
    return kp


def _make_edge(id=1, subject_id=5, source_id=1, target_id=2,
               relation_type="prerequisite", weight=1.0, confidence=1.0,
               source="manual", is_active=True, source_kp=None, target_kp=None):
    edge = MagicMock()
    edge.id = id
    edge.subject_id = subject_id
    edge.source_knowledge_point_id = source_id
    edge.target_knowledge_point_id = target_id
    edge.relation_type = relation_type
    edge.weight = weight
    edge.confidence = confidence
    edge.source = source
    edge.is_active = is_active
    edge.source_kp = source_kp or _make_kp(id=source_id)
    edge.target_kp = target_kp or _make_kp(id=target_id)
    return edge


def _make_question(id=1, subject_id=5, difficulty=3, is_active=True):
    q = MagicMock()
    q.id = id
    q.subject_id = subject_id
    q.difficulty = difficulty
    q.is_active = is_active
    return q


def _run(coro):
    return asyncio.run(coro)


# ── Test: create_knowledge_edge ──


class TestCreateKnowledgeEdge:
    def test_create_prerequisite_edge(self):
        """create_knowledge_edge 能创建 prerequisite 关系。"""
        from app.services.knowledge_graph_service import create_knowledge_edge

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="链表")
        kp2 = _make_kp(id=2, name="单链表")

        # 第一次查: 两个 KP 都存在
        db.execute.side_effect = [
            _make_execute_result(scalars=[kp1, kp2]),  # 查 KP 存在
            _make_execute_result(scalar_one_or_none=None),  # 查已有边 → 不存在
        ]
        # flush + refresh 后返回新边
        _make_edge(id=10, source_id=1, target_id=2, relation_type="prerequisite")
        db.refresh.side_effect = lambda e: None  # refresh 不报错

        result = _run(create_knowledge_edge(db, 5, 1, 2, "prerequisite"))
        assert result["created"] is True
        assert result["updated"] is False
        db.add.assert_called_once()

    def test_create_parent_edge(self):
        """create_knowledge_edge 能创建 parent 关系。"""
        from app.services.knowledge_graph_service import create_knowledge_edge

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="栈")
        kp2 = _make_kp(id=2, name="顺序栈")

        db.execute.side_effect = [
            _make_execute_result(scalars=[kp1, kp2]),
            _make_execute_result(scalar_one_or_none=None),
        ]

        result = _run(create_knowledge_edge(db, 5, 1, 2, "parent",
                                            weight=0.5, confidence=0.3, source="inferred"))
        assert result["created"] is True

    def test_create_related_edge(self):
        """create_knowledge_edge 能创建 related 关系。"""
        from app.services.knowledge_graph_service import create_knowledge_edge

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="图")
        kp2 = _make_kp(id=2, name="树")

        db.execute.side_effect = [
            _make_execute_result(scalars=[kp1, kp2]),
            _make_execute_result(scalar_one_or_none=None),
        ]

        result = _run(create_knowledge_edge(db, 5, 1, 2, "related"))
        assert result["created"] is True

    def test_create_next_edge(self):
        """create_knowledge_edge 能创建 next 关系。"""
        from app.services.knowledge_graph_service import create_knowledge_edge

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="排序")
        kp2 = _make_kp(id=2, name="快速排序")

        db.execute.side_effect = [
            _make_execute_result(scalars=[kp1, kp2]),
            _make_execute_result(scalar_one_or_none=None),
        ]

        result = _run(create_knowledge_edge(db, 5, 1, 2, "next"))
        assert result["created"] is True

    def test_prevent_self_loop(self):
        """create_knowledge_edge 能防止 source_id == target_id。"""
        from app.services.knowledge_graph_service import create_knowledge_edge

        db = _make_mock_db()

        with pytest.raises(ValueError, match="不能等于"):
            _run(create_knowledge_edge(db, 5, 1, 1, "related"))

    def test_prevent_cross_subject(self):
        """create_knowledge_edge 能防止跨 subject 连接。"""
        from app.services.knowledge_graph_service import create_knowledge_edge

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="链表", subject_id=5)
        kp2 = _make_kp(id=2, name="导数", subject_id=1)

        db.execute.side_effect = [
            _make_execute_result(scalars=[kp1, kp2]),
        ]

        with pytest.raises(ValueError, match="subject_id 不一致"):
            _run(create_knowledge_edge(db, 5, 1, 2, "related"))

    def test_upsert_existing_edge(self):
        """已存在的边更新而非重复创建。"""
        from app.services.knowledge_graph_service import create_knowledge_edge

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="链表")
        kp2 = _make_kp(id=2, name="单链表")
        existing_edge = _make_edge(id=5, source_id=1, target_id=2, relation_type="prerequisite")

        db.execute.side_effect = [
            _make_execute_result(scalars=[kp1, kp2]),
            _make_execute_result(scalar_one_or_none=existing_edge),
        ]

        result = _run(create_knowledge_edge(db, 5, 1, 2, "prerequisite",
                                            weight=0.8, confidence=0.9))
        assert result["created"] is False
        assert result["updated"] is True
        assert existing_edge.weight == 0.8
        assert existing_edge.confidence == 0.9


# ── Test: infer_simple_edges_from_names ──


class TestInferSimpleEdges:
    def test_infer_parent_edges_batch(self):
        """infer_simple_edges_from_names 批量创建 parent 边（前缀关系）。"""
        from app.services.knowledge_graph_service import infer_simple_edges_from_names

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="链表")
        kp2 = _make_kp(id=2, name="单链表")
        kp3 = _make_kp(id=3, name="双链表")

        # 第 1 次 execute: 查所有知识点 (用 .scalars().all())
        kp_result = _make_execute_result(scalars=[kp1, kp2, kp3])
        # 第 2 次 execute: 查已有推断边 (用 .all() 返回 tuples)
        edge_result = MagicMock()
        edge_result.all.return_value = []

        db.execute.side_effect = [kp_result, edge_result]

        result = _run(infer_simple_edges_from_names(db, subject_id=5))

        assert result["created"] == 2  # 链表→单链表, 链表→双链表
        assert result["skipped"] == 0
        # 验证使用 add_all 批量写入
        db.add_all.assert_called_once()
        edges = db.add_all.call_args[0][0]
        assert len(edges) == 2
        # 验证都是 parent 关系
        assert all(e.relation_type == "parent" for e in edges)
        # 验证 source 都是 "链表" (id=1)
        assert all(e.source_knowledge_point_id == 1 for e in edges)

    def test_infer_skips_existing_edges(self):
        """infer_simple_edges_from_names 跳过已存在的边。"""
        from app.services.knowledge_graph_service import infer_simple_edges_from_names

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="链表")
        kp2 = _make_kp(id=2, name="单链表")

        # 第 1 次: 查知识点
        kp_result = _make_execute_result(scalars=[kp1, kp2])
        # 第 2 次: 查已有推断边 → 已存在 (1, 2, "parent")
        edge_result = MagicMock()
        edge_result.all.return_value = [(1, 2, "parent")]

        db.execute.side_effect = [kp_result, edge_result]

        result = _run(infer_simple_edges_from_names(db, subject_id=5))

        assert result["created"] == 0
        assert result["skipped"] == 1
        db.add_all.assert_not_called()

    def test_infer_related_edges_for_overlapping_names(self):
        """infer_simple_edges_from_names 为名称重叠但非前缀的关系创建 related 边。"""
        from app.services.knowledge_graph_service import infer_simple_edges_from_names

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="二叉树")
        kp2 = _make_kp(id=2, name="平衡二叉树")
        kp3 = _make_kp(id=3, name="树")

        kp_result = _make_execute_result(scalars=[kp1, kp2, kp3])
        edge_result = MagicMock()
        edge_result.all.return_value = []

        db.execute.side_effect = [kp_result, edge_result]

        result = _run(infer_simple_edges_from_names(db, subject_id=5))

        # 树→二叉树(parent), 树→平衡二叉树(parent), 二叉树→平衡二叉树(parent)
        assert result["created"] == 3
        db.add_all.assert_called_once()

    def test_infer_no_edges_when_no_match(self):
        """infer_simple_edges_from_names 名称无匹配时不创建边。"""
        from app.services.knowledge_graph_service import infer_simple_edges_from_names

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="图")
        kp2 = _make_kp(id=2, name="栈")

        kp_result = _make_execute_result(scalars=[kp1, kp2])
        edge_result = MagicMock()
        edge_result.all.return_value = []

        db.execute.side_effect = [kp_result, edge_result]

        result = _run(infer_simple_edges_from_names(db, subject_id=5))

        assert result["created"] == 0
        assert result["skipped"] == 0
        assert result["deleted"] == 0  # 默认 force_rebuild=False
        db.add_all.assert_not_called()

    def test_force_rebuild_deletes_inferred_edges(self):
        """force_rebuild=True 时先删除所有 source='inferred' 边再重新推断。"""
        from app.services.knowledge_graph_service import infer_simple_edges_from_names

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="链表")
        kp2 = _make_kp(id=2, name="单链表")

        # 第 1 次 execute: DELETE inferred edges → 删了 3 条
        del_result = MagicMock()
        del_result.rowcount = 3
        # 第 2 次 execute: 查知识点
        kp_result = _make_execute_result(scalars=[kp1, kp2])
        # 第 3 次 execute: 查已有推断边 → 空（已被删除）
        edge_result = MagicMock()
        edge_result.all.return_value = []

        db.execute.side_effect = [del_result, kp_result, edge_result]

        result = _run(infer_simple_edges_from_names(
            db, subject_id=5, force_rebuild=True,
        ))

        assert result["deleted"] == 3
        assert result["created"] == 1  # 链表→单链表
        # 验证第 1 次 execute 被调用（DELETE 操作）
        assert db.execute.call_count == 3
        # 验证 flush 被调用（DELETE 后 flush + 批量 INSERT 后 flush）
        assert db.flush.call_count >= 1

    def test_force_rebuild_false_does_not_delete(self):
        """force_rebuild=False（默认）时不执行 DELETE。"""
        from app.services.knowledge_graph_service import infer_simple_edges_from_names

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="链表")
        kp2 = _make_kp(id=2, name="单链表")

        kp_result = _make_execute_result(scalars=[kp1, kp2])
        edge_result = MagicMock()
        edge_result.all.return_value = []

        db.execute.side_effect = [kp_result, edge_result]

        result = _run(infer_simple_edges_from_names(
            db, subject_id=5, force_rebuild=False,
        ))

        assert result["deleted"] == 0
        # 只有 2 次 execute：查知识点 + 查已有边，没有 DELETE
        assert db.execute.call_count == 2

    def test_force_rebuild_preserves_manual_edges(self):
        """force_rebuild=True 只删 source='inferred'，manual/imported/ai 边不受影响。

        验证 DELETE WHERE 条件包含 source='inferred'。
        """
        from app.services.knowledge_graph_service import infer_simple_edges_from_names

        db = _make_mock_db()
        kp1 = _make_kp(id=1, name="图")
        kp2 = _make_kp(id=2, name="栈")

        del_result = MagicMock()
        del_result.rowcount = 5
        kp_result = _make_execute_result(scalars=[kp1, kp2])
        edge_result = MagicMock()
        edge_result.all.return_value = []

        db.execute.side_effect = [del_result, kp_result, edge_result]

        _run(infer_simple_edges_from_names(
            db, subject_id=5, force_rebuild=True,
        ))

        # 验证第 1 次 execute 调用包含 DELETE 语句
        first_call = db.execute.call_args_list[0]
        stmt = first_call[0][0]
        # 语句应是 delete(KnowledgeEdge) 类型
        assert "DELETE" in str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        # 语句 WHERE 条件应包含 source='inferred'
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "inferred" in compiled


# ── Test: get_prerequisites ──


class TestGetPrerequisites:
    def test_one_layer_prerequisites(self):
        """get_prerequisites 能返回一层前置知识。"""
        from app.services.knowledge_graph_service import get_prerequisites

        db = _make_mock_db()
        kp_prereq = _make_kp(id=10, name="指针基础")
        edge = _make_edge(source_id=10, target_id=20, relation_type="prerequisite",
                          source_kp=kp_prereq)

        db.execute.return_value = _make_execute_result(scalars=[edge])

        result = _run(get_prerequisites(db, knowledge_point_id=20, max_depth=1))
        assert len(result) >= 1
        assert result[0]["knowledge_point_id"] == 10
        assert result[0]["depth"] == 1

    def test_two_layer_prerequisites(self):
        """get_prerequisites 能返回两层前置知识。"""
        from app.services.knowledge_graph_service import get_prerequisites

        db = _make_mock_db()
        kp_l1 = _make_kp(id=10, name="指针")
        kp_l2 = _make_kp(id=11, name="内存")
        edge_l1 = _make_edge(id=1, source_id=10, target_id=20, relation_type="prerequisite",
                              source_kp=kp_l1)
        edge_l2 = _make_edge(id=2, source_id=11, target_id=10, relation_type="prerequisite",
                              source_kp=kp_l2)

        # 第一次查 target=20 → 返回 edge_l1
        # 第二次查 target=10 → 返回 edge_l2
        db.execute.side_effect = [
            _make_execute_result(scalars=[edge_l1]),
            _make_execute_result(scalars=[edge_l2]),
        ]

        result = _run(get_prerequisites(db, knowledge_point_id=20, max_depth=2))
        assert len(result) == 2
        depths = {r["knowledge_point_id"]: r["depth"] for r in result}
        assert depths[10] == 1
        assert depths[11] == 2

    def test_prevent_cycle(self):
        """get_prerequisites 能防止循环。"""
        from app.services.knowledge_graph_service import get_prerequisites

        db = _make_mock_db()
        # A → B → A 循环
        kp_a = _make_kp(id=1, name="A")
        kp_b = _make_kp(id=2, name="B")
        edge_ab = _make_edge(source_id=2, target_id=1, relation_type="prerequisite",
                              source_kp=kp_b)
        edge_ba = _make_edge(source_id=1, target_id=2, relation_type="prerequisite",
                              source_kp=kp_a)

        # 查 target=1 → 返回 B (id=2)
        # 查 target=2 → 返回 A (id=1)，但 A 已在 visited 中
        db.execute.side_effect = [
            _make_execute_result(scalars=[edge_ab]),
            _make_execute_result(scalars=[edge_ba]),
        ]

        result = _run(get_prerequisites(db, knowledge_point_id=1, max_depth=2))
        # A 已在 visited 中（起始节点），所以不会重复
        kp_ids = [r["knowledge_point_id"] for r in result]
        assert 1 not in kp_ids  # 起始节点不应出现在结果中


# ── Test: build_user_knowledge_path ──


class TestBuildUserKnowledgePath:
    def test_build_path_with_weak_point(self):
        """build_user_knowledge_path 在有薄弱点时能生成路径。"""
        import sys

        import app.services
        from app.services.knowledge_path_service import build_user_knowledge_path

        db = _make_mock_db()

        _make_kp(id=20, name="链表")

        mock_mastery = MagicMock()
        mock_mastery.get_user_weak_knowledge_points = AsyncMock(return_value=[{
            "knowledge_point_id": 20,
            "name": "链表",
            "mastery_score": 0.3,
            "accuracy": 0.4,
            "attempt_count": 5,
            "weakness_level": "weak",
        }])

        mock_graph = MagicMock()
        mock_graph.get_prerequisites = AsyncMock(return_value=[])
        mock_graph.get_next_nodes = AsyncMock(return_value=[])
        mock_graph.get_related_nodes = AsyncMock(return_value=[])

        # UserKnowledgeState 查询返回 None
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        with patch.dict(sys.modules, {
            "app.services.mastery_service": mock_mastery,
            "app.services.knowledge_graph_service": mock_graph,
        }), patch.object(app.services, "mastery_service", mock_mastery, create=True), \
             patch.object(app.services, "knowledge_graph_service", mock_graph, create=True):
            result = _run(build_user_knowledge_path(db, user_id=1, subject_id=5))

            assert result["strategy"] == "knowledge_path"
            assert result["start_kp"] is not None
            assert result["start_kp"]["knowledge_point_id"] == 20
            assert len(result["nodes"]) >= 1  # 至少有 current 节点

    def test_prerequisite_low_mastery_ranks_first(self):
        """前置知识掌握度低时，前置节点排在当前薄弱点之前。"""
        # 此测试验证 priority 计算逻辑
        # 由于 mock 复杂，简化为直接测试 _compute_priorities 函数
        from app.services.knowledge_path_service import _compute_priorities

        nodes = [
            {
                "knowledge_point_id": 20,
                "name": "链表",
                "subject": "exam408-ds",
                "mastery_score": 0.4,
                "weakness_level": "weak",
                "path_role": "current",
                "priority": 0.0,
                "reason": "",
                "recommended_question_ids": [],
            },
            {
                "knowledge_point_id": 10,
                "name": "指针基础",
                "subject": "exam408-ds",
                "mastery_score": 0.3,  # 低掌握度
                "weakness_level": "weak",
                "path_role": "prerequisite",
                "priority": 0.0,
                "reason": "",
                "recommended_question_ids": [],
            },
        ]

        start_kp = {
            "knowledge_point_id": 20,
            "name": "链表",
            "mastery_score": 0.4,
        }

        _compute_priorities(nodes, start_kp)

        prereq_node = next(n for n in nodes if n["path_role"] == "prerequisite")
        current_node = next(n for n in nodes if n["path_role"] == "current")

        # 前置知识掌握度低(0.3 < 0.6) → 前置节点 priority 应高于 current
        assert prereq_node["priority"] > current_node["priority"], \
            f"前置 priority={prereq_node['priority']} 应 > current priority={current_node['priority']}"


# ── Test: attach_recommended_questions_to_path ──


class TestAttachRecommendedQuestions:
    def test_attach_questions_to_nodes(self):
        """attach_recommended_questions_to_path 能给每个节点挂题。"""
        from app.services.knowledge_path_service import (
            attach_recommended_questions_to_path,
        )

        db = _make_mock_db()

        nodes = [
            {
                "knowledge_point_id": 20,
                "name": "链表",
                "subject": "exam408-ds",
                "mastery_score": 0.3,
                "weakness_level": "weak",
                "path_role": "current",
                "priority": 0.8,
                "reason": "",
                "recommended_question_ids": [],
            },
        ]

        _make_question(id=100)
        _make_question(id=101)

        # 新实现使用 batch SELECT ... WHERE kp_id IN (...) 预取全部候选，内存中去重和排序
        # 返回候选行包含 knowledge_point_id, question_id, difficulty
        class _FakeRow:
            def __init__(self, knowledge_point_id, id, difficulty):
                self.knowledge_point_id = knowledge_point_id
                self.id = id
                self.difficulty = difficulty

        db.execute.return_value = _make_execute_result(all=[
            _FakeRow(20, 100, 3),
            _FakeRow(20, 101, 2),
        ])

        result = _run(attach_recommended_questions_to_path(
            db, user_id=1, subject_code="exam408-ds", nodes=nodes, questions_per_node=2,
        ))

        assert len(result) == 1
        assert len(result[0]["recommended_question_ids"]) == 2
        assert 100 in result[0]["recommended_question_ids"]
        assert 101 in result[0]["recommended_question_ids"]


# ── Test: smart_strategy=path ──


class TestSmartStrategyPath:
    def test_path_strategy_returns_questions(self):
        """smart_strategy=path 能返回题目。"""
        import app.services.knowledge_path_service
        import app.services.recommendation_experiment_service
        import app.services.recommendation_log_service
        from app.services.practice_service import get_smart_practice_questions

        db = _make_mock_db()
        q1 = _make_question(id=100)
        q2 = _make_question(id=101)

        mock_path = MagicMock()
        mock_path.get_user_path_recommendations = AsyncMock(return_value={
            "subject": "exam408-ds",
            "user_id": 1,
            "start_knowledge_point_id": 20,
            "strategy": "knowledge_path",
            "nodes": [{
                "knowledge_point_id": 20,
                "name": "链表",
                "subject": "exam408-ds",
                "path_role": "current",
                "priority": 0.8,
                "reason": "知识路径推荐：你在『链表』上较薄弱",
                "recommended_question_ids": [100, 101],
            }],
            "recommended_question_ids": [100, 101],
            "fallback_used": False,
        })

        # Question 查询
        db.execute.return_value = _make_execute_result(scalars=[q1, q2])

        with patch.object(
            app.services.knowledge_path_service,
            "get_user_path_recommendations",
            mock_path.get_user_path_recommendations,
        ), patch.object(
            app.services.recommendation_experiment_service,
            "resolve_strategy_for_user",
            new=AsyncMock(return_value={"source": "default"}),
        ), patch.object(
            app.services.recommendation_log_service,
            "create_recommendation_logs_isolated",
            new=AsyncMock(return_value=[]),
        ):
            questions, metadata = _run(get_smart_practice_questions(
                db, user_id=1, subject_code="exam408-ds", count=2,
                smart_strategy="path", subject_ids=[5],
            ))

            assert len(questions) == 2
            assert all(m["strategy"] == "knowledge_path" for m in metadata.values())

    def test_knowledge_path_endpoint_keeps_own_logs(self):
        """独立知识路径 API 仍写自身日志，刷题入口才关闭候选日志。"""
        import app.services.knowledge_path_service as path_service
        import app.services.recommendation_log_service as log_service

        db = _make_mock_db()
        db.get = AsyncMock(return_value=MagicMock(code="exam408-ds", name="408"))
        node = {
            "knowledge_point_id": 20,
            "name": "链表",
            "priority": 0.8,
            "reason": "knowledge path",
            "recommended_question_ids": [100],
        }
        log = AsyncMock(return_value=[1])

        with patch.object(
            path_service,
            "build_user_knowledge_path",
            new=AsyncMock(return_value={
                "nodes": [node],
                "strategy": "knowledge_path",
                "start_kp": node,
            }),
        ), patch.object(
            path_service,
            "attach_recommended_questions_to_path",
            new=AsyncMock(side_effect=lambda _db, _uid, _code, nodes, **_kw: nodes),
        ), patch.object(
            log_service,
            "create_recommendation_logs",
            log,
        ):
            result = _run(path_service.get_user_path_recommendations(
                db, user_id=1, subject=5,
            ))

        assert result["recommended_question_ids"] == [100]
        log.assert_awaited_once()
        assert log.await_args.kwargs["recommendations"][0]["question_id"] == 100

    def test_practice_path_disables_endpoint_logging(self):
        """刷题 path 必须把候选日志留给最终下发裁剪后的 smart 收尾。"""
        import app.services.knowledge_path_service as path_service
        import app.services.mastery_service as mastery_service
        import app.services.practice_service as practice_service
        import app.services.recommendation_experiment_service as experiment_service
        import app.services.recommendation_log_service as log_service

        db = _make_mock_db()
        result = {
            "subject_id": 5,
            "subject_code": "exam408-ds",
            "start_knowledge_point_id": 20,
            "strategy": "knowledge_path",
            "nodes": [],
            "recommended_question_ids": [],
            "fallback_used": True,
        }
        path = AsyncMock(return_value=result)

        with patch.object(
            path_service, "get_user_path_recommendations", path,
        ), patch.object(
            mastery_service,
            "get_user_weak_knowledge_points",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            experiment_service,
            "resolve_strategy_for_user",
            new=AsyncMock(return_value={"source": "default"}),
        ), patch.object(
            log_service,
            "create_recommendation_logs_isolated",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            practice_service,
            "_compute_weak_knowledge_points",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            practice_service,
            "get_practice_questions",
            new=AsyncMock(return_value=[]),
        ):
            from app.services.practice_service import get_smart_practice_questions

            questions, metadata = _run(get_smart_practice_questions(
                db, user_id=1, subject_code="exam408-ds", count=1,
                smart_strategy="path", subject_ids=[5],
            ))

        assert path.await_args.kwargs["write_logs"] is False
        assert questions == []
        assert metadata == {}

    def test_path_fallback_to_weakness_vector(self):
        """path 推荐失败时能 fallback 到 weakness_vector。"""
        import app.services.knowledge_path_service
        import app.services.mastery_service
        import app.services.practice_service
        import app.services.recommendation_experiment_service
        import app.services.recommendation_log_service
        from app.services.practice_service import get_smart_practice_questions

        db = _make_mock_db()
        q1 = _make_question(id=200)

        mock_path = MagicMock()
        mock_path.get_user_path_recommendations = AsyncMock(side_effect=Exception("graph error"))

        mock_mastery = MagicMock()
        mock_mastery.get_user_weak_knowledge_points = AsyncMock(return_value=[])

        # _compute_weak_knowledge_points 也返回空 → 退化随机
        # get_practice_questions 返回题目
        db.execute.return_value = _make_execute_result(scalars=[q1])

        with patch.object(
            app.services.knowledge_path_service,
            "get_user_path_recommendations",
            mock_path.get_user_path_recommendations,
        ), patch.object(
            app.services.mastery_service,
            "get_user_weak_knowledge_points",
            mock_mastery.get_user_weak_knowledge_points,
        ), patch.object(
            app.services.recommendation_experiment_service,
            "resolve_strategy_for_user",
            new=AsyncMock(return_value={"source": "default"}),
        ), patch.object(
            app.services.recommendation_log_service,
            "create_recommendation_logs_isolated",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            app.services.practice_service,
            "get_practice_questions",
            new=AsyncMock(return_value=[q1]),
        ):

            questions, metadata = _run(get_smart_practice_questions(
                db, user_id=1, subject_code="exam408-ds", count=1,
                smart_strategy="path", subject_ids=[5],
            ))

            assert [q.id for q in questions] == [200]
            assert metadata[200]["strategy"] == "random_fallback"


# ── Test: random/sequential 不受影响 ──


class TestExistingModesUnaffected:
    @staticmethod
    def _side_effect_once(questions):
        first = _make_execute_result(scalars=questions)
        empty = _make_execute_result(scalars=[])
        called = [False]
        def _side_effect(*a, **kw):
            if not called[0]:
                called[0] = True
                return first
            return empty
        return _side_effect

    def test_random_mode_unchanged(self):
        """random 模式不受影响。"""
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q1 = _make_question(1)
        q2 = _make_question(2)
        db.execute.side_effect = self._side_effect_once([q1, q2])

        with patch("app.services.practice_service.resolve_subject_ids", new_callable=AsyncMock, return_value=[1]):
            result = _run(get_practice_questions(db, user_id=1, subject_code="math2", count=5, mode="random"))
        assert len(result) == 2
        assert result[0].id == 1

    def test_sequential_mode_unchanged(self):
        """sequential 模式不受影响。"""
        import app.services.practice_service
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q1 = _make_question(1)

        with patch("app.services.practice_service.resolve_subject_ids",
                   new_callable=AsyncMock, return_value=[1]), patch.object(
            app.services.practice_service,
            "get_sequential_practice_questions",
            new=AsyncMock(return_value=([q1], {"reserved": 1})),
        ):
            result = _run(get_practice_questions(db, user_id=1, subject_code="math2", count=5, mode="sequential"))
        assert len(result) == 1


# ── Test: ReviewSchedule / SM-2 不受影响 ──


class TestReviewScheduleUnaffected:
    def test_sm2_service_not_modified(self):
        """sm2_service 未被修改。"""
        from app.services.sm2_service import calc_sm2

        result = calc_sm2(quality=3, efactor=2.5, interval=1, repetitions=1)
        assert "efactor" in result
        assert "interval" in result

    def test_review_scheduler_not_modified(self):
        """review_scheduler 模块仍可导入。"""
        from app.services import review_scheduler
        assert hasattr(review_scheduler, "get_today_review")
        assert hasattr(review_scheduler, "submit_review")
