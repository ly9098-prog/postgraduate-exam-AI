import hashlib
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db

logger = logging.getLogger(__name__)
from app.core.security import get_current_user
from app.models.question import Question
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.practice import (
    AnswerResult,
    AnswerSubmit,
    BatchSubmitRequest,
    BatchSubmitResponse,
    PracticeQuestionsResponse,
    PracticeQuestion,
    PracticeRecordItem,
    PracticeStatsResponse,
)
from app.services import practice_service as svc
from app.services.pdf_text_normalizer import deduplicate_repeated_text
from app.utils.trace.debug import create_trace_id, debug_log, save_debug_snapshot

_TRUE_FALSE_OPTIONS = {"A": "正确", "B": "错误"}


def _ensure_true_false_options(question_type: str, options: dict | None) -> dict | None:
    if question_type in ("true_false", "judgement") and not options:
        return _TRUE_FALSE_OPTIONS
    return options


def _sanitize_text_field(value: str | None) -> str | None:
    if not isinstance(value, str):
        return value
    return deduplicate_repeated_text(value)


def _sanitize_question_content(content: dict | None) -> dict | None:
    if not isinstance(content, dict):
        return content

    sanitized = dict(content)
    for field in ("text", "stem"):
        if field in sanitized:
            sanitized[field] = _sanitize_text_field(sanitized[field])
    return sanitized


def _sanitize_question_options(options: dict | None) -> dict | None:
    if not isinstance(options, dict):
        return options

    sanitized = dict(options)
    for key, value in sanitized.items():
        sanitized[key] = _sanitize_text_field(value)
    return sanitized


router = APIRouter(prefix="/api/v1/practice")


@router.get("/questions")
async def get_practice_questions(
    subject: str = Query(...),
    count: int = Query(20, ge=1, le=50),
    mode: str = Query("random"),
    knowledge_point: str | None = Query(None),
    exclude_answered: bool = Query(False),
    x_trace_id: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trace_id = x_trace_id or create_trace_id()
    kps = (
        [kp.strip() for kp in knowledge_point.split(",") if kp.strip()]
        if knowledge_point
        else None
    )
    questions = await svc.get_practice_questions(
        db=db,
        user_id=current_user.id,
        subject=subject,
        count=count,
        mode=mode,
        knowledge_points=kps,
        exclude_answered=exclude_answered,
    )
    # ── Layer 1 诊断：API 响应 stem 数据 ──
    for q in questions:
        content = _sanitize_question_content(q.content)
        stem = (content or {}).get("text") or (content or {}).get("stem") or ""
        logger.info(
            "[API_LAYER] qid=%s textLen=%d textHash=%s stemKeys=%s",
            q.id,
            len(stem),
            hashlib.sha256(stem.encode()).hexdigest()[:8],
            [k for k in (content or {}) if k in ("text", "stem", "segments")],
        )
    response = PracticeQuestionsResponse(
        questions=[
            PracticeQuestion(
                id=q.id,
                subject=q.subject,
                question_type=q.question_type,
                content=_sanitize_question_content(q.content),
                options=_sanitize_question_options(
                    _ensure_true_false_options(q.question_type, q.options)
                ),
                knowledge_points=q.knowledge_points,
                difficulty=q.difficulty,
                trace_id=trace_id,
            )
            for q in questions
        ],
        total=len(questions),
        mode=mode,
        trace_id=trace_id,
    )
    debug_log(
        trace_id,
        "API_RESPONSE",
        {"endpoint": "practice/questions", "subject": subject, "count": len(questions)},
    )
    save_debug_snapshot(
        trace_id,
        "api_response",
        {
            "endpoint": "practice/questions",
            "subject": subject,
            "question_ids": [q.id for q in questions],
            "total": len(questions),
        },
    )
    return response


@router.post("/submit", response_model=AnswerResult)
async def submit_answer(
    data: AnswerSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await svc.submit_answer(
            db=db,
            user_id=current_user.id,
            question_id=data.question_id,
            user_answer=data.user_answer,
            used_time=data.used_time,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 失效用户相关缓存
    await cache.delete(f"practice:stats:{current_user.id}:*")
    await cache.delete(f"stats:*:{current_user.id}*")

    return AnswerResult(**result)


@router.post("/batch-submit", response_model=BatchSubmitResponse)
async def batch_submit(
    data: BatchSubmitRequest,
    x_trace_id: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trace_id = x_trace_id or create_trace_id()
    debug_log(
        trace_id,
        "SUBMIT",
        {"endpoint": "practice/batch-submit", "answer_count": len(data.answers)},
    )
    save_debug_snapshot(
        trace_id,
        "submit_before",
        {"question_ids": [answer.question_id for answer in data.answers]},
    )
    try:
        result = await svc.batch_submit_answers(
            db=db,
            user_id=current_user.id,
            answers=[a.model_dump() for a in data.answers],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 失效用户相关缓存
    await cache.delete(f"practice:stats:{current_user.id}:*")
    await cache.delete(f"stats:*:{current_user.id}*")
    await cache.delete(f"review:*:{current_user.id}*")

    save_debug_snapshot(
        trace_id,
        "submit_after",
        {
            "total_correct": result["total_correct"],
            "total_wrong": result["total_wrong"],
            "result_count": len(result["results"]),
        },
    )
    return BatchSubmitResponse(
        results=[AnswerResult(**r) for r in result["results"]],
        total_correct=result["total_correct"],
        total_wrong=result["total_wrong"],
        trace_id=trace_id,
    )


@router.get("/stats", response_model=PracticeStatsResponse)
async def get_practice_stats(
    days: int = Query(7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"practice:stats:{current_user.id}:{days}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    data = await svc.get_practice_stats(db, current_user.id, days=days)
    result = PracticeStatsResponse(**data)
    await cache.set(cache_key, result.model_dump(), ttl=300)
    return result


@router.get("/records")
async def list_records(
    subject: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import and_, func, select
    from app.models.practice_record import PracticeRecord as PR

    conds = [PR.user_id == current_user.id]
    if subject:
        conds.append(PR.subject == subject)

    total = (
        await db.execute(select(func.count(PR.id)).where(and_(*conds)))
    ).scalar()

    rows = await db.execute(
        select(PR)
        .where(and_(*conds))
        .order_by(PR.answered_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = rows.scalars().all()

    return paginated_response(
        items=[PracticeRecordItem.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
    )
