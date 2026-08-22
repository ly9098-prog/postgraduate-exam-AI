from app.schemas.base import BaseModel
from datetime import datetime

from pydantic import ConfigDict

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


class SequentialPracticeProgress(BaseModel):
    """顺序刷题当前轮次进度。"""
    subject_id: int
    total_questions: int
    completed_questions: int
    remaining_questions: int
    cycle_completed: bool
    next_question_id: int | None = None


class PracticeQuestionsResponse(BaseModel):
    questions: list[PracticeQuestion]
    total: int
    mode: str
    trace_id: str | None = None
    request_id: str | None = None
    sequential_progress: SequentialPracticeProgress | None = None


class SequentialPracticeResetRequest(BaseModel):
    subject_id: int


class SequentialPracticeResetResponse(BaseModel):
    subject_id: int
    reset: bool = True


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
    wrong_question_id: int | None = None


# --- POST /practice/batch-submit ---

class PracticeSessionMeta(BaseModel):
    """一次完整刷题会话的元数据（可选）。

    session 保持 optional：旧客户端只发送 answers 时后端仍正常答题，不创建
    PracticeSession。request_id 用于 (user_id, request_id) 幂等去重，防止网络
    重试把同一组刷题重复记成两条学习记录 —— 因此一旦携带 session，request_id
    必须提供，否则无法去重。
    """
    request_id: str
    subject_id: int | None = None
    mode: str = "random"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_sec: int | None = None
    question_count: int | None = None
    answered_count: int | None = None
    status: str = "completed"


class BatchSubmitRequest(BaseModel):
    answers: list[AnswerSubmit]
    session: PracticeSessionMeta | None = None


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
