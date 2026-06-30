"""知识点服务 — 规范化管理知识点 + 题目映射。"""
import logging
import re
import unicodedata

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.services.admin_subject_service import resolve_subject_ids

logger = logging.getLogger(__name__)

# ── 全角→半角映射 ──────────────────────────────────────────────

_FULLWIDTH_MAP = {
    "（": "(", "）": ")", "【": "[", "】": "]",
    "｛": "{", "｝": "}", "，": ",", "。": ".",
    "；": ";", "：": ":", "！": "!", "？": "?",
    "＋": "+", "－": "-", "＊": "*", "／": "/",
    "＝": "=", "＜": "<", "＞": ">",
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
}


def normalize_knowledge_name(name: str) -> str:
    """规范化知识点名称：去空格、合并多空格、英文小写、全角→半角。"""
    if not name:
        return ""
    # 全角→半角（ASCII 部分）
    s = "".join(_FULLWIDTH_MAP.get(ch, ch) for ch in name)
    # Unicode NFKC 归一化（全角字母 → 半角）
    s = unicodedata.normalize("NFKC", s)
    # 去首尾空格
    s = s.strip()
    # 多空格合并
    s = re.sub(r"\s+", " ", s)
    # 英文转小写，中文保持原样
    s = s.lower()
    return s


async def get_or_create_knowledge_point(
    db: AsyncSession,
    subject: str,
    name: str,
) -> KnowledgePoint:
    """按 subject + normalized_name 查找或创建知识点。"""
    normalized = normalize_knowledge_name(name)
    if not normalized:
        raise ValueError("知识点名称不能为空")

    result = await db.execute(
        select(KnowledgePoint).where(
            KnowledgePoint.subject == subject,
            KnowledgePoint.normalized_name == normalized,
        )
    )
    kp = result.scalar_one_or_none()
    if kp:
        return kp

    kp = KnowledgePoint(
        subject=subject,
        name=name.strip(),
        normalized_name=normalized,
    )
    db.add(kp)
    await db.flush()
    return kp


async def sync_question_knowledge_points(
    db: AsyncSession,
    question: Question,
    source: str = "imported",
) -> dict:
    """从 question.knowledge_points JSON 同步到 question_knowledge_points 表。

    返回: {"created": int, "skipped": int, "total": int}
    """
    kps_raw = question.knowledge_points
    if not kps_raw or not isinstance(kps_raw, list):
        return {"created": 0, "skipped": 0, "total": 0}

    # 过滤空值
    kp_names = [str(kp).strip() for kp in kps_raw if kp]
    if not kp_names:
        return {"created": 0, "skipped": 0, "total": 0}

    created = 0
    skipped = 0

    for kp_name in kp_names:
        try:
            kp = await get_or_create_knowledge_point(db, question.subject_ref.code if question.subject_ref else None, kp_name)
        except ValueError:
            skipped += 1
            continue

        # 检查是否已有映射
        existing = await db.execute(
            select(QuestionKnowledgePoint).where(
                QuestionKnowledgePoint.question_id == question.id,
                QuestionKnowledgePoint.knowledge_point_id == kp.id,
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        mapping = QuestionKnowledgePoint(
            question_id=question.id,
            knowledge_point_id=kp.id,
            role="main",
            weight=1.0,
            source=source,
        )
        db.add(mapping)
        created += 1

    await db.flush()
    return {"created": created, "skipped": skipped, "total": len(kp_names)}


async def backfill_question_knowledge_points(
    db: AsyncSession,
    subject: str | None = None,
    limit: int = 500,
) -> dict:
    """批量同步题目知识点到映射表。

    subject 支持精确匹配或前缀匹配（如 exam408 → exam408、exam408-ds）。
    """
    conditions = [Question.is_active == True]
    if subject:
        ids = await resolve_subject_ids(db, subject)
        conditions.append(Question.subject_id.in_(ids))

    result = await db.execute(
        select(Question)
        .where(and_(*conditions))
        .limit(limit)
    )
    questions = list(result.scalars().all())

    total_created = 0
    total_skipped = 0
    total_questions = 0
    errors = []

    for q in questions:
        total_questions += 1
        try:
            stats = await sync_question_knowledge_points(db, q, source="backfill")
            total_created += stats["created"]
            total_skipped += stats["skipped"]
        except Exception as exc:
            errors.append({"question_id": q.id, "error": str(exc)})
            logger.warning("backfill KP failed for qid=%d: %s", q.id, exc)

    await db.flush()

    return {
        "total_questions": total_questions,
        "created": total_created,
        "skipped": total_skipped,
        "errors": errors[:20],
    }


async def get_knowledge_status(db: AsyncSession) -> dict:
    """返回知识点映射状态统计。"""
    total_kp = (await db.execute(select(func.count(KnowledgePoint.id)))).scalar() or 0
    total_mappings = (
        await db.execute(select(func.count(QuestionKnowledgePoint.id)))
    ).scalar() or 0

    # 有映射的不同题目数
    mapped_qids = (
        await db.execute(
            select(func.count(func.distinct(QuestionKnowledgePoint.question_id)))
        )
    ).scalar() or 0

    # 总活跃题目数
    total_questions = (
        await db.execute(
            select(func.count(Question.id)).where(Question.is_active == True)
        )
    ).scalar() or 0

    return {
        "total_knowledge_points": total_kp,
        "total_question_mappings": total_mappings,
        "mapped_questions": mapped_qids,
        "unmapped_questions": max(0, total_questions - mapped_qids),
    }
