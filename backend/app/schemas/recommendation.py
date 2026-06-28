"""Phase 4 — 推荐策略配置 + A/B 实验 + 指标 + 质量报告 Schema。"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── 策略配置 ──


class StrategyConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field("", max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    scene: str = Field(..., pattern="^(practice_smart|similar|knowledge_path|wrong_variant)$")
    is_active: bool = True
    is_default: bool = False
    weight_vector_similarity: float = Field(0.5, ge=0.0, le=1.0)
    weight_knowledge_overlap: float = Field(0.2, ge=0.0, le=1.0)
    weight_difficulty_match: float = Field(0.1, ge=0.0, le=1.0)
    weight_mastery_gap: float = Field(0.1, ge=0.0, le=1.0)
    weight_path_priority: float = Field(0.1, ge=0.0, le=1.0)
    exploration_ratio: float = Field(0.1, ge=0.0, le=1.0)
    config_json: Optional[dict] = None


class StrategyConfigUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    weight_vector_similarity: Optional[float] = Field(None, ge=0.0, le=1.0)
    weight_knowledge_overlap: Optional[float] = Field(None, ge=0.0, le=1.0)
    weight_difficulty_match: Optional[float] = Field(None, ge=0.0, le=1.0)
    weight_mastery_gap: Optional[float] = Field(None, ge=0.0, le=1.0)
    weight_path_priority: Optional[float] = Field(None, ge=0.0, le=1.0)
    exploration_ratio: Optional[float] = Field(None, ge=0.0, le=1.0)
    config_json: Optional[dict] = None


class StrategyConfigResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    scene: str
    is_active: bool
    is_default: bool
    weight_vector_similarity: float
    weight_knowledge_overlap: float
    weight_difficulty_match: float
    weight_mastery_gap: float
    weight_path_priority: float
    exploration_ratio: float
    config_json: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── A/B 实验 ──


class ExperimentVariant(BaseModel):
    key: str
    strategy: str
    ratio: float = Field(ge=0.0, le=1.0)


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scene: str = Field(..., pattern="^(practice_smart|similar|knowledge_path)$")
    description: Optional[str] = Field(None, max_length=512)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    traffic_ratio: float = Field(1.0, ge=0.0, le=1.0)
    variants: list[ExperimentVariant] = Field(..., min_length=2)
    max_traffic_percent: float = Field(100.0, ge=0.0, le=100.0)
    fallback_strategy_name: Optional[str] = Field(None, max_length=64)
    auto_pause_on_error_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    min_sample_size: int = Field(100, ge=0)


class ExperimentStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(draft|running|paused|finished)$")


class ExperimentResponse(BaseModel):
    id: int
    name: str
    scene: str
    description: Optional[str] = None
    status: str
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    traffic_ratio: float
    variants: Optional[list[dict]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── 指标聚合 ──


class MetricsAggregateRequest(BaseModel):
    date: Optional[date] = None
    subject: Optional[str] = None


class MetricsAggregateResponse(BaseModel):
    aggregated_rows: int
    target_date: str
    subject: Optional[str] = None


class MetricsDailyResponse(BaseModel):
    date: date
    subject: str
    scene: str
    strategy: str
    variant_key: Optional[str] = None
    exposure_count: int
    click_count: int
    answer_count: int
    correct_count: int
    wrong_count: int
    avg_recommend_score: float
    avg_similarity: float
    avg_mastery_before: Optional[float] = None
    avg_mastery_after: Optional[float] = None
    avg_mastery_delta: Optional[float] = None
    completion_rate: float
    accuracy: float
    ctr: float

    model_config = {"from_attributes": True}


class VariantComparisonResponse(BaseModel):
    experiment_id: int
    experiment_name: str
    variants: list[dict]


# ── 质量报告 ──


class RecommendationQualityReportResponse(BaseModel):
    summary: dict
    warnings: list[str]
    hot_questions: list[dict]
    high_fallback_scenes: list[dict]
    low_similarity_samples: list[dict]


class KnowledgeQualityReportResponse(BaseModel):
    summary: dict
    warnings: list[str]
    isolated_knowledge_points: list[dict]
    low_question_count_points: list[dict]
    cycles: list[list[int]]

# ── Phase 4.5: 种子策略 ──


class SeedStrategiesResponse(BaseModel):
    created: int
    updated: int
    skipped: int


# ── Phase 4.5: 实验安全阀 ──


class SafetyCheckResponse(BaseModel):
    paused: bool
    reason: Optional[str] = None
    metrics: dict


# ── Phase 4.5: 指标补跑 ──


class MetricsBackfillRequest(BaseModel):
    date_from: date
    date_to: date
    subject: Optional[str] = None


class MetricsBackfillResponse(BaseModel):
    success_dates: list[str]
    failed_dates: list[str]
    errors: list[str]


# ── Phase 4.5: 健康报告 ──


class HealthReportResponse(BaseModel):
    total_recommendation_logs: int
    fallback_rate: float
    empty_recommendation_count: int
    low_similarity_rate: float
    strategy_resolve_failed_count: int
    experiment_assignment_count: int
    experiment_variant_distribution: dict
    vector_recall_failure_count: int
    knowledge_path_empty_count: int
    top_fallback_scenes: list[dict]
    top_error_strategies: list[dict]
    warnings: list[str]


# ── Phase 4.5: 实验响应扩展 ──


class ExperimentResponseExtended(BaseModel):
    id: int
    name: str
    scene: str
    description: Optional[str] = None
    status: str
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    traffic_ratio: float
    variants: Optional[list[dict]] = None
    max_traffic_percent: float = 100.0
    fallback_strategy_name: Optional[str] = None
    auto_pause_on_error_rate: Optional[float] = None
    min_sample_size: int = 100
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
