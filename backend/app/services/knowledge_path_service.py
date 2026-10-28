"""Phase 3 — 知识路径推荐服务。

基于知识图谱和用户掌握度，构建个性化学习路径并推荐题目。
"""

import logging
import random

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState

logger = logging.getLogger(__name__)


def _normalize_mastery_score(score: float | int | None) -> float:
    """Convert persisted mastery_score (0..100) to a safe 0..1 value."""
    try:
        value = float(50.0 if score is None else score)
    except (TypeError, ValueError):
        value = 50.0
    return max(0.0, min(value, 100.0)) / 100.0


def _mastery_to_target_difficulty(score: float | int | None) -> float:
    """Map mastery_score 0..100 to the Question.difficulty 1..5 scale."""
    return 1.0 + 4.0 * _normalize_mastery_score(score)


def _normalize_edge_weight(weight: float | int | None) -> float:
    """Normalize graph edge weights while preserving the common 0..1 scale."""
    try:
        value = max(0.0, float(weight or 0.0))
    except (TypeError, ValueError):
        return 0.0
    if value <= 1.0:
        return value
    return min(value / 10.0, 1.0)


async def _resolve_subject_id(
    db: AsyncSession, subject: str | int | None
) -> int | None:
    """Resolve an id or exact canonical subject code to ``subject_id``."""
    from app.services.subject_resolution import resolve_subject_id

    return await resolve_subject_id(db, subject)


async def _attach_subject_info(db: AsyncSession, nodes: list[dict]) -> list[dict]:
    """Bulk-load Subject labels for node subject_ids (single query, avoid N+1)."""
    ids = {n.get("subject_id") for n in nodes if n.get("subject_id")}
    if not ids:
        return nodes
    result = await db.execute(select(Subject).where(Subject.id.in_(ids)))
    subject_map = {s.id: s for s in result.scalars().all()}
    for n in nodes:
        subj = subject_map.get(n.get("subject_id"))
        if subj:
            n["subject_code"] = subj.code
            n["subject_name"] = subj.name
    return nodes


async def build_user_knowledge_path(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None,
    start_knowledge_point_id: int | None = None,
    limit: int = 8,
) -> dict:
    """构建用户知识路径。

    逻辑:
    1. 确定起点（传入的 start_kp 或最薄弱点）
    2. 查 prerequisites / next / related 节点
    3. 批量查询掌握度，减少 N+1
    4. 计算 priority 排序
    5. 返回节点列表

    返回: {"start_kp": dict, "nodes": list[dict], "strategy": str}
    """
    from app.services import knowledge_graph_service, mastery_service

    start_kp = await _resolve_start_point(
        db, user_id, subject_id, start_knowledge_point_id, mastery_service
    )
    if not start_kp:
        return {"start_kp": None, "nodes": [], "strategy": "empty"}

    nodes = [_build_node(start_kp, path_role="current", priority=0.0)]
    nodes += await _collect_neighbor_nodes(
        db, knowledge_graph_service, start_kp["knowledge_point_id"]
    )
    await _attach_subject_info(db, nodes + [start_kp])
    await _apply_mastery(db, user_id, nodes, start_kp)
    _compute_priorities(nodes, start_kp)
    return {
        "start_kp": start_kp,
        "nodes": _dedupe_and_limit_nodes(nodes, limit),
        "strategy": "knowledge_path",
    }


async def _resolve_start_point(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None,
    start_knowledge_point_id: int | None,
    mastery_service,
) -> dict | None:
    """Resolve the explicit active start, weakest point, or a random catalogue point."""
    if start_knowledge_point_id:
        explicit = await _load_explicit_start_point(db, start_knowledge_point_id)
        if explicit is not None:
            return explicit

    weak_kps = await mastery_service.get_user_weak_knowledge_points(
        db, user_id, subject_id, limit=1
    )
    if weak_kps:
        return weak_kps[0]
    return await _random_start_point(db, subject_id)


async def _load_explicit_start_point(
    db: AsyncSession, start_knowledge_point_id: int
) -> dict | None:
    result = await db.execute(
        select(KnowledgePoint).where(
            KnowledgePoint.id == start_knowledge_point_id,
            KnowledgePoint.is_active,
        )
    )
    point = result.scalar_one_or_none()
    if point is None:
        return None
    return _start_point_view(point)


async def _random_start_point(db: AsyncSession, subject_id: int | None) -> dict | None:
    # No mastery evidence: random offset avoids ORDER BY random().
    count_result = await db.execute(
        select(func.count(KnowledgePoint.id)).where(
            KnowledgePoint.subject_id == subject_id,
            KnowledgePoint.is_active,
        )
    )
    total = count_result.scalar() or 0
    if total == 0:
        return None

    offset = random.randint(0, total - 1)
    result = await db.execute(
        select(KnowledgePoint)
        .where(
            KnowledgePoint.subject_id == subject_id,
            KnowledgePoint.is_active,
        )
        .offset(offset)
        .limit(1)
    )
    point = result.scalar_one_or_none()
    return None if point is None else _start_point_view(point)


def _start_point_view(point: KnowledgePoint) -> dict:
    return {
        "knowledge_point_id": point.id,
        "name": point.name,
        "subject_id": point.subject_id,
        "mastery_score": None,
        "weakness_level": "unknown",
    }


async def _collect_neighbor_nodes(
    db: AsyncSession, graph_service, start_kp_id: int
) -> list[dict]:
    """Collect prerequisite/next/related nodes while isolating each port failure."""
    nodes: list[dict] = []

    try:
        prereqs = await graph_service.get_prerequisites(db, start_kp_id, max_depth=1)
        for p in prereqs[:3]:
            nodes.append(_build_node(p, path_role="prerequisite", priority=0.0))
    except Exception:
        logger.warning("get_prerequisites failed for kp=%d", start_kp_id, exc_info=True)

    try:
        nexts = await graph_service.get_next_nodes(db, start_kp_id, max_depth=1)
        for n in nexts[:3]:
            # get_next_nodes may fall back to related; the response role must
            # follow relation_type rather than the port that returned it.
            relation_role = "next" if n.get("relation_type") == "next" else "related"
            nodes.append(_build_node(n, path_role=relation_role, priority=0.0))
    except Exception:
        logger.warning("get_next_nodes failed for kp=%d", start_kp_id, exc_info=True)

    try:
        relateds = await graph_service.get_related_nodes(db, start_kp_id, limit=3)
        for r in relateds[:3]:
            nodes.append(_build_node(r, path_role="related", priority=0.0))
    except Exception:
        logger.warning("get_related_nodes failed for kp=%d", start_kp_id, exc_info=True)
    return nodes


async def _apply_mastery(
    db: AsyncSession, user_id: int, nodes: list[dict], start_kp: dict
) -> None:
    """Batch-load mastery and refresh nodes plus an unevaluated start point."""
    all_kp_ids = list(
        {n["knowledge_point_id"] for n in nodes if n.get("knowledge_point_id")}
    )
    mastery_map = (
        await _batch_get_mastery(db, user_id, all_kp_ids) if all_kp_ids else {}
    )
    for node in nodes:
        kp_id = node["knowledge_point_id"]
        if kp_id in mastery_map:
            node["mastery_score"] = mastery_map[kp_id]["mastery_score"]
            node["weakness_level"] = mastery_map[kp_id]["weakness_level"]

    start_kp_id = start_kp["knowledge_point_id"]
    if start_kp.get("mastery_score") is None and start_kp_id in mastery_map:
        start_kp["mastery_score"] = mastery_map[start_kp_id]["mastery_score"]
        start_kp["weakness_level"] = mastery_map[start_kp_id]["weakness_level"]


def _dedupe_and_limit_nodes(nodes: list[dict], limit: int) -> list[dict]:
    """Keep the highest-priority occurrence of each point, then apply the limit."""
    seen_ids = set()
    unique_nodes = []
    for node in sorted(nodes, key=lambda item: -item["priority"]):
        if node["knowledge_point_id"] not in seen_ids:
            seen_ids.add(node["knowledge_point_id"])
            unique_nodes.append(node)
    return unique_nodes[:limit]


async def attach_recommended_questions_to_path(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    nodes: list[dict],
    questions_per_node: int = 3,
    exclude_answered: bool = True,
) -> list[dict]:
    """Attach globally deduplicated question IDs to every knowledge-point node."""
    kp_ids = [n.get("knowledge_point_id") for n in nodes if n.get("knowledge_point_id")]
    if not kp_ids:
        return nodes

    need = questions_per_node * 3
    candidates_by_kp = await _load_path_question_candidates(
        db, user_id, kp_ids, need, exclude_answered
    )
    global_seen_ids: set[int] = set()

    # Shuffle node order so first-enumerated nodes don't get unfair priority.
    shuffled_nodes = list(nodes)
    random.shuffle(shuffled_nodes)
    for node in shuffled_nodes:
        node["recommended_question_ids"] = await _recommend_for_node(
            db,
            user_id,
            subject_code,
            node,
            candidates_by_kp.get(node["knowledge_point_id"], []),
            need,
            questions_per_node,
            exclude_answered,
            global_seen_ids,
        )
    return nodes


async def _load_path_question_candidates(
    db: AsyncSession,
    user_id: int,
    kp_ids: list[int],
    need: int,
    exclude_answered: bool,
) -> dict[int, list[tuple[int, float | None]]]:
    """Batch-load active candidates once, excluding answered questions when requested."""
    conditions = [
        QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids),
        Question.is_active,
    ]
    if exclude_answered:
        answered_sub = (
            select(PracticeRecord.question_id)
            .where(PracticeRecord.user_id == user_id)
            .distinct()
        )
        conditions.append(Question.id.notin_(answered_sub))

    result = await db.execute(
        select(
            QuestionKnowledgePoint.knowledge_point_id,
            Question.id,
            Question.difficulty,
        )
        .join(
            QuestionKnowledgePoint,
            QuestionKnowledgePoint.question_id == Question.id,
        )
        .where(and_(*conditions))
        .limit(need * max(1, len(kp_ids)))
    )
    candidates_by_kp: dict[int, list[tuple[int, float | None]]] = {}
    for row in result.all():
        candidates_by_kp.setdefault(row.knowledge_point_id, []).append(
            (row.id, row.difficulty)
        )
    return candidates_by_kp


async def _recommend_for_node(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    node: dict,
    candidates: list[tuple[int, float | None]],
    need: int,
    questions_per_node: int,
    exclude_answered: bool,
    global_seen_ids: set[int],
) -> list[int]:
    """Select near-target questions, then use vector recall only for the shortfall."""
    recommended: list[int] = []
    target_difficulty = _mastery_to_target_difficulty(node.get("mastery_score"))
    kp_candidates = list(candidates)
    kp_candidates.sort(key=lambda item: abs(float(item[1] or 3) - target_difficulty))

    for q_id, _difficulty in kp_candidates:
        if q_id in global_seen_ids:
            continue
        recommended.append(q_id)
        global_seen_ids.add(q_id)
        if len(recommended) >= need:
            break
    recommended = recommended[:questions_per_node]

    if len(recommended) < questions_per_node:
        try:
            from app.services import vector_retrieval_service

            recalls = await vector_retrieval_service.vector_recall_by_text(
                db=db,
                user_id=user_id,
                subject=subject_code,
                query_text=node.get("name", ""),
                count=questions_per_node - len(recommended),
                exclude_answered=exclude_answered,
            )
            _merge_vector_recalls(
                recalls, questions_per_node, recommended, global_seen_ids
            )
        except Exception:
            logger.warning(
                "vector_recall_by_text 补齐失败 kp=%d",
                node["knowledge_point_id"],
                exc_info=True,
            )
    return recommended


def _merge_vector_recalls(
    recalls, questions_per_node: int, recommended: list[int], global_seen_ids: set[int]
) -> None:
    for rec in recalls or []:
        qid = rec["question_id"]
        if qid not in global_seen_ids:
            recommended.append(qid)
            global_seen_ids.add(qid)
            if len(recommended) >= questions_per_node:
                break


async def get_user_path_recommendations(
    db: AsyncSession,
    user_id: int,
    subject: str | int | None,
    start_knowledge_point_id: int | None = None,
    limit: int = 8,
    questions_per_node: int = 3,
    write_logs: bool = True,
) -> dict:
    """Build the path, attach questions, optionally log candidates, and project a response."""
    subject_id, subject_code, subject_name = await _resolve_subject_labels(db, subject)
    path_result = await build_user_knowledge_path(
        db,
        user_id,
        subject_id,
        start_knowledge_point_id=start_knowledge_point_id,
        limit=limit,
    )
    nodes = path_result.get("nodes", [])
    strategy = path_result.get("strategy", "knowledge_path")
    start_kp = path_result.get("start_kp")

    if not nodes:
        return _empty_path_response(
            user_id, subject_id, subject_code, subject_name, start_kp
        )

    nodes = await attach_recommended_questions_to_path(
        db,
        user_id,
        subject_code,
        nodes,
        questions_per_node=questions_per_node,
    )
    await _write_path_recommendation_logs(
        db, user_id, subject_code, nodes, strategy, write_logs
    )
    return _path_response(
        user_id,
        subject_id,
        subject_code,
        subject_name,
        start_kp,
        strategy,
        nodes,
    )


async def _resolve_subject_labels(
    db: AsyncSession, subject: str | int | None
) -> tuple[int | None, str, str]:
    subject_id = await _resolve_subject_id(db, subject)
    subject_obj = await db.get(Subject, subject_id) if subject_id is not None else None
    return (
        subject_id,
        subject_obj.code if subject_obj else "",
        subject_obj.name if subject_obj else "",
    )


def _empty_path_response(
    user_id: int,
    subject_id: int | None,
    subject_code: str,
    subject_name: str,
    start_kp: dict | None,
) -> dict:
    return {
        "subject_id": subject_id,
        "subject_code": subject_code,
        "subject_name": subject_name,
        "user_id": user_id,
        "start_knowledge_point_id": start_kp["knowledge_point_id"]
        if start_kp
        else None,
        "strategy": "empty",
        "nodes": [],
        "recommended_question_ids": [],
        "fallback_used": True,
    }


async def _write_path_recommendation_logs(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    nodes: list[dict],
    strategy: str,
    write_logs: bool,
) -> None:
    """Write candidate logs best-effort; logging must never change the response."""
    try:
        recs = [
            {
                "question_id": qid,
                "subject": subject_code,
                "recommend_score": node.get("priority"),
                "similarity": None,
                "reason": node.get("reason", ""),
            }
            for node in nodes
            for qid in node.get("recommended_question_ids", [])
        ]
        if recs and write_logs:
            from app.services import recommendation_log_service

            await recommendation_log_service.create_recommendation_logs(
                db=db,
                user_id=user_id,
                recommendations=recs,
                scene="knowledge_path",
                strategy=strategy,
            )
    except Exception:
        logger.warning("knowledge_path 推荐日志写入失败（不影响结果）", exc_info=True)


def _path_response(
    user_id: int,
    subject_id: int | None,
    subject_code: str,
    subject_name: str,
    start_kp: dict | None,
    strategy: str,
    nodes: list[dict],
) -> dict:
    return {
        "subject_id": subject_id,
        "subject_code": subject_code,
        "subject_name": subject_name,
        "user_id": user_id,
        "start_knowledge_point_id": start_kp["knowledge_point_id"]
        if start_kp
        else None,
        "strategy": strategy,
        "nodes": nodes,
        "recommended_question_ids": list(
            dict.fromkeys(
                qid
                for node in nodes
                for qid in node.get("recommended_question_ids", [])
            )
        ),
        "fallback_used": False,
    }


# ── 内部辅助函数 ──


async def _batch_get_mastery(
    db: AsyncSession,
    user_id: int,
    kp_ids: list[int],
) -> dict[int, dict]:
    """批量获取用户对多个知识点的掌握度（替代 N+1 循环调用 _get_mastery_for_kp）。"""
    if not kp_ids:
        return {}
    result = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.knowledge_point_id.in_(kp_ids),
        )
    )
    states = {s.knowledge_point_id: s for s in result.scalars().all()}
    return {
        kp_id: {
            "mastery_score": states[kp_id].mastery_score if kp_id in states else None,
            "weakness_level": states[kp_id].weakness_level
            if kp_id in states
            else "unknown",
        }
        for kp_id in kp_ids
    }


def _build_node(kp_data: dict, path_role: str, priority: float) -> dict:
    """构建一个路径节点。"""
    return {
        "knowledge_point_id": kp_data["knowledge_point_id"],
        "name": kp_data.get("name", ""),
        "subject_id": kp_data.get("subject_id"),
        "subject_code": kp_data.get("subject_code", ""),
        "subject_name": kp_data.get("subject_name", ""),
        "mastery_score": kp_data.get("mastery_score"),
        "weakness_level": kp_data.get("weakness_level", "unknown"),
        "relation_type": kp_data.get("relation_type", path_role),
        "edge_id": kp_data.get("edge_id"),
        "edge_weight": kp_data.get("weight"),
        "edge_confidence": kp_data.get("confidence"),
        "depth": kp_data.get("depth", 0 if path_role == "current" else 1),
        "path_role": path_role,
        "priority": priority,
        "reason": "",
        "recommended_question_ids": [],
    }


def _compute_priorities(nodes: list[dict], start_kp: dict):
    """Compute and assign each node's priority and user-facing reason in place."""
    for node in nodes:
        node["priority"] = _node_priority(node, nodes)
        node["reason"] = _node_reason(node)


def _weak_priority(node: dict, role: str) -> float:
    if role == "current":
        return 0.8
    if node.get("weakness_level") == "weak":
        return 1.0
    if node.get("weakness_level") == "medium":
        return 0.6
    return 0.3


def _prerequisite_priority(role: str, mastery: float) -> float:
    if role != "prerequisite":
        return 0.0
    # A weak prerequisite must be learned before the current point.
    return 0.9 if mastery < 0.6 else 0.3


def _edge_signal(node: dict) -> float:
    edge_weight = _normalize_edge_weight(node.get("edge_weight"))
    if node.get("edge_weight") is None:
        edge_weight = 0.5
    edge_confidence = max(0.0, min(float(node.get("edge_confidence") or 1.0), 1.0))
    return edge_weight * edge_confidence


def _has_weak_prerequisite(nodes: list[dict], kp_id: int) -> bool:
    return any(
        node["path_role"] == "prerequisite"
        and _normalize_mastery_score(node.get("mastery_score")) < 0.6
        for node in nodes
        if node["knowledge_point_id"] != kp_id
    )


def _node_priority(node: dict, nodes: list[dict]) -> float:
    mastery = _normalize_mastery_score(node.get("mastery_score"))
    role = node["path_role"]
    priority = (
        _weak_priority(node, role) * 0.40
        + _prerequisite_priority(role, mastery) * 0.25
        + (1.0 - mastery) * 0.25
        + _edge_signal(node) * 0.10
    )

    if role == "next":
        priority *= 0.7
    elif role == "related":
        priority *= 0.5
    elif role == "current":
        priority *= 1.1
        if _has_weak_prerequisite(nodes, node["knowledge_point_id"]):
            priority *= 0.85
    return round(priority, 4)


def _node_reason(node: dict) -> str:
    role = node["path_role"]
    if role == "current":
        return f"知识路径推荐：你在『{node['name']}』上较薄弱，建议重点练习"
    if role == "prerequisite":
        return f"前置知识：掌握『{node['name']}』有助于理解当前知识点"
    if role == "next":
        return f"下一步：掌握『{node['name']}』是当前的进阶方向"
    if role == "related":
        return f"相关知识：『{node['name']}』与当前知识点相关"
    return ""
