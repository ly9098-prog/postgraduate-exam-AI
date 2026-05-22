from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.question import Question
from app.models.user import User
from app.schemas.practice import (
    BatchQuestionsRequest,
    BatchQuestionsResponse,
    PracticeRecordSummary,
    PracticeResult,
    PracticeResultItem,
    PracticeSubmit,
    SingleCheckRequest,
    SingleCheckResult,
)
from app.services import practice_service as svc

router = APIRouter(prefix="/api/v1/practice")


@router.post("/check", response_model=SingleCheckResult)
async def check_answer(
    data: SingleCheckRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """单题判题：提交答案，返回对错和解析"""
    result = await db.execute(
        select(Question).where(Question.id == data.question_id, Question.is_active == True)
    )
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")

    is_correct = data.answer.strip() == q.answer.strip()
    return SingleCheckResult(
        question_id=q.id,
        user_answer=data.answer,
        correct_answer=q.answer,
        is_correct=is_correct,
        analysis=q.analysis,
    )


@router.post("/batch-questions", response_model=BatchQuestionsResponse)
async def batch_questions(
    data: BatchQuestionsRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """批量预加载题目（不含答案，避免提前泄露）"""
    questions = await svc.get_batch_questions(
        db, subject=data.subject, count=data.count, exclude_ids=data.exclude_ids
    )
    return BatchQuestionsResponse(
        questions=[_strip_answer(q) for q in questions],
        total=len(questions),
    )


def _strip_answer(q: Question) -> dict:
    """返回题目时不暴露答案，防止前端预加载时泄露"""
    return {
        "id": q.id,
        "subject": q.subject,
        "question_type": q.question_type,
        "content": q.content,
        "options": q.options,
        "difficulty": q.difficulty,
    }


@router.post("/submit")
async def submit_practice(
    data: PracticeSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        record, results = await svc.submit(
            db=db,
            user_id=current_user.id,
            subject=data.subject,
            answers=[a.model_dump() for a in data.answers],
            mode=data.mode,
            duration_sec=data.duration_sec,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PracticeResult(
        record_id=record.id,
        subject=record.subject,
        mode=record.mode,
        correct_count=record.correct_count,
        wrong_count=record.wrong_count,
        total=len(results),
        duration_sec=record.duration_sec,
        results=[PracticeResultItem(**r) for r in results],
    )


@router.get("/records")
async def list_records(
    subject: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await svc.list_records(db, current_user.id, subject, page, page_size)
    return {
        "items": [
            PracticeRecordSummary(
                id=r.id,
                subject=r.subject,
                mode=r.mode,
                correct_count=r.correct_count,
                wrong_count=r.wrong_count,
                total=(r.correct_count + r.wrong_count),
                duration_sec=r.duration_sec,
                created_at=r.created_at,
            )
            for r in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/records/{record_id}")
async def get_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await svc.get_by_id(db, current_user.id, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    result = await db.execute(
        select(Question).where(
            Question.id.in_(record.question_ids), Question.is_active == True
        )
    )
    questions = {q.id: q for q in result.scalars().all()}

    results = []
    for qid in record.question_ids:
        q = questions.get(qid)
        user_ans = record.answers.get(str(qid), "")
        results.append(
            PracticeResultItem(
                question_id=qid,
                user_answer=user_ans,
                correct_answer=q.answer if q else "",
                is_correct=(user_ans.strip() == q.answer.strip() if q else False),
                analysis=q.analysis if q else None,
            )
        )

    return PracticeResult(
        record_id=record.id,
        subject=record.subject,
        mode=record.mode,
        correct_count=record.correct_count,
        wrong_count=record.wrong_count,
        total=len(results),
        duration_sec=record.duration_sec,
        results=results,
    )
