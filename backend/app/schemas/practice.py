from app.schemas.base import BaseModel
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field

PracticeMode = Literal["random", "smart", "similar", "sequential"]

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
    question_version: str | None = None


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
    mode: PracticeMode
    trace_id: str | None = None
    request_id: str | None = None
    sequential_progress: SequentialPracticeProgress | None = None
    batch_token: str | None = None
    submission_request_id: str | None = None


class SequentialPracticeResetRequest(BaseModel):
    subject_id: int


class SequentialPracticeResetResponse(BaseModel):
    subject_id: int
    reset: bool = True


# --- POST /practice/submit ---

class AnswerSubmit(BaseModel):
    question_id: int = Field(gt=0)
    user_answer: str = Field(max_length=4096)
    used_time: int | None = Field(default=None, ge=0, le=6 * 60 * 60)
    request_id: str | None = Field(default=None, max_length=128)


class AnswerResult(BaseModel):
    question_id: int
    is_correct: bool
    correct_answer: str
    status: str = "wrong"
    analysis: str | None = None
    knowledge_points: list | None = None
    is_wrong_added: bool = False
    wrong_question_id: int | None = None


# --- POST /practice/batch-submit ---

class PracticeSessionMeta(BaseModel):
    """一次完整刷题会话的元数据。

    新版 batch-submit 必须携带 session，并与服务器签发的 batch_token 共同
    绑定科目、模式、request_id、题目集合和提交时序。
    """
    request_id: str = Field(min_length=1, max_length=128)
    subject_id: int = Field(gt=0)
    mode: PracticeMode = "random"
    started_at: datetime
    finished_at: datetime
    duration_sec: int = Field(ge=0, le=6 * 60 * 60)
    question_count: int = Field(ge=1, le=50)
    answered_count: int = Field(ge=0, le=50)
    status: Literal["completed"] = "completed"


class BatchSubmitRequest(BaseModel):
    answers: list[AnswerSubmit] = Field(default_factory=list, max_length=50)
    skipped_question_ids: list[int] = Field(default_factory=list, max_length=50)
    # New batch submissions are always server-issued.  Requiring both fields at
    # the API boundary prevents callers from silently falling back to an
    # unbound legacy path that could enumerate question ids for answers.
    batch_token: str = Field(min_length=16, max_length=8192)
    session: PracticeSessionMeta


class BatchSubmitResponse(BaseModel):
    results: list[AnswerResult]
    total_correct: int
    total_wrong: int
    total_skipped: int = 0
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
