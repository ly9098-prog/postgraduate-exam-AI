"""Phase 4 — 推荐 A/B 实验服务。"""

import hashlib
import logging
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import shanghai_date_utc_range, utcnow
from app.models.recommendation_experiment import RecommendationExperiment
from app.models.recommendation_experiment_assignment import (
    RecommendationExperimentAssignment,
)
from app.models.recommendation_log import RecommendationLog
from app.services.unique_conflict import (
    is_unique_violation as _is_unique_violation,
)
from app.services.unique_conflict import (
    start_explicit_transaction as _start_explicit_transaction,
)

logger = logging.getLogger(__name__)


def _stable_bucket(experiment_id: int, user_id: int, salt: str) -> float:
    """返回 [0, 1) 的稳定桶值；不同 salt 彼此独立。"""
    raw = f"{salt}:{experiment_id}:{user_id}"
    return int(hashlib.md5(raw.encode()).hexdigest(), 16) % 10000 / 10000.0


async def _load_assignment(
    db: AsyncSession,
    *,
    experiment_id: int,
    user_id: int,
) -> RecommendationExperimentAssignment | None:
    result = await db.execute(
        select(RecommendationExperimentAssignment).where(
            RecommendationExperimentAssignment.experiment_id == experiment_id,
            RecommendationExperimentAssignment.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _claim_assignment(
    db: AsyncSession,
    assignment: RecommendationExperimentAssignment,
) -> RecommendationExperimentAssignment | None:
    """Insert one assignment without poisoning the caller's transaction."""
    await _start_explicit_transaction(db)
    try:
        async with db.begin_nested():
            db.add(assignment)
            await db.flush()
    except IntegrityError as exc:
        if not _is_unique_violation(exc):
            raise
        return None
    return assignment


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
    existing = await _load_assignment(
        db,
        experiment_id=experiment_id,
        user_id=user_id,
    )

    # 获取实验信息。即使已经分过组，也要重新应用当前 traffic cap；管理员
    # 下调流量时才能立即把超出 cap 的历史用户移出实验。
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

    # “是否进入实验”和“进入后分到哪个 variant”必须使用不同的稳定桶。
    # 旧实现复用同一个 hash：当 max_traffic_percent=50 且 A/B=50/50 时，
    # 只有 hash<0.5 的用户能进入实验，而这些用户又全部落入 A，B 永远无流量。
    enrollment_bucket = _stable_bucket(experiment_id, user_id, "traffic")
    variant_bucket = _stable_bucket(experiment_id, user_id, "variant")

    raw_traffic_ratio = getattr(experiment, "traffic_ratio", 1.0)
    traffic_ratio = (
        float(raw_traffic_ratio) if isinstance(raw_traffic_ratio, (int, float)) else 1.0
    )
    traffic_ratio = max(0.0, min(traffic_ratio, 1.0))

    raw_max_traffic = getattr(experiment, "max_traffic_percent", 100.0)
    max_traffic_percent = (
        float(raw_max_traffic) if isinstance(raw_max_traffic, (int, float)) else 100.0
    )
    max_traffic_ratio = max(0.0, min(max_traffic_percent / 100.0, 1.0))
    effective_traffic_ratio = min(traffic_ratio, max_traffic_ratio)

    if enrollment_bucket >= effective_traffic_ratio:
        return {
            "experiment_id": experiment_id,
            "user_id": user_id,
            "variant_key": None,
            "strategy": None,
            "excluded_by_traffic_limit": True,
        }

    if existing:
        return {
            "experiment_id": existing.experiment_id,
            "user_id": existing.user_id,
            "variant_key": existing.variant_key,
            "strategy": existing.strategy,
        }

    # 按 ratio 累计分配。ExperimentCreate 已校验 ratio 总和为 1；这里仍保留
    # 最后一组兜底，以兼容历史脏数据。
    cumulative = 0.0
    assigned_variant = variants[-1]
    for v in variants:
        cumulative += float(v.get("ratio", 0.0) or 0.0)
        if variant_bucket < cumulative:
            assigned_variant = v
            break

    assignment = RecommendationExperimentAssignment(
        experiment_id=experiment_id,
        user_id=user_id,
        variant_key=assigned_variant["key"],
        strategy=assigned_variant["strategy"],
    )
    claimed = await _claim_assignment(db, assignment)
    if claimed is None:
        # A concurrent request may have won uq_rea_experiment_user. Reload the
        # stable winner after the savepoint rollback instead of aborting the
        # caller's outer transaction or silently switching this user to default.
        assignment = await _load_assignment(
            db,
            experiment_id=experiment_id,
            user_id=user_id,
        )
        if assignment is None:
            raise RuntimeError(
                "recommendation assignment disappeared after unique conflict"
            )

    return {
        "experiment_id": experiment_id,
        "user_id": user_id,
        "variant_key": assignment.variant_key,
        "strategy": assignment.strategy,
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
        "source": "experiment" | "default" | "traffic_excluded",
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
        if assignment.get("excluded_by_traffic_limit"):
            # 未进入实验流量的用户应完整走默认路径，日志也不能打上
            # experiment_id，否则安全检查/实验样本量会把非实验用户算进去。
            return {
                "experiment_id": None,
                "variant_key": None,
                "strategy": default_strategy,
                "source": "traffic_excluded",
            }

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
    date_from: date,
    date_to: date,
) -> dict:
    """评估指定实验本身的安全性，错误率过高时自动暂停。

    daily 聚合表没有 experiment_id，不能仅按 variant_key(A/B/...) 过滤，
    否则会把其他实验的 A/B 数据混入当前实验。这里直接聚合原始推荐日志。
    """
    exp_result = await db.execute(
        select(RecommendationExperiment).where(
            RecommendationExperiment.id == experiment_id
        )
    )
    experiment = exp_result.scalar_one_or_none()
    if not experiment:
        return {"paused": False, "reason": "实验不存在", "metrics": {}}

    day_start = shanghai_date_utc_range(date_from)[0]
    day_end = shanghai_date_utc_range(date_to + timedelta(days=1))[0]
    variant_keys = [
        str(variant.get("key", "")).strip()
        for variant in (experiment.variants or [])
        if isinstance(variant, dict) and str(variant.get("key", "")).strip()
    ]

    result = await db.execute(
        select(
            func.count(RecommendationLog.id).label("exposure_count"),
            func.count(RecommendationLog.answered_at).label("answer_count"),
            func.coalesce(
                func.sum(
                    case(
                        (RecommendationLog.is_correct.is_(False), 1),
                        else_=0,
                    )
                ),
                0,
            ).label("wrong_count"),
        ).where(
            RecommendationLog.experiment_id == experiment_id,
            RecommendationLog.shown_at >= day_start,
            RecommendationLog.shown_at < day_end,
            RecommendationLog.variant_key.in_(variant_keys) if variant_keys else False,
        )
    )
    row = result.one()
    total_exposure = int(row.exposure_count or 0)
    total_answers = int(row.answer_count or 0)
    total_errors = int(row.wrong_count or 0)

    metrics = {
        "total_answers": total_answers,
        "total_errors": total_errors,
        "total_exposure": total_exposure,
        "error_rate": total_errors / total_answers if total_answers > 0 else 0.0,
        "min_sample_size": experiment.min_sample_size,
        "auto_pause_threshold": experiment.auto_pause_on_error_rate,
    }

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
    variants_data = [
        v.model_dump() if hasattr(v, "model_dump") else v for v in variants
    ]

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

    now = utcnow()
    if status == "running":
        # 当前解析器每个 scene 只会消费一个 active experiment。若允许多个实验
        # 同时标记 running，较旧实验会“看似运行、实际零流量”。启动新实验时
        # 自动暂停同 scene 的其它 running 实验，使控制台状态与真实流量一致。
        other_result = await db.execute(
            select(RecommendationExperiment).where(
                RecommendationExperiment.scene == experiment.scene,
                RecommendationExperiment.id != experiment.id,
                RecommendationExperiment.status == "running",
            )
        )
        for other in other_result.scalars().all():
            other.status = "paused"
            other.ended_at = now

        experiment.status = "running"
        if experiment.started_at is None:
            experiment.started_at = now
        experiment.ended_at = None
    elif status == "paused":
        experiment.status = "paused"
        experiment.ended_at = now
    elif status == "finished":
        experiment.status = "finished"
        experiment.ended_at = now
    else:
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
