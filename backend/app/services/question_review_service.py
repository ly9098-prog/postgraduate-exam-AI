"""Leitner 题目盒子 + next_review_at 复习调度服务。

V2 核心：为每个用户、每道题维护独立的复习状态，
根据答题表现动态计算 box_level 和 next_review_at。
"""

import logging
from datetime import datetime, timedelta

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

    return max(level - 2, 0)


def compute_next_review_at(box_level: int) -> datetime:
    """根据盒子等级计算下次复习时间。"""
    interval_days = LEITNER_INTERVAL_DAYS.get(box_level, 1)
    return utcnow() + timedelta(days=interval_days)


async def update_user_question_state_after_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
    used_time: int | None = None,
) -> None:
    """每次提交答案后，创建或更新 user_question_state。

    采用 best-effort 模式：失败时记录日志，不影响答题主流程。
    使用 flush() 而非 commit()，由调用方控制事务边界。
    """
    now = utcnow()

    # 查询已有状态
    result = await db.execute(
        select(UserQuestionState).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id == question_id,
        )
    )
    state = result.scalar_one_or_none()

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
    state.next_review_at = compute_next_review_at(new_box_level)

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
    state_map: dict[int, datetime | None] = {
        row[0]: row[1] for row in result.all()
    }

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
