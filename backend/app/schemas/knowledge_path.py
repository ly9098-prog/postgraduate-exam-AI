"""Phase 3 — 知识图谱边 + 知识路径推荐 Schema。"""
from pydantic import BaseModel, Field

# ── 知识图谱边 ──

class KnowledgeEdgeCreate(BaseModel):
    source_knowledge_point_id: int
    target_knowledge_point_id: int
    relation_type: str = Field(..., pattern="^(prerequisite|parent|related|next)$")
    weight: float = Field(1.0, ge=0.0, le=10.0)
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    source: str = Field("manual", pattern="^(manual|imported|ai|inferred)$")


class KnowledgeEdgeResponse(BaseModel):
    id: int
    subject: str
    source_knowledge_point_id: int
    source_name: str | None = None
    target_knowledge_point_id: int
    target_name: str | None = None
    relation_type: str
    weight: float
    confidence: float
    source: str

    model_config = {"from_attributes": True}


class KnowledgeEdgeBackfillRequest(BaseModel):
    subject: str
    mode: str = Field("simple", pattern="^(simple)$")
    limit: int = Field(500, ge=1, le=5000)
    force_rebuild: bool = Field(
        False,
        description="True 时先删除该科目所有 source='inferred' 边再重新推断，manual/imported/ai 不受影响",
    )


class KnowledgeEdgeStatusResponse(BaseModel):
    subject: str
    total_edges: int
    prerequisite_edges: int
    parent_edges: int
    related_edges: int
    next_edges: int
    active_edges: int


# ── 知识路径推荐 ──

class KnowledgePathNode(BaseModel):
    knowledge_point_id: int
    name: str
    subject: str
    mastery_score: float | None = None
    weakness_level: str | None = None
    # weak_point / prerequisite / current / next / related
    path_role: str
    priority: float = 0.0
    reason: str = ""
    recommended_question_ids: list[int] = []


class KnowledgePathResponse(BaseModel):
    subject: str
    user_id: int
    start_knowledge_point_id: int | None = None
    strategy: str
    nodes: list[KnowledgePathNode]
    recommended_question_ids: list[int]
    fallback_used: bool = False
