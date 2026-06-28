"""Phase 4 — 推荐质量 + 知识图谱质量报告服务。"""
import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.recommendation_log import RecommendationLog

logger = logging.getLogger(__name__)


async def build_recommendation_quality_report(
    db: AsyncSession,
    subject: str | None = None,
) -> dict:
    """生成推荐质量报告。

    检查项:
    - 最近 7 天无推荐日志
    - 推荐题过度集中
    - 推荐重复率
    - fallback 比例过高
    - 平均 similarity 过低
    """
    warnings = []
    cutoff_7d = func.now() - timedelta(days=7)
    cutoff_30d = func.now() - timedelta(days=30)

    # 基础条件
    conditions = [RecommendationLog.shown_at >= cutoff_30d]
    if subject:
        conditions.append(RecommendationLog.subject == subject)

    # 1. 最近 7 天有无推荐日志
    recent_count_result = await db.execute(
        select(func.count(RecommendationLog.id)).where(
            RecommendationLog.shown_at >= cutoff_7d,
            *([] if not subject else [RecommendationLog.subject == subject]),
        )
    )
    recent_count = recent_count_result.scalar() or 0
    if recent_count == 0:
        warnings.append("最近 7 天没有任何推荐日志")

    # 2. 推荐题过度集中（某些 question_id 被推荐次数过高）
    hot_q_result = await db.execute(
        select(
            RecommendationLog.question_id,
            func.count(RecommendationLog.id).label("rec_count"),
        )
        .where(*conditions)
        .group_by(RecommendationLog.question_id)
        .order_by(func.count(RecommendationLog.id).desc())
        .limit(10)
    )
    hot_questions = []
    for row in hot_q_result.all():
        qid, cnt = row
        hot_questions.append({"question_id": qid, "recommend_count": cnt})
        if cnt > 100:
            warnings.append(f"题目 {qid} 被推荐 {cnt} 次，可能过度集中")

    # 3. fallback 比例
    scene_strategy_result = await db.execute(
        select(
            RecommendationLog.scene,
            RecommendationLog.strategy,
            func.count(RecommendationLog.id).label("cnt"),
        )
        .where(*conditions)
        .group_by(RecommendationLog.scene, RecommendationLog.strategy)
    )
    total_logs = 0
    fallback_logs = 0
    scene_counts = {}
    for row in scene_strategy_result.all():
        scene, strategy, cnt = row
        total_logs += cnt
        scene_counts[scene] = scene_counts.get(scene, 0) + cnt
        if "fallback" in strategy or "random" in strategy:
            fallback_logs += cnt

    high_fallback_scenes = []
    if total_logs > 0:
        fallback_ratio = fallback_logs / total_logs
        if fallback_ratio > 0.7:
            warnings.append(f"fallback/random 策略比例 {fallback_ratio:.1%}，过高")
            high_fallback_scenes.append({
                "scene": "all",
                "fallback_ratio": round(fallback_ratio, 4),
            })

    # 4. 平均 similarity
    avg_sim_result = await db.execute(
        select(func.avg(RecommendationLog.similarity)).where(*conditions)
    )
    avg_similarity = avg_sim_result.scalar()
    low_similarity_samples = []
    if avg_similarity is not None and avg_similarity < 0.3:
        warnings.append(f"平均 similarity {avg_similarity:.3f}，偏低")
        # 查询低 similarity 样本
        low_sim_result = await db.execute(
            select(
                RecommendationLog.id,
                RecommendationLog.question_id,
                RecommendationLog.similarity,
                RecommendationLog.strategy,
            ).where(
                *conditions,
                RecommendationLog.similarity.isnot(None),
                RecommendationLog.similarity < 0.3,
            ).order_by(RecommendationLog.similarity.asc()).limit(10)
        )
        for row in low_sim_result.all():
            low_similarity_samples.append({
                "log_id": row[0],
                "question_id": row[1],
                "similarity": round(row[2], 4) if row[2] is not None else None,
                "strategy": row[3],
            })

    # 5. 推荐日志总量
    total_result = await db.execute(
        select(func.count(RecommendationLog.id)).where(*conditions)
    )
    total_count = total_result.scalar() or 0

    summary = {
        "total_logs_30d": total_count,
        "recent_logs_7d": recent_count,
        "hot_question_count": len(hot_questions),
        "fallback_ratio": round(fallback_logs / total_logs, 4) if total_logs > 0 else None,
        "avg_similarity": round(avg_similarity, 4) if avg_similarity is not None else None,
    }

    return {
        "summary": summary,
        "warnings": warnings,
        "hot_questions": hot_questions[:10],
        "high_fallback_scenes": high_fallback_scenes,
        "low_similarity_samples": low_similarity_samples,
    }


async def build_knowledge_quality_report(
    db: AsyncSession,
    subject: str | None = None,
) -> dict:
    """生成知识图谱质量报告。

    检查项:
    - 无题目映射的知识点
    - 孤立知识点（无边）
    - 低 confidence 边比例
    - prerequisite 循环
    - 每个知识点题量分布
    """
    warnings = []

    # 基础条件
    kp_conditions = [KnowledgePoint.is_active == True]  # noqa: E712
    if subject:
        kp_conditions.append(KnowledgePoint.subject == subject)

    # 1. 获取所有知识点
    kp_result = await db.execute(
        select(KnowledgePoint).where(*kp_conditions)
    )
    all_kps = kp_result.scalars().all()
    kp_ids = {kp.id for kp in all_kps}

    if not kp_ids:
        return {
            "summary": {"total_knowledge_points": 0},
            "warnings": ["没有任何活跃知识点"],
            "isolated_knowledge_points": [],
            "low_question_count_points": [],
            "cycles": [],
        }

    # 2. 每个知识点的题目数
    qkp_result = await db.execute(
        select(
            QuestionKnowledgePoint.knowledge_point_id,
            func.count(QuestionKnowledgePoint.question_id).label("q_count"),
        )
        .where(QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids))
        .group_by(QuestionKnowledgePoint.knowledge_point_id)
    )
    kp_question_count = {row[0]: row[1] for row in qkp_result.all()}

    # 无题知识点
    no_question_kps = []
    low_question_kps = []
    for kp in all_kps:
        q_count = kp_question_count.get(kp.id, 0)
        if q_count == 0:
            no_question_kps.append({
                "knowledge_point_id": kp.id,
                "name": kp.name,
                "subject": kp.subject,
            })
        elif q_count < 3:
            low_question_kps.append({
                "knowledge_point_id": kp.id,
                "name": kp.name,
                "subject": kp.subject,
                "question_count": q_count,
            })

    if no_question_kps:
        warnings.append(f"{len(no_question_kps)} 个知识点没有任何题目映射")

    # 3. 孤立知识点（无边）
    edge_result = await db.execute(
        select(
            KnowledgeEdge.source_knowledge_point_id,
            KnowledgeEdge.target_knowledge_point_id,
        ).where(
            KnowledgeEdge.subject == subject if subject else True,
            KnowledgeEdge.is_active == True,  # noqa: E712
        )
    )
    connected_kp_ids = set()
    for row in edge_result.all():
        connected_kp_ids.add(row[0])
        connected_kp_ids.add(row[1])

    isolated_kps = []
    for kp in all_kps:
        if kp.id not in connected_kp_ids:
            isolated_kps.append({
                "knowledge_point_id": kp.id,
                "name": kp.name,
                "subject": kp.subject,
            })

    if isolated_kps:
        warnings.append(f"{len(isolated_kps)} 个知识点没有任何边连接（孤立）")

    # 4. 低 confidence 边
    low_conf_result = await db.execute(
        select(func.count(KnowledgeEdge.id)).where(
            KnowledgeEdge.subject == subject if subject else True,
            KnowledgeEdge.is_active == True,  # noqa: E712
            KnowledgeEdge.confidence < 0.3,
        )
    )
    low_conf_count = low_conf_result.scalar() or 0

    # 5. 总边数
    total_edge_result = await db.execute(
        select(func.count(KnowledgeEdge.id)).where(
            KnowledgeEdge.subject == subject if subject else True,
            KnowledgeEdge.is_active == True,  # noqa: E712
        )
    )
    total_edges = total_edge_result.scalar() or 0

    # 6. prerequisite 循环检测（简化：只检查直接双向边）
    cycles = []
    if total_edges > 0:
        cycle_result = await db.execute(
            select(
                KnowledgeEdge.source_knowledge_point_id,
                KnowledgeEdge.target_knowledge_point_id,
            ).where(
                KnowledgeEdge.subject == subject if subject else True,
                KnowledgeEdge.relation_type == "prerequisite",
                KnowledgeEdge.is_active == True,  # noqa: E712
            )
        )
        prereq_edges = {(row[0], row[1]) for row in cycle_result.all()}
        for (s, t) in prereq_edges:
            if (t, s) in prereq_edges:
                cycles.append([s, t])

    if cycles:
        warnings.append(f"检测到 {len(cycles)} 个 prerequisite 双向循环")

    summary = {
        "total_knowledge_points": len(all_kps),
        "total_edges": total_edges,
        "isolated_count": len(isolated_kps),
        "no_question_count": len(no_question_kps),
        "low_confidence_edge_count": low_conf_count,
        "cycle_count": len(cycles),
    }

    return {
        "summary": summary,
        "warnings": warnings,
        "isolated_knowledge_points": isolated_kps[:50],
        "low_question_count_points": low_question_kps[:50],
        "cycles": cycles[:20],
    }
