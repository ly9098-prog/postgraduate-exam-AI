"""Phase 4.5 — 推荐系统健康报告服务。"""
import logging

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recommendation_log import RecommendationLog

logger = logging.getLogger(__name__)


async def build_recommendation_health_report(
    db: AsyncSession,
    subject: str | None = None,
    date_from=None,
    date_to=None,
) -> dict:
    """构建推荐系统健康报告。

    基于 recommendation_logs 和 recommendation_metrics_daily 计算。
    """
    from datetime import date, datetime, timedelta

    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=30)

    day_start = datetime.combine(date_from, datetime.min.time())
    day_end = datetime.combine(date_to, datetime.max.time())

    conditions = [
        RecommendationLog.shown_at >= day_start,
        RecommendationLog.shown_at <= day_end,
    ]
    if subject:
        conditions.append(RecommendationLog.subject == subject)

    # 1. 总推荐日志数
    total_result = await db.execute(
        select(func.count(RecommendationLog.id)).where(*conditions)
    )
    total_logs = total_result.scalar() or 0

    # 2. fallback 率
    fallback_result = await db.execute(
        select(
            func.count(RecommendationLog.id).label("total"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            RecommendationLog.strategy.in_(["fallback", "fallback_random", "random"]),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("fallback_count"),
        ).where(*conditions)
    )
    fallback_row = fallback_result.one()
    fallback_total = fallback_row[0] or 0
    fallback_count = fallback_row[1] or 0
    fallback_rate = fallback_count / fallback_total if fallback_total > 0 else 0.0

    # 3. 低相似度率
    low_sim_result = await db.execute(
        select(
            func.count(RecommendationLog.id).label("total_with_sim"),
            func.coalesce(
                func.sum(
                    case(
                        (RecommendationLog.similarity < 0.3, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("low_sim_count"),
        ).where(
            *conditions,
            RecommendationLog.similarity.isnot(None),
        )
    )
    low_sim_row = low_sim_result.one()
    low_sim_total = low_sim_row[0] or 0
    low_sim_count = low_sim_row[1] or 0
    low_similarity_rate = low_sim_count / low_sim_total if low_sim_total > 0 else 0.0

    # 4. 实验分组统计
    exp_result = await db.execute(
        select(
            func.count(RecommendationLog.id),
        ).where(
            *conditions,
            RecommendationLog.experiment_id.isnot(None),
        )
    )
    experiment_assignment_count = exp_result.scalar() or 0

    # 5. 实验变体分布
    variant_result = await db.execute(
        select(
            RecommendationLog.variant_key,
            func.count(RecommendationLog.id),
        ).where(
            *conditions,
            RecommendationLog.variant_key.isnot(None),
        ).group_by(RecommendationLog.variant_key)
    )
    variant_distribution = {row[0]: row[1] for row in variant_result.all()}

    # 6. 向量召回失败数（similarity IS NULL 或 < 0.1）
    vector_fail_result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            (RecommendationLog.similarity.is_(None)) | (RecommendationLog.similarity < 0.1),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            )
        ).where(
            *conditions,
            RecommendationLog.scene.in_(["practice_smart", "similar"]),
        )
    )
    vector_recall_failure_count = vector_fail_result.scalar() or 0

    # 7. Top fallback scenes
    scene_result = await db.execute(
        select(
            RecommendationLog.scene,
            func.count(RecommendationLog.id),
        ).where(
            *conditions,
            RecommendationLog.strategy.in_(["fallback", "fallback_random", "random"]),
        ).group_by(RecommendationLog.scene).order_by(func.count(RecommendationLog.id).desc()).limit(5)
    )
    top_fallback_scenes = [{"scene": row[0], "count": row[1]} for row in scene_result.all()]

    # 8. Top error strategies
    error_result = await db.execute(
        select(
            RecommendationLog.strategy,
            func.count(RecommendationLog.id),
        ).where(
            *conditions,
            RecommendationLog.is_correct == False,  # noqa: E712
        ).group_by(RecommendationLog.strategy).order_by(func.count(RecommendationLog.id).desc()).limit(5)
    )
    top_error_strategies = [{"strategy": row[0], "error_count": row[1]} for row in error_result.all()]

    # 9. 生成 warnings
    warnings = []
    if fallback_rate > 0.7:
        warnings.append(f"Fallback 率过高: {fallback_rate:.1%}")
    if low_similarity_rate > 0.5:
        warnings.append(f"低相似度率过高: {low_similarity_rate:.1%}")
    if total_logs == 0:
        warnings.append("30 天内无推荐日志")
    if vector_recall_failure_count > total_logs * 0.3 and total_logs > 0:
        warnings.append("向量召回失败率超过 30%")

    return {
        "total_recommendation_logs": total_logs,
        "fallback_rate": round(fallback_rate, 4),
        "empty_recommendation_count": 0,  # 无法从日志直接推断
        "low_similarity_rate": round(low_similarity_rate, 4),
        "strategy_resolve_failed_count": fallback_count,
        "experiment_assignment_count": experiment_assignment_count,
        "experiment_variant_distribution": variant_distribution,
        "vector_recall_failure_count": vector_recall_failure_count,
        "knowledge_path_empty_count": 0,  # 需要更复杂的查询
        "top_fallback_scenes": top_fallback_scenes,
        "top_error_strategies": top_error_strategies,
        "warnings": warnings,
    }
