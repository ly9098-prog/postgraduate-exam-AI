import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.cache import cache
from app.core.database import get_db
from app.core.security import get_current_user
from app.features.text_normalizer import _split_inline_roman_subitems
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.schemas.common import RawPaginatedResponse, paginated_response
from app.schemas.wrong_question import (
    TaskFlowResponse,
    WrongQuestionBatchRequest,
    WrongQuestionBatchResponse,
    WrongQuestionResponse,
    WrongQuestionStats,
    WrongQuestionUpdate,
)
from app.services import wrong_question_service as svc
from app.services.knowledge_point_service import load_question_kps
from app.services.pdf_text_normalizer import deduplicate_repeated_text
from app.utils.question_content import strip_student_segment_metadata

# Regex: lines ending with a trailing operator (OCR-split code expressions)
_CODE_OP_SPLIT_RE = re.compile(
    r'(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$'
)

_CODE_SIGNALS = [
    'return', 'printf', 'scanf', 'malloc', 'free', 'NULL',
    'struct', 'typedef', 'enum', 'union',
    'int ', 'void ', 'char ', 'float ', 'double ',
    'bool', 'const', 'static', 'sizeof',
    '->', '::', '{', '}', ';',
    '++', '--', '+=', '-=', '*=', '/=',
    '#include', '#define',
]
_CONTROL_KW = [
    'for', 'while', 'if', 'else if', 'else', 'switch',
    'return', 'break', 'continue', 'case', 'do',
]
_DS_KW = [
    'LNode', 'TNode', 'BiTNode', 'BiTree', 'BSTNode', 'LinkList',
    'SqList', 'Stack', 'Queue', 'SqStack', 'ElemType', 'Status',
]


def _contains_code(text: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    score = sum(1 for sig in _CODE_SIGNALS if sig in text)
    score += sum(2 for kw in _DS_KW if kw in text)
    score += sum(
        1 for kw in _CONTROL_KW
        if re.search(r'\b' + re.escape(kw) + r'\b', text)
    )
    return score >= 3

router = APIRouter(prefix="/api/v1/wrong-questions")


def _fix_code_operator_splits(text: str) -> str:
    """Merge lines where a trailing operator was split across newlines by OCR."""
    if not isinstance(text, str) or "\n" not in text:
        return text
    lines = text.split("\n")
    merged = [lines[0]]
    for line in lines[1:]:
        if _CODE_OP_SPLIT_RE.search(merged[-1]):
            merged[-1] += line.lstrip()
        else:
            merged.append(line)
    return "\n".join(merged)


def _sanitize_text_field(value: str | None) -> str | None:
    if not isinstance(value, str):
        return value
    value = re.sub(r"\r\n?", "\n", value)
    # Preserve code indentation/repeated statements. Applying ordinary OCR
    # dedup/roman splitting to code can silently change the question itself.
    if _contains_code(value):
        return _fix_code_operator_splits(value)
    value = deduplicate_repeated_text(value)
    value = _split_inline_roman_subitems(value)
    return _fix_code_operator_splits(value)


def _sanitize_content(content: dict | str | None) -> dict | None:
    if isinstance(content, str):
        content = {"text": content}
    if not isinstance(content, dict):
        return None
    sanitized = dict(content)
    for field in ("text", "stem"):
        if field in sanitized:
            sanitized[field] = _sanitize_text_field(sanitized[field])

    # Prefer stem over text when both exist — stem has better code formatting
    if "text" in sanitized and "stem" in sanitized and sanitized.get("stem"):
        sanitized["text"] = sanitized["stem"]

    # Strip admin-only fields
    sanitized.pop("source_snapshot_url", None)
    sanitized.pop("source_snapshot_full_page", None)
    sanitized.pop("visual_regions", None)
    sanitized.pop("visual_region_ids", None)

    return strip_student_segment_metadata(sanitized)


def _sanitize_option_value(value: str | None) -> str | None:
    """Sanitize an option without roman-subitem splitting or deduplication."""
    if not isinstance(value, str):
        return value
    value = re.sub(r"\r\n?", "\n", value)
    value = _fix_code_operator_splits(value)
    return re.sub(r"\n+", " ", value).strip()


def _sanitize_options(options: dict | None) -> dict | None:
    if not isinstance(options, dict):
        return options
    sanitized = dict(options)
    for key, value in sanitized.items():
        if isinstance(value, dict):
            rich = dict(value)
            text = rich.get("text")
            if text in (None, ""):
                text = rich.get("value")
            if isinstance(text, str):
                rich["text"] = _sanitize_option_value(text)
            sanitized[key] = rich
        else:
            sanitized[key] = _sanitize_option_value(value)
    return sanitized


def enrich_wq(wq, question, knowledge_points=None, **extra):
    ai_analysis = extra["ai_analysis_override"] if "ai_analysis_override" in extra else wq.ai_analysis
    raw_ai_analysis = wq.ai_analysis if isinstance(wq.ai_analysis, dict) else {}
    raw_ai_meta = raw_ai_analysis.get("_meta") if isinstance(raw_ai_analysis, dict) else None
    raw_generated_at = (
        str(raw_ai_meta.get("generated_at") or "").strip()
        if isinstance(raw_ai_meta, dict)
        else ""
    )
    ai_status = extra.get("ai_analysis_status_override")
    if ai_status is None:
        ai_status = "ready" if isinstance(ai_analysis, dict) and ai_analysis else "empty"
    # 硬删除的题（question 为 None）→ knowledge_points 应为 None 而非 []；
    # 存活但无知识点的题 → []。不依赖调用方是否传默认值。
    if question is None:
        kps = None
    else:
        kps = knowledge_points if knowledge_points is not None else []
    return WrongQuestionResponse(
        id=wq.id,
        question_id=wq.question_id,
        wrong_answer=wq.wrong_answer,
        error_type=wq.error_type,
        review_count=wq.review_count,
        created_at=wq.created_at,
        updated_at=wq.updated_at,
        subject_id=question.subject_id if question else None,
        subject_code=question.subject_ref.code if question and question.subject_ref else None,
        subject_name=question.subject_ref.name if question and question.subject_ref else None,
        question_type=question.question_type if question else None,
        content=_sanitize_content(question.content) if question else None,
        options=_sanitize_options(question.options) if question else None,
        answer=question.answer if question else None,
        analysis=question.analysis if question else None,
        knowledge_points=kps,
        image_url=question.image_url if question else None,
        ai_analysis=ai_analysis,
        ai_analysis_status=ai_status,
        ai_analysis_generated_at=raw_generated_at or None,
        # New enriched fields
        wrong_count=extra.get("wrong_count", wq.review_count or 0),
        review_record_count=extra.get("review_record_count", 0),
        mastery_percent=extra.get("mastery_percent", 0.0),
        is_mastered=extra.get("is_mastered", wq.mastered or False),
        next_review_at=extra.get("next_review_at", None),
        last_reviewed_at=extra.get("last_reviewed_at", None),
        last_wrong_at=extra.get("last_wrong_at", wq.last_review_at),
    )


async def _load_current_question_view(db: AsyncSession, wq: WrongQuestion):
    """Load the current question-bank projection for wrong-book display.

    ``WrongQuestion.question_version_id`` intentionally remains the immutable
    revision that produced the learner's latest wrong answer.  It is still used
    by review records/schedules for historical grading, but the wrong-book UI
    must follow the latest published question content after an admin correction.
    """
    result = await db.execute(
        select(Question)
        .options(joinedload(Question.subject_ref))
        .where(Question.id == wq.question_id)
    )
    question = result.scalar_one_or_none()
    if question is None:
        return None, []
    kp_map = await load_question_kps(db, [int(question.id)])
    return question, kp_map.get(int(question.id), [])


async def _enrich_single_wq_extra(
    db: AsyncSession, user_id: int, wq: WrongQuestion
) -> dict:
    """Compute enrichment fields for a single WrongQuestion (detail endpoints)."""
    review_record_count = int((
        await db.scalar(
            select(func.count(ReviewRecord.id)).where(
                ReviewRecord.question_id == wq.question_id,
                ReviewRecord.question_version_id == wq.question_version_id,
                ReviewRecord.user_id == user_id,
            )
        )
    ) or 0)

    schedule = await db.scalar(
        select(ReviewSchedule).where(
            ReviewSchedule.question_id == wq.question_id,
            ReviewSchedule.question_version_id == wq.question_version_id,
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.is_active,
        )
    )
    from app.services.review_scheduler import review_mastery_percent

    is_mastered = bool(wq.mastered or (schedule and schedule.mastered))
    mastery_percent = 1.0 if is_mastered else round(
        review_mastery_percent(schedule.repetitions if schedule else 0) / 100, 4
    )
    return {
        "review_record_count": review_record_count,
        "next_review_at": schedule.next_review_at if schedule and not schedule.mastered else None,
        "last_reviewed_at": schedule.last_reviewed_at if schedule else None,
        "mastery_percent": mastery_percent,
    }


@router.get("", response_model=RawPaginatedResponse)
async def list_wrong(
    subject_id: int | None = Query(None),
    error_type: str | None = Query(None),
    topic: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await svc.list_wrong_enriched(
        db, current_user.id, subject_id, error_type, topic, page, page_size
    )

    # Apply text sanitization
    for item in items:
        item["content"] = _sanitize_content(item.get("content"))
        item["options"] = _sanitize_options(item.get("options"))

    return paginated_response(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=WrongQuestionStats)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stats = await svc.get_stats(db, current_user.id)
    return WrongQuestionStats(**stats)


@router.get("/task-flow", response_model=TaskFlowResponse)
async def get_task_flow(
    subject_id: int | None = Query(None),
    error_type: str | None = Query(None),
    topic: str | None = Query(None),
    preview_size: int = Query(3, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """错题任务流分组：今日应复习 → 高频错题 → 最近新增 → 待巩固 → 已掌握."""
    result = await svc.get_task_flow(
        db, current_user.id, subject_id, error_type, topic, preview_size
    )
    # Keep task-flow preview rows byte-for-byte compatible with the ordinary
    # wrong-question list rendering contract.  Without this, switching views
    # could reintroduce raw OCR newlines/admin-only content for the same item.
    for group in result.get("groups", []):
        for item in group.get("items", []):
            item["content"] = _sanitize_content(item.get("content"))
            item["options"] = _sanitize_options(item.get("options"))
    return result


@router.get("/{wq_id}", response_model=WrongQuestionResponse)
async def get_wrong(
    wq_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单条错题详情（含关联题目信息）"""
    wq = await svc.get_by_id(db, current_user.id, wq_id)
    if not wq:
        raise HTTPException(status_code=404, detail="错题记录不存在")

    question, knowledge_points = await _load_current_question_view(db, wq)
    extra = await _enrich_single_wq_extra(db, current_user.id, wq)
    if question is not None:
        from app.services import ai_service

        cache_state = await ai_service.evaluate_cached_error_analysis(
            db,
            wq,
            question,
            knowledge_points=knowledge_points,
        )
        extra["ai_analysis_override"] = cache_state.get("analysis")
        extra["ai_analysis_status_override"] = cache_state.get("status")
    return enrich_wq(wq, question, knowledge_points=knowledge_points, **extra)


@router.put("/{wq_id}", response_model=WrongQuestionResponse)
async def update_wrong(
    wq_id: int,
    data: WrongQuestionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wq = await svc.update_wrong(
        db, current_user.id, wq_id, data.error_type
    )
    if not wq:
        raise HTTPException(status_code=404, detail="错题记录不存在")

    question, knowledge_points = await _load_current_question_view(db, wq)
    extra = await _enrich_single_wq_extra(db, current_user.id, wq)
    return enrich_wq(wq, question, knowledge_points=knowledge_points, **extra)



@router.post("/batch", response_model=WrongQuestionBatchResponse)
async def batch_operate(
    data: WrongQuestionBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量操作错题本记录。id 去重后限制 1~100；非本人的记录静默跳过。"""
    result = await svc.batch_operate(db, current_user.id, data.action.value, data.ids)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail="批量操作失败")

    # Invalidate caches so list/stats/dashboard reflect changes immediately
    uid = current_user.id
    patterns = [
        f"wrong_questions:*:{uid}*",
        f"stats:*:{uid}*",
        # review 缓存键实际形态包括 review:today:{uid}:...、
        # review:today_overview:{uid}、review:schedule_stats:{uid}:...。
        # 旧 pattern 的 uid 位置写反，导致掌握/重新加入后入口页短暂显示旧数量。
        f"review:*:{uid}*",
        f"stats:dashboard*:{uid}*",
    ]
    for p in patterns:
        await cache.delete(p)

    return result
