from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.question import QuestionCreate, QuestionResponse
from app.services import question_service as svc

router = APIRouter(prefix="/api/v1/questions")


@router.post("", response_model=QuestionResponse)
async def create_question(
    data: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = await svc.create(
        db=db,
        subject=data.subject,
        question_type=data.question_type,
        content=data.content,
        options=data.options,
        answer=data.answer,
        analysis=data.analysis,
        knowledge_points=data.knowledge_points,
        difficulty=data.difficulty,
        source=data.source,
        year=data.year,
    )
    return q


@router.get("")
async def list_questions(
    subject: str | None = Query(None),
    question_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    items, total = await svc.list_questions(db, subject, question_type, page, page_size)
    return paginated_response(
        items=[QuestionResponse.model_validate(q) for q in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/random", response_model=QuestionResponse | None)
async def random_question(
    subject: str | None = Query(None),
    question_type: str | None = Query(None),
    exclude_ids: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    exclude = []
    if exclude_ids:
        exclude = [int(x.strip()) for x in exclude_ids.split(",") if x.strip()]
    q = await svc.get_random(db, subject, question_type, exclude)
    if not q:
        raise HTTPException(status_code=404, detail="没有符合条件的题目")
    return q


@router.get("/{question_id}/detail")
async def get_question_detail(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import func, select

    from app.models.practice_record import PracticeRecord

    result = await db.execute(
        select(func.count(PracticeRecord.id)).where(
            PracticeRecord.user_id == current_user.id,
            PracticeRecord.question_id == question_id,
        )
    )
    if result.scalar() == 0:
        raise HTTPException(
            status_code=403,
            detail="请先完成答题后再查看答案",
        )

    q = await svc.get_by_id(db, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")

    return {
        "id": q.id,
        "subject": q.subject,
        "question_type": q.question_type,
        "content": q.content,
        "options": q.options,
        "answer": q.answer,
        "analysis": q.analysis,
        "knowledge_points": q.knowledge_points,
    }


@router.get("/{question_id}", response_model=QuestionResponse)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = await svc.get_by_id(db, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    return q
