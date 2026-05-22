from datetime import date

from pydantic import BaseModel


class OverviewStats(BaseModel):
    total_questions: int = 0
    total_correct: int = 0
    total_wrong: int = 0
    accuracy: float = 0.0
    total_duration_sec: int = 0
    consecutive_days: int = 0
    today_questions: int = 0
    today_correct: int = 0
    today_duration_sec: int = 0
    mastered_count: int = 0
    due_review_count: int = 0


class SubjectStats(BaseModel):
    subject: str
    total_questions: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    accuracy: float = 0.0
    total_duration_sec: int = 0
    avg_duration_sec: float = 0.0


class TrendPoint(BaseModel):
    date: str
    questions: int = 0
    correct: int = 0
    accuracy: float = 0.0


class BehaviorStats(BaseModel):
    avg_time_sec: float = 0.0
    total_answers: int = 0
    view_answer_rate: float = 0.0
    abandon_rate: float = 0.0
    error_type_distribution: list[dict] = []
    hourly_activity: list[dict] = []


class ForgettingTrend(BaseModel):
    high_forget_count: int = 0
    stuck_questions: int = 0
    pseudo_mastered: list[dict] = []
    top_forgotten_topics: list[dict] = []


class DashboardResponse(BaseModel):
    overview: OverviewStats
    subject_stats: list[SubjectStats]
    recent_trend: list[TrendPoint]
    behavior: BehaviorStats
    forgetting: ForgettingTrend
