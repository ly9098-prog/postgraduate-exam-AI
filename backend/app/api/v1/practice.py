import builtins as _practice_request_builtins
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db
from app.core.log_context import get_log_context, normalize_trace_id  # noqa: F401
from app.core.security import get_current_user, get_optional_current_user
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.practice import (
    AnswerResult,  # noqa: F401 -- live submission response dependency
    BatchSubmitRequest,
    BatchSubmitResponse,
    PracticeKnowledgeSummaryResponse,
    PracticeMode,
    PracticeQuestionsResponse,
    PracticeRecordItem,
    PracticeSessionScopeResponse,
    PracticeStatsResponse,
    SequentialPracticeResetRequest,
    SequentialPracticeResetResponse,
)
from app.services import practice_service as svc
from app.services.knowledge_point_service import load_question_kps  # noqa: F401
from app.services.practice import request_submission as _request_submission
from app.services.practice.candidate_selection import PracticeCandidateError
from app.services.practice.final_candidates import PracticeCandidateConflictError
from app.services.practice.issued_response import IncompletePracticeRevisionError
from app.services.practice.question_issuance import (
    issue_practice_questions,
    release_unissued_reservations,
)
from app.services.practice.request_assembly import PracticeQuestionsRequest
from app.services.practice.request_filters import PracticeRequestFilterError
from app.services.practice.request_scope import PracticeScopeNotFoundError
from app.utils.trace.debug import debug_log, save_debug_snapshot  # noqa: F401

logger = logging.getLogger(__name__)


def _practice_request_port(name):
    """Resolve the original route dependency when the request uses it."""
    if name in globals():
        return globals()[name]
    return getattr(_practice_request_builtins, name)


router = APIRouter(prefix="/api/v1/practice")


@router.get("/subjects")
async def get_practice_subjects(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    """返回公共学习科目目录，不按游客可出题范围裁剪。"""
    return await svc.get_practice_subject_tree(db)


@router.get("/questions", response_model=PracticeQuestionsResponse)
async def get_practice_questions(
    response: Response,
    subject_id: int = Query(...),
    include_children: bool = Query(True),
    count: int = Query(20, ge=1, le=50),
    mode: PracticeMode = Query("random"),
    knowledge_point: str | None = Query(None),
    knowledge_point_id: int | None = Query(None, ge=1),
    include_descendants: bool = Query(False),
    exclude_answered: bool = Query(False),
    no_repeat_days: int | None = Query(None, ge=1, le=365),
    use_leitner: bool = Query(True),
    source_question_id: int | None = Query(None),
    question_ids: str | None = Query(None, max_length=1024),
    start_request_id: str | None = Query(None, max_length=128),
    # smart 默认走综合 scored；客户端仍只需要传 mode=smart。
    # weakness_vector 保留为显式 fallback / A/B control。
    smart_strategy: str = Query("scored"),
    plan_token: str | None = Query(None, max_length=2048),
    x_trace_id: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Personalized practice batches contain a signed immutable-revision token.
    # Never let a WebView/proxy reuse an older GET response after a question edit.
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"

    request = PracticeQuestionsRequest(
        user_id=current_user.id,
        subject_id=subject_id,
        include_children=include_children,
        count=count,
        mode=mode,
        knowledge_point=knowledge_point,
        knowledge_point_id=knowledge_point_id,
        include_descendants=include_descendants,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
        use_leitner=use_leitner,
        source_question_id=source_question_id,
        question_ids=question_ids,
        start_request_id=start_request_id,
        smart_strategy=smart_strategy,
        plan_token=plan_token,
        trace_header=x_trace_id,
    )
    return await _issue_questions_response(db, request)


async def _issue_questions_response(
    db: AsyncSession, request: PracticeQuestionsRequest,
) -> PracticeQuestionsResponse:
    try:
        batch = await issue_practice_questions(db, request)
    except PracticeScopeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PracticeRequestFilterError, PracticeCandidateError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PracticeCandidateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IncompletePracticeRevisionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if batch.mode == "sequential":
        await release_unissued_reservations(
            db, user_id=request.user_id, subject_id=request.subject_id, batch=batch,
        )
        # Commit only after signing, serialization and diagnostics all succeed.
        # The request dependency rolls back failures before this point.
        await db.commit()
    return batch.response


@router.post(
    "/sequential/reset",
    response_model=SequentialPracticeResetResponse,
)
async def reset_sequential_practice(
    data: SequentialPracticeResetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成一轮后显式开始新的顺序刷题轮次。"""
    resolved = await svc.resolve_subject_id_to_code(db, data.subject_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="科目不存在")

    has_enabled_children, scope_subject_ids = await svc.resolve_practice_subject_scope(
        db,
        data.subject_id,
        include_children=False,
    )
    if has_enabled_children or len(scope_subject_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail="顺序练习仅支持具体科目，不支持父级科目聚合刷题",
        )

    await svc.reset_sequential_progress(
        db,
        user_id=current_user.id,
        subject_id=data.subject_id,
    )
    return SequentialPracticeResetResponse(subject_id=data.subject_id, reset=True)


@router.post("/batch-submit", response_model=BatchSubmitResponse)
async def batch_submit(
    data: BatchSubmitRequest,
    x_trace_id: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _request_submission.batch_submit(
        data, x_trace_id, db, current_user, ports=_practice_request_port
    )


@router.get("/session/scope", response_model=PracticeSessionScopeResponse)
async def get_practice_session_scope_snapshot(
    request_id: str = Query(..., min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the immutable semantic scope persisted for a completed batch."""
    from app.services.practice.session_scope import get_practice_session_scope

    found, scope = await get_practice_session_scope(
        db,
        user_id=current_user.id,
        request_id=request_id,
    )
    if not found:
        raise HTTPException(status_code=404, detail="练习会话不存在")
    return PracticeSessionScopeResponse(request_id=request_id, scope=scope)


@router.get(
    "/session/knowledge-summary", response_model=PracticeKnowledgeSummaryResponse
)
async def get_practice_session_knowledge_summary(
    request_id: str = Query(..., min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return post-projection knowledge impact for one completed practice session.

    The endpoint deliberately reports ``processing`` while answer-projection outbox
    tasks are pending, so the result UI never presents stale mastery values as final.
    """
    from app.services.practice.knowledge_session_summary import (
        get_session_knowledge_summary,
    )

    summary = await get_session_knowledge_summary(
        db,
        user_id=current_user.id,
        request_id=request_id,
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="练习会话不存在")
    return PracticeKnowledgeSummaryResponse(**summary)


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
    subject_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import and_, func, select

    from app.models.admin import Subject
    from app.models.practice_record import PracticeRecord as PR

    conds = [PR.user_id == current_user.id]
    if subject_id:
        conds.append(PR.subject_id == subject_id)

    total = (await db.execute(select(func.count(PR.id)).where(and_(*conds)))).scalar()

    rows = await db.execute(
        select(
            PR.id,
            PR.question_id,
            PR.subject_id,
            Subject.code.label("subject_code"),
            Subject.name.label("subject_name"),
            PR.question_type,
            PR.user_answer,
            PR.is_correct,
            PR.used_time,
            PR.answered_at,
        )
        .outerjoin(Subject, Subject.id == PR.subject_id)
        .where(and_(*conds))
        .order_by(PR.answered_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = rows.all()

    return paginated_response(
        items=[
            PracticeRecordItem(
                id=r.id,
                question_id=r.question_id,
                subject_id=r.subject_id,
                subject_code=r.subject_code or "",
                subject_name=r.subject_name or "",
                question_type=r.question_type,
                user_answer=r.user_answer,
                is_correct=r.is_correct,
                used_time=r.used_time,
                answered_at=r.answered_at,
            )
            for r in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── V3: 知识点掌握度查询接口 ──


@router.get("/knowledge-states")
async def get_knowledge_states(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询当前用户所有知识点掌握状态。

    可选 status 过滤：weak / normal / good / mastered / observing / possible_weak / possible_mastered。
    """
    from sqlalchemy import select as sa_select

    # 获取所有科目的状态（跨科目汇总）
    # 先获取用户有记录的科目列表
    from app.models.user_knowledge_state import UserKnowledgeState
    from app.services import mastery_service

    subjects_result = await db.execute(
        sa_select(UserKnowledgeState.subject_id)
        .where(UserKnowledgeState.user_id == current_user.id)
        .distinct()
    )
    subjects = [row[0] for row in subjects_result.all()]

    all_items = []
    for subject_id in subjects:
        states = await mastery_service.get_user_knowledge_states(
            db,
            current_user.id,
            subject_id,
        )
        all_items.extend(states)

    # status 过滤
    if status:
        all_items = [item for item in all_items if item.get("weakness_level") == status]

    # 按 mastery_score 升序
    all_items.sort(key=lambda x: x.get("mastery_score", 50))

    # 限制数量
    all_items = all_items[:limit]

    # 转换为 Schema
    from app.schemas.mastery import KnowledgeStateItem, KnowledgeStateListResponse

    items = [
        KnowledgeStateItem(
            knowledge_point_id=item.get("knowledge_point_id"),
            knowledge_point=item.get("name", ""),
            mastery_score=item.get("mastery_score", 50.0),
            confidence=item.get("confidence", 0.0),
            label=item.get("weakness_level", "observing"),
            answer_count=item.get("attempt_count", 0),
            correct_count=item.get("correct_count", 0),
            wrong_count=item.get("wrong_count", 0),
            recent_wrong_count=item.get("recent_wrong_count", 0),
            last_practiced_at=item.get("last_practiced_at"),
        )
        for item in all_items
    ]

    return KnowledgeStateListResponse(items=items, total=len(items))


@router.get("/weak-knowledge-points")
async def get_weak_knowledge_points(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询用户明确薄弱的知识点（mastery_score < 40 且 confidence >= 0.3）。

    主要为 V4 智能推荐提供数据基础。
    """
    from sqlalchemy import select as sa_select

    from app.models.user_knowledge_state import UserKnowledgeState
    from app.services import mastery_service

    # 获取用户有记录的科目
    subjects_result = await db.execute(
        sa_select(UserKnowledgeState.subject_id)
        .where(UserKnowledgeState.user_id == current_user.id)
        .distinct()
    )
    subjects = [row[0] for row in subjects_result.all()]

    all_weak = []
    for subject_id in subjects:
        weak = await mastery_service.get_user_weak_knowledge_points(
            db,
            current_user.id,
            subject_id,
            limit=limit,
        )
        all_weak.extend(weak)

    # 过滤：只保留 mastery_score < 40 且 confidence >= 0.3
    all_weak = [
        item
        for item in all_weak
        if item.get("mastery_score", 50) < 40 and item.get("confidence", 0) >= 0.3
    ]

    # 排序：mastery_score ASC, recent_wrong_count DESC
    all_weak.sort(
        key=lambda x: (x.get("mastery_score", 50), -x.get("attempt_count", 0))
    )
    all_weak = all_weak[:limit]

    from app.schemas.mastery import KnowledgeStateItem, KnowledgeStateListResponse

    items = [
        KnowledgeStateItem(
            knowledge_point_id=item.get("knowledge_point_id"),
            knowledge_point=item.get("name", ""),
            mastery_score=item.get("mastery_score", 50.0),
            confidence=item.get("confidence", 0.0),
            label=item.get("weakness_level", "weak"),
            answer_count=item.get("attempt_count", 0),
            correct_count=item.get("correct_count", 0)
            if isinstance(item.get("correct_count"), int)
            else round(item.get("accuracy", 0) * item.get("attempt_count", 0)),
            wrong_count=item.get("wrong_count", 0)
            if isinstance(item.get("wrong_count"), int)
            else item.get("attempt_count", 0)
            - round(item.get("accuracy", 0) * item.get("attempt_count", 0)),
            recent_wrong_count=item.get("recent_wrong_count", 0),
        )
        for item in all_weak
    ]

    return KnowledgeStateListResponse(items=items, total=len(items))
