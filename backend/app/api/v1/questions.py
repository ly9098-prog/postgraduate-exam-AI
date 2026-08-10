from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_app_permission
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.question import (
    QuestionCreate,
    QuestionPublicResponse,
    QuestionResponse,
)
from app.services import question_service as svc
from app.services.knowledge_point_service import load_question_kps

router = APIRouter(prefix="/api/v1/questions")


def _sanitize_content(content: dict | None) -> dict | None:
    """Strip admin-only fields from question content before returning to students."""
    if not isinstance(content, dict):
        return content
    sanitized = dict(content)
    sanitized.pop("source_snapshot_url", None)
    sanitized.pop("source_snapshot_full_page", None)
    sanitized.pop("visual_regions", None)
    sanitized.pop("visual_region_ids", None)
    return sanitized


def _public_question(question, kps=None) -> QuestionPublicResponse:
    payload = QuestionPublicResponse.model_validate(question)
    if kps is not None:
        payload = payload.model_copy(update={"knowledge_points": kps})
    subject = question.subject_ref
    return payload.model_copy(update={
        "subject_code": subject.code if subject else "",
        "subject_name": subject.name if subject else "",
        "content": _sanitize_content(payload.content),
    })


@router.post("", response_model=QuestionResponse)
async def create_question(
    data: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("question:write")),
):
    q = await svc.create(
        db=db,
        subject_id=data.subject_id,
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
    kp_map = await load_question_kps(db, [q.id])
    payload = QuestionResponse.model_validate(q)
    return payload.model_copy(update={"knowledge_points": kp_map.get(q.id, [])})


@router.get("")
async def list_questions(
    subject_id: int | None = Query(None),
    question_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    items, total = await svc.list_questions(db, subject_id, question_type, page, page_size)
    kp_map = await load_question_kps(db, [q.id for q in items])
    return paginated_response(
        items=[_public_question(q, kp_map.get(q.id, [])) for q in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/random", response_model=QuestionPublicResponse | None)
async def random_question(
    subject_id: int | None = Query(None),
    question_type: str | None = Query(None),
    exclude_ids: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    exclude = []
    if exclude_ids:
        exclude = [int(x.strip()) for x in exclude_ids.split(",") if x.strip()]
    q = await svc.get_random(db, subject_id, question_type, exclude)
    if not q:
        raise HTTPException(status_code=404, detail="没有符合条件的题目")
    kp_map = await load_question_kps(db, [q.id])
    return _public_question(q, kp_map.get(q.id, []))


@router.get("/{question_id}/similar")
async def get_similar_questions(
    question_id: int,
    count: int = Query(5, ge=1, le=20),
    exclude_answered: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取相似题目推荐。向量优先 + 规则兜底，统一由 ai_learning_service 处理。"""
    from app.services import ai_learning_service

    result = await ai_learning_service.recommend_similar_questions(
        db=db,
        user_id=current_user.id,
        question_id=question_id,
        count=count,
    )
    return result


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

    kp_map = await load_question_kps(db, [q.id])
    return {
        "id": q.id,
        "subject_id": q.subject_id,
        "subject_code": q.subject_ref.code if q.subject_ref else None,
        "subject_name": q.subject_ref.name if q.subject_ref else None,
        "question_type": q.question_type,
        "content": _sanitize_content(q.content),
        "options": q.options,
        "answer": q.answer,
        "analysis": q.analysis,
        "knowledge_points": kp_map.get(q.id, []),
    }


@router.get("/{question_id}", response_model=QuestionPublicResponse)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = await svc.get_by_id(db, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    kp_map = await load_question_kps(db, [q.id])
    return _public_question(q, kp_map.get(q.id, []))
