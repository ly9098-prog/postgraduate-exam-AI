"""Phase 4 — 推荐策略配置 + A/B 实验 + 指标 + 质量报告 Schema。"""
from datetime import date as date_cls
from datetime import datetime

from pydantic import BaseModel, Field

# ── 策略配置 ──


class StrategyConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field("", max_length=128)
    description: str | None = Field(None, max_length=512)
    scene: str = Field(..., pattern="^(practice_smart|similar|knowledge_path|wrong_variant)$")
    is_active: bool = True
    is_default: bool = False
    weight_vector_similarity: float = Field(0.5, ge=0.0, le=1.0)
    weight_knowledge_overlap: float = Field(0.2, ge=0.0, le=1.0)
    weight_difficulty_match: float = Field(0.1, ge=0.0, le=1.0)
    weight_mastery_gap: float = Field(0.1, ge=0.0, le=1.0)
    weight_path_priority: float = Field(0.1, ge=0.0, le=1.0)
    exploration_ratio: float = Field(0.1, ge=0.0, le=1.0)
    config_json: dict | None = None


class StrategyConfigUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    weight_vector_similarity: float | None = Field(None, ge=0.0, le=1.0)
    weight_knowledge_overlap: float | None = Field(None, ge=0.0, le=1.0)
    weight_difficulty_match: float | None = Field(None, ge=0.0, le=1.0)
    weight_mastery_gap: float | None = Field(None, ge=0.0, le=1.0)
    weight_path_priority: float | None = Field(None, ge=0.0, le=1.0)
    exploration_ratio: float | None = Field(None, ge=0.0, le=1.0)
    config_json: dict | None = None


class StrategyConfigResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str | None = None
    scene: str
    is_active: bool
    is_default: bool
    weight_vector_similarity: float
    weight_knowledge_overlap: float
    weight_difficulty_match: float
    weight_mastery_gap: float
    weight_path_priority: float
    exploration_ratio: float
    config_json: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── A/B 实验 ──


class ExperimentVariant(BaseModel):
    key: str
    strategy: str
    ratio: float = Field(ge=0.0, le=1.0)


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scene: str = Field(..., pattern="^(practice_smart|similar|knowledge_path)$")
    description: str | None = Field(None, max_length=512)
    start_at: datetime | None = None
    end_at: datetime | None = None
    traffic_ratio: float = Field(1.0, ge=0.0, le=1.0)
    variants: list[ExperimentVariant] = Field(..., min_length=2)
    max_traffic_percent: float = Field(100.0, ge=0.0, le=100.0)
    fallback_strategy_name: str | None = Field(None, max_length=64)
    auto_pause_on_error_rate: float | None = Field(None, ge=0.0, le=1.0)
    min_sample_size: int = Field(100, ge=0)


class ExperimentStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(draft|running|paused|finished)$")


class ExperimentResponse(BaseModel):
    id: int
    name: str
    scene: str
    description: str | None = None
    status: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    traffic_ratio: float
    variants: list[dict] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── 指标聚合 ──


class MetricsAggregateRequest(BaseModel):
    date: date_cls | None = None
    subject_id: int | None = None


class MetricsAggregateResponse(BaseModel):
    aggregated_rows: int
    target_date: str
    subject_id: int | None = None


class MetricsDailyResponse(BaseModel):
    date: date_cls
    subject_id: int
    subject_code: str | None = None
    subject_name: str | None = None
    scene: str
    strategy: str
    variant_key: str | None = None
    exposure_count: int
    click_count: int
    answer_count: int
    correct_count: int
    wrong_count: int
    avg_recommend_score: float
    avg_similarity: float
    avg_mastery_before: float | None = None
    avg_mastery_after: float | None = None
    avg_mastery_delta: float | None = None
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
    reason: str | None = None
    metrics: dict


# ── Phase 4.5: 指标补跑 ──


class MetricsBackfillRequest(BaseModel):
    date_from: date_cls
    date_to: date_cls
    subject_id: int | None = None


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
    description: str | None = None
    status: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    traffic_ratio: float
    variants: list[dict] | None = None
    max_traffic_percent: float = 100.0
    fallback_strategy_name: str | None = None
    auto_pause_on_error_rate: float | None = None
    min_sample_size: int = 100
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
