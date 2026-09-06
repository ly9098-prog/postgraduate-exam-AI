"""Phase 4 — 推荐指标聚合与查询服务。"""
import logging
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import shanghai_date_utc_range, shanghai_today
from app.models.recommendation_experiment import RecommendationExperiment
from app.models.recommendation_log import RecommendationLog
from app.models.recommendation_metrics_daily import RecommendationMetricsDaily
from app.services.admin_subject_service import resolve_subject_ids

logger = logging.getLogger(__name__)


async def aggregate_recommendation_metrics_daily(
    db: AsyncSession,
    target_date: date | None = None,
    subject_id: int | None = None,
) -> dict:
    """从 recommendation_logs 聚合指定日期的指标，UPSERT 到 daily 表。

    返回聚合行数。
    """
    if target_date is None:
        target_date = shanghai_today()

    # recommendation_logs 按 naive UTC 存储，这里将北京时间自然日转换为 UTC 半开区间。
    day_start, day_end = shanghai_date_utc_range(target_date)

    # 聚合查询
    conditions = [
        RecommendationLog.shown_at >= day_start,
        RecommendationLog.shown_at < day_end,
    ]
    if subject_id:
        conditions.append(RecommendationLog.subject_id.in_(await resolve_subject_ids(db, subject_id)))

    agg_query = (
        select(
            RecommendationLog.subject_id,
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
                func.sum(case((~RecommendationLog.is_correct, 1), else_=0)), 0
            ).label("wrong_count"),
            func.avg(RecommendationLog.recommend_score).label("avg_recommend_score"),
            func.avg(RecommendationLog.similarity).label("avg_similarity"),
            func.avg(RecommendationLog.mastery_before).label("avg_mastery_before"),
            func.avg(RecommendationLog.mastery_after).label("avg_mastery_after"),
            func.avg(RecommendationLog.mastery_delta).label("avg_mastery_delta"),
        )
        .where(*conditions)
        .group_by(
            RecommendationLog.subject_id,
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
                RecommendationMetricsDaily.subject_id == row.subject_id,
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
                subject_id=row.subject_id,
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
    return {"aggregated_rows": count, "target_date": str(target_date), "subject_id": subject_id}


async def get_recommendation_metrics(
    db: AsyncSession,
    date_from: date,
    date_to: date,
    subject_id: int | None = None,
    scene: str | None = None,
    strategy: str | None = None,
) -> list[dict]:
    """查询每日聚合指标（优先读 daily 表）。"""
    conditions = [
        RecommendationMetricsDaily.date >= date_from,
        RecommendationMetricsDaily.date <= date_to,
    ]
    if subject_id:
        conditions.append(RecommendationMetricsDaily.subject_id.in_(await resolve_subject_ids(db, subject_id)))
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

    daily_rows = [_daily_to_dict(r) for r in rows]
    return await _attach_subject_labels(db, daily_rows)


async def compare_experiment_variants(
    db: AsyncSession,
    experiment_id: int,
    date_from: date,
    date_to: date,
) -> dict:
    """精确对比指定实验各分组指标。

    ``recommendation_metrics_daily`` 没有 experiment_id，variant_key 又通常复用
    A/B/C；如果按 daily 表的 variant_key 聚合，会把其他实验的数据混进来。
    因此实验对比直接从 recommendation_logs 按 experiment_id 聚合。
    """
    exp_result = await db.execute(
        select(RecommendationExperiment).where(RecommendationExperiment.id == experiment_id)
    )
    experiment = exp_result.scalar_one_or_none()
    if not experiment:
        return {"experiment_id": experiment_id, "experiment_name": "", "variants": []}

    # 分组来自实验定义本身，而不是 assignment 表。这样尚未分到用户的分组也会
    # 以 0 指标展示，不会在管理端凭空消失。
    variant_keys: list[str] = []
    for variant in experiment.variants or []:
        key = str(variant.get("key", "")).strip() if isinstance(variant, dict) else ""
        if key and key not in variant_keys:
            variant_keys.append(key)

    if not variant_keys:
        return {
            "experiment_id": experiment_id,
            "experiment_name": experiment.name,
            "variants": [],
        }

    day_start = shanghai_date_utc_range(date_from)[0]
    day_end = shanghai_date_utc_range(date_to + timedelta(days=1))[0]

    metrics_result = await db.execute(
        select(
            RecommendationLog.variant_key,
            func.count(RecommendationLog.id).label("exposure_count"),
            func.count(RecommendationLog.clicked_at).label("click_count"),
            func.count(RecommendationLog.answered_at).label("answer_count"),
            func.coalesce(
                func.sum(case((RecommendationLog.is_correct.is_(True), 1), else_=0)), 0
            ).label("correct_count"),
            func.avg(RecommendationLog.mastery_delta).label("avg_mastery_delta"),
        )
        .where(
            RecommendationLog.experiment_id == experiment_id,
            RecommendationLog.shown_at >= day_start,
            RecommendationLog.shown_at < day_end,
            RecommendationLog.variant_key.in_(variant_keys),
        )
        .group_by(RecommendationLog.variant_key)
    )
    metrics_by_variant = {row.variant_key: row for row in metrics_result.all()}

    variants_data = []
    for variant_key in variant_keys:
        row = metrics_by_variant.get(variant_key)
        exposure = int(row.exposure_count or 0) if row else 0
        clicks = int(row.click_count or 0) if row else 0
        answers = int(row.answer_count or 0) if row else 0
        correct = int(row.correct_count or 0) if row else 0
        avg_mastery_delta = row.avg_mastery_delta if row else None

        variants_data.append({
            "variant_key": variant_key,
            "exposure_count": exposure,
            "answer_count": answers,
            "correct_count": correct,
            "accuracy": round(correct / answers, 4) if answers else 0.0,
            "completion_rate": round(answers / exposure, 4) if exposure else 0.0,
            "avg_mastery_delta": (
                round(float(avg_mastery_delta), 4) if avg_mastery_delta is not None else None
            ),
            "ctr": round(clicks / exposure, 4) if exposure else 0.0,
        })

    return {
        "experiment_id": experiment_id,
        "experiment_name": experiment.name,
        "variants": variants_data,
    }


def _daily_to_dict(m: RecommendationMetricsDaily) -> dict:
    return {
        "date": m.date,
        "subject_id": m.subject_id,
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


async def _attach_subject_labels(db: AsyncSession, rows: list[dict]) -> list[dict]:
    """批量加载 subject_id 对应的 code/name 并挂到每行（单次查询，避免 N+1）。"""
    from app.models.admin import Subject

    ids = {r.get("subject_id") for r in rows if r.get("subject_id") is not None}
    labels: dict[int, tuple[str, str]] = {}
    if ids:
        result = await db.execute(select(Subject).where(Subject.id.in_(ids)))
        for s in result.scalars().all():
            labels[s.id] = (s.code, s.name)
    for r in rows:
        sid = r.get("subject_id")
        if sid in labels:
            r["subject_code"], r["subject_name"] = labels[sid]
    return rows

async def backfill_metrics(
    db: AsyncSession,
    date_from: date,
    date_to: date,
    subject_id: int | None = None,
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
            # Isolate each day in a SAVEPOINT.  PostgreSQL marks the whole
            # transaction aborted after a statement error; without a nested
            # transaction the documented "单天失败不影响其他天" behavior is
            # false and every later day fails as well.
            async with db.begin_nested():
                await aggregate_recommendation_metrics_daily(
                    db, target_date=current, subject_id=subject_id,
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
