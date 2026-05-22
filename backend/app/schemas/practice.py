from datetime import datetime

from pydantic import BaseModel


class AnswerItem(BaseModel):
    question_id: int
    answer: str


class PracticeSubmit(BaseModel):
    subject: str
    mode: str = "random"
    answers: list[AnswerItem]
    duration_sec: int = 0


class PracticeResultItem(BaseModel):
    question_id: int
    user_answer: str
    correct_answer: str
    is_correct: bool
    analysis: str | None = None


class PracticeResult(BaseModel):
    record_id: int
    subject: str
    mode: str
    correct_count: int
    wrong_count: int
    total: int
    duration_sec: int
    results: list[PracticeResultItem]


class SingleCheckResult(BaseModel):
    question_id: int
    user_answer: str
    correct_answer: str
    is_correct: bool
    analysis: str | None = None


class SingleCheckRequest(BaseModel):
    question_id: int
    answer: str


class BatchQuestionsRequest(BaseModel):
    subject: str
    count: int = 10
    exclude_ids: list[int] = []


class BatchQuestionsResponse(BaseModel):
    questions: list[dict]
    total: int


class PracticeRecordSummary(BaseModel):
    id: int
    subject: str
    mode: str
    correct_count: int
    wrong_count: int
    total: int
    duration_sec: int
    created_at: datetime
