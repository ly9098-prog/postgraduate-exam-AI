from app.schemas.base import BaseModel


class BehaviorRecord(BaseModel):
    question_id: int
    time_spent_sec: int = 0
    view_answer_count: int = 0
    switch_count: int = 0
    is_abandoned: bool = False
    is_final_correct: bool | None = None
    user_answer: str | None = None
    correct_answer: str | None = None


class BehaviorSubmit(BaseModel):
    subject_id: int | None = None
    session_type: str = "random"
    records: list[BehaviorRecord]


class BehaviorStatsResponse(BaseModel):
    total_answers: int
    correct_count: int
    accuracy: float
    avg_time_sec: float
    by_subject: list[dict]
