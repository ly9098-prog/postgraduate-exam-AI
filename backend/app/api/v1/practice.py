from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db
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

_TRUE_FALSE_OPTIONS = {"A": "正确", "B": "错误"}


def _ensure_true_false_options(question_type: str, options: dict | None) -> dict | None:
    if question_type in ("true_false", "judgement") and not options:
        return _TRUE_FALSE_OPTIONS
    return options


router = APIRouter(prefix="/api/v1/practice")


@router.get("/questions")
async def get_practice_questions(
    subject: str = Query(...),
    count: int = Query(20, ge=1, le=50),
    mode: str = Query("random"),
    knowledge_point: str | None = Query(None),
    exclude_answered: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
    return PracticeQuestionsResponse(
        questions=[
            PracticeQuestion(
                id=q.id,
                subject=q.subject,
                question_type=q.question_type,
                content=q.content,
                options=_ensure_true_false_options(q.question_type, q.options),
                knowledge_points=q.knowledge_points,
                difficulty=q.difficulty,
            )
            for q in questions
        ],
        total=len(questions),
        mode=mode,
    )


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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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

    return BatchSubmitResponse(
        results=[AnswerResult(**r) for r in result["results"]],
        total_correct=result["total_correct"],
        total_wrong=result["total_wrong"],
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
