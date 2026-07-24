"""Phase 3 — 知识路径推荐服务。

基于知识图谱和用户掌握度，构建个性化学习路径并推荐题目。
"""
import logging

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState

logger = logging.getLogger(__name__)


async def build_user_knowledge_path(
    db: AsyncSession,
    user_id: int,
    subject: str,
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

    # 1. 确定起点
    start_kp = None
    if start_knowledge_point_id:
        kp_result = await db.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.id == start_knowledge_point_id,
                KnowledgePoint.is_active == True,
            )
        )
        start_kp_model = kp_result.scalar_one_or_none()
        if start_kp_model:
            start_kp = {
                "knowledge_point_id": start_kp_model.id,
                "name": start_kp_model.name,
                "subject": start_kp_model.subject,
                "mastery_score": None,
                "weakness_level": "unknown",
            }

    if not start_kp:
        # 取最薄弱知识点
        weak_kps = await mastery_service.get_user_weak_knowledge_points(
            db, user_id, subject, limit=1,
        )
        if weak_kps:
            start_kp = weak_kps[0]
        else:
            # 没有任何掌握度数据，随机选一个知识点（random offset avoids ORDER BY random())
            count_result = await db.execute(
                select(func.count(KnowledgePoint.id))
                .where(
                    KnowledgePoint.subject == subject,
                    KnowledgePoint.is_active == True,
                )
            )
            total = count_result.scalar() or 0
            if total == 0:
                random_kp = None
            else:
                import random
                offset = random.randint(0, total - 1)
                kp_result = await db.execute(
                    select(KnowledgePoint)
                    .where(
                        KnowledgePoint.subject == subject,
                        KnowledgePoint.is_active == True,
                    )
                    .offset(offset)
                    .limit(1)
                )
                random_kp = kp_result.scalar_one_or_none()
            if random_kp:
                start_kp = {
                    "knowledge_point_id": random_kp.id,
                    "name": random_kp.name,
                    "subject": random_kp.subject,
                    "mastery_score": None,
                    "weakness_level": "unknown",
                }

    if not start_kp:
        return {"start_kp": None, "nodes": [], "strategy": "empty"}

    # 2. 查各方向节点（不含掌握度，稍后批量查询）
    nodes = []

    # 当前起点
    nodes.append(_build_node(start_kp, path_role="current", priority=0.0))

    # 前置知识
    try:
        prereqs = await knowledge_graph_service.get_prerequisites(
            db, start_kp["knowledge_point_id"], max_depth=1,
        )
        for p in prereqs[:3]:
            nodes.append(_build_node(
                p, path_role="prerequisite", priority=0.0,
            ))
    except Exception:
        logger.warning("get_prerequisites failed for kp=%d", start_kp["knowledge_point_id"], exc_info=True)

    # 后续节点
    try:
        nexts = await knowledge_graph_service.get_next_nodes(
            db, start_kp["knowledge_point_id"], max_depth=1,
        )
        for n in nexts[:3]:
            nodes.append(_build_node(
                n, path_role="next", priority=0.0,
            ))
    except Exception:
        logger.warning("get_next_nodes failed for kp=%d", start_kp["knowledge_point_id"], exc_info=True)

    # 相关节点
    try:
        relateds = await knowledge_graph_service.get_related_nodes(
            db, start_kp["knowledge_point_id"], limit=3,
        )
        for r in relateds[:3]:
            nodes.append(_build_node(
                r, path_role="related", priority=0.0,
            ))
    except Exception:
        logger.warning("get_related_nodes failed for kp=%d", start_kp["knowledge_point_id"], exc_info=True)

    # 3. 批量查询掌握度（替代每次循环调 N+1 次 _get_mastery_for_kp）
    all_kp_ids = list({n["knowledge_point_id"] for n in nodes if n.get("knowledge_point_id")})
    mastery_map = await _batch_get_mastery(db, user_id, all_kp_ids) if all_kp_ids else {}
    for node in nodes:
        kp_id = node["knowledge_point_id"]
        if kp_id in mastery_map:
            node["mastery_score"] = mastery_map[kp_id]["mastery_score"]
            node["weakness_level"] = mastery_map[kp_id]["weakness_level"]

    # 3b. 起点若尚未填充掌握度（从 weak_kps 来的可能已有），从 mastery_map 刷新
    start_kp_id = start_kp["knowledge_point_id"]
    if start_kp.get("mastery_score") is None and start_kp_id in mastery_map:
        start_kp["mastery_score"] = mastery_map[start_kp_id]["mastery_score"]
        start_kp["weakness_level"] = mastery_map[start_kp_id]["weakness_level"]

    # 4. 计算 priority
    _compute_priorities(nodes, start_kp)

    # 5. 排序：priority DESC，去重
    seen_ids = set()
    unique_nodes = []
    for n in sorted(nodes, key=lambda x: -x["priority"]):
        if n["knowledge_point_id"] not in seen_ids:
            seen_ids.add(n["knowledge_point_id"])
            unique_nodes.append(n)

    unique_nodes = unique_nodes[:limit]

    strategy = "knowledge_path"
    return {"start_kp": start_kp, "nodes": unique_nodes, "strategy": strategy}


async def attach_recommended_questions_to_path(
    db: AsyncSession,
    user_id: int,
    subject: str,
    nodes: list[dict],
    questions_per_node: int = 3,
    exclude_answered: bool = True,
) -> list[dict]:
    """为每个知识点节点推荐题目。

    逻辑:
    - 从 question_knowledge_points 找题
    - 优先未做题
    - 优先 difficulty 接近用户水平
    - 不足时调用 vector_retrieval_service.vector_recall_by_text 补齐
    - 不返回答案
    - 每个节点挂 recommended_question_ids
    - 总题目去重
    """
    global_seen_ids = set()

    # 构建已做题子查询（用于 SQL 端过滤，避免加载全部已做题 ID 到内存）
    answered_sub = (
        select(PracticeRecord.question_id)
        .where(PracticeRecord.user_id == user_id)
        .distinct()
    ) if exclude_answered else None

    for node in nodes:
        kp_id = node["knowledge_point_id"]
        recommended = []

        # 1. 从 question_knowledge_points 找题（random offset avoids ORDER BY random())
        conditions = [
            QuestionKnowledgePoint.knowledge_point_id == kp_id,
            Question.is_active == True,
        ]
        if answered_sub is not None:
            conditions.append(Question.id.notin_(answered_sub))
        if global_seen_ids:
            conditions.append(Question.id.notin_(global_seen_ids))

        need = questions_per_node * 3

        # Count matching questions
        count_result = await db.execute(
            select(func.count(Question.id))
            .join(
                QuestionKnowledgePoint,
                QuestionKnowledgePoint.question_id == Question.id,
            )
            .where(and_(*conditions))
        )
        total = count_result.scalar() or 0

        if total > 0:
            import random
            # Fetch a randomized sample using random offset
            max_offset = max(0, total - need)
            offset = random.randint(0, max_offset)
            q_result = await db.execute(
                select(Question.id, Question.difficulty)
                .join(
                    QuestionKnowledgePoint,
                    QuestionKnowledgePoint.question_id == Question.id,
                )
                .where(and_(*conditions))
                .offset(offset)
                .limit(need)
            )
            candidates = q_result.all()
        else:
            candidates = []

        for q_id, q_diff in candidates:
            recommended.append(q_id)
            global_seen_ids.add(q_id)
            if len(recommended) >= questions_per_node:
                break

        # 2. 不足时向量补齐
        if len(recommended) < questions_per_node:
            try:
                from app.services import vector_retrieval_service

                recalls = await vector_retrieval_service.vector_recall_by_text(
                    db=db,
                    user_id=user_id,
                    subject=subject,
                    query_text=node.get("name", ""),
                    count=questions_per_node - len(recommended),
                    exclude_answered=exclude_answered,
                )
                for rec in (recalls or []):
                    qid = rec["question_id"]
                    if qid not in global_seen_ids:
                        recommended.append(qid)
                        global_seen_ids.add(qid)
                        if len(recommended) >= questions_per_node:
                            break
            except Exception:
                logger.warning("vector_recall_by_text 补齐失败 kp=%d", kp_id, exc_info=True)

        node["recommended_question_ids"] = recommended

    return nodes


async def get_user_path_recommendations(
    db: AsyncSession,
    user_id: int,
    subject: str,
    start_knowledge_point_id: int | None = None,
    limit: int = 8,
    questions_per_node: int = 3,
) -> dict:
    """完整知识路径推荐流程。

    1. build_user_knowledge_path
    2. attach_recommended_questions_to_path
    3. 写 recommendation_logs (scene='knowledge_path')
    4. 返回完整路径和推荐题 ID

    返回 KnowledgePathResponse-like dict。
    """
    path_result = await build_user_knowledge_path(
        db, user_id, subject,
        start_knowledge_point_id=start_knowledge_point_id,
        limit=limit,
    )

    nodes = path_result.get("nodes", [])
    strategy = path_result.get("strategy", "knowledge_path")
    start_kp = path_result.get("start_kp")

    if not nodes:
        return {
            "subject": subject,
            "user_id": user_id,
            "start_knowledge_point_id": start_kp["knowledge_point_id"] if start_kp else None,
            "strategy": "empty",
            "nodes": [],
            "recommended_question_ids": [],
            "fallback_used": True,
        }

    # 挂题
    nodes = await attach_recommended_questions_to_path(
        db, user_id, subject, nodes,
        questions_per_node=questions_per_node,
    )

    # 汇总推荐题 ID
    all_recommended = []
    for n in nodes:
        all_recommended.extend(n.get("recommended_question_ids", []))

    # 写推荐日志（best-effort）
    try:
        from app.services import recommendation_log_service

        recs = []
        for n in nodes:
            for qid in n.get("recommended_question_ids", []):
                recs.append({
                    "question_id": qid,
                    "subject": subject,
                    "recommend_score": n.get("priority"),
                    "similarity": None,
                    "reason": n.get("reason", ""),
                })
        if recs:
            await recommendation_log_service.create_recommendation_logs(
                db=db,
                user_id=user_id,
                recommendations=recs,
                scene="knowledge_path",
                strategy=strategy,
            )
    except Exception:
        logger.warning("knowledge_path 推荐日志写入失败（不影响结果）", exc_info=True)

    return {
        "subject": subject,
        "user_id": user_id,
        "start_knowledge_point_id": start_kp["knowledge_point_id"] if start_kp else None,
        "strategy": strategy,
        "nodes": nodes,
        "recommended_question_ids": list(dict.fromkeys(all_recommended)),  # 去重保序
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
            "weakness_level": states[kp_id].weakness_level if kp_id in states else "unknown",
        }
        for kp_id in kp_ids
    }


async def _get_mastery_for_kp(
    db: AsyncSession,
    user_id: int,
    knowledge_point_id: int,
) -> dict:
    """获取用户对某知识点的掌握度。"""
    result = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.knowledge_point_id == knowledge_point_id,
        )
    )
    state = result.scalar_one_or_none()
    if state:
        return {
            "mastery_score": state.mastery_score,
            "weakness_level": state.weakness_level,
        }
    return {"mastery_score": None, "weakness_level": "unknown"}


def _build_node(kp_data: dict, path_role: str, priority: float) -> dict:
    """构建一个路径节点。"""
    return {
        "knowledge_point_id": kp_data["knowledge_point_id"],
        "name": kp_data.get("name", ""),
        "subject": kp_data.get("subject", ""),
        "mastery_score": kp_data.get("mastery_score"),
        "weakness_level": kp_data.get("weakness_level", "unknown"),
        "path_role": path_role,
        "priority": priority,
        "reason": "",
        "recommended_question_ids": [],
    }


def _compute_priorities(nodes: list[dict], start_kp: dict):
    """计算每个节点的 priority。

    priority =
        weak_point_priority * 0.40
        + prerequisite_priority * 0.25
        + mastery_gap * 0.25
        + edge_weight * 0.10

    规则:
    - 起点 weak_point priority 最高
    - 如果前置知识 mastery_score < 0.6，前置排在起点之前
    - next 排在起点之后
    - related 只作补充
    """
    start_mastery = start_kp.get("mastery_score") or 0.5

    for node in nodes:
        kp_id = node["knowledge_point_id"]
        mastery = node.get("mastery_score") or 0.0
        role = node["path_role"]

        # weak_point_priority: 越薄弱越高
        if role == "current":
            weak_priority = 0.8
        elif node.get("weakness_level") == "weak":
            weak_priority = 1.0
        elif node.get("weakness_level") == "medium":
            weak_priority = 0.6
        else:
            weak_priority = 0.3

        # prerequisite_priority: 前置知识掌握度低时优先级高
        if role == "prerequisite":
            if mastery < 0.6:
                prereq_priority = 0.9  # 前置知识薄弱 → 必须先学
            else:
                prereq_priority = 0.3  # 前置知识掌握好 → 不紧急
        else:
            prereq_priority = 0.0

        # mastery_gap: 掌握度差距越大越优先
        mastery_gap = 1.0 - mastery  # [0, 1]

        # edge_weight: 默认 0.5（无直接边信息时）
        edge_weight = node.get("weight", 0.5) if "weight" in node else 0.5

        # 综合计算
        priority = (
            weak_priority * 0.40
            + prereq_priority * 0.25
            + mastery_gap * 0.25
            + edge_weight * 0.10
        )

        # 角色调整
        if role == "next":
            priority *= 0.7  # next 节点优先级降低
        elif role == "related":
            priority *= 0.5  # related 节点优先级最低
        elif role == "current":
            priority *= 1.1  # 当前薄弱点稍微提升

        # 如果前置知识掌握度低且当前是起点，降低起点优先级让前置排前面
        if role == "current":
            has_weak_prereq = any(
                n["path_role"] == "prerequisite"
                and (n.get("mastery_score") or 0.0) < 0.6
                for n in nodes
                if n["knowledge_point_id"] != kp_id
            )
            if has_weak_prereq:
                priority *= 0.85

        node["priority"] = round(priority, 4)

        # 生成 reason
        if role == "current":
            node["reason"] = f"知识路径推荐：你在『{node['name']}』上较薄弱，建议重点练习"
        elif role == "prerequisite":
            node["reason"] = f"前置知识：掌握『{node['name']}』有助于理解当前知识点"
        elif role == "next":
            node["reason"] = f"下一步：掌握『{node['name']}』是当前的进阶方向"
        elif role == "related":
            node["reason"] = f"相关知识：『{node['name']}』与当前知识点相关"
