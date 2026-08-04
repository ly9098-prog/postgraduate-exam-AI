"""推荐日志服务 — 记录推荐→作答反馈闭环。"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.question import Question
from app.models.recommendation_log import RecommendationLog
from app.models.subject_resolver import resolve_subject_id_from_legacy

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
    科目身份统一使用 subject_id；若调用方在每条 recommendation 里传了遗留的
    ``subject`` 字符串（旧协议兼容边界），本函数通过 subject 表解析成 subject_id。
    返回新创建的日志 ID 列表。
    """
    # 必须 commit：get_db 依赖（database.py）的会话在请求结束关闭时不会自动提交，
    # 只 flush 会导致推荐日志随事务回滚而丢失（历史 bug：recommendation_logs 恒为空）。
    now = utcnow()
    logs = []

    # 遗留字符串 subject → subject_id 的批量解析缓存（按原始值缓存，含未命中 None）
    legacy_sid_cache: dict[str, int | None] = {}
    # question_id → subject_id 缓存（subject 全部来源都无法解析时的兜底）
    qid_sid_cache: dict[int, int | None] = {}

    for rec in recommendations:
        sid = subject_id
        if sid is None:
            rec_sid = rec.get("subject_id")
            if isinstance(rec_sid, int):
                sid = rec_sid
            else:
                raw = rec.get("subject")
                if isinstance(raw, int):
                    sid = raw
                elif isinstance(raw, str) and raw:
                    if raw not in legacy_sid_cache:
                        legacy_sid_cache[raw] = await resolve_subject_id_from_legacy(db, raw)
                    sid = legacy_sid_cache[raw]

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

        log = RecommendationLog(
            user_id=user_id,
            question_id=rec["question_id"],
            subject_id=sid,
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

    await db.commit()
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
