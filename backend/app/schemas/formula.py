from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Category ──

class FormulaCategoryCreate(BaseModel):
    parent_id: int | None = None
    exam_scope: str = "math2"
    node_type: str
    code: str
    name: str
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


class FormulaCategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class FormulaCategoryResponse(BaseModel):
    id: int
    parent_id: int | None
    exam_scope: str
    node_type: str
    code: str
    name: str
    description: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    children: list["FormulaCategoryResponse"] = []

    model_config = {"from_attributes": True}


# ── Tags ──

class FormulaTagResponse(BaseModel):
    id: int
    code: str
    name: str
    sort_order: int

    model_config = {"from_attributes": True}


# ── Formula Card ──

class FormulaBlock(BaseModel):
    label: str | None = None
    latex: str
    note: str | None = None


class FormulaExample(BaseModel):
    question: str
    short_solution: str
    answer: str
    error_tip: str | None = None


class FormulaCardCreate(BaseModel):
    category_id: int
    title: str
    aliases: list[str] | None = None
    search_text: str | None = None
    card_type: str = "pure_formula"
    summary: str | None = None
    formula_blocks: list[FormulaBlock] = Field(min_length=1, max_length=8)
    conditions: str | None = None
    symbol_notes: str | None = None
    secondary_conclusions: str | None = None
    error_tips: str | None = None
    examples: list[FormulaExample] | None = Field(None, max_length=3)
    function_properties: dict[str, Any] | None = None
    sort_order: int = 0
    tag_ids: list[int] = []
    source_type: str | None = None
    source_title: str | None = None
    source_ref: str | None = None


class FormulaCardUpdate(BaseModel):
    category_id: int | None = None
    title: str | None = None
    aliases: list[str] | None = None
    search_text: str | None = None
    card_type: str | None = None
    summary: str | None = None
    formula_blocks: list[FormulaBlock] | None = None
    conditions: str | None = None
    symbol_notes: str | None = None
    secondary_conclusions: str | None = None
    error_tips: str | None = None
    examples: list[FormulaExample] | None = None
    function_properties: dict[str, Any] | None = None
    sort_order: int | None = None
    tag_ids: list[int] | None = None


class FormulaCardResponse(BaseModel):
    id: int
    exam_scope: str
    category_id: int
    title: str
    aliases: list[str] | None
    search_text: str | None
    card_type: str
    summary: str | None
    formula_blocks: list[dict[str, Any]]
    conditions: str | None
    symbol_notes: str | None
    secondary_conclusions: str | None
    error_tips: str | None
    examples: list[dict[str, Any]] | None
    function_properties: dict[str, Any] | None
    sort_order: int
    status: str
    tags: list[FormulaTagResponse] = []
    published_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Favorites ──

class FormulaFavoriteToggle(BaseModel):
    pass  # Just the auth context


# ── Random ──

class FormulaRandomQuery(BaseModel):
    subject_code: str | None = None
    chapter_id: int | None = None
    category_id: int | None = None
    tags: str | None = None
    exclude_ids: list[int] = Field(default_factory=list, max_length=20)


# ── User API query params ──

class FormulaListQuery(BaseModel):
    subject_code: str | None = None
    chapter_id: int | None = None
    category_id: int | None = None
    tags: str | None = None
    q: str | None = None
    favorite_only: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


# ── State machine ──

class FormulaReviewAction(BaseModel):
    action: str  # approve | reject | publish | offline | restore
    rejection_reason: str | None = None


class FormulaBatchReview(BaseModel):
    card_ids: list[int] = Field(min_length=1)
    action: str
    rejection_reason: str | None = None


# ── Import job ──

class FormulaImportJobResponse(BaseModel):
    id: int
    source_type: str
    status: str
    progress: float
    stage: str | None
    error_message: str | None
    source_filename: str | None
    total_items: int
    processed_items: int
    failed_items: int
    retry_of: int | None
    metadata_json: dict | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FormulaImportItemResponse(BaseModel):
    id: int
    job_id: int
    source_locator: str | None
    raw_text: str | None
    raw_image_url: str | None
    generated_content: dict | None
    card_type: str | None
    confidence: float | None
    risk_flags: list | None
    latex_valid: bool | None
    latex_errors: list | None
    scope_check: dict | None
    duplicate_check: dict | None
    review_status: str
    rejection_reason: str | None
    result_card_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FormulaImportItemReview(BaseModel):
    review_status: str  # approved | rejected
    rejection_reason: str | None = None
