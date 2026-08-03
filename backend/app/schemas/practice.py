from datetime import datetime

from pydantic import BaseModel, ConfigDict

# --- GET /practice/questions ---

class PracticeQuestion(BaseModel):
    """刷题用题目（不含答案）"""
    id: int
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    question_type: str
    content: dict
    options: dict | None = None
    knowledge_points: list | None = None
    difficulty: int = 3
    image_url: list | None = None
    trace_id: str | None = None
    recommend_reason: str | None = None
    recommend_score: float | None = None
    strategy: str | None = None
    similarity: float | None = None


class PracticeQuestionsResponse(BaseModel):
    questions: list[PracticeQuestion]
    total: int
    mode: str
    trace_id: str | None = None
    request_id: str | None = None


# --- POST /practice/submit ---

class AnswerSubmit(BaseModel):
    question_id: int
    user_answer: str
    used_time: int | None = None
    request_id: str | None = None


class AnswerResult(BaseModel):
    question_id: int
    is_correct: bool
    correct_answer: str
    analysis: str | None = None
    knowledge_points: list | None = None
    is_wrong_added: bool = False


# --- POST /practice/batch-submit ---

class BatchSubmitRequest(BaseModel):
    answers: list[AnswerSubmit]


class BatchSubmitResponse(BaseModel):
    results: list[AnswerResult]
    total_correct: int
    total_wrong: int
    trace_id: str | None = None


# --- GET /practice/stats ---

class DailyStats(BaseModel):
    date: str
    answered: int
    correct: int


class SubjectStats(BaseModel):
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    answered: int
    correct: int
    accuracy: float


class PracticeStatsResponse(BaseModel):
    total_answered: int
    total_correct: int
    accuracy: float
    by_subject: list[SubjectStats] = []
    daily_stats: list[DailyStats] = []
    current_streak: int = 0


# --- GET /questions/{id}/detail ---

class QuestionDetailResponse(BaseModel):
    id: int
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    question_type: str
    content: dict
    options: dict | None = None
    answer: str
    analysis: str | None = None
    knowledge_points: list | None = None
    image_url: list | None = None

    model_config = ConfigDict(from_attributes=True)


# --- GET /practice/records (history) ---

class PracticeRecordItem(BaseModel):
    id: int
    question_id: int
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    question_type: str
    user_answer: str
    is_correct: bool
    used_time: int | None
    answered_at: datetime

    model_config = ConfigDict(from_attributes=True)
