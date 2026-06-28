"""Phase 4 — 推荐 A/B 实验服务。"""
import hashlib
import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.recommendation_experiment import RecommendationExperiment
from app.models.recommendation_experiment_assignment import RecommendationExperimentAssignment
from app.models.recommendation_metrics_daily import RecommendationMetricsDaily

logger = logging.getLogger(__name__)


async def get_active_experiment(
    db: AsyncSession,
    scene: str,
) -> RecommendationExperiment | None:
    """获取当前 running 且在时间范围内的实验（最新创建）。"""
    now = utcnow()
    result = await db.execute(
        select(RecommendationExperiment)
        .where(
            RecommendationExperiment.scene == scene,
            RecommendationExperiment.status == "running",
        )
        .order_by(RecommendationExperiment.created_at.desc())
    )
    experiments = result.scalars().all()

    for exp in experiments:
        # 检查时间范围
        if exp.start_at and now < exp.start_at:
            continue
        if exp.end_at and now > exp.end_at:
            continue
        return exp

    return None


async def assign_user_to_variant(
    db: AsyncSession,
    user_id: int,
    experiment_id: int,
) -> dict:
    """为用户分配实验分组。

    已分配则返回已有分组；未分配则按 variants.ratio 稳定 hash 分配。
    """
    # 查已有分配
    result = await db.execute(
        select(RecommendationExperimentAssignment).where(
            RecommendationExperimentAssignment.experiment_id == experiment_id,
            RecommendationExperimentAssignment.user_id == user_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return {
            "experiment_id": existing.experiment_id,
            "user_id": existing.user_id,
            "variant_key": existing.variant_key,
            "strategy": existing.strategy,
        }

    # 获取实验信息
    exp_result = await db.execute(
        select(RecommendationExperiment).where(
            RecommendationExperiment.id == experiment_id,
        )
    )
    experiment = exp_result.scalar_one_or_none()
    if not experiment or not experiment.variants:
        return {
            "experiment_id": experiment_id,
            "user_id": user_id,
            "variant_key": None,
            "strategy": None,
        }

    variants = experiment.variants
    # 稳定 hash: hash(f"{experiment_id}:{user_id}") % 10000 / 10000
    hash_input = f"{experiment_id}:{user_id}"
    hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16) % 10000 / 10000.0

    # Phase 4.5: 流量上限检查
    raw_max_traffic = getattr(experiment, "max_traffic_percent", 100.0)
    max_traffic = raw_max_traffic if isinstance(raw_max_traffic, (int, float)) else 100.0
    if max_traffic is None:
        max_traffic = 100.0
    if hash_value * 100 > max_traffic:
        return {
            "experiment_id": experiment_id,
            "user_id": user_id,
            "variant_key": None,
            "strategy": None,
            "excluded_by_traffic_limit": True,
        }

    # 按 ratio 累计分配
    cumulative = 0.0
    assigned_variant = variants[-1]  # 默认最后一个
    for v in variants:
        cumulative += v.get("ratio", 0.0)
        if hash_value < cumulative:
            assigned_variant = v
            break

    assignment = RecommendationExperimentAssignment(
        experiment_id=experiment_id,
        user_id=user_id,
        variant_key=assigned_variant["key"],
        strategy=assigned_variant["strategy"],
    )
    db.add(assignment)
    await db.flush()

    return {
        "experiment_id": experiment_id,
        "user_id": user_id,
        "variant_key": assigned_variant["key"],
        "strategy": assigned_variant["strategy"],
    }


async def resolve_strategy_for_user(
    db: AsyncSession,
    user_id: int,
    scene: str,
    default_strategy: str,
) -> dict:
    """解析用户当前应使用的推荐策略。

    返回:
    {
        "experiment_id": int | None,
        "variant_key": str | None,
        "strategy": str,
        "source": "experiment" | "default",
    }
    """
    try:
        experiment = await get_active_experiment(db, scene)
        if not experiment:
            return {
                "experiment_id": None,
                "variant_key": None,
                "strategy": default_strategy,
                "source": "default",
            }

        assignment = await assign_user_to_variant(db, user_id, experiment.id)
        strategy = assignment.get("strategy") or default_strategy

        return {
            "experiment_id": experiment.id,
            "variant_key": assignment.get("variant_key"),
            "strategy": strategy,
            "source": "experiment",
        }
    except Exception:
        logger.warning("resolve_strategy_for_user 失败，使用默认策略", exc_info=True)
        return {
            "experiment_id": None,
            "variant_key": None,
            "strategy": default_strategy,
            "source": "default",
        }


async def evaluate_experiment_safety(
    db: AsyncSession,
    experiment_id: int,
    date_from,
    date_to,
) -> dict:
    """评估实验安全性，错误率过高时自动暂停。

    返回: {"paused": bool, "reason": str | None, "metrics": dict}
    """
    exp_result = await db.execute(
        select(RecommendationExperiment).where(RecommendationExperiment.id == experiment_id)
    )
    experiment = exp_result.scalar_one_or_none()
    if not experiment:
        return {"paused": False, "reason": "实验不存在", "metrics": {}}

    # 查询该实验日期范围内的指标
    result = await db.execute(
        select(
            RecommendationMetricsDaily.variant_key,
            func.sum(RecommendationMetricsDaily.answer_count),
            func.sum(RecommendationMetricsDaily.wrong_count),
            func.sum(RecommendationMetricsDaily.exposure_count),
        ).where(
            RecommendationMetricsDaily.date >= date_from,
            RecommendationMetricsDaily.date <= date_to,
            RecommendationMetricsDaily.variant_key.isnot(None),
        ).group_by(RecommendationMetricsDaily.variant_key)
    )
    rows = result.all()

    total_answers = sum(r[1] or 0 for r in rows)
    total_errors = sum(r[2] or 0 for r in rows)
    total_exposure = sum(r[3] or 0 for r in rows)

    metrics = {
        "total_answers": total_answers,
        "total_errors": total_errors,
        "total_exposure": total_exposure,
        "error_rate": total_errors / total_answers if total_answers > 0 else 0.0,
        "min_sample_size": experiment.min_sample_size,
        "auto_pause_threshold": experiment.auto_pause_on_error_rate,
    }

    # 判断是否需要暂停
    auto_pause_rate = experiment.auto_pause_on_error_rate
    min_sample = experiment.min_sample_size or 100

    if auto_pause_rate is not None and total_answers >= min_sample:
        error_rate = total_errors / total_answers
        if error_rate > auto_pause_rate:
            experiment.status = "paused"
            experiment.ended_at = utcnow()
            await db.flush()
            return {
                "paused": True,
                "reason": f"错误率 {error_rate:.2%} 超过阈值 {auto_pause_rate:.2%}",
                "metrics": metrics,
            }

    return {"paused": False, "reason": None, "metrics": metrics}


async def create_experiment(
    db: AsyncSession,
    payload: dict,
) -> dict:
    """创建实验。"""
    payload = {**payload}  # shallow copy — 避免 pop 修改调用方 dict
    variants = payload.pop("variants", [])
    # 转换为 list[dict]
    variants_data = [v.model_dump() if hasattr(v, "model_dump") else v for v in variants]

    experiment = RecommendationExperiment(
        **payload,
        variants=variants_data,
    )
    db.add(experiment)
    await db.flush()
    await db.refresh(experiment)

    return _experiment_to_dict(experiment)


async def update_experiment_status(
    db: AsyncSession,
    experiment_id: int,
    status: str,
) -> dict | None:
    """更新实验状态。"""
    result = await db.execute(
        select(RecommendationExperiment).where(
            RecommendationExperiment.id == experiment_id,
        )
    )
    experiment = result.scalar_one_or_none()
    if not experiment:
        return None

    experiment.status = status
    await db.flush()
    await db.refresh(experiment)
    return _experiment_to_dict(experiment)


async def list_experiments(
    db: AsyncSession,
    scene: str | None = None,
) -> list[dict]:
    """列出实验。"""
    q = select(RecommendationExperiment)
    if scene:
        q = q.where(RecommendationExperiment.scene == scene)
    q = q.order_by(RecommendationExperiment.created_at.desc())

    result = await db.execute(q)
    experiments = result.scalars().all()
    return [_experiment_to_dict(e) for e in experiments]


def _experiment_to_dict(exp: RecommendationExperiment) -> dict:
    return {
        "id": exp.id,
        "name": exp.name,
        "scene": exp.scene,
        "description": exp.description,
        "status": exp.status,
        "start_at": exp.start_at,
        "end_at": exp.end_at,
        "traffic_ratio": exp.traffic_ratio,
        "variants": exp.variants,
        "max_traffic_percent": getattr(exp, "max_traffic_percent", 100.0),
        "fallback_strategy_name": getattr(exp, "fallback_strategy_name", None),
        "auto_pause_on_error_rate": getattr(exp, "auto_pause_on_error_rate", None),
        "min_sample_size": getattr(exp, "min_sample_size", 100),
        "started_at": getattr(exp, "started_at", None),
        "ended_at": getattr(exp, "ended_at", None),
        "created_at": exp.created_at,
        "updated_at": exp.updated_at,
    }
