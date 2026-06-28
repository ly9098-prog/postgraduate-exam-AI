"""推荐日志服务 — 记录推荐→作答反馈闭环。"""
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
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
    # Phase 4: 实验分组 + 策略配置 + 掌握度
    experiment_id: int | None = None,
    variant_key: str | None = None,
    strategy_config_id: int | None = None,
    mastery_before: float | None = None,
) -> list[int]:
    """批量创建推荐日志。

    recommendations: 每项至少包含 question_id，可选 recommend_score / similarity / reason。
    返回新创建的日志 ID 列表。
    """
    now = utcnow()
    logs = []

    for rec in recommendations:
        log = RecommendationLog(
            user_id=user_id,
            question_id=rec["question_id"],
            subject=rec.get("subject", ""),
            scene=scene,
            strategy=strategy,
            source_question_id=source_question_id,
            recommend_score=rec.get("recommend_score"),
            similarity=rec.get("similarity"),
            reason=rec.get("reason"),
            request_id=request_id,
            experiment_id=experiment_id,
            variant_key=variant_key,
            strategy_config_id=strategy_config_id,
            mastery_before=mastery_before,
            shown_at=now,
        )
        db.add(log)
        logs.append(log)

    await db.flush()
    return [log.id for log in logs]


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
    await db.flush()
    return True
