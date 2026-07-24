"""题目发布服务：将审核通过的题目从 question_imports 发布到 questions 正式题库。"""

from __future__ import annotations

import difflib
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.features.question_pipeline import (
    _find_duplicate_by_hash,
    process_question_pipeline,
)
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.schemas.question_publish import (
    ApproveAndPublishResponse,
    PublishDetailItem,
    PublishResponse,
)

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 100


async def _migrate_old_approved(db: AsyncSession) -> int:
    """将旧版 approve 流程中仅改状态但未写入 questions 表的记录补发布。"""
    migrate_columns = [
        QuestionImport.id,
        QuestionImport.status,
        QuestionImport.question_id,
        QuestionImport.batch_id,
        QuestionImport.source_type,
        QuestionImport.source_file,
        QuestionImport.subject_id,
        QuestionImport.question_type,
        QuestionImport.raw_data,
        QuestionImport.parsed_content,
        QuestionImport.parsed_options,
        QuestionImport.parsed_answer,
        QuestionImport.parsed_analysis,
        QuestionImport.ai_metadata,
    ]

    # 1. 已有 question_id 的，只更新状态标记
    result = await db.execute(
        select(QuestionImport)
        .options(load_only(*migrate_columns))
        .where(
            QuestionImport.status == "approved",
            QuestionImport.question_id.isnot(None),
        )
    )
    records = list(result.scalars().all())
    for r in records:
        r.status = "published"
    migrated_status = len(records)

    # 2. question_id 为空的旧 approved 记录，补写入 questions 表
    result2 = await db.execute(
        select(QuestionImport)
        .options(load_only(*migrate_columns))
        .where(
            QuestionImport.status == "approved",
            QuestionImport.question_id.is_(None),
        )
    )
    orphans = list(result2.scalars().all())
    published_orphans = 0
    for qi in orphans:
        item = await publish_single_question(db, qi)
        if item["status"] == "published":
            published_orphans += 1
        elif item["status"] == "duplicate":
            qi.status = "published"
            qi.question_id = item["question_id"]

    if migrated_status or published_orphans:
        logger.info(
            "Migrated old approved records: status_only=%d, orphans_published=%d",
            migrated_status, published_orphans,
        )
    return migrated_status + published_orphans


async def _find_duplicate_by_stem_similarity(
    db: AsyncSession,
    subject_id: int | None,
    stem: str,
) -> Question | None:
    """Hash 未命中时的回退方案：按题干文本相似度检测重复。"""
    if not subject_id or not stem:
        return None
    stem_clean = re.sub(r"\s+", "", stem.strip())
    if not stem_clean:
        return None
    result = await db.execute(
        select(Question).where(
            Question.subject_id == subject_id,
            Question.is_active == True,
        )
    )
    for q in result.scalars().all():
        q_stem = (q.content or {}).get("text", "")
        q_stem_clean = re.sub(r"\s+", "", q_stem.strip())
        if not q_stem_clean:
            continue
        ratio = difflib.SequenceMatcher(None, stem_clean, q_stem_clean).ratio()
        if ratio >= 0.92:
            logger.info(
                "[StemSimilarity] question %s (subject_id=%s) matches import (ratio=%.4f)",
                q.id, subject_id, ratio,
            )
            return q
    return None


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

    # Resolve subject from subject_id if available
    if qi.subject_id and qi.subject_ref:
        subject_code = qi.subject_ref.code
    elif qi.subject_id:
        # subject_ref not loaded, look up
        from app.models.admin import Subject
        subj = await db.get(Subject, qi.subject_id)
        if subj:
            subject_code = subj.code
    else:
        subject_code = None

    result = process_question_pipeline(
        {
            "subject": subject_code,
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

    duplicate = await _find_duplicate_by_hash(
        db, result["normalized"]["subject"], result["normalized"]["question_hash"],
        subject_id=qi.subject_id,
    )
    if duplicate:
        logger.info(
            "[DuplicateCheck] questionId=%s importId=%s hash=%s result=matched_question matchedId=%s",
            duplicate.id,
            qi.id,
            result["normalized"]["question_hash"],
            duplicate.id,
        )
        return {
            "id": qi.id,
            "status": "duplicate",
            "question_id": duplicate.id,
            "reason": "question_hash collision",
        }

    # Stem-similarity fallback: 应对归一化规则变更导致 hash 不匹配的场景
    stem = (result.get("normalized") or {}).get("stem", "")
    if stem:
        similar = await _find_duplicate_by_stem_similarity(
            db, qi.subject_id, stem,
        )
        if similar:
            logger.info(
                "[StemFallback] questionId=%s importId=%s result=matched_by_stem matchedId=%s",
                similar.id, qi.id, similar.id,
            )
            return {
                "id": qi.id,
                "status": "duplicate",
                "question_id": similar.id,
                "reason": "stem_similarity_fallback",
            }

    q_fields = dict(result["question_fields"])
    # Ensure subject_id comes from the import record (authoritative source)
    q_fields["subject_id"] = qi.subject_id
    # P1-5: 保留 segments/render_mode 等结构化内容
    qi_content = qi.parsed_content or {}
    if isinstance(qi_content, dict) and qi_content.get("render_mode") == "segments":
        q_fields["content"] = {
            **(q_fields.get("content") or {}),
            "render_mode": "segments",
            "segments": qi_content.get("segments"),
        }

    from app.utils.question_content import extract_image_urls_from_content
    image_urls = extract_image_urls_from_content(qi_content)
    if image_urls:
        q_fields["image_url"] = image_urls

    # Preserve source snapshot metadata for admin audit/review
    if isinstance(qi_content, dict):
        for key in ("source_snapshot_url", "source_snapshot_full_page"):
            if key in qi_content:
                content = dict(q_fields.get("content") or {})
                content[key] = qi_content[key]
                q_fields["content"] = content

    q = Question(
        **q_fields,
        source=qi.source_file,
        source_type=qi.source_type,
        source_file=qi.source_file,
        import_batch_id=qi.batch_id,
        raw_content=str(qi.raw_data),
        review_status="approved",
        is_active=True,
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
            # Resolve subject from subject_id if available
            if qi.subject_id and qi.subject_ref:
                subject_code = qi.subject_ref.code
            elif qi.subject_id:
                from app.models.admin import Subject
                subj = await db.get(Subject, qi.subject_id)
                if subj:
                    subject_code = subj.code
            else:
                subject_code = None
            validate_result = process_question_pipeline(
                {
                    "subject": subject_code,
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


async def get_publish_history(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> PublishHistoryResponse:
    """查询发布历史：按 batch_id 聚合 question_imports 中已发布的记录。"""
    from app.schemas.question_publish import PublishHistoryItem, PublishHistoryResponse

    published_statuses = ("published", "duplicate", "failed")

    # 1. Count distinct batches with published items
    count_result = await db.execute(
        select(func.count(func.distinct(QuestionImport.batch_id))).where(
            QuestionImport.status.in_(published_statuses)
        )
    )
    total = int(count_result.scalar() or 0)

    if total == 0:
        return PublishHistoryResponse(total=0, page=page, page_size=page_size, items=[])

    # 2. Get batch-level info (paginated)
    batch_query = (
        select(
            QuestionImport.batch_id,
            func.max(QuestionImport.updated_at).label("published_at"),
            func.count().label("total"),
        )
        .where(QuestionImport.status.in_(published_statuses))
        .group_by(QuestionImport.batch_id)
        .order_by(func.max(QuestionImport.updated_at).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    batch_result = await db.execute(batch_query)
    batch_rows = batch_result.all()

    # 3. Get per-batch status stats
    batch_ids = [row.batch_id for row in batch_rows]
    if batch_ids:
        stats_query = (
            select(
                QuestionImport.batch_id,
                QuestionImport.status,
                func.count().label("cnt"),
            )
            .where(
                QuestionImport.batch_id.in_(batch_ids),
                QuestionImport.status.in_(published_statuses),
            )
            .group_by(QuestionImport.batch_id, QuestionImport.status)
        )
        stats_result = await db.execute(stats_query)
        stats_rows = stats_result.all()
    else:
        stats_rows = []

    # 4. Aggregate stats per batch
    stats_map: dict = {}
    for row in stats_rows:
        bid = row[0]
        status = row[1]
        cnt = row[2]
        if bid not in stats_map:
            stats_map[bid] = {"published": 0, "duplicate": 0, "failed": 0}
        stats_map[bid][status] = int(cnt)

    items = []
    for row in batch_rows:
        bid = row.batch_id
        s = stats_map.get(bid, {})
        items.append(PublishHistoryItem(
            batch_id=bid,
            published_at=row.published_at,
            total=int(row.total),
            published=s.get("published", 0),
            duplicates=s.get("duplicate", 0),
            failed=s.get("failed", 0),
        ))

    return PublishHistoryResponse(total=total, page=page, page_size=page_size, items=items)
