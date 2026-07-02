import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.question import Question
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.wrong_question import (
    WrongQuestionQualityUpdate,
    WrongQuestionResponse,
    WrongQuestionStats,
    WrongQuestionUpdate,
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
    )


@router.get("")
async def list_wrong(
    subject: str | None = Query(None),
    error_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await svc.list_wrong(
        db, current_user.id, subject, error_type, page, page_size
    )

    question_ids = [w.question_id for w in items]
    if question_ids:
        result = await db.execute(
            select(Question).options(selectinload(Question.subject_ref)).where(Question.id.in_(question_ids))
        )
        questions = {q.id: q for q in result.scalars().all()}
    else:
        questions = {}

    return paginated_response(
        items=[enrich_wq(w, questions.get(w.question_id)) for w in items],
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
