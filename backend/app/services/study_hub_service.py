"""408 智能学习中心聚合与决策服务。

这个模块只负责“今天先做什么”的决策与解释，不创建第二套刷题/复习事实源。
所有任务最终仍落到现有 review 或 practice runner。
"""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import (
    EXAM408_ALL_CODES,
    EXAM408_CORE_CODES,
    EXAM408_ROOT_CODE,
    select_408_subject_records,
)
from app.core.time_utils import shanghai_date_utc_range, shanghai_today
from app.models.admin import QuestionVersion, Subject
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.models.user_question_difficulty_state import UserQuestionDifficultyState
from app.services import adaptive_learning_service, review_scheduler

WEAK_TASK_COUNT = 8
HARD_TASK_COUNT = 5
PATH_TASK_COUNT = 6
SMART_TASK_COUNT = 10

_ANSWERABLE_TYPES = (
    "single_choice",
    "multiple_choice",
    "true_false",
    "multi_blank_choice",
)


def _minutes_for_questions(count: int, *, per_question_sec: int = 90) -> int:
    count = max(0, int(count or 0))
    if count <= 0:
        return 0
    return max(1, min(120, round(count * per_question_sec / 60)))


def _practice_params(
    *,
    subject_id: int,
    mode: str,
    count: int,
    knowledge_point: str | None = None,
    question_ids: list[int] | None = None,
    allow_repeat: bool = False,
) -> dict:
    params: dict = {
        "subject_id": int(subject_id),
        "mode": str(mode),
        "count": int(count),
        "autostart": 1,
        "source": "study_hub",
    }
    if knowledge_point:
        params["knowledge_point"] = str(knowledge_point)
    if question_ids:
        params["question_ids"] = ",".join(str(int(qid)) for qid in question_ids)
    if allow_repeat:
        params["allow_repeat"] = 1
    return params


async def _load_subject_scope(db: AsyncSession) -> tuple[Subject | None, list[Subject]]:
    rows = list((await db.scalars(
        select(Subject).where(Subject.code.in_(EXAM408_ALL_CODES))
    )).all())
    selected = select_408_subject_records(rows)
    by_code = {str(row.code): row for row in selected}
    root = by_code.get(EXAM408_ROOT_CODE)
    cores = [by_code[code] for code in EXAM408_CORE_CODES if code in by_code]
    if root is None or len(cores) != len(EXAM408_CORE_CODES):
        return None, []
    return root, cores


async def _load_408_practice_counts(
    db: AsyncSession,
    user_id: int,
    core_subject_ids: list[int],
) -> tuple[int, int]:
    """Return (total, today) practice counts strictly inside canonical 408 leaves.

    The global stats service intentionally represents the whole account.  Study Hub
    is a 408 product surface, so keep its goal/progress counters isolated even if
    other subjects are enabled again in the future.
    """
    if not core_subject_ids:
        return 0, 0

    total = (await db.execute(
        select(func.count(PracticeRecord.id)).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.subject_id.in_(core_subject_ids),
        )
    )).scalar_one() or 0

    today_start, tomorrow_start = shanghai_date_utc_range(shanghai_today())
    today = (await db.execute(
        select(func.count(PracticeRecord.id)).where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.subject_id.in_(core_subject_ids),
            PracticeRecord.answered_at >= today_start,
            PracticeRecord.answered_at < tomorrow_start,
        )
    )).scalar_one() or 0
    return int(total), int(today)


async def _build_subject_mastery(
    db: AsyncSession,
    user_id: int,
    core_subjects: list[Subject],
) -> list[dict]:
    core_ids = [int(subject.id) for subject in core_subjects]
    if not core_ids:
        return []

    rows = await db.execute(
        select(
            UserKnowledgeState.subject_id,
            func.avg(UserKnowledgeState.mastery_score),
            func.avg(UserKnowledgeState.confidence),
            func.coalesce(func.sum(UserKnowledgeState.attempt_count), 0),
            func.coalesce(func.sum(UserKnowledgeState.correct_count), 0),
            func.coalesce(func.sum(UserKnowledgeState.wrong_count), 0),
            func.count(UserKnowledgeState.id),
        )
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id.in_(core_ids),
            UserKnowledgeState.attempt_count > 0,
        )
        .group_by(UserKnowledgeState.subject_id)
    )
    aggregate = {int(row[0]): row for row in rows.all()}

    result: list[dict] = []
    for subject in core_subjects:
        row = aggregate.get(int(subject.id))
        if row is None:
            result.append({
                "subject_id": int(subject.id),
                "subject_code": str(subject.code),
                "subject_name": str(subject.name),
                "data_available": False,
                "mastery_score": None,
                "confidence": 0.0,
                "attempt_count": 0,
                "accuracy": None,
            })
            continue
        attempts = int(row[3] or 0)
        correct = int(row[4] or 0)
        result.append({
            "subject_id": int(subject.id),
            "subject_code": str(subject.code),
            "subject_name": str(subject.name),
            "data_available": bool(row[6] and attempts > 0),
            "mastery_score": round(float(row[1] or 0.0), 1),
            "confidence": round(float(row[2] or 0.0), 3),
            "attempt_count": attempts,
            "accuracy": round(correct / attempts, 4) if attempts > 0 else None,
        })
    return result


async def _pick_weak_point(
    db: AsyncSession,
    user_id: int,
    core_subject_ids: list[int],
) -> dict | None:
    """Pick a real, trainable weak point with a deterministic ranking.

    A low mastery row is not enough: the current question bank must still contain
    at least three approved, answerable questions whose mutable row and issued
    revision agree on the same canonical 408 subject.
    """
    available_count = func.count(func.distinct(Question.id))
    row = (await db.execute(
        select(
            UserKnowledgeState.knowledge_point_id,
            KnowledgePoint.name,
            UserKnowledgeState.subject_id,
            Subject.code,
            Subject.name,
            UserKnowledgeState.mastery_score,
            UserKnowledgeState.confidence,
            UserKnowledgeState.attempt_count,
            UserKnowledgeState.wrong_count,
            UserKnowledgeState.recent_wrong_count,
            available_count.label("available_question_count"),
        )
        .join(KnowledgePoint, KnowledgePoint.id == UserKnowledgeState.knowledge_point_id)
        .join(Subject, Subject.id == UserKnowledgeState.subject_id)
        .join(
            QuestionKnowledgePoint,
            QuestionKnowledgePoint.knowledge_point_id == UserKnowledgeState.knowledge_point_id,
        )
        .join(Question, Question.id == QuestionKnowledgePoint.question_id)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id.in_(core_subject_ids),
            UserKnowledgeState.attempt_count >= 2,
            UserKnowledgeState.mastery_score < 70,
            KnowledgePoint.is_active.is_(True),
            KnowledgePoint.subject_id == UserKnowledgeState.subject_id,
            Question.subject_id == UserKnowledgeState.subject_id,
            Question.is_active.is_(True),
            Question.review_status == "approved",
            QuestionVersion.question_id == Question.id,
            QuestionVersion.subject_id == Question.subject_id,
            QuestionVersion.question_type == Question.question_type,
            QuestionVersion.question_type.in_(_ANSWERABLE_TYPES),
            QuestionVersion.is_active.is_(True),
        )
        .group_by(
            UserKnowledgeState.knowledge_point_id,
            KnowledgePoint.name,
            UserKnowledgeState.subject_id,
            Subject.code,
            Subject.name,
            UserKnowledgeState.mastery_score,
            UserKnowledgeState.confidence,
            UserKnowledgeState.attempt_count,
            UserKnowledgeState.wrong_count,
            UserKnowledgeState.recent_wrong_count,
        )
        .having(available_count >= 3)
        .order_by(
            case((UserKnowledgeState.recent_wrong_count >= 2, 0), else_=1),
            UserKnowledgeState.recent_wrong_count.desc(),
            UserKnowledgeState.mastery_score.asc(),
            UserKnowledgeState.wrong_count.desc(),
            UserKnowledgeState.knowledge_point_id.asc(),
        )
        .limit(1)
    )).first()
    if row is None:
        return None
    return {
        "knowledge_point_id": int(row[0]),
        "knowledge_point_name": str(row[1]),
        "subject_id": int(row[2]),
        "subject_code": str(row[3] or ""),
        "subject_name": str(row[4] or ""),
        "mastery_score": round(float(row[5] or 0.0), 1),
        "confidence": round(float(row[6] or 0.0), 3),
        "attempt_count": int(row[7] or 0),
        "wrong_count": int(row[8] or 0),
        "recent_wrong_count": int(row[9] or 0),
        "available_question_count": int(row[10] or 0),
    }


async def _pick_hard_questions(
    db: AsyncSession,
    user_id: int,
    core_subject_ids: list[int],
    *,
    limit: int = HARD_TASK_COUNT,
) -> list[dict]:
    rows = await db.execute(
        select(
            UserQuestionDifficultyState.question_id,
            UserQuestionDifficultyState.personal_difficulty_score,
            UserQuestionDifficultyState.wrong_count,
            Question.subject_id,
        )
        .join(Question, Question.id == UserQuestionDifficultyState.question_id)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .where(
            UserQuestionDifficultyState.user_id == user_id,
            UserQuestionDifficultyState.difficulty_label == "hard",
            Question.subject_id.in_(core_subject_ids),
            Question.is_active.is_(True),
            Question.review_status == "approved",
            QuestionVersion.question_id == Question.id,
            QuestionVersion.subject_id == Question.subject_id,
            QuestionVersion.question_type == Question.question_type,
            QuestionVersion.question_type.in_(_ANSWERABLE_TYPES),
            QuestionVersion.is_active.is_(True),
        )
        .order_by(
            UserQuestionDifficultyState.personal_difficulty_score.desc(),
            UserQuestionDifficultyState.wrong_count.desc(),
            UserQuestionDifficultyState.question_id.asc(),
        )
        .limit(limit)
    )
    return [
        {
            "question_id": int(row[0]),
            "difficulty_score": round(float(row[1] or 0.0), 1),
            "wrong_count": int(row[2] or 0),
            "subject_id": int(row[3]),
        }
        for row in rows.all()
    ]


async def _count_trainable_kp_questions(
    db: AsyncSession,
    *,
    knowledge_point_id: int,
    subject_id: int,
) -> int:
    result = await db.execute(
        select(func.count(func.distinct(Question.id)))
        .join(QuestionKnowledgePoint, QuestionKnowledgePoint.question_id == Question.id)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .where(
            QuestionKnowledgePoint.knowledge_point_id == knowledge_point_id,
            Question.subject_id == subject_id,
            Question.is_active.is_(True),
            Question.review_status == "approved",
            QuestionVersion.question_id == Question.id,
            QuestionVersion.subject_id == Question.subject_id,
            QuestionVersion.question_type == Question.question_type,
            QuestionVersion.question_type.in_(_ANSWERABLE_TYPES),
            QuestionVersion.is_active.is_(True),
        )
    )
    return int(result.scalar_one() or 0)


async def _pick_path_prerequisite(
    db: AsyncSession,
    user_id: int,
    core_subject_ids: list[int],
) -> dict | None:
    target_rows = await db.execute(
        select(KnowledgeEdge.target_knowledge_point_id)
        .where(
            KnowledgeEdge.subject_id.in_(core_subject_ids),
            KnowledgeEdge.relation_type == "prerequisite",
            KnowledgeEdge.is_active.is_(True),
        )
        .distinct()
        .order_by(KnowledgeEdge.target_knowledge_point_id.asc())
    )
    target_ids = [int(row[0]) for row in target_rows.all()]
    if not target_ids:
        return None

    context = await adaptive_learning_service.get_recommendation_graph_context(
        db,
        user_id,
        target_ids,
        subject_ids=core_subject_ids,
    )
    blocked_targets = context.get("blocked_targets") or {}
    if not blocked_targets:
        return None

    # 确定性选择：阻塞前置最多的 target 优先；同数时 target id 小者优先。
    ranked_targets = sorted(
        ((int(target_id), blockers) for target_id, blockers in blocked_targets.items()),
        key=lambda item: (-len(item[1] or []), item[0]),
    )
    target_id, blockers = ranked_targets[0]
    blockers = sorted(
        blockers or [],
        key=lambda item: (
            float(item.get("mastery_score", 50.0)),
            -float(item.get("path_quality", 0.0)),
            int(item.get("knowledge_point_id") or 0),
        ),
    )
    for prereq in blockers:
        prereq_subject_id = int(prereq.get("subject_id") or 0)
        prereq_kp_id = int(prereq.get("knowledge_point_id") or 0)
        if prereq_subject_id not in core_subject_ids or prereq_kp_id <= 0:
            continue
        available_count = await _count_trainable_kp_questions(
            db,
            knowledge_point_id=prereq_kp_id,
            subject_id=prereq_subject_id,
        )
        if available_count < 3:
            continue

        subject = (await db.execute(
            select(Subject).where(Subject.id == prereq_subject_id)
        )).scalar_one_or_none()
        if subject is None:
            continue
        return {
            "target_knowledge_point_id": target_id,
            "target_knowledge_point_name": str(prereq.get("origin_name") or ""),
            "knowledge_point_id": prereq_kp_id,
            "knowledge_point_name": str(prereq.get("name") or ""),
            "subject_id": prereq_subject_id,
            "subject_code": str(subject.code),
            "subject_name": str(subject.name),
            "mastery_score": round(float(prereq.get("mastery_score") or 0.0), 1),
            "available_question_count": available_count,
        }
    return None


async def get_study_hub_overview(db: AsyncSession, user_id: int) -> dict:
    root, core_subjects = await _load_subject_scope(db)
    if root is None or len(core_subjects) != len(EXAM408_CORE_CODES):
        # 迁移/科目治理异常时宁可明确失败态，也不要用旧编码或名称猜测产品身份。
        fallback_task = {
            "key": "scope-not-ready",
            "task_type": "smart_practice",
            "priority": 1,
            "title": "408 科目配置需要检查",
            "reason": "未找到完整的 canonical 408 科目树，请先完成科目治理后再开始智能学习。",
            "action_label": "查看刷题入口",
            "route": "practice",
            "route_params": {},
            "estimated_question_count": 0,
            "estimated_minutes": 0,
        }
        return {
            "date": shanghai_today().isoformat(),
            "scope": EXAM408_ROOT_CODE,
            "scope_ready": False,
            "fallback_used": True,
            "today_question_count": 0,
            "total_practice_count": 0,
            "review": {},
            "primary_task": fallback_task,
            "tasks": [fallback_task],
            "subject_mastery": [],
        }

    root_id = int(root.id)
    core_ids = [int(subject.id) for subject in core_subjects]

    review_overview = await review_scheduler.get_today_review_overview(db, user_id)
    total_practice_count, today_question_count = await _load_408_practice_counts(
        db, user_id, core_ids
    )
    subject_mastery = await _build_subject_mastery(db, user_id, core_subjects)
    weak_point = await _pick_weak_point(db, user_id, core_ids)
    hard_questions = await _pick_hard_questions(db, user_id, core_ids)
    path_prereq = await _pick_path_prerequisite(db, user_id, core_ids)

    remaining_review = int(review_overview.get("today_remaining_count") or 0)

    tasks: list[dict] = []

    if remaining_review > 0:
        overdue = int(review_overview.get("today_overdue_count") or 0)
        reason = (
            f"其中 {overdue} 道已经逾期，先处理可避免复习债继续累积。"
            if overdue > 0
            else "这些题已经进入最佳复习窗口，优先巩固比继续加新题更划算。"
        )
        tasks.append({
            "key": "review:due",
            "task_type": "review",
            "priority": 0,
            "title": f"先完成 {remaining_review} 道到期复习",
            "reason": reason,
            "action_label": "开始今日复习",
            "route": "review_today",
            "route_params": {},
            "estimated_question_count": remaining_review,
            "estimated_minutes": int(review_overview.get("estimated_minutes") or 0),
        })

    if weak_point is not None:
        recent_wrong = int(weak_point["recent_wrong_count"])
        if recent_wrong >= 2:
            reason = (
                f"「{weak_point['knowledge_point_name']}」近期重复错误 {recent_wrong} 次，"
                f"当前掌握度约 {round(weak_point['mastery_score'])} 分。"
            )
        else:
            reason = (
                f"已练 {weak_point['attempt_count']} 次，当前掌握度约 "
                f"{round(weak_point['mastery_score'])} 分，适合做一轮小范围强化。"
            )
        weak_count = min(WEAK_TASK_COUNT, int(weak_point["available_question_count"]))
        tasks.append({
            "key": f"weak:{weak_point['knowledge_point_id']}",
            "task_type": "weakness",
            "priority": 0,
            "title": f"强化「{weak_point['knowledge_point_name']}」",
            "reason": reason,
            "action_label": "开始弱项强化",
            "route": "practice",
            "route_params": _practice_params(
                subject_id=weak_point["subject_id"],
                mode="random",
                count=weak_count,
                knowledge_point=weak_point["knowledge_point_name"],
                allow_repeat=True,
            ),
            "estimated_question_count": weak_count,
            "estimated_minutes": _minutes_for_questions(weak_count),
            "subject_id": weak_point["subject_id"],
            "subject_code": weak_point["subject_code"],
            "subject_name": weak_point["subject_name"],
            "knowledge_point_id": weak_point["knowledge_point_id"],
            "knowledge_point_name": weak_point["knowledge_point_name"],
        })

    if hard_questions:
        hard_ids = [item["question_id"] for item in hard_questions]
        max_wrong = max(int(item["wrong_count"]) for item in hard_questions)
        reason = (
            f"系统识别出 {len(hard_ids)} 道个人高难题"
            + (f"，其中最高已错 {max_wrong} 次。" if max_wrong > 0 else "，适合重新检验解题稳定性。")
        )
        tasks.append({
            "key": "hard:top",
            "task_type": "hard_questions",
            "priority": 0,
            "title": f"重练 {len(hard_ids)} 道个人难题",
            "reason": reason,
            "action_label": "开始困难题重练",
            "route": "practice",
            "route_params": _practice_params(
                subject_id=root_id,
                mode="random",
                count=len(hard_ids),
                question_ids=hard_ids,
            ),
            "estimated_question_count": len(hard_ids),
            "estimated_minutes": _minutes_for_questions(len(hard_ids), per_question_sec=120),
            "subject_id": root_id,
            "subject_code": str(root.code),
            "subject_name": str(root.name),
            "question_ids": hard_ids,
        })

    used_kp_ids = {
        int(task["knowledge_point_id"])
        for task in tasks
        if task.get("knowledge_point_id") is not None
    }
    if path_prereq is not None and path_prereq["knowledge_point_id"] not in used_kp_ids:
        target_name = path_prereq["target_knowledge_point_name"] or "后续知识点"
        path_count = min(PATH_TASK_COUNT, int(path_prereq["available_question_count"]))
        tasks.append({
            "key": f"path:{path_prereq['knowledge_point_id']}:{path_prereq['target_knowledge_point_id']}",
            "task_type": "knowledge_path",
            "priority": 0,
            "title": f"先补「{path_prereq['knowledge_point_name']}」",
            "reason": (
                f"它是「{target_name}」的前置知识，当前掌握度约 "
                f"{round(path_prereq['mastery_score'])} 分；先补前置再推进更稳。"
            ),
            "action_label": "继续知识路径",
            "route": "practice",
            "route_params": _practice_params(
                subject_id=path_prereq["subject_id"],
                mode="random",
                count=path_count,
                knowledge_point=path_prereq["knowledge_point_name"],
                allow_repeat=True,
            ),
            "estimated_question_count": path_count,
            "estimated_minutes": _minutes_for_questions(path_count),
            "subject_id": path_prereq["subject_id"],
            "subject_code": path_prereq["subject_code"],
            "subject_name": path_prereq["subject_name"],
            "knowledge_point_id": path_prereq["knowledge_point_id"],
            "knowledge_point_name": path_prereq["knowledge_point_name"],
        })

    # 无历史数据时明确回退随机；有数据时进入现有 smart 推荐链，后续的题目级
    # exposure/click/answer 继续沿用 recommendation_log/feedback 机制。
    is_new_user = total_practice_count <= 0
    smart_mode = "random" if is_new_user else "smart"
    tasks.append({
        "key": "practice:fallback" if is_new_user else "practice:smart",
        "task_type": "smart_practice",
        "priority": 0,
        "title": "完成第一组 408 练习" if is_new_user else "继续 408 智能新题",
        "reason": (
            "当前学习数据还不足，先完成一组四科练习建立个性化推荐基线。"
            if is_new_user
            else "结合当前知识状态与近期表现继续推进新题，避免只在旧错题里循环。"
        ),
        "action_label": "开始 408 练习" if is_new_user else "开始智能练习",
        "route": "practice",
        "route_params": _practice_params(
            subject_id=root_id,
            mode=smart_mode,
            count=SMART_TASK_COUNT,
        ),
        "estimated_question_count": SMART_TASK_COUNT,
        "estimated_minutes": _minutes_for_questions(SMART_TASK_COUNT),
        "subject_id": root_id,
        "subject_code": str(root.code),
        "subject_name": str(root.name),
    })

    # 决策顺序是产品规则本身，保持确定性。完成复习后 review 会自然消失，
    # 其他任务只有学习状态真实变化时才会重新排序。
    task_order = {
        "review": 1,
        "weakness": 2,
        "hard_questions": 3,
        "knowledge_path": 4,
        "smart_practice": 5,
    }
    tasks.sort(key=lambda task: (task_order[task["task_type"]], task["key"]))
    for index, task in enumerate(tasks, start=1):
        task["priority"] = index

    review_summary = {
        "due_count": int(review_overview.get("today_due_count") or 0),
        "completed_count": int(review_overview.get("today_completed_count") or 0),
        "remaining_count": remaining_review,
        "overdue_count": int(review_overview.get("today_overdue_count") or 0),
        "estimated_minutes": int(review_overview.get("estimated_minutes") or 0),
    }

    return {
        "date": shanghai_today().isoformat(),
        "scope": EXAM408_ROOT_CODE,
        "scope_ready": True,
        "fallback_used": is_new_user,
        "today_question_count": today_question_count,
        "total_practice_count": total_practice_count,
        "review": review_summary,
        "primary_task": tasks[0],
        "tasks": tasks,
        "subject_mastery": subject_mastery,
    }
