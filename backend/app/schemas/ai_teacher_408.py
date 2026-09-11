"""408 专项 AI 老师的固定动作协议。"""

from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel

AITeacher408Action = Literal[
    "explain_correct",
    "explain_options",
    "core_concept",
    "similar_question",
    "harder_question",
    "connect_knowledge",
    "high_frequency_traps",
]


class AITeacher408ActionInfo(BaseModel):
    action: AITeacher408Action
    label: str
    description: str


class AITeacher408ActionsResponse(BaseModel):
    prompt_version: str
    actions: list[AITeacher408ActionInfo]


class AITeacher408Request(BaseModel):
    question_id: int = Field(gt=0)
    action: AITeacher408Action
    question_version_id: int | None = Field(default=None, gt=0)
    diagnosis_id: int | None = Field(default=None, gt=0)
    exam_attempt_id: int | None = Field(default=None, gt=0)
    # 普通练习结果可能尚未落下可引用的诊断事实，允许携带本次答案作为低信任上下文。
    # 正确答案、解析与题目版本绝不从客户端接收。
    user_answer: str | None = Field(default=None, max_length=1000)


class AITeacher408Section(BaseModel):
    heading: str = ""
    points: list[str] = Field(default_factory=list)


class AITeacher408KnowledgePoint(BaseModel):
    name: str = ""
    relation: str = ""
    mastery_hint: str = ""


class AITeacher408PracticeQuestion(BaseModel):
    stem: str = ""
    options: dict[str, str] = Field(default_factory=dict)
    answer: str = ""
    analysis: str = ""
    difficulty_delta: int = 0


class AITeacher408NextAction(BaseModel):
    type: str = "none"
    label: str = ""
    params: dict = Field(default_factory=dict)


class AITeacher408Personalization(BaseModel):
    used_mastery: bool = False
    used_recent_errors: bool = False
    used_error_diagnosis: bool = False
    used_knowledge_graph: bool = False
    weak_point_names: list[str] = Field(default_factory=list)


class AITeacher408Response(BaseModel):
    question_id: int
    question_version_id: int
    action: AITeacher408Action
    action_label: str
    prompt_version: str
    title: str = ""
    summary: str = ""
    sections: list[AITeacher408Section] = Field(default_factory=list)
    knowledge_points: list[AITeacher408KnowledgePoint] = Field(default_factory=list)
    practice_question: AITeacher408PracticeQuestion | None = None
    next_action: AITeacher408NextAction = Field(default_factory=AITeacher408NextAction)
    personalization: AITeacher408Personalization = Field(
        default_factory=AITeacher408Personalization
    )
    tokens_used: int = 0
    from_fallback: bool = False
