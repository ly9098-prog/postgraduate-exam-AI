"""V3 知识点掌握度查询 Schema。"""
from datetime import datetime

from pydantic import BaseModel


class KnowledgeStateItem(BaseModel):
    """单个知识点掌握状态。"""
    knowledge_point_id: int | None = None
    knowledge_point: str
    mastery_score: float
    confidence: float
    label: str
    answer_count: int
    correct_count: int
    wrong_count: int
    recent_wrong_count: int = 0
    last_practiced_at: datetime | None = None


class KnowledgeStateListResponse(BaseModel):
    """知识点掌握状态列表响应。"""
    items: list[KnowledgeStateItem]
    total: int
