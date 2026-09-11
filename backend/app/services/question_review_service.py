"""Leitner 题目盒子 + next_review_at 复习调度服务。

V2 核心：为每个用户、每道题维护独立的复习状态，
根据答题表现动态计算 box_level 和 next_review_at。
"""

import inspect
import logging
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.user_question_state import UserQuestionState

logger = logging.getLogger(__name__)

# ── Leitner 间隔映射（天） ──
# box_level → 下次复习间隔天数
LEITNER_INTERVAL_DAYS: dict[int, int] = {
    0: 1,
    1: 3,
    2: 7,
    3: 14,
    4: 30,
    5: 60,
}

LEITNER_MAX_BOX = 5

# 复习掌握度与 Leitner 盒子统一：无需新增字段或迁移。
# 0 级代表刚做错；达到 3 级（80%）即自动掌握。
REVIEW_MASTERY_BY_BOX: dict[int, float] = {
    0: 0.20,
    1: 0.45,
    2: 0.65,
    3: 0.80,
    4: 0.90,
    5: 1.00,
}
AUTO_MASTERY_MIN_BOX = 3
AUTO_MASTERY_THRESHOLD = REVIEW_MASTERY_BY_BOX[AUTO_MASTERY_MIN_BOX]


def mastery_ratio_for_box(box_level: int | None) -> float:
    level = max(0, min(LEITNER_MAX_BOX, int(box_level or 0)))
    return REVIEW_MASTERY_BY_BOX[level]


def mastery_percent_for_box(box_level: int | None) -> int:
    return round(mastery_ratio_for_box(box_level) * 100)


def compute_next_box_level(
    current_box_level: int | None,
    is_correct: bool,
) -> int:
    """根据答题结果计算新的 Leitner 盒子等级。

    答对：box_level + 1，最高 5。
    答错：box_level - 2，最低 0。
    """
    level = current_box_level if current_box_level is not None else 0

    if is_correct:
        return min(level + 1, LEITNER_MAX_BOX)

    # 一次答错必须退出自动掌握区间。否则 5 级题按旧规则只降到 3 级，
    # 仍会显示 80% 并再次被判为已掌握，与“答错即取消掌握”冲突。
    return min(max(level - 2, 0), AUTO_MASTERY_MIN_BOX - 1)


class ReviewTransition(NamedTuple):
    """本次作答发生前的复习到期状态。

    必须在覆盖 ``next_review_at`` 之前计算，并传给 V6 自适应逻辑；否则
    V6 读到的是本次作答后新生成的未来复习时间，导致到期复习永远无法命中。
    """

    is_due_review: bool
    is_overdue_review: bool


def compute_next_review_at(box_level: int, base_time: datetime | None = None) -> datetime:
    """根据盒子等级计算下次复习时间。

    ``base_time`` 由答题记录时间传入时，可保证批量提交的复习时间与实际
    PracticeRecord.answered_at 使用同一时间基准。
    """
    interval_days = LEITNER_INTERVAL_DAYS.get(box_level, 1)
    return (base_time or utcnow()) + timedelta(days=interval_days)


async def update_user_question_state_after_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
    used_time: int | None = None,
    answered_at: datetime | None = None,
) -> ReviewTransition:
    """每次提交答案后，创建或更新 user_question_state。

    返回本次作答**之前**的到期状态，供 V6 自适应逻辑使用。这样调用方即使
    先更新 Leitner，再更新 V6，也不会用新的 ``next_review_at`` 错判本次复习。

    采用 best-effort 模式：失败时记录日志，不影响答题主流程。
    使用 flush() 而非 commit()，由调用方控制事务边界。
    """
    now = answered_at or utcnow()

    # 查询已有状态，并在任何字段覆盖之前保存本次作答前的到期状态。
    result = await db.execute(
        select(UserQuestionState).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id == question_id,
        )
    )
    state = result.scalar_one_or_none()

    previous_next_review_at = state.next_review_at if state is not None else None
    is_due_review = bool(
        previous_next_review_at is not None and now >= previous_next_review_at
    )
    is_overdue_review = bool(
        previous_next_review_at is not None
        and now >= previous_next_review_at + timedelta(days=1)
    )

    if state is None:
        # 首次作答：创建新状态
        state = UserQuestionState(
            user_id=user_id,
            question_id=question_id,
            box_level=0,
            answer_count=0,
            correct_count=0,
            wrong_count=0,
            correct_streak=0,
            wrong_streak=0,
        )
        db.add(state)

    # 计算新盒子等级
    new_box_level = compute_next_box_level(state.box_level, is_correct)
    state.box_level = new_box_level
    state.last_answered_at = now
    state.next_review_at = compute_next_review_at(new_box_level, base_time=now)

    # 更新计数
    state.answer_count = (state.answer_count or 0) + 1

    if is_correct:
        state.correct_count = (state.correct_count or 0) + 1
        state.correct_streak = (state.correct_streak or 0) + 1
        state.wrong_streak = 0
    else:
        state.wrong_count = (state.wrong_count or 0) + 1
        state.wrong_streak = (state.wrong_streak or 0) + 1
        state.correct_streak = 0

    state.last_is_correct = is_correct
    state.last_answer_time_seconds = used_time
    state.updated_at = now

    await db.flush()
    return ReviewTransition(
        is_due_review=is_due_review,
        is_overdue_review=is_overdue_review,
    )


async def get_due_question_ids(
    db: AsyncSession,
    user_id: int,
    question_ids: list[int],
) -> set[int]:
    """批量检查哪些题目已到期可以出现。

    返回：可以出现的 question_id 集合。
    规则：
    - 没有 UserQuestionState 记录 → 新题，可以出现
    - next_review_at IS NULL → 可以出现
    - next_review_at <= now → 到期，可以出现
    - next_review_at > now → 未到期，不出现
    """
    if not question_ids:
        return set()

    now = utcnow()
    result = await db.execute(
        select(UserQuestionState.question_id, UserQuestionState.next_review_at).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id.in_(question_ids),
        )
    )
    values = result.all()
    if inspect.isawaitable(values):
        values = await values
    state_map: dict[int, datetime | None] = {row[0]: row[1] for row in values}

    due_ids: set[int] = set()
    for qid in question_ids:
        if qid not in state_map:
            # 新题，没有状态记录
            due_ids.add(qid)
        elif state_map[qid] is None:
            # next_review_at 为空
            due_ids.add(qid)
        elif state_map[qid] <= now:
            # 已到期
            due_ids.add(qid)
        # else: 未到期，不加入

    return due_ids


async def get_user_question_mastery(
    db: AsyncSession,
    user_id: int,
    question_id: int,
) -> dict:
    """读取统一的题目复习掌握度。

    没有状态记录时按“刚进入错题本”的 20% 处理，避免异步投影尚未完成时
    错题本短暂显示 0%。
    """
    result = await db.execute(
        select(UserQuestionState).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id == question_id,
        )
    )
    state = result.scalar_one_or_none()
    box_level = state.box_level if state is not None else 0
    ratio = mastery_ratio_for_box(box_level)
    return {
        "box_level": box_level,
        "mastery_ratio": ratio,
        "mastery_percent": round(ratio * 100),
        "auto_mastered": ratio >= AUTO_MASTERY_THRESHOLD,
    }
