"""Guest practice contracts: browsing and evaluating without an account."""

from pydantic import Field

from app.schemas.base import BaseModel


class GuestPracticeQuestion(BaseModel):
    """Student-facing question preview; never carries the answer."""

    id: int
    question_version_id: int
    question_version: int
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    question_type: str
    content: dict
    options: dict | None = None
    knowledge_points: list | None = None
    difficulty: int = 3
    image_url: list | None = None


class GuestPracticeQuestionsResponse(BaseModel):
    questions: list[GuestPracticeQuestion]
    total: int
    subject_id: int
    subject_name: str = ""
    batch_token: str
    expires_at: int


class GuestAnswerSubmit(BaseModel):
    question_id: int = Field(gt=0)
    user_answer: str = Field(default="", max_length=4096)


class GuestEvaluateRequest(BaseModel):
    batch_token: str = Field(min_length=1, max_length=8192)
    answers: list[GuestAnswerSubmit] = Field(default_factory=list, max_length=5)


class GuestEvaluationItem(BaseModel):
    question_id: int
    question_type: str
    is_correct: bool | None = None
    user_answer: str = ""
    correct_answer: str = ""
    analysis: str | None = None
    reference_only: bool = False


class GuestEvaluateResponse(BaseModel):
    items: list[GuestEvaluationItem]
    total: int
    objective_total: int
    objective_correct: int
    objective_incorrect: int
    subjective_total: int
    skipped_total: int
