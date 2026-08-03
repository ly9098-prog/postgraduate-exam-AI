from pydantic import BaseModel


class DataAvailableMixin(BaseModel):
    data_available: bool = True


class TodayQuality(DataAvailableMixin):
    score: int = 0
    label: str = "数据不足"
    questions: int = 0
    accuracy: float = 0.0
    avg_time_sec: float = 0.0


class DayBreakdown(BaseModel):
    date: str
    questions: int = 0
    accuracy: float = 0.0


class WeeklyConsistency(DataAvailableMixin):
    score: int = 0
    label: str = "数据不足"
    active_days: int = 0
    days: int = 7
    total_questions: int = 0
    day_breakdown: list[DayBreakdown] = []


class WeakTopicItem(BaseModel):
    knowledge_point_id: int
    name: str
    subject_id: int | None = None
    subject_code: str = ""
    subject_name: str = ""
    mastery_score: float = 0.0
    attempt_count: int = 0
    wrong_count: int = 0
    recent_wrong_count: int = 0
    due_review_count: int = 0
    last_practiced_at: str | None = None


class WeakTopicRanking(DataAvailableMixin):
    items: list[WeakTopicItem] = []


class RepeatTopicItem(BaseModel):
    name: str
    count: int = 0


class RepeatWrongAnalysis(DataAvailableMixin):
    repeat_wrong_count: int = 0
    total_wrong_count: int = 0
    repeat_rate: float = 0.0
    is_high: bool = False
    status_label: str = ""
    top_repeat_topics: list[RepeatTopicItem] = []


class SpeedAccuracySubject(BaseModel):
    subject_id: int | None = None
    subject_code: str = ""
    subject_name: str = ""
    avg_time_correct_sec: float = 0.0
    avg_time_wrong_sec: float = 0.0
    questions: int = 0
    status_label: str = "数据不足"


class SpeedAccuracyAnalysis(DataAvailableMixin):
    overall_status: str = ""
    overall_label: str = "数据不足"
    avg_time_correct_sec: float = 0.0
    avg_time_wrong_sec: float = 0.0
    fast_wrong_count: int = 0
    slow_wrong_count: int = 0
    by_subject: list[SpeedAccuracySubject] = []


class NewVsReview(DataAvailableMixin):
    new_count: int = 0
    new_accuracy: float = 0.0
    review_count: int = 0
    review_accuracy: float = 0.0
    label: str = "数据不足"
    summary: str = ""


class InputOutputItem(BaseModel):
    subject_id: int | None = None
    subject_code: str = ""
    subject_name: str = ""
    total_questions: int = 0
    total_duration_sec: int = 0
    accuracy: float = 0.0
    time_per_question_sec: float = 0.0
    efficiency_score: float = 0.0
    efficiency_label: str = "数据不足"
    suggestion: str = ""


class InputOutputAnalysis(DataAvailableMixin):
    items: list[InputOutputItem] = []
    global_avg_time_sec: float = 0.0


class ActionPlanItem(BaseModel):
    type: str = "practice"
    priority: int = 0
    title: str = ""
    desc: str = ""
    action_data: dict = {}


class ActionPlan(DataAvailableMixin):
    items: list[ActionPlanItem] = []


class DashboardInsightsResponse(BaseModel):
    today_quality: TodayQuality | None = None
    weekly_consistency: WeeklyConsistency | None = None
    weak_topic_ranking: WeakTopicRanking | None = None
    repeat_wrong_analysis: RepeatWrongAnalysis | None = None
    speed_accuracy: SpeedAccuracyAnalysis | None = None
    new_vs_review: NewVsReview | None = None
    input_output: InputOutputAnalysis | None = None
    action_plan: ActionPlan | None = None
