"""推荐日志服务 — 记录推荐→作答反馈闭环。"""
import logging
from datetime import timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.core.time_utils import utcnow
from app.models.question import Question
from app.models.recommendation_log import RecommendationLog

logger = logging.getLogger(__name__)


async def create_recommendation_logs(
    db: AsyncSession,
    user_id: int,
    recommendations: list[dict],
    scene: str,
    strategy: str,
    request_id: str | None = None,
    source_question_id: int | None = None,
    subject_id: int | None = None,
    # Phase 4: 实验分组 + 策略配置 + 掌握度
    experiment_id: int | None = None,
    variant_key: str | None = None,
    strategy_config_id: int | None = None,
    mastery_before: float | None = None,
) -> list[int]:
    """批量创建推荐日志。

    recommendations: 每项至少包含 question_id，可选 recommend_score / similarity / reason。
    科目身份统一使用 subject_id。调用方未提供 subject_id 时，仅允许根据 question_id
    的真实归属回填，不再接受字符串 subject/旧编码。
    返回新创建的日志 ID 列表。
    """
    # 必须 commit：get_db 依赖（database.py）的会话在请求结束关闭时不会自动提交，
    # 只 flush 会导致推荐日志随事务回滚而丢失（历史 bug：recommendation_logs 恒为空）。
    now = utcnow()
    logs = []

    # question_id → subject_id 缓存（subject 全部来源都无法解析时的兜底）
    qid_sid_cache: dict[int, int | None] = {}

    for rec in recommendations:
        sid = subject_id
        if sid is None:
            rec_sid = rec.get("subject_id")
            if isinstance(rec_sid, int):
                sid = rec_sid

        # 调用方未带 subject 时，按问题归属推导（与导入回填同一优先级）
        if sid is None:
            qid = rec.get("question_id")
            if isinstance(qid, int) and qid not in qid_sid_cache:
                qid_sid_cache[qid] = (await db.execute(
                    select(Question.subject_id).where(Question.id == qid)
                )).scalar_one_or_none()
            if isinstance(qid, int):
                sid = qid_sid_cache[qid]

        if sid is None:
            logger.warning(
                "推荐日志缺少可解析的 subject_id，跳过 question_id=%s", rec.get("question_id"),
            )
            continue

        # 一批推荐中可能同时包含 scored、weakness fallback、随机补齐等来源。
        # 允许逐条覆盖策略/实验元数据，批次参数仅作为旧调用方的默认值。
        rec_strategy = rec.get("strategy") or strategy
        rec_experiment_id = rec.get("experiment_id", experiment_id)
        rec_variant_key = rec.get("variant_key", variant_key)
        rec_strategy_config_id = rec.get("strategy_config_id", strategy_config_id)
        rec_mastery_before = rec.get("mastery_before", mastery_before)

        log = RecommendationLog(
            user_id=user_id,
            question_id=rec["question_id"],
            subject_id=sid,
            scene=scene,
            strategy=rec_strategy,
            source_question_id=source_question_id,
            recommend_score=rec.get("recommend_score"),
            similarity=rec.get("similarity"),
            reason=rec.get("reason"),
            request_id=request_id,
            experiment_id=rec_experiment_id,
            variant_key=rec_variant_key,
            strategy_config_id=rec_strategy_config_id,
            mastery_before=rec_mastery_before,
            shown_at=now,
        )
        db.add(log)
        logs.append(log)

    await db.commit()
    return [log.id for log in logs]


async def create_recommendation_logs_isolated(**kwargs) -> list[int]:
    """Write optional recommendation analytics outside the practice DB session.

    Practice question delivery must not fail because an analytics insert/commit
    failed.  PostgreSQL marks the current transaction aborted after a statement
    error, so merely catching an exception around ``create_recommendation_logs``
    is insufficient when it shares the request's AsyncSession.  Use an isolated
    short-lived session for this best-effort side effect.
    """
    kwargs.pop("db", None)
    async with async_session() as isolated_db:
        return await create_recommendation_logs(db=isolated_db, **kwargs)


async def retain_recommendation_logs_for_questions(
    db: AsyncSession,
    *,
    user_id: int,
    request_id: str | None,
    question_ids: set[int] | list[int],
) -> int:
    """Remove exposure rows that were created for candidates not actually issued.

    Smart/similar strategies may write recommendation logs before the API's final
    immutable-revision/subject guard runs.  If that guard drops a stale or invalid
    candidate, keeping its ``shown_at`` row makes exposure and conversion metrics
    claim the user saw a question that never reached the signed batch.
    """
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return 0

    keep_ids = {int(qid) for qid in question_ids if qid is not None}
    conditions = [
        RecommendationLog.user_id == int(user_id),
        RecommendationLog.request_id == normalized_request_id,
    ]
    if keep_ids:
        conditions.append(RecommendationLog.question_id.notin_(keep_ids))

    # This is analytics cleanup, not part of question delivery.  Keep it on an
    # independent transaction for the same reason as isolated log creation: a
    # failed DELETE/COMMIT must never poison the request session used to load the
    # immutable revisions and issue the signed practice batch.
    async with async_session() as isolated_db:
        result = await isolated_db.execute(sa_delete(RecommendationLog).where(*conditions))
        await isolated_db.commit()
    deleted = int(getattr(result, "rowcount", 0) or 0)
    if deleted:
        logger.info(
            "pruned %d unissued recommendation logs user_id=%s request_id=%s",
            deleted, user_id, normalized_request_id,
        )
    return deleted


async def mark_recommendation_clicked(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    request_id: str | None = None,
) -> bool:
    """标记推荐题目被用户点击。"""
    now = utcnow()

    conditions = [
        RecommendationLog.user_id == user_id,
        RecommendationLog.question_id == question_id,
        RecommendationLog.clicked_at == None,  # noqa: E711
    ]
    if request_id:
        conditions.append(RecommendationLog.request_id == request_id)

    result = await db.execute(
        select(RecommendationLog)
        .where(*conditions)
        .order_by(RecommendationLog.shown_at.desc())
        .limit(1)
    )
    log = result.scalar_one_or_none()
    if not log:
        return False

    log.clicked_at = now
    await db.flush()
    return True


async def mark_recommendation_answered(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
    request_id: str | None = None,
    # Phase 4: 掌握度变化
    mastery_after: float | None = None,
    mastery_delta: float | None = None,
) -> bool:
    """标记推荐题目已被作答。"""
    now = utcnow()

    conditions = [
        RecommendationLog.user_id == user_id,
        RecommendationLog.question_id == question_id,
        RecommendationLog.answered_at == None,  # noqa: E711
    ]
    if request_id:
        conditions.append(RecommendationLog.request_id == request_id)

    result = await db.execute(
        select(RecommendationLog)
        .where(*conditions)
        .order_by(RecommendationLog.shown_at.desc())
        .limit(1)
    )
    log = result.scalar_one_or_none()
    if not log:
        return False

    log.answered_at = now
    log.is_correct = is_correct
    if mastery_after is not None:
        log.mastery_after = mastery_after
    if mastery_delta is not None:
        log.mastery_delta = mastery_delta
        # 推荐曝光时未必能低成本获得“题目所有知识点的平均掌握度”。
        # 答题后已拿到 before/after 的差值时，可无损反推出 mastery_before，
        # 让 recommendation_metrics_daily 的掌握度提升指标真正有数据。
        if log.mastery_before is None and mastery_after is not None:
            log.mastery_before = mastery_after - mastery_delta
    await db.flush()
    return True


async def cleanup_expired_recommendation_logs(
    db: AsyncSession,
    retention_days: int,
    batch_size: int = 1000,
) -> int:
    """删除超期推荐日志（按 shown_at），批量处理。

    返回删除的总行数。
    """
    cutoff = utcnow() - timedelta(days=retention_days)
    total_deleted = 0

    while True:
        batch_ids = (
            await db.execute(
                select(RecommendationLog.id)
                .where(RecommendationLog.shown_at < cutoff)
                .order_by(RecommendationLog.id)
                .limit(batch_size)
            )
        ).scalars().all()

        if not batch_ids:
            break

        await db.execute(sa_delete(RecommendationLog).where(RecommendationLog.id.in_(batch_ids)))
        await db.commit()
        total_deleted += len(batch_ids)

    return total_deleted
