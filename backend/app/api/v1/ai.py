import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.runtime_paths import API_V1_PREFIX
from app.core.security import get_current_user
from app.models.exam import ExamAttempt, ExamPaperQuestion
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.schemas.ai import (
    AiAnalysisStatusResponse,
    AiFeedbackRequest,
    AiModelAvailabilityResponse,
    AiPrewarmRequest,
    AiPrewarmResponse,
    AiRecoveryRequest,
    AiRecoveryResponse,
    AiResponse,
    ErrorAnalysisRequest,
    StudyAdviceRequest,
)
from app.schemas.ai_learning import (
    AIExplainRequest,
    AIExplainResponse,
    AIMistakeAnalysisRequest,
    AIMistakeAnalysisResponse,
    AIRecommendRequest,
    AIRecommendResponse,
    AIReportRequest,
    AIReportResponse,
    Recommendation,
    StrongPoint,
    WeakPoint,
)
from app.schemas.ai_teacher_408 import (
    AITeacher408ActionsResponse,
    AITeacher408Request,
    AITeacher408Response,
)
from app.services import ai_learning_service, ai_teacher_408_service
from app.services import ai_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_V1_PREFIX}/ai")


@router.get("/error-analysis/availability", response_model=AiModelAvailabilityResponse)
async def error_analysis_availability(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.ai.analysis_availability import availability_for_user

    return await availability_for_user(db, current_user.id)


async def _get_wrong_question_for_answer_ai(
    db: AsyncSession,
    *,
    user_id: int,
    wrong_question_id: int,
) -> WrongQuestion:
    # This helper is hit repeatedly by the mini-program's long-running AI status
    # polling. Resolve ownership and the active-exam answer-leak guard in one SQL
    # round trip instead of issuing a second query for every poll.
    active_exam_exists = (
        select(ExamPaperQuestion.id)
        .join(ExamAttempt, ExamAttempt.paper_id == ExamPaperQuestion.paper_id)
        .where(
            ExamAttempt.user_id == user_id,
            ExamAttempt.status == "in_progress",
            ExamPaperQuestion.question_id == WrongQuestion.question_id,
        )
        .correlate(WrongQuestion)
        .exists()
    )
    row = (
        await db.execute(
            select(WrongQuestion, active_exam_exists.label("ai_blocked")).where(
                WrongQuestion.id == wrong_question_id,
                WrongQuestion.user_id == user_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="错题记录不存在")

    wq, ai_blocked = row
    if bool(ai_blocked):
        message = "考试进行中禁止调用会泄露答案或解析的 AI 能力，请交卷后再使用。"
        raise HTTPException(
            status_code=409,
            detail={"code": "exam_in_progress_ai_blocked", "message": message},
        )
    return wq


# ============================================================
# 现有端点
# ============================================================


@router.post("/error-analysis")
async def error_analysis(
    data: ErrorAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_wrong_question_for_answer_ai(
        db,
        user_id=current_user.id,
        wrong_question_id=data.wrong_question_id,
    )
    try:
        result = await svc.analyze_error(
            db,
            current_user.id,
            data.wrong_question_id,
            force_regenerate=data.force_regenerate,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AiResponse(
        session_type="error_analysis",
        **result,
    )


@router.get(
    "/error-analysis/status/{wrong_question_id}",
    response_model=AiAnalysisStatusResponse,
)
async def error_analysis_status(
    wrong_question_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lightweight persisted-result status for long-running Mini Program calls.

    This intentionally avoids the full wrong-question enrichment/freshness path
    on every poll. The caller compares ``generated_at`` with the marker captured
    before generation, so an old/stale cache cannot be mistaken for the new
    result it is waiting for.
    """
    wq = await _get_wrong_question_for_answer_ai(
        db,
        user_id=current_user.id,
        wrong_question_id=wrong_question_id,
    )

    cached = svc.build_any_cached_error_analysis_response(wq)
    if cached is None:
        return AiAnalysisStatusResponse(
            ready=False,
            generated_at=svc.ai_analysis_generated_at(wq.ai_analysis),
        )
    return AiAnalysisStatusResponse(
        ready=True,
        content=cached.get("content"),
        generated_at=cached.get("generated_at"),
    )


@router.post("/error-analysis/recover", response_model=AiRecoveryResponse)
async def recover_error_analysis(
    data: AiRecoveryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue a backup generation after the mini-program transport times out.

    wx.request cannot remain open for the full provider budget used by slow
    compatible models. The original HTTP handler normally keeps running, so this
    backup is revision-aware and force-regeneration-aware: the worker skips the
    backup when the original request has already committed a newer generation.
    """
    from app.ai.prewarm_revision import build_prewarm_revision
    from app.services.ai_prewarm_worker import enqueue_prewarm

    wq = await _get_wrong_question_for_answer_ai(
        db,
        user_id=current_user.id,
        wrong_question_id=data.wrong_question_id,
    )

    revision = build_prewarm_revision(
        review_count=wq.review_count,
        wrong_answer=wq.wrong_answer,
    )
    # Trust the persisted server marker over the client for the initial baseline
    # when the client does not have one (e.g. older cached page data).
    baseline = data.baseline_generated_at
    if data.force_regenerate and baseline is None:
        baseline = svc.ai_analysis_generated_at(wq.ai_analysis) or ""

    queued = await enqueue_prewarm(
        wq.id,
        current_user.id,
        revision=revision,
        recovery_mode=True,
        force_regenerate=bool(data.force_regenerate),
        baseline_generated_at=baseline if data.force_regenerate else None,
        task_id_override=f"prewarm-recovery:{wq.id}:{uuid.uuid4().hex}",
        # A recovery task may initially observe the original request's lock.
        # Give durable retries enough time to outlive that request instead of
        # exhausting the normal short prewarm retry budget.
        max_retries_override=6,
    )
    return AiRecoveryResponse(queued=queued)


@router.post("/error-analysis/prewarm", response_model=AiPrewarmResponse)
async def prewarm_analysis(
    data: AiPrewarmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量预生成错题 AI 分析。后台任务统一校验缓存新鲜度并按需生成。"""
    from app.ai.prewarm_revision import build_prewarm_revision
    from app.services.ai_prewarm_worker import enqueue_prewarm

    queued: list[int] = []
    skipped: list[int] = []

    # Batch load all wrong questions in one query to avoid N+1
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id.in_(data.wrong_question_ids),
            WrongQuestion.user_id == current_user.id,
        )
    )
    wq_map = {wq.id: wq for wq in result.scalars().all()}
    blocked_question_ids = (
        await ai_teacher_408_service.active_exam_blocked_question_ids(
            db,
            user_id=current_user.id,
            question_ids=[int(wq.question_id) for wq in wq_map.values()],
        )
    )

    for wq_id in data.wrong_question_ids:
        wq = wq_map.get(wq_id)
        if not wq:
            skipped.append(wq_id)
            continue
        if int(wq.question_id) in blocked_question_ids:
            skipped.append(wq_id)
            continue
        # The worker is the authoritative freshness checker. Do not skip merely
        # because a JSON cache exists: prompt/model/question revisions may make
        # that cache stale. Revisioned task ids still dedupe identical events.
        revision = build_prewarm_revision(
            review_count=wq.review_count,
            wrong_answer=wq.wrong_answer,
        )
        queued_ok = await enqueue_prewarm(
            wq_id,
            current_user.id,
            revision=revision,
        )
        if not queued_ok:
            logger.warning(
                "Prewarm queue unavailable (Redis?), skipped wq_id=%d", wq_id
            )
            skipped.append(wq_id)
            continue
        queued.append(wq_id)

    return AiPrewarmResponse(queued=queued, skipped=skipped)


@router.post("/study-advice")
async def study_advice(
    data: StudyAdviceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await svc.generate_advice(db, current_user.id, data.subject_id)

    return AiResponse(
        session_type="study_advice",
        **result,
    )


# ============================================================
# Stage 13: AI 学习引擎
# ============================================================


@router.post("/explain", response_model=AIExplainResponse)
async def ai_explain(
    data: AIExplainRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 题目讲解。"""
    try:
        await ai_teacher_408_service.assert_ai_answer_access_allowed(
            db, user_id=current_user.id, question_id=data.question_id
        )
        result = await ai_learning_service.ai_explain(
            db=db,
            user_id=current_user.id,
            question_id=data.question_id,
            user_answer=data.user_answer,
            is_correct=data.is_correct,
            focus=data.focus,
        )
    except ai_teacher_408_service.AIExamInProgressError as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "exam_in_progress_ai_blocked", "message": str(e)},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AIExplainResponse(**result)


@router.post("/recommend", response_model=AIRecommendResponse)
async def ai_recommend(
    data: AIRecommendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 相似题推荐（规则推荐）。"""
    try:
        result = await ai_learning_service.recommend_similar_questions(
            db=db,
            user_id=current_user.id,
            question_id=data.question_id,
            count=data.count,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AIRecommendResponse(
        source_question_id=result["source_question_id"],
        recommendations=[Recommendation(**r) for r in result["recommendations"]],
        strategy=result["strategy"],
        tokens_used=result["tokens_used"],
    )


@router.post("/report", response_model=AIReportResponse)
async def ai_report(
    data: AIReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 学习报告。"""
    result = await ai_learning_service.generate_learning_report(
        db=db,
        user_id=current_user.id,
        subject_id=data.subject_id,
        days=data.days,
    )

    return AIReportResponse(
        subject_id=result["subject_id"],
        subject_code=result["subject_code"],
        subject_name=result["subject_name"],
        period_days=result["period_days"],
        total_answered=result["total_answered"],
        accuracy=result["accuracy"],
        weak_points=[WeakPoint(**wp) for wp in result["weak_points"]],
        strong_points=[StrongPoint(**sp) for sp in result["strong_points"]],
        learning_suggestions=result["learning_suggestions"],
        tokens_used=result["tokens_used"],
        from_fallback=result["from_fallback"],
    )


@router.post("/analyze-mistake", response_model=AIMistakeAnalysisResponse)
async def ai_analyze_mistake(
    data: AIMistakeAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 错因分析。"""
    try:
        await ai_teacher_408_service.assert_ai_answer_access_allowed(
            db, user_id=current_user.id, question_id=data.question_id
        )
        result = await ai_learning_service.ai_analyze_mistake(
            db=db,
            user_id=current_user.id,
            question_id=data.question_id,
            user_answer=data.user_answer,
            correct_answer=data.correct_answer,
        )
    except ai_teacher_408_service.AIExamInProgressError as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "exam_in_progress_ai_blocked", "message": str(e)},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return AIMistakeAnalysisResponse(**result)


@router.get("/408-teacher/actions", response_model=AITeacher408ActionsResponse)
async def ai_teacher_408_actions(
    current_user: User = Depends(get_current_user),
):
    """返回服务端冻结的 408 AI 老师固定动作，不接受自由 prompt。"""
    _ = current_user
    return AITeacher408ActionsResponse(**ai_teacher_408_service.get_actions())


@router.post("/408-teacher", response_model=AITeacher408Response)
async def ai_teacher_408(
    data: AITeacher408Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行一个固定 408 教学动作。考试进行中 fail-closed。"""
    from app.services.ai.analysis_availability import AnalysisUnavailableError

    try:
        result = await ai_teacher_408_service.run_teacher_action(
            db,
            user_id=current_user.id,
            question_id=data.question_id,
            action=data.action,
            question_version_id=data.question_version_id,
            diagnosis_id=data.diagnosis_id,
            exam_attempt_id=data.exam_attempt_id,
            user_answer=data.user_answer,
        )
    except AnalysisUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "ai_service_unavailable", **exc.state},
        ) from exc
    except ai_teacher_408_service.AIExamInProgressError as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "exam_in_progress_ai_blocked", "message": str(e)},
        )
    except ai_teacher_408_service.AITeacher408AccessError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AITeacher408Response(**result)


@router.post("/feedback")
async def ai_feedback(
    data: AiFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 结果反馈：用户标记 AI 解析/建议不准确。

    反馈内容记录到 ai_feedback_logs 表，用于后续模型改进和质量监控。
    """
    from app.models.ai_feedback_log import AiFeedbackLog

    log = AiFeedbackLog(
        user_id=current_user.id,
        source=data.source,
        feedback_type=data.feedback_type,
        question_id=data.question_id,
        detail=data.detail,
    )
    db.add(log)
    await db.commit()

    return {"message": "反馈已提交，感谢您的帮助"}
