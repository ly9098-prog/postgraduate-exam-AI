from pydantic import BaseModel, ConfigDict, field_validator

from app.features.question_type import QT_SINGLE_CHOICE, validate_question_type


class QuestionCreate(BaseModel):
    subject: str
    question_type: str = QT_SINGLE_CHOICE
    content: dict
    options: dict | None = None
    answer: str
    analysis: str | None = None
    knowledge_points: list[str] | None = None
    difficulty: int = 3
    source: str | None = None
    year: int | None = None

    @field_validator("question_type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        return validate_question_type(v)


class QuestionRandomParams(BaseModel):
    subject: str | None = None
    question_type: str | None = None
    knowledge_points: list[str] | None = None
    difficulty: int | None = None
    exclude_ids: list[int] | None = None


class QuestionResponse(BaseModel):
    id: int
    subject: str
    question_type: str
    content: dict
    options: dict | None = None
    answer: str
    analysis: str | None = None
    knowledge_points: list | None = None
    difficulty: int
    source: str | None = None
    year: int | None = None
    image_url: list | None = None

    model_config = ConfigDict(from_attributes=True)


class QuestionPublicResponse(BaseModel):
    """Student-facing question payload; deliberately excludes answer/analysis."""

    id: int
    subject: str
    question_type: str
    content: dict
    options: dict | None = None
    knowledge_points: list | None = None
    difficulty: int
    source: str | None = None
    year: int | None = None
    image_url: list | None = None

    model_config = ConfigDict(from_attributes=True)
