from app.schemas.base import BaseModel
"""V6 个性化调度 Schema"""


class AdaptiveOverviewResponse(BaseModel):
    # V6.1: 间隔倍率
    interval_factor: float = 1.0
    interval_status: str = "normal"
    target_recall_rate: float = 0.8
    recent_due_recall_rate: float = 0.0

    # V6.2: 难度
    hard_question_count: int = 0

    # V6.3: 路径
    fast_forgetting_knowledge_count: int = 0
    path_blocked_knowledge_count: int = 0

    # V6.4: 权重状态
    weights_adjusted: bool = False
    weight_summary: str = ""


class HardQuestionItem(BaseModel):
    question_id: int
    knowledge_point_id: int | None = None
    knowledge_point_name: str | None = None
    personal_difficulty_score: float = 0.0
    difficulty_label: str = "normal"
    wrong_count: int = 0
    avg_answer_time_seconds: float | None = None
    next_review_at: str | None = None


class HardQuestionsResponse(BaseModel):
    total: int = 0
    items: list[HardQuestionItem] = []


class PathBlockedItem(BaseModel):
    knowledge_point_id: int
    knowledge_point_name: str
    status: str = "blocked"
    reason: str = ""
    blocked_by: list[dict] = []


class KnowledgePathResponse(BaseModel):
    total: int = 0
    items: list[PathBlockedItem] = []
