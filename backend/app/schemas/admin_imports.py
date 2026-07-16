from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.features.question_type import validate_question_type


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


class AdminImportQuestionItemBrief(BaseModel):
    """摘要版导入题目，不包含 raw_data / parsed_content / parsed_options 等大字段。

    列表页使用此 schema，详情页使用完整的 AdminImportQuestionItem。
    """
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _fill_subject_display(cls, data):
        if hasattr(data, "subject_ref"):
            ref = data.subject_ref
            if ref:
                if isinstance(data, dict):
                    data.setdefault("subject_code", ref.code)
                    data.setdefault("subject_name", ref.name)
                else:
                    pass  # ORM object — from_attributes picks up labeled columns
        return data

    id: int
    batch_id: str
    source_type: str
    source_file: str | None = None
    subject_id: int | None = None
    subject_code: str | None = None
    subject_name: str | None = None
    question_type: str | None = None
    parsed_answer: str | None = None
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
    content_preview: str = ""
    risk_flags: list[str] = []
    risk_level: str = "low"
    risk_reasons: list[str] = []
    # ── 导入审核定位与答案状态 ──
    source_question_no: str | None = None
    source_question_label: str | None = None
    source_image_seq: int | None = None
    source_image_name: str | None = None
    source_page_start: int | None = None
    source_page_end: int | None = None
    source_order_index: int | None = None
    raw_text_preview: str | None = None
    source_locator: str | None = None
    answer_status: str | None = None
    answer_source: str | None = None
    answer_confidence: float | None = None
    review_priority: int | None = None
    created_at: datetime
    updated_at: datetime


class AdminImportQuestionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _fill_subject_display(cls, data):
        if hasattr(data, "subject_ref"):
            ref = data.subject_ref
            if ref:
                if isinstance(data, dict):
                    data.setdefault("subject_code", ref.code)
                    data.setdefault("subject_name", ref.name)
                else:
                    pass  # ORM object — from_attributes picks up labeled columns
        return data

    id: int
    batch_id: str
    source_type: str
    source_file: str | None = None
    subject_id: int | None = None
    subject_code: str | None = None
    subject_name: str | None = None
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
    risk_flags: list[str] = []
    risk_level: str = "low"
    risk_reasons: list[str] = []
    # ── 导入审核定位与答案状态 ──
    source_question_no: str | None = None
    source_question_label: str | None = None
    source_image_seq: int | None = None
    source_image_name: str | None = None
    source_page_start: int | None = None
    source_page_end: int | None = None
    source_order_index: int | None = None
    raw_text_preview: str | None = None
    source_locator: str | None = None
    answer_status: str | None = None
    answer_source: str | None = None
    answer_confidence: float | None = None
    review_priority: int | None = None
    created_at: datetime
    updated_at: datetime


class AdminImportBatchDetail(AdminImportBatchListItem):
    items: list[AdminImportQuestionItemBrief]
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
    subject: str | None = Field(None, deprecated=True, description="Deprecated alias of subject_id. Legacy subject string will be resolved to subject_id internally.")
    subject_id: int | None = None
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

    @field_validator("question_type")
    @classmethod
    def _validate_type(cls, v: str | None) -> str | None:
        if v is not None:
            validate_question_type(v)
        return v
    # ── 导入审核定位与答案状态字段 ──
    source_question_no: str | None = None
    source_question_label: str | None = None
    source_image_seq: int | None = None
    source_image_name: str | None = None
    source_page_start: int | None = None
    source_page_end: int | None = None
    source_order_index: int | None = None
    raw_text_preview: str | None = None
    answer_status: str | None = None
    answer_source: str | None = None
    answer_confidence: float | None = None
    review_priority: int | None = None


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
    fields: list[str] = Field(..., description="补全字段列表: answer, analysis, knowledge_points, difficulty, subject_id, question_type, stem, options, tips, tags")
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
    subject: str = Field("", deprecated=True, description="Deprecated alias of subject_id")
    subject_id: int | None = None


class TextParseQuestion(BaseModel):
    subject: str | None = Field(None, deprecated=True, description="Deprecated alias of subject_id")
    subject_id: int | None = None
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
    subject: str = Field("", deprecated=True, description="Deprecated alias of subject_id")
    subject_id: int | None = None
    stem: str
    options: list[dict] = []
    answer: str | list[str] | bool | None = None
    analysis: str | None = None
    question_type: str | None = None
    knowledge_points: list[str] = []
    difficulty: int = 3

    @field_validator("question_type")
    @classmethod
    def _validate_type(cls, v: str | None) -> str | None:
        if v is not None:
            validate_question_type(v)
        return v


class TextImportRequest(BaseModel):
    subject: str = Field("", deprecated=True, description="Deprecated alias of subject_id")
    subject_id: int | None = None
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


# --- 批量图片导题 ---

class BatchImageUploadResponse(BaseModel):
    job_id: str
    status: str
    total: int = 0  # 实际入队的图片数
    rejected: int = 0  # 上传时校验未通过、未入队的文件数
    rejected_files: list[str] = []
    concurrency: int = 2
    duplicate: bool = False  # true=命中 dedup，返回已有 job_id


class BatchImageJobItem(BaseModel):
    id: int
    seq: int
    source_file: str | None = None
    status: str  # pending | processing | succeeded | failed
    review_batch_id: str | None = None
    question_count: int = 0
    error_message: str | None = None
    has_ocr_cache: bool = False
    # Idempotency / trace identifiers (echoed back from upload)
    batch_import_id: str | None = None
    image_import_id: str | None = None
    request_id: str | None = None


class TraceEventItem(BaseModel):
    """Single trace event in the append-only event log.

    seq is per-job monotonic. item_seq=None means job-level event.
    """
    seq: int
    item_seq: int
    step: str
    status: str
    message: str
    duration_ms: int | None = None
    created_at: str
    request_id: str | None = None
    image_import_id: str | None = None
    batch_import_id: str | None = None


class BatchImageJobStatusResponse(BaseModel):
    job_id: str
    status: str  # queued | running | completed | failed
    source_type: str = "image"
    subject: str | None = Field(None, deprecated=True, description="Deprecated alias of subject_id")
    subject_id: int | None = None
    concurrency: int = 2
    total: int = 0
    completed: int = 0
    processing: int = 0
    pending: int = 0
    succeeded: int = 0
    failed: int = 0
    total_questions: int = 0
    merged_batch_id: str = ""
    is_merged: bool = False  # 显式标记跨图合并状态，替代隐式 review_batch_id 推断
    partial_failure: bool = False  # 部分成功（有成功也有失败）
    current_seq: int = 0
    current_file: str = ""
    error_message: str | None = None
    started_at: str = ""
    finished_at: str = ""
    items: list[BatchImageJobItem] = []
    trace_events: list[TraceEventItem] = []  # append-only event log (backend source of truth)


class BatchImageReparseResponse(BaseModel):
    item_id: int
    status: str
    review_batch_id: str | None = None
    question_count: int = 0
    error_message: str | None = None


# ── 快速补充答案 ──


class BatchAnswerPreviewRequest(BaseModel):
    raw_text: str = Field(..., max_length=50_000, description="用户输入的原始答案串")
    allow_partial_prefix: bool = True  # 允许只处理前 N 题


class BatchAnswerPreviewItem(BaseModel):
    import_id: int
    source_order_index: int | None = None
    source_question_no: str | None = None
    stem_excerpt: str = ""
    question_type: str | None = None
    original_answer: str | None = None
    input_answer: str | None = None
    normalized_answer: str | None = None
    status: str
    status_message: str = ""
    will_update: bool = False
    validation_errors: list[str] = []


class BatchAnswerPreviewSummary(BaseModel):
    batch_total: int = 0
    parsed_answer_count: int = 0
    target_question_count: int = 0
    remaining_question_count: int = 0
    writable_count: int = 0
    skipped_existing_count: int = 0
    skipped_existing_same_count: int = 0
    unsupported_count: int = 0
    invalid_count: int = 0
    warning_count: int = 0
    order_anomaly_count: int = 0


class BatchAnswerPreviewResponse(BaseModel):
    batch_id: str
    preview_token: str
    operation_id: str = ""
    summary: BatchAnswerPreviewSummary
    items: list[BatchAnswerPreviewItem]
    warnings: list[str] = []


class BatchAnswerApplyRequest(BaseModel):
    preview_token: str
    operation_id: str = ""


class BatchAnswerApplyResponse(BaseModel):
    operation_id: str = ""
    updated_count: int = 0
    skipped_existing_count: int = 0
    remaining_count: int = 0
    batch_stats: dict = {}


# ── 快速补充答案 — 图片导入（Phase 2） ──


class BatchAnswerImagePreviewMode(str, Enum):
    ANSWER_ONLY = "answer_only"
    ANSWER_ANALYSIS = "answer_analysis"


class BatchAnswerImagePreviewItem(BaseModel):
    import_id: int | None = None  # None = unmatched
    source_order_index: int | None = None
    source_question_no: str | None = None
    stem_excerpt: str = ""
    question_type: str | None = None
    original_answer: str | None = None
    original_analysis: str | None = None
    extracted_answer: str | None = None
    extracted_analysis: str | None = None
    status: str  # matched | unmatched | ambiguous
    status_message: str = ""
    will_update_answer: bool = False
    will_update_analysis: bool = False
    validation_errors: list[str] = []
    # Image provenance
    source_filename: str | None = None
    image_index: int | None = None
    ocr_confidence: float | None = None
    extract_method: str | None = None  # "rule" | "llm"
    raw_text_excerpt: str | None = None  # first 200 chars


class BatchAnswerImagePreviewSummary(BaseModel):
    total_images: int = 0
    extracted_entries: int = 0
    matched_count: int = 0
    unmatched_count: int = 0
    ambiguous_count: int = 0
    writable_answer_count: int = 0
    writable_analysis_count: int = 0
    skipped_existing_answer_count: int = 0
    skipped_existing_analysis_count: int = 0


class BatchAnswerImagePreviewResponse(BaseModel):
    batch_id: str
    preview_token: str
    operation_id: str = ""
    summary: BatchAnswerImagePreviewSummary
    items: list[BatchAnswerImagePreviewItem]
    warnings: list[str] = []


class BatchAnswerImageApplyRequest(BaseModel):
    preview_token: str
    operation_id: str = ""


class BatchAnswerImageApplyResponse(BaseModel):
    operation_id: str = ""
    updated_answer_count: int = 0
    updated_analysis_count: int = 0
    skipped_existing_answer_count: int = 0
    skipped_existing_analysis_count: int = 0
    remaining_count: int = 0
    batch_stats: dict = {}
