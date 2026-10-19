import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db
from app.core.log_context import get_log_context, normalize_trace_id
from app.core.security import get_current_user
from app.models.sequential_reservation import SequentialReservation
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.practice import (
    AnswerResult,
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
from app.services.practice.batch_issuance import (
    PracticeIssueContext,
    build_signed_practice_response,
)
from app.services.practice.candidate_schedule import filter_due_candidates
from app.services.practice.candidate_selection import (
    PracticeCandidateError,
    PracticeCandidateRequest,
    select_practice_candidates,
)
from app.services.practice.final_candidates import (
    PracticeCandidateConflictError,
    prepare_final_candidates,
)
from app.services.practice.issued_response import (
    IncompletePracticeRevisionError,
)
from app.services.practice.request_filters import (
    PracticeRequestFilterError,
    parse_targeted_question_ids,
    validate_knowledge_point_filters,
)
from app.services.practice.request_scope import (
    PracticeScopeNotFoundError,
    resolve_knowledge_filter,
    resolve_subject_scope,
)
from app.utils.trace.debug import debug_log, save_debug_snapshot

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/practice")


@router.get("/subjects")
async def get_practice_subjects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回刷题页可用科目树（动态，不硬编码）。"""
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

    try:
        subject_scope = await resolve_subject_scope(
            db, subject_id=subject_id, include_children=include_children, mode=mode,
        )
    except PracticeScopeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PracticeRequestFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    subject_code = subject_scope.code
    has_enabled_children = subject_scope.has_enabled_children
    scope_subject_ids = subject_scope.subject_ids

    # 始终使用 subject_code（字符串）作查询参数，避免与 VARCHAR 列比较时类型不匹配
    subject_for_query: str = subject_code

    trace_id = str(get_log_context().get("trace_id") or normalize_trace_id(x_trace_id))
    try:
        validate_knowledge_point_filters(
            knowledge_point=knowledge_point,
            knowledge_point_id=knowledge_point_id,
            include_descendants=include_descendants,
            mode=mode,
        )
    except PracticeRequestFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        knowledge_filter = await resolve_knowledge_filter(
            db,
            knowledge_point=knowledge_point,
            knowledge_point_id=knowledge_point_id,
            subject_ids=scope_subject_ids,
            include_descendants=include_descendants,
        )
    except PracticeScopeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    knowledge_scope = knowledge_filter.scope
    knowledge_point_ids = knowledge_filter.point_ids
    kps = knowledge_filter.names

    try:
        targeted_question_ids = parse_targeted_question_ids(
            question_ids,
            source_question_id=source_question_id,
            knowledge_points=kps,
            knowledge_point_ids=knowledge_point_ids,
            mode=mode,
        )
    except PracticeRequestFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if targeted_question_ids:
        # A targeted retry is an explicit set, not a candidate pool.  Honour
        # every requested id (the client may omit ``count`` or leave its
        # generic default in place) and make the signed session count match
        # that immutable set instead of silently truncating it.
        count = len(targeted_question_ids)

    candidate_request = PracticeCandidateRequest(
        user_id=current_user.id,
        subject_id=subject_id,
        subject_code=subject_for_query,
        subject_ids=scope_subject_ids,
        count=count,
        mode=mode,
        knowledge_points=kps,
        knowledge_point_ids=knowledge_point_ids,
        include_descendants=include_descendants,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
        use_leitner=use_leitner,
        source_question_id=source_question_id,
        targeted_question_ids=targeted_question_ids,
        start_request_id=start_request_id,
        smart_strategy=smart_strategy,
    )
    try:
        candidates = await select_practice_candidates(db, candidate_request)
    except PracticeCandidateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mode = candidates.mode
    questions = await filter_due_candidates(
        db,
        candidate_request,
        candidates.questions,
        mode=mode,
    )
    question_metadata = candidates.metadata
    request_id = candidates.request_id
    sequential_reservation_request_id = candidates.reservation_request_id
    # Validate immutable revisions and the final subject scope before signing.
    try:
        final_candidates = await prepare_final_candidates(
            db,
            candidate_request,
            questions,
            mode=mode,
            metadata=question_metadata,
            request_id=request_id,
        )
    except PracticeCandidateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    questions = final_candidates.questions
    final_question_ids = {int(question.id) for question in questions}
    # ── 结构化日志：刷题请求范围与分布 ──
    scope_desc = "聚合" if len(scope_subject_ids) > 1 else "精确"
    from collections import Counter

    subject_distribution = dict(Counter(q.subject_id for q in questions))
    logger.info(
        "[PRACTICE_SCOPE] subject_id=%s subject_code=%s include_children=%s "
        "include_descendants=%s knowledge_scope_size=%d has_children=%s "
        "scope=%s scope_ids=%s mode=%s count=%d result_count=%d subject_distribution=%s",
        subject_id,
        subject_code,
        include_children,
        include_descendants,
        len(knowledge_point_ids or []),
        has_enabled_children,
        scope_desc,
        scope_subject_ids,
        mode,
        count,
        len(questions),
        subject_distribution,
    )
    try:
        response = await build_signed_practice_response(
            db,
            candidate_request,
            candidates,
            final_candidates,
            PracticeIssueContext(
                trace_id=trace_id,
                knowledge_scope=knowledge_scope,
                knowledge_point_id=knowledge_point_id,
                plan_token=plan_token,
                question_ids=question_ids,
            ),
        )
    except IncompletePracticeRevisionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    debug_log(
        trace_id,
        "API_RESPONSE",
        {
            "endpoint": "practice/questions",
            "subject_id": subject_id,
            "count": len(questions),
        },
    )
    save_debug_snapshot(
        trace_id,
        "api_response",
        {
            "endpoint": "practice/questions",
            "subject_id": subject_id,
            "question_ids": [q.id for q in questions],
            "total": len(questions),
        },
    )
    if mode == "sequential":
        # A revision/scope guard may remove a question after reservation.  Do
        # not leave a lease for an item that was never included in the signed
        # response; the whole cleanup remains in this request transaction.
        await db.execute(
            delete(SequentialReservation).where(
                SequentialReservation.user_id == current_user.id,
                SequentialReservation.subject_id == subject_id,
                SequentialReservation.start_request_id
                == sequential_reservation_request_id,
                SequentialReservation.question_id.notin_(final_question_ids),
            )
        )
        # Reservation writes are intentionally committed only after the full
        # response has been assembled. Any exception before this point causes
        # the request transaction to roll back and leaves no ghost claims.
        await db.commit()
    return response


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
    trace_id = str(get_log_context().get("trace_id") or normalize_trace_id(x_trace_id))
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
            session_meta=data.session.model_dump()
            if data.session is not None
            else None,
            skipped_question_ids=data.skipped_question_ids,
            batch_token=data.batch_token,
        )
    except svc.PracticeBatchTokenError as e:
        logger.warning(
            "practice submit batch token rejected uid=%s trace_id=%s: %s",
            current_user.id,
            trace_id,
            e,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "PRACTICE_BATCH_INVALID",
                "retryable": False,
            },
        )
    except svc.PracticeSubmissionConflictError as e:
        logger.warning(
            "practice submit idempotency conflict uid=%s trace_id=%s: %s",
            current_user.id,
            trace_id,
            e,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "PRACTICE_SUBMISSION_CONFLICT",
                "retryable": False,
            },
        )
    except ValueError as e:
        logger.warning(
            "practice submit payload rejected uid=%s trace_id=%s: %s",
            current_user.id,
            trace_id,
            e,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "PRACTICE_PAYLOAD_INVALID",
                "retryable": False,
            },
        )

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
            "total_skipped": result.get("total_skipped", 0),
            "result_count": len(result["results"]),
        },
    )
    return BatchSubmitResponse(
        results=[AnswerResult(**r) for r in result["results"]],
        total_correct=result["total_correct"],
        total_wrong=result["total_wrong"],
        total_skipped=result.get("total_skipped", 0),
        trace_id=trace_id,
        knowledge_session=result.get("knowledge_session"),
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
