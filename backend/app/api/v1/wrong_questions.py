import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Float, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import cache
from app.core.database import get_db
from app.core.security import get_current_user
from app.features.text_normalizer import _split_inline_roman_subitems
from app.models.question import Question
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.user import User
from app.models.user_question_state import UserQuestionState
from app.models.wrong_question import WrongQuestion
from app.schemas.common import RawPaginatedResponse, paginated_response
from app.schemas.wrong_question import (
    TaskFlowResponse,
    WrongQuestionBatchRequest,
    WrongQuestionBatchResponse,
    WrongQuestionQualityUpdate,
    WrongQuestionResponse,
    WrongQuestionStats,
    WrongQuestionUpdate,
)
from app.services import wrong_question_service as svc
from app.services.knowledge_point_service import load_question_kps
from app.services.pdf_text_normalizer import deduplicate_repeated_text

# Regex: lines ending with a trailing operator (OCR-split code expressions)
_CODE_OP_SPLIT_RE = re.compile(
    r'(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$'
)

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
    value = deduplicate_repeated_text(value)
    value = _split_inline_roman_subitems(value)
    value = _fix_code_operator_splits(value)
    return value


def _sanitize_content(content: dict | None) -> dict | None:
    if not isinstance(content, dict):
        return content
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

    return sanitized


def _sanitize_option_value(value: str | None) -> str | None:
    """Sanitize a single option value — skip roman-subitem splitting.

    Option values are short display text (e.g. \"I、II、III\", \"O(n)\").
    Applying _split_inline_roman_subitems here corrupts enumeration values
    by inserting newlines inside short option text. Only apply code-operator
    split (for code options) and skip dedup/roman-split entirely.
    """
    if not isinstance(value, str):
        return value
    value = _fix_code_operator_splits(value)
    return value


def _sanitize_options(options: dict | None) -> dict | None:
    if not isinstance(options, dict):
        return options
    sanitized = dict(options)
    for key, value in sanitized.items():
        sanitized[key] = _sanitize_option_value(value)
    return sanitized


def enrich_wq(wq, question, knowledge_points=None, **extra):
    ai_status = "ready" if isinstance(wq.ai_analysis, dict) and wq.ai_analysis else "empty"
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
        ai_analysis=wq.ai_analysis,
        ai_analysis_status=ai_status,
        # New enriched fields
        wrong_count=extra.get("wrong_count", wq.review_count or 0),
        review_record_count=extra.get("review_record_count", 0),
        mastery_percent=extra.get("mastery_percent", 0.0),
        is_mastered=extra.get("is_mastered", wq.mastered or False),
        next_review_at=extra.get("next_review_at", None),
        last_reviewed_at=extra.get("last_reviewed_at", None),
        last_wrong_at=extra.get("last_wrong_at", wq.last_review_at),
    )


async def _enrich_single_wq_extra(
    db: AsyncSession, user_id: int, wq: WrongQuestion
) -> dict:
    """Compute enrichment fields for a single WrongQuestion (detail endpoints)."""
    review_record_count = (
        await db.execute(
            select(func.count(ReviewRecord.id)).where(
                ReviewRecord.question_id == wq.question_id,
                ReviewRecord.user_id == user_id,
            )
        )
    ).scalar() or 0

    next_review = await db.execute(
        select(ReviewSchedule.next_review_at).where(
            ReviewSchedule.question_id == wq.question_id,
            ReviewSchedule.user_id == user_id,
            ~ReviewSchedule.mastered,
        ).order_by(ReviewSchedule.next_review_at.asc().nulls_last()).limit(1)
    )

    last_reviewed = await db.execute(
        select(ReviewSchedule.last_reviewed_at).where(
            ReviewSchedule.question_id == wq.question_id,
            ReviewSchedule.user_id == user_id,
        ).order_by(ReviewSchedule.last_reviewed_at.desc().nulls_last()).limit(1)
    )

    mastery_pct = (
        await db.execute(
            select(
                case(
                    (UserQuestionState.answer_count > 0,
                     func.cast(UserQuestionState.correct_count, Float) /
                     func.cast(UserQuestionState.answer_count, Float)),
                    else_=0.0,
                )
            ).where(
                UserQuestionState.question_id == wq.question_id,
                UserQuestionState.user_id == user_id,
            )
        )
    ).scalar() or 0.0

    return {
        "review_record_count": review_record_count,
        "next_review_at": next_review.scalar_one_or_none(),
        "last_reviewed_at": last_reviewed.scalar_one_or_none(),
        "mastery_percent": round(float(mastery_pct), 4),
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

    result = await db.execute(
        select(Question).options(selectinload(Question.subject_ref)).where(Question.id == wq.question_id)
    )
    question = result.scalar_one_or_none()
    kp_map = await load_question_kps(db, [wq.question_id])
    extra = await _enrich_single_wq_extra(db, current_user.id, wq)
    return enrich_wq(wq, question, knowledge_points=kp_map.get(wq.question_id, []), **extra)


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

    result = await db.execute(
        select(Question).options(selectinload(Question.subject_ref)).where(Question.id == wq.question_id)
    )
    question = result.scalar_one_or_none()
    kp_map = await load_question_kps(db, [wq.question_id])
    extra = await _enrich_single_wq_extra(db, current_user.id, wq)
    return enrich_wq(wq, question, knowledge_points=kp_map.get(wq.question_id, []), **extra)


@router.put("/{wq_id}/quality", response_model=WrongQuestionResponse)
async def rate_quality(
    wq_id: int,
    data: WrongQuestionQualityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wq = await svc.update_quality(db, current_user.id, wq_id, data.quality)
    if not wq:
        raise HTTPException(status_code=404, detail="错题记录不存在")

    result = await db.execute(
        select(Question).options(selectinload(Question.subject_ref)).where(Question.id == wq.question_id)
    )
    question = result.scalar_one_or_none()
    kp_map = await load_question_kps(db, [wq.question_id])
    extra = await _enrich_single_wq_extra(db, current_user.id, wq)
    return enrich_wq(wq, question, knowledge_points=kp_map.get(wq.question_id, []), **extra)


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
        f"review:today:*:{uid}*",
        f"stats:dashboard*:{uid}*",
    ]
    for p in patterns:
        await cache.delete(p)

    return result
