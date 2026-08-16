"""Phase 4 — 推荐策略 / 实验 / 指标 / 质量报告 Admin API。"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.recommendation import (
    ExperimentCreate,
    ExperimentResponseExtended,
    ExperimentStatusUpdate,
    HealthReportResponse,
    KnowledgeQualityReportResponse,
    MetricsAggregateRequest,
    MetricsAggregateResponse,
    MetricsBackfillRequest,
    MetricsBackfillResponse,
    MetricsDailyResponse,
    RecommendationQualityReportResponse,
    SafetyCheckResponse,
    SeedStrategiesResponse,
    StrategyConfigCreate,
    StrategyConfigResponse,
    VariantComparisonResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/v1/recommendation", tags=["admin-recommendation"])


# ── 策略配置 ──


@router.get("/strategies", response_model=list[StrategyConfigResponse])
async def list_strategies(
    scene: str | None = Query(None),
    _=Depends(require_permissions("recommendation:read")),
    db: AsyncSession = Depends(get_db),
):
    """查询策略配置列表。"""
    from app.services import recommendation_strategy_service

    configs = await recommendation_strategy_service.list_strategy_configs(db, scene=scene)
    return [StrategyConfigResponse(**c) for c in configs]


@router.post("/strategies", response_model=StrategyConfigResponse)
async def create_or_update_strategy(
    data: StrategyConfigCreate,
    _=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """创建或更新策略配置。"""
    from app.services import recommendation_strategy_service

    result = await recommendation_strategy_service.create_or_update_strategy_config(
        db, data.model_dump(),
    )
    await db.commit()
    return StrategyConfigResponse(**result)


# ── A/B 实验 ──


@router.get("/experiments", response_model=list[ExperimentResponseExtended])
async def list_experiments(
    scene: str | None = Query(None),
    _=Depends(require_permissions("recommendation:read")),
    db: AsyncSession = Depends(get_db),
):
    """查询实验列表。"""
    from app.services import recommendation_experiment_service

    experiments = await recommendation_experiment_service.list_experiments(db, scene=scene)
    return [ExperimentResponseExtended(**e) for e in experiments]


@router.post("/experiments", response_model=ExperimentResponseExtended)
async def create_experiment(
    data: ExperimentCreate,
    _=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """创建实验。"""
    from app.services import recommendation_experiment_service

    result = await recommendation_experiment_service.create_experiment(
        db, data.model_dump(),
    )
    await db.commit()
    return ExperimentResponseExtended(**result)


@router.patch("/experiments/{experiment_id}/status", response_model=ExperimentResponseExtended)
async def update_experiment_status(
    experiment_id: int,
    data: ExperimentStatusUpdate,
    _=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """修改实验状态。"""
    from app.services import recommendation_experiment_service

    result = await recommendation_experiment_service.update_experiment_status(
        db, experiment_id, data.status,
    )
    if not result:
        raise HTTPException(status_code=404, detail="实验不存在")
    await db.commit()
    return ExperimentResponseExtended(**result)


# ── 指标聚合 ──


@router.post("/metrics/aggregate", response_model=MetricsAggregateResponse)
async def aggregate_metrics(
    data: MetricsAggregateRequest,
    _=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """聚合指定日期推荐指标。"""
    from app.services import recommendation_metrics_service

    result = await recommendation_metrics_service.aggregate_recommendation_metrics_daily(
        db, target_date=data.date, subject_id=data.subject_id,
    )
    await db.commit()
    return MetricsAggregateResponse(**result)


@router.get("/metrics", response_model=list[MetricsDailyResponse])
async def get_metrics(
    date_from: date = Query(...),
    date_to: date = Query(...),
    subject_id: int | None = Query(None),
    scene: str | None = Query(None),
    strategy: str | None = Query(None),
    _=Depends(require_permissions("recommendation:read")),
    db: AsyncSession = Depends(get_db),
):
    """查询每日推荐指标。"""
    from app.services import recommendation_metrics_service

    rows = await recommendation_metrics_service.get_recommendation_metrics(
        db, date_from=date_from, date_to=date_to,
        subject_id=subject_id, scene=scene, strategy=strategy,
    )
    return [MetricsDailyResponse(**r) for r in rows]


# ── 实验对比 ──


@router.get("/experiments/{experiment_id}/compare", response_model=VariantComparisonResponse)
async def compare_experiment_variants(
    experiment_id: int,
    date_from: date = Query(...),
    date_to: date = Query(...),
    _=Depends(require_permissions("recommendation:read")),
    db: AsyncSession = Depends(get_db),
):
    """返回实验各分组对比指标。"""
    from app.services import recommendation_metrics_service

    result = await recommendation_metrics_service.compare_experiment_variants(
        db, experiment_id=experiment_id,
        date_from=date_from, date_to=date_to,
    )
    return VariantComparisonResponse(**result)


# ── 质量报告 ──


@router.get("/quality-report", response_model=RecommendationQualityReportResponse)
async def get_recommendation_quality_report(
    subject_id: int | None = Query(None),
    _=Depends(require_permissions("recommendation:read")),
    db: AsyncSession = Depends(get_db),
):
    """返回推荐质量报告。"""
    from app.services import recommendation_quality_service

    result = await recommendation_quality_service.build_recommendation_quality_report(
        db, subject_id=subject_id,
    )
    return RecommendationQualityReportResponse(**result)


@router.get("/knowledge-quality-report", response_model=KnowledgeQualityReportResponse)
async def get_knowledge_quality_report(
    subject_id: int | None = Query(None),
    _=Depends(require_permissions("recommendation:read")),
    db: AsyncSession = Depends(get_db),
):
    """返回知识图谱质量报告。"""
    from app.services import recommendation_quality_service

    result = await recommendation_quality_service.build_knowledge_quality_report(
        db, subject_id=subject_id,
    )
    return KnowledgeQualityReportResponse(**result)

# ── Phase 4.5: 种子策略 ──


@router.post("/strategies/seed", response_model=SeedStrategiesResponse)
async def seed_strategies(
    _=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """种子默认推荐策略。"""
    from app.services import recommendation_seed_service

    result = await recommendation_seed_service.seed_default_recommendation_strategies(db)
    await db.commit()
    return SeedStrategiesResponse(**result)


# ── Phase 4.5: 实验安全检查 ──


@router.post("/experiments/{experiment_id}/safety-check", response_model=SafetyCheckResponse)
async def safety_check(
    experiment_id: int,
    date_from: date = Query(...),
    date_to: date = Query(...),
    _=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """评估实验安全性，错误率过高时自动暂停。"""
    from app.services import recommendation_experiment_service

    result = await recommendation_experiment_service.evaluate_experiment_safety(
        db, experiment_id, date_from, date_to,
    )
    await db.commit()
    return SafetyCheckResponse(**result)


# ── Phase 4.5: 指标补跑 ──


@router.post("/metrics/backfill", response_model=MetricsBackfillResponse)
async def backfill_metrics(
    data: MetricsBackfillRequest,
    _=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """补跑日期范围内的推荐指标聚合。"""
    from app.services import recommendation_metrics_service

    result = await recommendation_metrics_service.backfill_metrics(
        db, date_from=data.date_from, date_to=data.date_to, subject_id=data.subject_id,
    )
    await db.commit()
    return MetricsBackfillResponse(**result)


# ── Phase 4.5: 健康报告 ──


@router.get("/health-report", response_model=HealthReportResponse)
async def health_report(
    subject_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    _=Depends(require_permissions("recommendation:read")),
    db: AsyncSession = Depends(get_db),
):
    """推荐系统健康报告。"""
    from app.services import recommendation_health_service

    result = await recommendation_health_service.build_recommendation_health_report(
        db, subject_id=subject_id, date_from=date_from, date_to=date_to,
    )
    return HealthReportResponse(**result)
