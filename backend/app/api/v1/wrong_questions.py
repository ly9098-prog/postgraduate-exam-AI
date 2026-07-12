import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import cache
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.question import Question
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.wrong_question import (
    BatchAction,
    WrongQuestionBatchRequest,
    WrongQuestionBatchResponse,
    WrongQuestionQualityUpdate,
    WrongQuestionResponse,
    WrongQuestionStats,
    WrongQuestionUpdate,
    TaskFlowResponse,
)
from app.services import wrong_question_service as svc
from app.features.text_normalizer import _split_inline_roman_subitems
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


def enrich_wq(wq, question):
    ai_status = "ready" if isinstance(wq.ai_analysis, dict) and wq.ai_analysis else "empty"
    return WrongQuestionResponse(
        id=wq.id,
        question_id=wq.question_id,
        wrong_answer=wq.wrong_answer,
        error_type=wq.error_type,
        review_count=wq.review_count,
        created_at=wq.created_at,
        updated_at=wq.updated_at,
        subject=question.subject_ref.code if question and question.subject_ref else None,
        question_type=question.question_type if question else None,
        content=_sanitize_content(question.content) if question else None,
        options=_sanitize_options(question.options) if question else None,
        answer=question.answer if question else None,
        analysis=question.analysis if question else None,
        knowledge_points=question.knowledge_points if question else None,
        ai_analysis=wq.ai_analysis,
        ai_analysis_status=ai_status,
    )


@router.get("")
async def list_wrong(
    subject: str | None = Query(None),
    error_type: str | None = Query(None),
    topic: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await svc.list_wrong_enriched(
        db, current_user.id, subject, error_type, topic, page, page_size
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
    subject: str | None = Query(None),
    error_type: str | None = Query(None),
    topic: str | None = Query(None),
    preview_size: int = Query(3, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """错题任务流分组：今日应复习 → 高频错题 → 最近新增 → 待巩固 → 已掌握."""
    result = await svc.get_task_flow(
        db, current_user.id, subject, error_type, topic, preview_size
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
    return enrich_wq(wq, question)


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
    return enrich_wq(wq, question)


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
    return enrich_wq(wq, question)


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
