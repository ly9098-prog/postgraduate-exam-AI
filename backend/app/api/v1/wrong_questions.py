import builtins as _wrong_book_builtins
import re
from datetime import date

from fastapi import (  # noqa: F401 -- live route dependency port
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from sqlalchemy import case, func, select  # noqa: F401 -- live route dependency port
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload  # noqa: F401 -- live route dependency port

from app.core.cache import cache  # noqa: F401 -- live route dependency port
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.subject_scope import (
    selected_408_subject_ids,  # noqa: F401 -- live route dependency port
)
from app.features.text_normalizer import (
    _split_inline_roman_subitems,  # noqa: F401 -- live route dependency port
)
from app.models.admin import Subject  # noqa: F401 -- live route dependency port
from app.models.question import Question
from app.models.review_scheduler import (  # noqa: F401 -- live route dependency port
    ReviewRecord,
    ReviewSchedule,
)
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.schemas.common import (  # noqa: F401 -- live route dependency port
    RawPaginatedResponse,
    paginated_response,
)
from app.schemas.error_diagnosis import (
    ErrorDiagnosisConfirmRequest,
    ErrorDiagnosisResponse,
    ErrorDiagnosisStatsResponse,
    ErrorDiagnosisSuggestResponse,
    ErrorTaxonomyItem,
)
from app.schemas.wrong_question import (
    TaskFlowResponse,
    WrongQuestionBatchRequest,
    WrongQuestionBatchResponse,
    WrongQuestionResponse,
    WrongQuestionStats,
    WrongQuestionUpdate,
)
from app.services import error_diagnosis_service
from app.services import wrong_book_diagnosis as _wrong_wrong_book_diagnosis
from app.services import wrong_book_mutations as _wrong_wrong_book_mutations
from app.services import wrong_book_projection as _wrong_wrong_book_projection
from app.services import wrong_book_queries as _wrong_wrong_book_queries
from app.services import wrong_book_reading as _wrong_wrong_book_reading
from app.services import wrong_book_sanitization as _wrong_wrong_book_sanitization
from app.services import wrong_question_service as svc
from app.services.knowledge_point_service import (
    load_question_kps,  # noqa: F401 -- live route dependency port
)
from app.services.pdf_text_normalizer import (
    deduplicate_repeated_text,  # noqa: F401 -- live route dependency port
)
from app.utils.question_content import (
    reconcile_student_stem_fields,  # noqa: F401 -- live route dependency port
    strip_student_segment_metadata,  # noqa: F401 -- live route dependency port
)


def _wrong_book_port(name):
    """Read original route dependencies at their use sites."""
    if name in globals():
        return globals()[name]
    return getattr(_wrong_book_builtins, name)


# Regex: lines ending with a trailing operator (OCR-split code expressions)
_CODE_OP_SPLIT_RE = re.compile(r"(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$")

_CODE_SIGNALS = [
    "return",
    "printf",
    "scanf",
    "malloc",
    "free",
    "NULL",
    "struct",
    "typedef",
    "enum",
    "union",
    "int ",
    "void ",
    "char ",
    "float ",
    "double ",
    "bool",
    "const",
    "static",
    "sizeof",
    "->",
    "::",
    "{",
    "}",
    ";",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    "#include",
    "#define",
]
_CONTROL_KW = [
    "for",
    "while",
    "if",
    "else if",
    "else",
    "switch",
    "return",
    "break",
    "continue",
    "case",
    "do",
]
_DS_KW = [
    "LNode",
    "TNode",
    "BiTNode",
    "BiTree",
    "BSTNode",
    "LinkList",
    "SqList",
    "Stack",
    "Queue",
    "SqStack",
    "ElemType",
    "Status",
]


def _contains_code(text: str) -> bool:
    return _wrong_wrong_book_sanitization._contains_code(text, ports=_wrong_book_port)


router = APIRouter(prefix="/api/v1/wrong-questions")


async def _resolve_product_subject_ids(
    db: AsyncSession, product_scope: str | None
) -> set[int] | None:
    return await _wrong_wrong_book_queries._resolve_product_subject_ids(
        db, product_scope, ports=_wrong_book_port
    )


def _fix_code_operator_splits(text: str) -> str:
    """Merge lines where a trailing operator was split across newlines by OCR."""
    return _wrong_wrong_book_sanitization._fix_code_operator_splits(
        text, ports=_wrong_book_port
    )


def _sanitize_text_field(value: str | None) -> str | None:
    return _wrong_wrong_book_sanitization._sanitize_text_field(
        value, ports=_wrong_book_port
    )


def _sanitize_content(content: dict | str | None) -> dict | None:
    return _wrong_wrong_book_sanitization._sanitize_content(
        content, ports=_wrong_book_port
    )


def _sanitize_option_value(value: str | None) -> str | None:
    """Sanitize an option without roman-subitem splitting or deduplication."""
    return _wrong_wrong_book_sanitization._sanitize_option_value(
        value, ports=_wrong_book_port
    )


def _sanitize_options(options: dict | None) -> dict | None:
    return _wrong_wrong_book_sanitization._sanitize_options(
        options, ports=_wrong_book_port
    )


def enrich_wq(wq, question, knowledge_points=None, **extra):
    return _wrong_wrong_book_projection.enrich_wq(
        _wrong_book_port, wq, question, knowledge_points, **extra
    )


async def _load_current_question_view(db: AsyncSession, wq: WrongQuestion):
    """Load the current question-bank projection for wrong-book display.

    ``WrongQuestion.question_version_id`` intentionally remains the immutable
    revision that produced the learner's latest wrong answer.  It is still used
    by review records/schedules for historical grading, but the wrong-book UI
    must follow the latest published question content after an admin correction.
    """
    return await _wrong_wrong_book_queries._load_current_question_view(
        db, wq, ports=_wrong_book_port
    )


async def _load_wrong_detail_view(
    db: AsyncSession, user_id: int, wq_id: int
) -> tuple[WrongQuestion | None, Question | None, list]:
    """Load the wrong row and current question projection in one round trip.

    The detail endpoint previously queried ``wrong_questions`` and ``questions``
    serially before any enrichment work. This join preserves the same ownership
    and active-row semantics while removing one latency-sensitive DB hop.
    Knowledge-point names remain a separate batched lookup.
    """
    return await _wrong_wrong_book_queries._load_wrong_detail_view(
        db, user_id, wq_id, ports=_wrong_book_port
    )


async def _enrich_single_wq_extra(
    db: AsyncSession, user_id: int, wq: WrongQuestion
) -> dict:
    """Compute detail enrichment in one database round trip.

    The wrong-detail screen is latency-sensitive and this data used to be read
    with two serial queries. Aggregate schedule fields so the query still
    returns one row when no active schedule exists, while the scalar count keeps
    the review-record lookup index friendly.
    """
    return await _wrong_wrong_book_queries._enrich_single_wq_extra(
        db, user_id, wq, ports=_wrong_book_port
    )


def _validate_wrong_book_dates(date_from: date | None, date_to: date | None) -> None:
    return _wrong_wrong_book_queries._validate_wrong_book_dates(
        date_from, date_to, ports=_wrong_book_port
    )


@router.get("", response_model=RawPaginatedResponse)
async def list_wrong(
    subject_id: int | None = Query(None),
    error_type: str | None = Query(None),
    topic: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    product_scope: str | None = Query(None),
    date_from: date | None = Query(
        None, description="加入错题本的起始日期（北京时间，含当天）"
    ),
    date_to: date | None = Query(
        None, description="加入错题本的结束日期（北京时间，含当天）"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _wrong_wrong_book_reading.list_wrong(
        subject_id,
        error_type,
        topic,
        page,
        page_size,
        product_scope,
        date_from,
        date_to,
        db,
        current_user,
        ports=_wrong_book_port,
    )


@router.get("/stats", response_model=WrongQuestionStats)
async def get_stats(
    product_scope: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_subject_ids = await _resolve_product_subject_ids(db, product_scope)
    stats = await svc.get_stats(
        db, current_user.id, allowed_subject_ids=allowed_subject_ids
    )
    return WrongQuestionStats(**stats)


@router.get("/task-flow", response_model=TaskFlowResponse)
async def get_task_flow(
    subject_id: int | None = Query(None),
    error_type: str | None = Query(None),
    topic: str | None = Query(None),
    preview_size: int = Query(3, ge=1, le=10),
    product_scope: str | None = Query(None),
    date_from: date | None = Query(
        None, description="加入错题本的起始日期（北京时间，含当天）"
    ),
    date_to: date | None = Query(
        None, description="加入错题本的结束日期（北京时间，含当天）"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """错题任务流分组：今日应复习 → 高频错题 → 最近新增 → 待巩固 → 已掌握."""
    return await _wrong_wrong_book_reading.get_task_flow(
        subject_id,
        error_type,
        topic,
        preview_size,
        product_scope,
        date_from,
        date_to,
        db,
        current_user,
        ports=_wrong_book_port,
    )


@router.get("/diagnosis/taxonomy", response_model=list[ErrorTaxonomyItem])
async def get_error_diagnosis_taxonomy(
    current_user: User = Depends(get_current_user),
):
    return error_diagnosis_service.taxonomy_items()


@router.get("/diagnosis/stats", response_model=ErrorDiagnosisStatsResponse)
async def get_error_diagnosis_stats(
    window_days: int = Query(30, ge=7, le=365),
    subject_id: int | None = Query(None),
    knowledge_point_id: int | None = Query(None),
    product_scope: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_subject_ids = await _resolve_product_subject_ids(db, product_scope)
    return await error_diagnosis_service.get_stats(
        db,
        user_id=current_user.id,
        window_days=window_days,
        subject_id=subject_id,
        knowledge_point_id=knowledge_point_id,
        allowed_subject_ids=allowed_subject_ids,
    )


@router.get("/{wq_id}", response_model=WrongQuestionResponse)
async def get_wrong(
    wq_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单条错题详情（含关联题目信息）"""
    return await _wrong_wrong_book_reading.get_wrong(
        wq_id, db, current_user, ports=_wrong_book_port
    )


@router.get("/{wq_id}/diagnosis", response_model=ErrorDiagnosisResponse)
async def get_wrong_error_diagnosis(
    wq_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _wrong_wrong_book_diagnosis.get_wrong_error_diagnosis(
        wq_id, db, current_user, ports=_wrong_book_port
    )


@router.put("/{wq_id}/diagnosis", response_model=ErrorDiagnosisResponse)
async def confirm_wrong_error_diagnosis(
    wq_id: int,
    data: ErrorDiagnosisConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _wrong_wrong_book_diagnosis.confirm_wrong_error_diagnosis(
        wq_id, data, db, current_user, ports=_wrong_book_port
    )


@router.post("/{wq_id}/diagnosis/suggest", response_model=ErrorDiagnosisSuggestResponse)
async def suggest_wrong_error_diagnosis(
    wq_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _wrong_wrong_book_diagnosis.suggest_wrong_error_diagnosis(
        wq_id, db, current_user, ports=_wrong_book_port
    )


@router.put("/{wq_id}", response_model=WrongQuestionResponse)
async def update_wrong(
    wq_id: int,
    data: WrongQuestionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _wrong_wrong_book_mutations.update_wrong(
        wq_id, data, db, current_user, ports=_wrong_book_port
    )


@router.post("/batch", response_model=WrongQuestionBatchResponse)
async def batch_operate(
    data: WrongQuestionBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量操作错题本记录。id 去重后限制 1~100；非本人的记录静默跳过。"""
    return await _wrong_wrong_book_mutations.batch_operate(
        data, db, current_user, ports=_wrong_book_port
    )
