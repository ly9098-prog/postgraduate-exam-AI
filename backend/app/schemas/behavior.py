from app.schemas.base import BaseModel


class BehaviorStatsResponse(BaseModel):
    total_answers: int
    correct_count: int
    accuracy: float
    avg_time_sec: float
    by_subject: list[dict]
