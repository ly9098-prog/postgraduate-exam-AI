"""题目发布服务：将审核通过的题目从 question_imports 发布到 questions 正式题库。"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.question_pipeline import (
    _get_qi,
    find_duplicate_question,
    process_question_pipeline,
)
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.schemas.question_publish import (
    ApproveAndPublishResponse,
    PublishDetailItem,
    PublishHistoryItem,
    PublishHistoryResponse,
    PublishResponse,
)

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 100


async def _migrate_old_approved(db: AsyncSession) -> int:
    """将旧版 approve 流程中已创建 Question 的记录补齐为 published 状态。"""
    result = await db.execute(
        select(QuestionImport).where(
            QuestionImport.status == "approved",
            QuestionImport.question_id.isnot(None),
        )
    )
    records = list(result.scalars().all())
    for r in records:
        r.status = "published"
    if records:
        logger.info("Migrated %d old approved records to published", len(records))
    return len(records)


async def publish_single_question(db: AsyncSession, qi: QuestionImport) -> dict:
    """发布单条记录到 questions 表。不提交事务。"""
    if qi.status == "published":
        return {
            "id": qi.id,
            "status": "failed",
            "question_id": qi.question_id,
            "reason": "已发布",
        }
    if qi.status != "approved":
        return {
            "id": qi.id,
            "status": "failed",
            "question_id": None,
            "reason": f"状态为 {qi.status}，非 approved",
        }

    ai_meta = qi.ai_metadata or {}
    kps = ai_meta.get("knowledge_points") if isinstance(ai_meta, dict) else None
    diff = ai_meta.get("difficulty") if isinstance(ai_meta, dict) else None

    result = process_question_pipeline(
        {
            "subject": qi.subject,
            "question_type": qi.question_type,
            "parsed_content": qi.parsed_content,
            "parsed_options": qi.parsed_options,
            "parsed_answer": qi.parsed_answer,
            "parsed_analysis": qi.parsed_analysis,
            "knowledge_points": kps,
            "difficulty": diff,
        },
        "manual",
        {"file": qi.source_file or "", "page": 0},
    )

    if not result["is_valid"]:
        return {
            "id": qi.id,
            "status": "failed",
            "question_id": None,
            "reason": f"数据不完整：{'; '.join(result['errors'])}",
        }

    duplicate = await find_duplicate_question(
        db, result["normalized"]["subject"], result["normalized"]["stem"]
    )
    if duplicate:
        logger.info(
            "Publish duplicate: import_id=%s stem_hash=%s existing_question_id=%s",
            qi.id,
            result["stem_hash"],
            duplicate.id,
        )
        return {
            "id": qi.id,
            "status": "duplicate",
            "question_id": duplicate.id,
            "reason": "stem_hash collision",
        }

    q = Question(
        **result["question_fields"],
        source=qi.source_file,
        source_type=qi.source_type,
        source_file=qi.source_file,
        import_batch_id=qi.batch_id,
        raw_content=str(qi.raw_data),
        review_status="approved",
    )
    db.add(q)
    await db.flush()
    await db.refresh(q)

    qi.status = "published"
    qi.question_id = q.id

    return {"id": qi.id, "status": "published", "question_id": q.id}


async def publish_questions(
    db: AsyncSession,
    question_ids: list[int] | None = None,
    batch_id: str | None = None,
) -> PublishResponse:
    """批量发布审核通过的题目到正式题库。"""
    await _migrate_old_approved(db)

    if question_ids:
        stmt = select(QuestionImport).where(
            QuestionImport.id.in_(question_ids),
            QuestionImport.status == "approved",
        )
    elif batch_id:
        stmt = select(QuestionImport).where(
            QuestionImport.batch_id == batch_id,
            QuestionImport.status == "approved",
        )
    else:
        stmt = select(QuestionImport).where(
            QuestionImport.status == "approved",
        )

    stmt = stmt.limit(MAX_BATCH_SIZE)
    result = await db.execute(stmt)
    records = list(result.scalars().all())

    details: list[dict] = []
    stats = {"published": 0, "duplicate": 0, "failed": 0}

    for qi in records:
        item = await publish_single_question(db, qi)
        details.append(item)
        if item["status"] in stats:
            stats[item["status"]] += 1

    await db.commit()

    return PublishResponse(
        total=len(records),
        published=stats["published"],
        duplicates=stats["duplicate"],
        failed=stats["failed"],
        details=[PublishDetailItem(**d) for d in details],
    )


async def get_publish_history(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> PublishHistoryResponse:
    """查询发布历史（按 batch_id 聚合）。"""
    conditions = [QuestionImport.status == "published"]
    if status:
        conditions.append(QuestionImport.status == status)

    count_stmt = select(func.count(func.distinct(QuestionImport.batch_id))).where(
        *conditions
    )
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    batch_stmt = (
        select(
            QuestionImport.batch_id,
            func.max(QuestionImport.updated_at).label("published_at"),
            func.count(QuestionImport.id).label("total"),
        )
        .where(*conditions)
        .group_by(QuestionImport.batch_id)
        .order_by(func.max(QuestionImport.updated_at).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    batch_result = await db.execute(batch_stmt)
    batch_rows = batch_result.all()

    items: list[PublishHistoryItem] = []
    for row in batch_rows:
        stats_stmt = select(
            QuestionImport.status,
            func.count(QuestionImport.id),
        ).where(
            QuestionImport.batch_id == row.batch_id,
            QuestionImport.status.in_(["published", "duplicate"]),
        ).group_by(QuestionImport.status)
        stats_result = await db.execute(stats_stmt)
        stats_map = {r[0]: r[1] for r in stats_result.all()}

        items.append(
            PublishHistoryItem(
                batch_id=row.batch_id,
                published_at=row.published_at,
                total=row.total,
                published=stats_map.get("published", 0),
                duplicates=stats_map.get("duplicate", 0),
                failed=0,
            )
        )

    return PublishHistoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


async def approve_and_publish(
    db: AsyncSession,
    question_ids: list[int],
) -> ApproveAndPublishResponse:
    """快捷操作：审核通过并发布，一步完成。"""
    await _migrate_old_approved(db)

    if not question_ids:
        return ApproveAndPublishResponse(
            total=0, approved=0, published=0, duplicates=0, failed=0, details=[]
        )

    stmt = select(QuestionImport).where(QuestionImport.id.in_(question_ids))
    result = await db.execute(stmt)
    records = list(result.scalars().all())

    approved_count = 0
    details: list[dict] = []
    stats = {"published": 0, "duplicate": 0, "failed": 0}

    for qi in records:
        if qi.status == "published":
            details.append(
                {"id": qi.id, "status": "failed", "question_id": qi.question_id, "reason": "已发布"}
            )
            stats["failed"] += 1
            continue
        if qi.status == "rejected":
            details.append(
                {"id": qi.id, "status": "failed", "question_id": None, "reason": "已拒绝"}
            )
            stats["failed"] += 1
            continue

        if qi.status == "pending":
            ai_meta = qi.ai_metadata or {}
            kps = ai_meta.get("knowledge_points") if isinstance(ai_meta, dict) else None
            diff = ai_meta.get("difficulty") if isinstance(ai_meta, dict) else None
            validate_result = process_question_pipeline(
                {
                    "subject": qi.subject,
                    "question_type": qi.question_type,
                    "parsed_content": qi.parsed_content,
                    "parsed_options": qi.parsed_options,
                    "parsed_answer": qi.parsed_answer,
                    "parsed_analysis": qi.parsed_analysis,
                    "knowledge_points": kps,
                    "difficulty": diff,
                },
                "manual",
                {"file": qi.source_file or "", "page": 0},
            )
            if not validate_result["is_valid"]:
                details.append(
                    {
                        "id": qi.id,
                        "status": "failed",
                        "question_id": None,
                        "reason": f"数据不完整：{'; '.join(validate_result['errors'])}",
                    }
                )
                stats["failed"] += 1
                continue

            qi.status = "approved"
            qi.question_id = None
            approved_count += 1

        item = await publish_single_question(db, qi)
        details.append(item)
        if item["status"] in stats:
            stats[item["status"]] += 1

    await db.commit()

    return ApproveAndPublishResponse(
        total=len(records),
        approved=approved_count,
        published=stats["published"],
        duplicates=stats["duplicate"],
        failed=stats["failed"],
        details=[PublishDetailItem(**d) for d in details],
    )
