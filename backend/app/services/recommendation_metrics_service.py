"""Phase 4 — 推荐指标聚合与查询服务。"""
import logging
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recommendation_experiment import RecommendationExperiment
from app.models.recommendation_experiment_assignment import RecommendationExperimentAssignment
from app.models.recommendation_log import RecommendationLog
from app.models.recommendation_metrics_daily import RecommendationMetricsDaily

logger = logging.getLogger(__name__)


async def aggregate_recommendation_metrics_daily(
    db: AsyncSession,
    target_date: date | None = None,
    subject: str | None = None,
) -> dict:
    """从 recommendation_logs 聚合指定日期的指标，UPSERT 到 daily 表。

    返回聚合行数。
    """
    if target_date is None:
        target_date = date.today()

    # 构建日期范围（当天 00:00 ~ 次日 00:00）
    from datetime import datetime, timedelta
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    # 聚合查询
    conditions = [
        RecommendationLog.shown_at >= day_start,
        RecommendationLog.shown_at < day_end,
    ]
    if subject:
        conditions.append(RecommendationLog.subject == subject)

    agg_query = (
        select(
            func.date(RecommendationLog.shown_at).label("date"),
            RecommendationLog.subject,
            RecommendationLog.scene,
            RecommendationLog.strategy,
            RecommendationLog.variant_key,
            func.count(RecommendationLog.id).label("exposure_count"),
            func.count(RecommendationLog.clicked_at).label("click_count"),
            func.count(RecommendationLog.answered_at).label("answer_count"),
            func.coalesce(
                func.sum(case((RecommendationLog.is_correct, 1), else_=0)), 0
            ).label("correct_count"),
            func.coalesce(
                func.sum(case((not RecommendationLog.is_correct, 1), else_=0)), 0
            ).label("wrong_count"),
            func.avg(RecommendationLog.recommend_score).label("avg_recommend_score"),
            func.avg(RecommendationLog.similarity).label("avg_similarity"),
            func.avg(RecommendationLog.mastery_before).label("avg_mastery_before"),
            func.avg(RecommendationLog.mastery_after).label("avg_mastery_after"),
            func.avg(RecommendationLog.mastery_delta).label("avg_mastery_delta"),
        )
        .where(*conditions)
        .group_by(
            func.date(RecommendationLog.shown_at),
            RecommendationLog.subject,
            RecommendationLog.scene,
            RecommendationLog.strategy,
            RecommendationLog.variant_key,
        )
    )

    result = await db.execute(agg_query)
    rows = result.all()

    count = 0
    for row in rows:
        exposure = row.exposure_count or 0
        clicks = row.click_count or 0
        answers = row.answer_count or 0
        correct = row.correct_count or 0
        wrong = row.wrong_count or 0

        ctr = clicks / exposure if exposure > 0 else 0.0
        accuracy = correct / answers if answers > 0 else 0.0
        completion_rate = answers / exposure if exposure > 0 else 0.0

        # UPSERT: 先查是否存在
        existing_result = await db.execute(
            select(RecommendationMetricsDaily).where(
                RecommendationMetricsDaily.date == target_date,
                RecommendationMetricsDaily.subject == row.subject,
                RecommendationMetricsDaily.scene == row.scene,
                RecommendationMetricsDaily.strategy == row.strategy,
                RecommendationMetricsDaily.variant_key == row.variant_key,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.exposure_count = exposure
            existing.click_count = clicks
            existing.answer_count = answers
            existing.correct_count = correct
            existing.wrong_count = wrong
            existing.avg_recommend_score = row.avg_recommend_score or 0.0
            existing.avg_similarity = row.avg_similarity or 0.0
            existing.avg_mastery_before = row.avg_mastery_before
            existing.avg_mastery_after = row.avg_mastery_after
            existing.avg_mastery_delta = row.avg_mastery_delta
            existing.completion_rate = completion_rate
            existing.accuracy = accuracy
            existing.ctr = ctr
        else:
            daily = RecommendationMetricsDaily(
                date=target_date,
                subject=row.subject,
                scene=row.scene,
                strategy=row.strategy,
                variant_key=row.variant_key,
                exposure_count=exposure,
                click_count=clicks,
                answer_count=answers,
                correct_count=correct,
                wrong_count=wrong,
                avg_recommend_score=row.avg_recommend_score or 0.0,
                avg_similarity=row.avg_similarity or 0.0,
                avg_mastery_before=row.avg_mastery_before,
                avg_mastery_after=row.avg_mastery_after,
                avg_mastery_delta=row.avg_mastery_delta,
                completion_rate=completion_rate,
                accuracy=accuracy,
                ctr=ctr,
            )
            db.add(daily)

        count += 1

    await db.flush()
    return {"aggregated_rows": count, "target_date": str(target_date), "subject": subject}


async def get_recommendation_metrics(
    db: AsyncSession,
    date_from: date,
    date_to: date,
    subject: str | None = None,
    scene: str | None = None,
    strategy: str | None = None,
) -> list[dict]:
    """查询每日聚合指标（优先读 daily 表）。"""
    conditions = [
        RecommendationMetricsDaily.date >= date_from,
        RecommendationMetricsDaily.date <= date_to,
    ]
    if subject:
        conditions.append(RecommendationMetricsDaily.subject == subject)
    if scene:
        conditions.append(RecommendationMetricsDaily.scene == scene)
    if strategy:
        conditions.append(RecommendationMetricsDaily.strategy == strategy)

    result = await db.execute(
        select(RecommendationMetricsDaily)
        .where(*conditions)
        .order_by(RecommendationMetricsDaily.date, RecommendationMetricsDaily.scene)
    )
    rows = result.scalars().all()

    return [_daily_to_dict(r) for r in rows]


async def compare_experiment_variants(
    db: AsyncSession,
    experiment_id: int,
    date_from: date,
    date_to: date,
) -> dict:
    """对比实验各分组指标。"""
    # 获取实验信息
    exp_result = await db.execute(
        select(RecommendationExperiment).where(
            RecommendationExperiment.id == experiment_id,
        )
    )
    experiment = exp_result.scalar_one_or_none()
    if not experiment:
        return {"experiment_id": experiment_id, "experiment_name": "", "variants": []}

    # 获取该实验的所有分配
    assign_result = await db.execute(
        select(
            RecommendationExperimentAssignment.variant_key,
            RecommendationExperimentAssignment.strategy,
        ).where(
            RecommendationExperimentAssignment.experiment_id == experiment_id,
        ).distinct()
    )
    variant_keys = [row.variant_key for row in assign_result.all()]

    # 一次 GROUP BY 查询所有 variant 的聚合指标（避免 N+1）
    metrics_result = await db.execute(
        select(
            RecommendationMetricsDaily.variant_key,
            func.sum(RecommendationMetricsDaily.exposure_count),
            func.sum(RecommendationMetricsDaily.answer_count),
            func.sum(RecommendationMetricsDaily.correct_count),
            func.avg(RecommendationMetricsDaily.accuracy),
            func.avg(RecommendationMetricsDaily.completion_rate),
            func.avg(RecommendationMetricsDaily.avg_mastery_delta),
            func.avg(RecommendationMetricsDaily.ctr),
        ).where(
            RecommendationMetricsDaily.date >= date_from,
            RecommendationMetricsDaily.date <= date_to,
            RecommendationMetricsDaily.variant_key.in_(variant_keys),
        ).group_by(RecommendationMetricsDaily.variant_key)
    )
    metrics_by_variant = {row[0]: row for row in metrics_result.all()}

    variants_data = []
    for vk in variant_keys:
        row = metrics_by_variant.get(vk)
        if row:
            variants_data.append({
                "variant_key": vk,
                "exposure_count": row[1] or 0,
                "answer_count": row[2] or 0,
                "correct_count": row[3] or 0,
                "accuracy": round(row[4] or 0.0, 4),
                "completion_rate": round(row[5] or 0.0, 4),
                "avg_mastery_delta": round(row[6] or 0.0, 4) if row[6] is not None else None,
                "ctr": round(row[7] or 0.0, 4),
            })
        else:
            variants_data.append({
                "variant_key": vk,
                "exposure_count": 0,
                "answer_count": 0,
                "correct_count": 0,
                "accuracy": 0.0,
                "completion_rate": 0.0,
                "avg_mastery_delta": None,
                "ctr": 0.0,
            })

    return {
        "experiment_id": experiment_id,
        "experiment_name": experiment.name,
        "variants": variants_data,
    }


def _daily_to_dict(m: RecommendationMetricsDaily) -> dict:
    return {
        "date": m.date,
        "subject": m.subject,
        "scene": m.scene,
        "strategy": m.strategy,
        "variant_key": m.variant_key,
        "exposure_count": m.exposure_count,
        "click_count": m.click_count,
        "answer_count": m.answer_count,
        "correct_count": m.correct_count,
        "wrong_count": m.wrong_count,
        "avg_recommend_score": m.avg_recommend_score,
        "avg_similarity": m.avg_similarity,
        "avg_mastery_before": m.avg_mastery_before,
        "avg_mastery_after": m.avg_mastery_after,
        "avg_mastery_delta": m.avg_mastery_delta,
        "completion_rate": m.completion_rate,
        "accuracy": m.accuracy,
        "ctr": m.ctr,
    }

async def backfill_metrics(
    db: AsyncSession,
    date_from: date,
    date_to: date,
    subject: str | None = None,
) -> dict:
    """补跑日期范围内的指标聚合。

    单天失败不影响其他天。
    返回: {"success_dates": [str], "failed_dates": [str], "errors": [str]}
    """
    success_dates: list[str] = []
    failed_dates: list[str] = []
    errors: list[str] = []

    current = date_from
    while current <= date_to:
        try:
            await aggregate_recommendation_metrics_daily(
                db, target_date=current, subject=subject,
            )
            success_dates.append(str(current))
        except Exception as e:
            logger.warning("补跑 %s 失败: %s", current, e, exc_info=True)
            failed_dates.append(str(current))
            errors.append(str(e))
        current += timedelta(days=1)

    return {
        "success_dates": success_dates,
        "failed_dates": failed_dates,
        "errors": errors,
    }
