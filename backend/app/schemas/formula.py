from __future__ import annotations

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
    card_type: str = "auto"
    summary: str | None = None
    formula_blocks: list[FormulaBlock] = Field(min_length=1, max_length=8)
    conditions: str | None = None
    symbol_notes: str | None = None
    secondary_conclusions: str | None = None
    error_tips: str | None = None
    examples: list[FormulaExample] | None = Field(None, max_length=3)
    function_properties: dict[str, Any] | None = None
    graph_spec: dict | None = None
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
    graph_spec: dict | None = None
    sort_order: int | None = None
    tag_ids: list[int] | None = None


# ── Graph Asset ──

class FormulaGraphAssetResponse(BaseModel):
    """Full graph asset response model for admin and user-facing APIs."""
    id: int
    formula_card_id: int
    source_type: str
    template_type: str | None = None
    template_parameters: dict | None = None
    viewport: dict | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    original_svg_url: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    checksum: str | None = None
    renderer_version: int | None = None
    alt_text: str | None = None
    description: str | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    published_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Graph Spec (auto-generation) ──


class GraphSpecLayout(BaseModel):
    rows: int = Field(default=1, ge=1, le=3)
    columns: int = Field(default=1, ge=1, le=3)


class GraphSpecExpression(BaseModel):
    expression: str = Field(..., min_length=1, max_length=500)
    display_latex: str | None = Field(None, max_length=500)
    label: str | None = Field(None, max_length=100)
    line_style: str = "solid"  # solid | dashed | dotted | dashdot


class GraphSpecDomain(BaseModel):
    intervals: list[list[float | None]] = Field(default=[])
    exclude_points: list[float] = Field(default=[])


class GraphSpecAnnotation(BaseModel):
    x: float
    y: float
    label: str | None = None
    color: str | None = None
    point_style: str = "filled"  # filled | hollow


class GraphSpecRefLine(BaseModel):
    value: float
    label: str | None = None
    style: str = "dashed"  # solid | dashed | dotted | dashdot
    is_vertical: bool = True


class GraphSpecPanel(BaseModel):
    expressions: list[GraphSpecExpression] = Field(..., min_length=1, max_length=8)
    domain: GraphSpecDomain = Field(default_factory=GraphSpecDomain)
    axis_mode: str = "auto_robust"  # manual | auto | auto_robust
    x_range: list[float] = Field(default_factory=lambda: [-6, 6])
    y_range: list[float] = Field(default_factory=lambda: [-6, 6])
    annotations: list[GraphSpecAnnotation] = Field(default=[], max_length=20)
    vertical_lines: list[GraphSpecRefLine] = Field(default=[])
    horizontal_lines: list[GraphSpecRefLine] = Field(default=[])
    title: str | None = Field(None, max_length=100)
    x_label: str = "x"
    y_label: str = "y"


class GraphSpec(BaseModel):
    schema_version: int = Field(default=1, ge=1, le=99)
    render_mode: str = "explicit_2d"  # explicit_2d | preset_diagram | manual_only
    template: str = "single_function"
    layout: GraphSpecLayout = Field(default_factory=GraphSpecLayout)
    panels: list[GraphSpecPanel] = Field(..., min_length=1, max_length=9)


class QualityCheckResult(BaseModel):
    errors: list[str] = Field(default=[])
    warnings: list[str] = Field(default=[])
    passed: bool = False


class GraphPreviewResponse(BaseModel):
    preview_url: str
    thumbnail_url: str | None = None
    preview_token: str
    checksum: str
    width: int = 1600
    height: int = 1000
    mime_type: str = "image/png"
    quality: QualityCheckResult = Field(default_factory=lambda: QualityCheckResult(passed=True))
    expires_at: datetime


class GraphConfirmRequest(BaseModel):
    preview_token: str
    checksum: str
    card_version: int
    accept_warnings: bool = False
    alt_text: str | None = None
    description: str | None = None


class GraphConfirmResponse(BaseModel):
    asset: FormulaGraphAssetResponse
    graph_status: str = "ready"


class GraphAssetUpdate(BaseModel):
    alt_text: str | None = None
    description: str | None = None


class GraphBatchGenerateResponse(BaseModel):
    job_id: str
    total: int = 0


class GraphBatchJobStatus(BaseModel):
    job_id: str
    status: str  # running | completed | partial_failed | failed | cancelled
    progress: float
    total: int
    processed: int = 0
    succeeded: int
    failed: int
    skipped: int = 0
    errors: list[dict] = Field(default=[])
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None


# ── Formula Card (updated response) ──

class FormulaCardResponse(BaseModel):
    id: int
    exam_scope: str
    category_id: int
    title: str
    aliases: list[str] | None
    search_text: str | None
    card_type: str
    is_function_graph: bool
    summary: str | None
    formula_blocks: list[dict[str, Any]]
    conditions: str | None
    symbol_notes: str | None
    secondary_conclusions: str | None
    error_tips: str | None
    examples: list[dict[str, Any]] | None
    function_properties: dict[str, Any] | None
    graph_asset: FormulaGraphAssetResponse | None = None
    graph_assets: list[FormulaGraphAssetResponse] = Field(default=[])
    graph_specs: list[dict[str, Any]] = Field(default=[])
    graph_spec: dict | None = None
    draft_graph_spec: dict | None = None
    graph_status: str = "not_applicable"
    graph_last_error: str | None = None
    graph_generated_at: datetime | None = None
    graph_confirmed_at: datetime | None = None
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

_ACTION_TYPES = frozenset({"approve", "reject", "publish", "offline", "restore"})


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
