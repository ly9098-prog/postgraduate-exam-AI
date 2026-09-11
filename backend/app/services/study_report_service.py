"""V5 学习报告服务 — 纯统计查询，不修改任何数据。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import Date as SQLDate, case, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import (
    shanghai_date_utc_range,
    shanghai_today,
    shanghai_today_boundaries,
    utcnow,
)
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.models.user_question_state import UserQuestionState

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────


def _today_utc() -> datetime:
    """Return China today's midnight converted to naive UTC."""
    return shanghai_today_boundaries()[0]


async def _china_date_expr(db: AsyncSession, column):
    bind = await db.connection()
    if bind.sync_connection.dialect.name == "sqlite":
        return func.date(column, "+8 hours")
    return cast(column + text("INTERVAL '8 hours'"), SQLDate)


def _safe_accuracy(correct: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(correct / total * 100, 2)


def _extract_title(content_json) -> str:
    """从 Question.content (JSON) 中提取纯文本前 100 字符。"""
    if not content_json:
        return ""
    # 如果已经是字符串且不是 JSON 格式，直接截断返回
    if isinstance(content_json, str):
        stripped = content_json.strip()
        if not (stripped.startswith("[") or stripped.startswith("{")):
            return content_json[:100]
    try:
        content = (
            json.loads(content_json) if isinstance(content_json, str) else content_json
        )
        if isinstance(content, list):
            for seg in content:
                if isinstance(seg, dict) and seg.get("type") == "text":
                    return seg.get("text", "")[:100]
        if isinstance(content, str):
            return content[:100]
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


def _classify_mastery(confidence: float, mastery_score: float) -> str:
    if confidence < 0.3:
        return "unknown"
    if mastery_score < 40:
        return "weak"
    if mastery_score < 70:
        return "normal"
    if mastery_score < 85:
        return "good"
    return "mastered"


def _mastery_suggestion(status: str) -> str:
    return {
        "weak": "建议优先复习该知识点，并补充同类新题",
        "normal": "建议保持练习，重点关注错题",
        "good": "掌握较好，可以低频复习",
        "mastered": "已较稳定掌握，后续偶尔复现即可",
        "unknown": "数据较少，建议继续练习以提高判断准确度",
    }.get(status, "")


def _calc_priority(overdue_days: int, wrong_count: int, box_level: int) -> str:
    if overdue_days >= 3 or wrong_count >= 3 or box_level <= 1:
        return "high"
    if overdue_days >= 1 or wrong_count >= 1:
        return "medium"
    return "normal"


async def _subject_exists(db: AsyncSession, subject_id: int) -> bool:
    """Check whether a subject id exists in the subjects table."""
    from app.models.admin import Subject

    result = await db.execute(
        select(Subject.id).where(Subject.id == subject_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


# ── 1. Overview ─────────────────────────────────────────────────────


async def get_overview(
    db: AsyncSession, user_id: int, subject_id: int | None = None, days: int = 7
) -> dict:
    now = utcnow()
    today_start = _today_utc()
    recent_start = today_start - timedelta(days=days)

    # -- 答题统计（today / recent / total 一次查询） --
    pr_q = select(
        func.coalesce(
            func.sum(case((PracticeRecord.answered_at >= today_start, 1), else_=0)), 0
        ).label("today_count"),
        func.coalesce(
            func.sum(
                case(
                    (
                        (PracticeRecord.answered_at >= today_start)
                        & (PracticeRecord.is_correct == True),  # noqa: E712
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("today_correct"),
        func.coalesce(
            func.sum(case((PracticeRecord.answered_at >= recent_start, 1), else_=0)), 0
        ).label("recent_count"),
        func.coalesce(
            func.sum(
                case(
                    (
                        (PracticeRecord.answered_at >= recent_start)
                        & (PracticeRecord.is_correct == True),  # noqa: E712
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("recent_correct"),
        func.count(PracticeRecord.id).label("total_count"),
        func.coalesce(
            func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)),  # noqa: E712
            0,  # noqa: E712
        ).label("total_correct"),
    ).where(PracticeRecord.user_id == user_id)

    if subject_id is not None:
        pr_q = pr_q.where(PracticeRecord.subject_id == subject_id)

    pr_row = (await db.execute(pr_q)).one()
    today_count = int(pr_row.today_count or 0)
    today_correct = int(pr_row.today_correct or 0)
    recent_count = int(pr_row.recent_count or 0)
    recent_correct = int(pr_row.recent_correct or 0)
    total_count = int(pr_row.total_count or 0)
    total_correct = int(pr_row.total_correct or 0)

    # -- 待复习 / 逾期 --
    overdue_threshold = now - timedelta(days=1)

    def _uqs_count_q(where_extra):
        """构造 UserQuestionState 计数查询，支持可选 subject 过滤。"""
        q = select(func.count(UserQuestionState.id)).where(
            UserQuestionState.user_id == user_id, *where_extra
        )
        if subject_id is not None:
            q = q.join(Question, UserQuestionState.question_id == Question.id).where(
                Question.subject_id == subject_id
            )
        return q

    due_count = (
        await db.execute(
            _uqs_count_q(
                [
                    UserQuestionState.next_review_at <= now,
                    UserQuestionState.next_review_at.isnot(None),
                ]
            )
        )
    ).scalar_one()

    overdue_count = (
        await db.execute(
            _uqs_count_q(
                [
                    UserQuestionState.next_review_at < overdue_threshold,
                    UserQuestionState.next_review_at.isnot(None),
                ]
            )
        )
    ).scalar_one()

    # -- 错题统计（与知识点无关，始终计算） --
    def _wq_count_q(where_extra):
        q = select(func.count(UserQuestionState.id)).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.wrong_count > 0,
            *where_extra,
        )
        if subject_id is not None:
            q = q.join(Question, UserQuestionState.question_id == Question.id).where(
                Question.subject_id == subject_id
            )
        return q

    wrong_total = (await db.execute(_wq_count_q([]))).scalar_one()

    repeated_wrong = (
        await db.execute(_wq_count_q([UserQuestionState.wrong_count >= 3]))
    ).scalar_one()

    # -- 知识点分类 --
    ks_subject_filter = []
    if subject_id is not None:
        if not await _subject_exists(db, subject_id):
            # 该 subject_id 不存在，知识点统计返回 0，但错题统计仍有效
            return {
                "today_answer_count": today_count,
                "today_correct_count": today_correct,
                "today_accuracy": _safe_accuracy(today_correct, today_count),
                "recent_answer_count": recent_count,
                "recent_correct_count": recent_correct,
                "recent_accuracy": _safe_accuracy(recent_correct, recent_count),
                "total_answer_count": total_count,
                "total_correct_count": total_correct,
                "total_accuracy": _safe_accuracy(total_correct, total_count),
                "due_review_count": int(due_count),
                "overdue_review_count": int(overdue_count),
                "weak_knowledge_count": 0,
                "unstable_knowledge_count": 0,
                "mastered_knowledge_count": 0,
                "wrong_question_count": int(wrong_total),
                "repeated_wrong_question_count": int(repeated_wrong),
            }
        ks_subject_filter.append(UserKnowledgeState.subject_id == subject_id)

    def _ks_count_q(where_extra):
        q = select(func.count(UserKnowledgeState.id)).where(
            UserKnowledgeState.user_id == user_id, *ks_subject_filter, *where_extra
        )
        return q

    weak_count = (
        await db.execute(
            _ks_count_q(
                [
                    UserKnowledgeState.mastery_score < 40,
                    UserKnowledgeState.confidence >= 0.3,
                ]
            )
        )
    ).scalar_one()

    unstable_count = (
        await db.execute(
            _ks_count_q(
                [
                    UserKnowledgeState.mastery_score >= 40,
                    UserKnowledgeState.mastery_score < 85,
                    UserKnowledgeState.confidence >= 0.3,
                ]
            )
        )
    ).scalar_one()

    mastered_count = (
        await db.execute(
            _ks_count_q(
                [
                    UserKnowledgeState.mastery_score >= 85,
                    UserKnowledgeState.confidence >= 0.5,
                ]
            )
        )
    ).scalar_one()

    return {
        "today_answer_count": today_count,
        "today_correct_count": today_correct,
        "today_accuracy": _safe_accuracy(today_correct, today_count),
        "recent_answer_count": recent_count,
        "recent_correct_count": recent_correct,
        "recent_accuracy": _safe_accuracy(recent_correct, recent_count),
        "total_answer_count": total_count,
        "total_correct_count": total_correct,
        "total_accuracy": _safe_accuracy(total_correct, total_count),
        "due_review_count": int(due_count),
        "overdue_review_count": int(overdue_count),
        "weak_knowledge_count": int(weak_count),
        "unstable_knowledge_count": int(unstable_count),
        "mastered_knowledge_count": int(mastered_count),
        "wrong_question_count": int(wrong_total),
        "repeated_wrong_question_count": int(repeated_wrong),
    }


# ── 2. Review Plan ──────────────────────────────────────────────────


async def get_review_plan(
    db: AsyncSession, user_id: int, subject_id: int | None = None, limit: int = 20
) -> dict:
    now = utcnow()
    overdue_threshold = now - timedelta(days=1)

    # 总数
    def _rp_count_q(where_extra):
        q = select(func.count(UserQuestionState.id)).where(
            UserQuestionState.user_id == user_id, *where_extra
        )
        if subject_id is not None:
            q = q.join(Question, UserQuestionState.question_id == Question.id).where(
                Question.subject_id == subject_id
            )
        return q

    due_count = (
        await db.execute(
            _rp_count_q(
                [
                    UserQuestionState.next_review_at <= now,
                    UserQuestionState.next_review_at.isnot(None),
                ]
            )
        )
    ).scalar_one()

    overdue_count = (
        await db.execute(
            _rp_count_q(
                [
                    UserQuestionState.next_review_at < overdue_threshold,
                    UserQuestionState.next_review_at.isnot(None),
                ]
            )
        )
    ).scalar_one()

    # 明细列表（按优先级排序）
    items_q = select(
        UserQuestionState.question_id,
        UserQuestionState.box_level,
        UserQuestionState.wrong_count,
        UserQuestionState.correct_count,
        UserQuestionState.next_review_at,
    ).where(
        UserQuestionState.user_id == user_id,
        UserQuestionState.next_review_at <= now,
        UserQuestionState.next_review_at.isnot(None),
    )
    if subject_id is not None:
        items_q = items_q.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)

    items_q = items_q.order_by(
        UserQuestionState.next_review_at.asc(),
        UserQuestionState.box_level.asc(),
        UserQuestionState.wrong_count.desc(),
    ).limit(limit)

    rows = (await db.execute(items_q)).all()
    q_ids = [r.question_id for r in rows]

    # 批量加载知识点
    kp_map: dict[int, tuple[int, str]] = {}
    if q_ids:
        kp_rows = (
            await db.execute(
                select(
                    QuestionKnowledgePoint.question_id,
                    QuestionKnowledgePoint.knowledge_point_id,
                    KnowledgePoint.name,
                )
                .join(
                    KnowledgePoint,
                    QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
                )
                .where(QuestionKnowledgePoint.question_id.in_(q_ids))
                .order_by(QuestionKnowledgePoint.question_id, QuestionKnowledgePoint.id)
            )
        ).all()
        for r in kp_rows:
            if r.question_id not in kp_map:
                kp_map[r.question_id] = (r.knowledge_point_id, r.name)

    items = []
    for r in rows:
        overdue_days = (
            max(0, int((now - r.next_review_at).total_seconds() // 86400))
            if r.next_review_at
            else 0
        )
        kp = kp_map.get(r.question_id)
        items.append(
            {
                "question_id": r.question_id,
                "knowledge_point_id": kp[0] if kp else None,
                "knowledge_point_name": kp[1] if kp else None,
                "box_level": r.box_level,
                "wrong_count": r.wrong_count,
                "correct_count": r.correct_count,
                "next_review_at": r.next_review_at,
                "overdue_days": overdue_days,
                "priority": _calc_priority(overdue_days, r.wrong_count, r.box_level),
            }
        )

    return {
        "due_count": int(due_count),
        "overdue_count": int(overdue_count),
        "today_recommended_count": len(items),
        "items": items,
    }


# ── 3. Leitner Distribution ─────────────────────────────────────────

_BOX_META = [
    (0, "很不熟", "刚做错或反复错误，需要尽快复习"),
    (1, "初步接触", "刚开始掌握，需要短周期复习"),
    (2, "有点熟", "有一定掌握，需要周期复习"),
    (3, "较熟", "掌握较好，保持复习"),
    (4, "熟练", "较稳定掌握，低频复习"),
    (5, "稳定掌握", "长期稳定，偶尔复现"),
]


async def get_leitner_distribution(
    db: AsyncSession, user_id: int, subject_id: int | None = None
) -> dict:
    q = select(
        UserQuestionState.box_level,
        func.count(UserQuestionState.id).label("cnt"),
    ).where(UserQuestionState.user_id == user_id)

    if subject_id is not None:
        q = q.join(Question, UserQuestionState.question_id == Question.id).where(
            Question.subject_id == subject_id
        )

    q = q.group_by(UserQuestionState.box_level)
    rows = (await db.execute(q)).all()
    counts = {r.box_level: int(r.cnt) for r in rows}

    total = sum(counts.values())
    boxes = [
        {
            "box_level": lv,
            "label": label,
            "description": desc,
            "count": counts.get(lv, 0),
        }
        for lv, label, desc in _BOX_META
    ]

    return {"boxes": boxes, "total_tracked_questions": total}


# ── 4. Knowledge Mastery ────────────────────────────────────────────


async def get_knowledge_mastery(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    limit: int = 50,
    sort: str = "weak_first",
) -> dict:
    q = select(
        UserKnowledgeState.knowledge_point_id,
        KnowledgePoint.name.label("kp_name"),
        UserKnowledgeState.mastery_score,
        UserKnowledgeState.confidence,
        UserKnowledgeState.attempt_count,
        UserKnowledgeState.correct_count,
        UserKnowledgeState.wrong_count,
        UserKnowledgeState.recent_wrong_count,
        UserKnowledgeState.last_practiced_at,
    ).join(KnowledgePoint, UserKnowledgeState.knowledge_point_id == KnowledgePoint.id)

    q = q.where(UserKnowledgeState.user_id == user_id)
    if subject_id is not None:
        if not await _subject_exists(db, subject_id):
            return {
                "summary": {
                    "weak_count": 0,
                    "normal_count": 0,
                    "good_count": 0,
                    "mastered_count": 0,
                    "unknown_count": 0,
                },
                "items": [],
            }
        q = q.where(UserKnowledgeState.subject_id == subject_id)

    # 排序
    if sort == "mastered_first":
        q = q.order_by(UserKnowledgeState.mastery_score.desc())
    elif sort == "confidence_low":
        q = q.order_by(UserKnowledgeState.confidence.asc())
    elif sort == "recent_practiced":
        q = q.order_by(UserKnowledgeState.last_practiced_at.desc().nullslast())
    else:  # weak_first
        q = q.order_by(UserKnowledgeState.mastery_score.asc())

    q = q.limit(limit)
    rows = (await db.execute(q)).all()

    summary = {
        "weak_count": 0,
        "normal_count": 0,
        "good_count": 0,
        "mastered_count": 0,
        "unknown_count": 0,
    }
    items = []
    for r in rows:
        status = _classify_mastery(r.confidence, r.mastery_score)
        summary[f"{status}_count"] = summary.get(f"{status}_count", 0) + 1
        items.append(
            {
                "knowledge_point_id": r.knowledge_point_id,
                "knowledge_point_name": r.kp_name,
                "mastery_score": round(r.mastery_score, 1),
                "confidence": round(r.confidence, 2),
                "answer_count": r.attempt_count,
                "correct_count": r.correct_count,
                "wrong_count": r.wrong_count,
                "recent_wrong_count": r.recent_wrong_count,
                "last_practiced_at": r.last_practiced_at,
                "status": status,
                "suggestion": _mastery_suggestion(status),
            }
        )

    return {"summary": summary, "items": items}


# ── 5. Wrong Questions ──────────────────────────────────────────────


async def get_wrong_questions_summary(
    db: AsyncSession,
    user_id: int,
    subject_id: int | None = None,
    limit: int = 20,
    min_wrong_count: int = 1,
) -> dict:
    # 总数
    count_q = select(func.count(UserQuestionState.id)).where(
        UserQuestionState.user_id == user_id,
        UserQuestionState.wrong_count >= min_wrong_count,
    )
    if subject_id is not None:
        count_q = count_q.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)
    wrong_total = (await db.execute(count_q)).scalar_one()

    repeated_q = select(func.count(UserQuestionState.id)).where(
        UserQuestionState.user_id == user_id,
        UserQuestionState.wrong_count >= 3,
        UserQuestionState.wrong_count >= min_wrong_count,
    )
    if subject_id is not None:
        repeated_q = repeated_q.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)
    repeated_count = (await db.execute(repeated_q)).scalar_one()

    # 明细（先查 UserQuestionState + Question，再批量加载知识点，避免 outerjoin 行膨胀）
    detail_q = select(
        UserQuestionState.question_id,
        UserQuestionState.wrong_count,
        UserQuestionState.correct_count,
        UserQuestionState.answer_count,
        UserQuestionState.last_answered_at,
        UserQuestionState.next_review_at,
        UserQuestionState.box_level,
        Question.content.label("q_content"),
    ).where(
        UserQuestionState.user_id == user_id,
        UserQuestionState.wrong_count >= min_wrong_count,
    )
    if subject_id is not None:
        detail_q = detail_q.join(
            Question, UserQuestionState.question_id == Question.id
        ).where(Question.subject_id == subject_id)
    else:
        detail_q = detail_q.join(Question, UserQuestionState.question_id == Question.id)

    detail_q = detail_q.order_by(
        UserQuestionState.wrong_count.desc(),
        UserQuestionState.box_level.asc(),
        UserQuestionState.last_answered_at.desc().nullslast(),
    ).limit(limit)

    rows = (await db.execute(detail_q)).all()
    q_ids = [r.question_id for r in rows]

    # 批量加载知识点（每题只取第一个 KP）
    kp_map: dict[int, tuple[int, str]] = {}
    if q_ids:
        kp_rows = (
            await db.execute(
                select(
                    QuestionKnowledgePoint.question_id,
                    QuestionKnowledgePoint.knowledge_point_id,
                    KnowledgePoint.name,
                )
                .join(
                    KnowledgePoint,
                    QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
                )
                .where(QuestionKnowledgePoint.question_id.in_(q_ids))
                .order_by(QuestionKnowledgePoint.question_id, QuestionKnowledgePoint.id)
            )
        ).all()
        for r in kp_rows:
            if r.question_id not in kp_map:
                kp_map[r.question_id] = (r.knowledge_point_id, r.name)

    items = []
    for r in rows:
        if r.wrong_count >= 3:
            status = "repeated_wrong"
        elif r.correct_count == 0:
            status = "not_mastered"
        else:
            status = "needs_review"

        kp = kp_map.get(r.question_id)
        items.append(
            {
                "question_id": r.question_id,
                "title": _extract_title(r.q_content),
                "knowledge_point_id": kp[0] if kp else None,
                "knowledge_point_name": kp[1] if kp else None,
                "wrong_count": r.wrong_count,
                "correct_count": r.correct_count,
                "answer_count": r.answer_count,
                "last_answered_at": r.last_answered_at,
                "next_review_at": r.next_review_at,
                "box_level": r.box_level,
                "status": status,
            }
        )

    return {
        "wrong_question_count": int(wrong_total),
        "repeated_wrong_question_count": int(repeated_count),
        "items": items,
    }


# ── 6. Study Trend ──────────────────────────────────────────────────


async def get_study_trend(
    db: AsyncSession, user_id: int, subject_id: int | None = None, days: int = 7
) -> dict:
    today = shanghai_today()
    since = shanghai_date_utc_range(today - timedelta(days=days - 1))[0]
    day_expr = await _china_date_expr(db, PracticeRecord.answered_at)

    q = select(
        day_expr.label("d"),
        func.count(PracticeRecord.id).label("total"),
        func.coalesce(
            func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)),  # noqa: E712
            0,  # noqa: E712
        ).label("correct"),
    ).where(
        PracticeRecord.user_id == user_id,
        PracticeRecord.answered_at >= since,
    )
    if subject_id is not None:
        q = q.where(PracticeRecord.subject_id == subject_id)

    q = q.group_by(day_expr).order_by(day_expr)
    rows = (await db.execute(q)).all()

    data: dict[str, dict] = {}
    for r in rows:
        raw = r.d
        try:
            d_str = raw[:10] if isinstance(raw, str) else raw.isoformat()
        except (AttributeError, TypeError):
            d_str = str(raw)[:10]
        data[d_str] = {"total": int(r.total), "correct": int(r.correct)}

    items = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        d_str = d.isoformat()
        entry = data.get(d_str, {"total": 0, "correct": 0})
        total = entry["total"]
        correct = entry["correct"]
        items.append(
            {
                "date": d_str,
                "answer_count": total,
                "correct_count": correct,
                "wrong_count": total - correct,
                "accuracy": _safe_accuracy(correct, total),
            }
        )

    return {"days": days, "items": items}
