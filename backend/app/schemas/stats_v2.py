from datetime import date

from pydantic import BaseModel


class OverviewV2(BaseModel):
    total_questions: int = 0
    total_correct: int = 0
    total_wrong: int = 0
    accuracy: float = 0.0
    today_questions: int = 0
    today_correct: int = 0
    today_accuracy: float = 0.0
    today_duration_sec: int = 0
    consecutive_days: int = 0
    due_review_count: int = 0
    wrong_question_count: int = 0
    mastered_wrong_count: int = 0
    mastery_rate: float = 0.0


class RecommendationV2(BaseModel):
    priority: str = "practice"
    title: str = ""
    desc: str = ""
    tags: list[str] = []
    cta_text: str = ""
    cta_type: str = "practice"


class TrendPointV2(BaseModel):
    date: str
    questions: int = 0
    correct: int = 0
    accuracy: float = 0.0


class TrendsV2(BaseModel):
    days: int = 7
    points: list[TrendPointV2] = []
    previous_points: list[TrendPointV2] = []
    total_questions: int = 0
    active_days: int = 0
    avg_accuracy: float = 0.0
    previous_total_questions: int = 0
    previous_active_days: int = 0
    previous_avg_accuracy: float = 0.0
    summary: str = ""


class SubjectItemV2(BaseModel):
    subject: str
    label: str = ""
    total_questions: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    accuracy: float = 0.0
    total_duration_sec: int = 0


class SubjectAnalysisV2(BaseModel):
    items: list[SubjectItemV2] = []
    strongest: SubjectItemV2 | None = None
    weakest: SubjectItemV2 | None = None
    total_questions: int = 0


class ReviewRiskV2(BaseModel):
    high_forget_count: int = 0
    stuck_questions: int = 0
    pseudo_mastered_count: int = 0
    top_topics: list[dict] = []


class FeaturedBadge(BaseModel):
    key: str
    title: str
    desc: str
    unlocked: bool
    progress_text: str = ""


class GrowthV2(BaseModel):
    level: int = 1
    level_title: str = ""
    level_progress_pct: int = 0
    streak_title: str = ""
    featured_badges: list[FeaturedBadge] = []


class AdaptiveV2(BaseModel):
    visible: bool = False
    interval_status: str = "normal"
    interval_status_label: str = "节奏正常"
    recent_due_recall_rate: float = 0.0
    target_recall_rate: float = 0.8
    summary: str = ""


class YearlySummaryV2(BaseModel):
    active_days: int = 0
    total_questions: int = 0
    best_day_text: str = ""


class DashboardV2Response(BaseModel):
    overview: OverviewV2
    recommendation: RecommendationV2
    trends: TrendsV2
    subjects: SubjectAnalysisV2
    review_risk: ReviewRiskV2
    growth: GrowthV2 | None = None
    adaptive: AdaptiveV2 | None = None
    yearly_summary: YearlySummaryV2 | None = None
