from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel

SyllabusStatus = Literal["draft", "active", "archived"]
SyllabusMappingType = Literal["unchanged", "renamed", "added", "removed", "merged", "split", "replaced"]
SyllabusManualMappingType = Literal["merged", "split", "replaced"]


class SyllabusVersionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=2, max_length=128)
    effective_year: int = Field(ge=2000, le=2200)
    description: str | None = Field(default=None, max_length=2000)


class SyllabusVersionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    effective_year: int | None = Field(default=None, ge=2000, le=2200)
    description: str | None = Field(default=None, max_length=2000)


class SyllabusVersionSummary(BaseModel):
    id: int
    code: str
    name: str
    effective_year: int
    status: SyllabusStatus
    description: str | None = None
    knowledge_point_count: int = 0
    activated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SyllabusKnowledgePointItem(BaseModel):
    id: int
    knowledge_point_id: int
    subject_id: int
    subject_code: str
    subject_name: str
    name: str
    normalized_name: str
    description: str | None = None
    difficulty_level: int
    sort_order: int = 0


class SyllabusVersionDetail(SyllabusVersionSummary):
    knowledge_points: list[SyllabusKnowledgePointItem] = Field(default_factory=list)


class SyllabusMembershipReplace(BaseModel):
    knowledge_point_ids: list[int] = Field(default_factory=list, max_length=5000)


class SyllabusCatalogItem(BaseModel):
    knowledge_point_id: int
    subject_id: int
    subject_code: str
    subject_name: str
    name: str
    description: str | None = None
    difficulty_level: int
    included: bool = False


class SyllabusCatalogResponse(BaseModel):
    syllabus_version_id: int
    items: list[SyllabusCatalogItem] = Field(default_factory=list)


class SyllabusMappingCreate(BaseModel):
    from_syllabus_knowledge_point_id: int | None = None
    to_syllabus_knowledge_point_id: int | None = None
    relation_type: SyllabusManualMappingType
    note: str | None = Field(default=None, max_length=256)


class SyllabusMappingItem(BaseModel):
    id: int
    from_syllabus_knowledge_point_id: int | None = None
    to_syllabus_knowledge_point_id: int | None = None
    relation_type: SyllabusMappingType
    note: str | None = None
    from_name: str | None = None
    to_name: str | None = None
    created_at: datetime


class SyllabusCoverageItem(BaseModel):
    syllabus_knowledge_point_id: int
    knowledge_point_id: int
    subject_id: int
    subject_code: str
    subject_name: str
    name: str
    question_count: int = 0
    covered: bool = False


class SyllabusCoverageResponse(BaseModel):
    syllabus_version_id: int
    syllabus_code: str
    total_knowledge_points: int = 0
    covered_knowledge_points: int = 0
    coverage_ratio: float = 0.0
    items: list[SyllabusCoverageItem] = Field(default_factory=list)


class ActiveSyllabusSummary(BaseModel):
    id: int
    code: str
    name: str
    effective_year: int
