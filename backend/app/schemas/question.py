from pydantic import BaseModel


class QuestionCreate(BaseModel):
    subject: str
    question_type: str = "choice"
    content: dict
    options: dict | None = None
    answer: str
    analysis: str | None = None
    knowledge_points: list[str] | None = None
    difficulty: int = 3
    source: str | None = None
    year: int | None = None


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

    class Config:
        from_attributes = True
