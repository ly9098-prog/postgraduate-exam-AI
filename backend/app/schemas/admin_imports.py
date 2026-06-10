from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AdminImportBatchListItem(BaseModel):
    batch_id: str
    source_type: str
    source_file: str | None = None
    total_count: int
    pending_count: int
    approved_count: int
    rejected_count: int
    published_count: int
    ai_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminImportQuestionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: str
    source_type: str
    source_file: str | None = None
    subject: str | None = None
    question_type: str | None = None
    raw_data: dict
    parsed_content: dict | None = None
    parsed_options: dict | None = None
    parsed_answer: str | None = None
    parsed_analysis: str | None = None
    question_hash: str | None = None
    duplicate_status: str | None = "normal"
    duplicate_of_question_id: int | None = None
    duplicate_of_import_id: int | None = None
    status: str
    review_note: str | None = None
    question_id: int | None = None
    reject_reason: str | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    ai_generated: bool
    ai_source: str | None = None
    ai_confidence: float | None = None
    ai_metadata: dict | None = None
    ai_reviewed_at: datetime | None = None
    ai_answer_flag: bool
    created_at: datetime
    updated_at: datetime


class AdminImportBatchDetail(AdminImportBatchListItem):
    items: list[AdminImportQuestionItem]
    page: int
    page_size: int
    total_pages: int


class AdminImportEnrichResponse(BaseModel):
    task_id: str
    batch_id: str
    status: str
    created_at: datetime


class AdminImportCompleteResponse(BaseModel):
    missing: list[str]
    from_fallback: bool
    ai_metadata: dict
    tokens_used: int = 0
    duration_ms: int = 0
    item: AdminImportQuestionItem


class AdminImportQuestionUpdateRequest(BaseModel):
    subject: str | None = None
    question_type: str | None = None
    stem: str | None = None
    options: list[dict] | dict | None = None
    answer: str | None = None
    analysis: str | None = None
    parsed_content: dict | None = None
    parsed_options: dict | None = None
    parsed_answer: str | None = None
    parsed_analysis: str | None = None
    raw_data: dict | None = None
    review_note: str | None = None


class AdminImportRejectRequest(BaseModel):
    reason: str | None = None


class AdminImportActionResponse(BaseModel):
    id: int | None = None
    batch_id: str | None = None
    status: str
    affected_count: int = 0


class AdminImportDeleteResponse(BaseModel):
    batch_id: str | None = None
    id: int | None = None
    deleted_count: int


class AdminImportTaskStatusResponse(BaseModel):
    task_id: str
    batch_id: str
    status: str
    created_at: str | datetime
    updated_at: str | datetime | None = None
    total_count: int | None = None
    processed_count: int | None = None
    error_message: str | None = None


class AdminImportBatchCompleteRequest(BaseModel):
    import_ids: list[int] = Field(..., description="要补全的导入题目 ID 列表，最多 50 条")
    fields: list[str] = Field(..., description="补全字段列表: answer, analysis, knowledge_points, difficulty, subject, question_type, stem, options, tips, tags")
    strategy: str = Field("fill_empty", description="fill_empty | force_overwrite")


class AdminImportBatchCompleteItem(BaseModel):
    import_id: int
    status: str  # success | failed | skipped
    error: str | None = None
    completed_fields: list[str] = []


class AdminImportBatchCompleteResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    skipped: int
    items: list[AdminImportBatchCompleteItem]


class TextParseRequest(BaseModel):
    text: str = Field(..., max_length=100_000)  # ~100KB
    subject: str = ""  # 可选，为空时自动检测


class TextParseQuestion(BaseModel):
    subject: str | None = None
    question_type: str | None = None
    stem: str = ""
    options: list[dict] = []
    answer: str | list[str] | bool | None = None
    analysis: str | None = None
    knowledge_points: list[str] = []
    difficulty: int = 3
    is_valid: bool = False
    errors: list[str] = []
    warnings: list[str] = []
    question_hash: str | None = None
    stem_hash: str | None = None
    block_index: int = 0
    detection_method: str = "unknown"


class TextParseResponse(BaseModel):
    questions: list[TextParseQuestion]
    warnings: list[str] = []
    raw_count: int = 0
    valid_count: int = 0


class TextImportQuestion(BaseModel):
    subject: str = ""
    stem: str
    options: list[dict] = []
    answer: str | list[str] | bool | None = None
    analysis: str | None = None
    question_type: str | None = None
    knowledge_points: list[str] = []
    difficulty: int = 3


class TextImportRequest(BaseModel):
    subject: str = ""
    questions: list[TextImportQuestion]


class TextImportResultItem(BaseModel):
    block_index: int
    import_id: int | None = None
    status: str = "ok"  # ok | fail | duplicate
    error: str | None = None


class TextImportResponse(BaseModel):
    batch_id: str
    items: list[TextImportResultItem]
    total: int
    succeeded: int
    failed: int
    duplicates_filtered: int = 0
