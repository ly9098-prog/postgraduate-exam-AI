"""AI 学习引擎相关 Pydantic 模型。"""

from pydantic import ConfigDict, Field

from app.schemas.base import BaseModel

# ============================================================
# Request Models
# ============================================================


class AIExplainRequest(BaseModel):
    question_id: int
    user_answer: str | None = None
    is_correct: bool | None = None
    focus: str = Field(default="solution", description="solution / mistake / knowledge")


class AIRecommendRequest(BaseModel):
    question_id: int
    count: int = Field(default=5, ge=1, le=20)


class AIReportRequest(BaseModel):
    subject_id: int
    days: int = Field(default=7, ge=1, le=90)


class AIMistakeAnalysisRequest(BaseModel):
    question_id: int
    user_answer: str
    correct_answer: str


# ============================================================
# Response Models
# ============================================================


class AIExplainResponse(BaseModel):
    question_id: int
    explanation: str = ""
    solution_steps: list[str] = []
    key_knowledge_points: list[str] = []
    common_mistakes: list[str] = []
    tokens_used: int = 0
    from_fallback: bool = False


class Recommendation(BaseModel):
    question_id: int
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    question_type: str
    stem: str
    knowledge_points: list[str] = []
    match_reason: str = ""
    difficulty: int | None = None
    similarity: float | None = None
    recommend_score: float | None = None

    model_config = ConfigDict(from_attributes=True)


class AIRecommendResponse(BaseModel):
    source_question_id: int
    recommendations: list[Recommendation]
    strategy: str = "rule_based"
    tokens_used: int = 0


class WeakPoint(BaseModel):
    knowledge_point: str
    accuracy: float
    suggestion: str = ""


class StrongPoint(BaseModel):
    knowledge_point: str
    accuracy: float
    suggestion: str = ""


class AIReportResponse(BaseModel):
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    period_days: int
    total_answered: int
    accuracy: float
    weak_points: list[WeakPoint] = []
    strong_points: list[StrongPoint] = []
    learning_suggestions: list[str] = []
    tokens_used: int = 0
    from_fallback: bool = False


class AIMistakeAnalysisResponse(BaseModel):
    error_type: str = ""
    error_type_label: str = ""
    analysis: str = ""
    suggestion: str = ""
    tokens_used: int = 0
    from_fallback: bool = False
