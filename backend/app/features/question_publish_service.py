"""题目发布服务：将审核通过的题目从 question_imports 发布到 questions 正式题库。"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.time_utils import unix_timestamp
from app.features.question_pipeline import process_question_pipeline
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.schemas.question_publish import (
    ApproveAndPublishResponse,
    PublishDetailItem,
    PublishResponse,
)
from app.utils.question_content import (
    extract_image_urls_from_content,
    reconcile_student_stem_fields,
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
        QuestionImport.source_question_no,
        QuestionImport.source_question_label,
        QuestionImport.created_at,
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
        .order_by(QuestionImport.id.asc())
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


_SOURCE_QUESTION_PREFIX_RE = re.compile(
    r"^\s*(?:第\s*)?(?:\d{1,4}(?:\s*[-－—]\s*\d+)?|[一二三四五六七八九十百]+)"
    r"\s*(?:题)?\s*[.．、,，:：;；)）]\s*"
)


def _strip_source_question_prefix(
    text: Any,
    source_question_label: str | None = None,
    source_question_no: str | None = None,
) -> str:
    """清除题干开头的原题号，只处理开头，避免误伤正文中的编号。"""
    value = str(text or "").lstrip()
    if not value:
        return ""

    label_text = str(source_question_label or "").strip()
    if label_text:
        cleaned = re.sub(rf"^\s*{re.escape(label_text)}\s*", "", value, count=1)
        if cleaned != value:
            return cleaned.lstrip()

    number_text = str(source_question_no or "").strip()
    if number_text:
        cleaned = re.sub(
            rf"^\s*{re.escape(number_text)}\s*[.．、,，:：;；)）]\s*",
            "",
            value,
            count=1,
        )
        if cleaned != value:
            return cleaned.lstrip()

    return _SOURCE_QUESTION_PREFIX_RE.sub("", value, count=1).lstrip()


def _clean_import_content(qi: QuestionImport) -> dict:
    """构造发布专用 content 副本，并同步清洗 text/stem/首个文本 segment。"""
    content = deepcopy(qi.parsed_content) if isinstance(qi.parsed_content, dict) else {}
    label = qi.source_question_label
    number = qi.source_question_no

    source_stem = content.get("text") or content.get("stem") or ""
    cleaned_stem = _strip_source_question_prefix(source_stem, label, number)
    if source_stem:
        content["text"] = cleaned_stem
        if "stem" in content:
            content["stem"] = cleaned_stem

    segments = content.get("segments")
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            for key in ("text", "markdown"):
                if isinstance(segment.get(key), str) and segment[key].strip():
                    segment[key] = _strip_source_question_prefix(segment[key], label, number)
                    return content
    return content


def _normalize_dedupe_text(value: Any) -> str:
    text = _strip_source_question_prefix(value)
    text = text.replace("\xa0", " ").replace("　", " ")
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text)
    return re.sub(r"\s+", "", text).casefold()


def _normalize_dedupe_options(options: Any) -> tuple[tuple[str, str], ...]:
    if not options:
        return ()
    items: list[tuple[str, str]] = []
    if isinstance(options, dict):
        iterator = options.items()
    elif isinstance(options, list):
        iterator = []
        for index, item in enumerate(options):
            if isinstance(item, dict):
                key = item.get("key") or item.get("label") or item.get("option") or index
                value = item.get("text") or item.get("value") or item.get("content") or ""
            else:
                key, value = index, item
            iterator.append((key, value))
    else:
        return (("", _normalize_dedupe_text(options)),)

    for key, value in iterator:
        if isinstance(value, dict):
            value = value.get("text") or value.get("value") or value.get("content") or ""
        normalized = _normalize_dedupe_text(value)
        if normalized:
            items.append((str(key).strip().upper(), normalized))
    return tuple(sorted(items))


async def _find_duplicate_questions(
    db: AsyncSession,
    subject_id: int | None,
    stem: str,
    options: Any,
) -> list[Question]:
    """按题干、题干+选项查找重复题；答案不参与判重。"""
    if subject_id is None:
        return []
    target_stem = _normalize_dedupe_text(stem)
    if not target_stem:
        return []
    target_options = _normalize_dedupe_options(options)

    result = await db.execute(
        select(Question).where(
            Question.subject_id == subject_id,
            Question.is_active.is_(True),
        )
    )
    matches: list[Question] = []
    for question in result.scalars().all():
        content = question.content if isinstance(question.content, dict) else {}
        existing_stem = _normalize_dedupe_text(content.get("text") or content.get("stem"))
        if existing_stem != target_stem:
            continue

        # 指纹不含答案。仅题干相同不够判重：408 类题库存在大量同题干不同选项的题
        # （如“以下说法中，错误的是()”），题干单指纹会把它们误合并导致丢题。
        # 必须题干 + 选项都一致才判为重复。
        existing_options = _normalize_dedupe_options(question.options)
        stem_options_duplicate = (existing_stem, existing_options) == (
            target_stem,
            target_options,
        )
        if stem_options_duplicate:
            matches.append(question)
    return matches


async def _duplicate_import_ranks(
    db: AsyncSession, question_ids: list[int]
) -> dict[int, tuple[datetime | None, int | None]]:
    if not question_ids:
        return {}
    result = await db.execute(
        select(
            QuestionImport.question_id,
            func.max(QuestionImport.created_at),
            func.max(QuestionImport.id),
        )
        .where(QuestionImport.question_id.in_(question_ids))
        .group_by(QuestionImport.question_id)
    )
    return {
        int(question_id): (created_at, int(import_id) if import_id is not None else None)
        for question_id, created_at, import_id in result.all()
        if question_id is not None
    }


def _datetime_rank(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    return unix_timestamp(value)


async def _retain_latest_duplicate(
    db: AsyncSession,
    qi: QuestionImport,
    duplicates: list[Question],
    q_fields: dict,
    kp_names,
) -> tuple[Question, bool]:
    """合并重复题。返回（保留的 Question，当前导入是否为最新）。"""
    ranks = await _duplicate_import_ranks(db, [question.id for question in duplicates])

    def question_rank(question: Question) -> tuple[int, int, float]:
        linked_created_at, linked_import_id = ranks.get(question.id, (None, None))
        if linked_import_id is not None:
            return 1, linked_import_id, _datetime_rank(linked_created_at)
        return 0, question.id, _datetime_rank(question.created_at)

    retained = max(duplicates, key=question_rank)
    retained_created_at, retained_import_id = ranks.get(retained.id, (None, None))
    if retained_import_id is not None:
        current_is_latest = qi.id >= retained_import_id
    else:
        current_is_latest = _datetime_rank(qi.created_at) >= _datetime_rank(
            retained_created_at or retained.created_at
        )

    obsolete_ids = [question.id for question in duplicates if question.id != retained.id]
    if obsolete_ids:
        from app.services.question_revision_service import ensure_question_revision

        for question in duplicates:
            if question.id in obsolete_ids:
                question.is_active = False
                await ensure_question_revision(
                    db, question, change_source="import_dedupe", edit_reason="duplicate superseded"
                )
        await db.execute(
            update(QuestionImport)
            .where(QuestionImport.question_id.in_(obsolete_ids))
            .values(question_id=retained.id)
        )

    if current_is_latest:
        # knowledge_points 已由调用方 pop 出 q_fields；这里同步关联表（subject 取更新后值）
        for field, value in q_fields.items():
            setattr(retained, field, value)
        retained.source = qi.source_file
        retained.source_type = qi.source_type
        retained.source_file = qi.source_file
        retained.import_batch_id = qi.batch_id
        retained.raw_content = str(qi.raw_data)
        retained.review_status = "approved"
        retained.is_active = True
        retained.sync_version = (retained.sync_version or 0) + 1
        # 只同步非空提取结果：pipeline 恒输出 knowledge_points 键，空数组表示
        # 「本次提取无知识点」而非「用户显式清空」——此时保留既有映射，避免
        # 用空数据覆盖保留题已有的优质知识点。
        if kp_names:
            from app.services.knowledge_point_service import (
                sync_question_knowledge_points,
            )

            await sync_question_knowledge_points(
                db, retained, kp_names, source="imported", replace=True
            )
        from app.services.question_revision_service import ensure_question_revision

        await ensure_question_revision(
            db, retained, change_source="import_dedupe", edit_reason="retained duplicate updated"
        )

    qi.status = "published"
    qi.question_id = retained.id
    return retained, current_is_latest


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
    subject_code = None
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

    cleaned_content = _clean_import_content(qi)
    result = process_question_pipeline(
        {
            "subject": subject_code,
            "question_type": qi.question_type,
            "parsed_content": cleaned_content,
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

    q_fields = dict(result["question_fields"])
    # Ensure subject_id comes from the import record (authoritative source)
    q_fields["subject_id"] = qi.subject_id
    # P1-5: 保留 segments/render_mode 等结构化内容
    qi_content = cleaned_content
    if isinstance(qi_content, dict) and qi_content.get("render_mode") == "segments":
        q_fields["content"] = {
            **(q_fields.get("content") or {}),
            "render_mode": "segments",
            "segments": qi_content.get("segments"),
        }
    if isinstance(q_fields.get("content"), dict):
        q_fields["content"] = reconcile_student_stem_fields(q_fields["content"])

    image_urls = extract_image_urls_from_content(qi_content)

    # Preserve source snapshot metadata for admin audit/review
    if isinstance(qi_content, dict):
        for key in ("source_snapshot_url", "source_snapshot_full_page"):
            if key in qi_content:
                content = dict(q_fields.get("content") or {})
                content[key] = qi_content[key]
                q_fields["content"] = content

    # 图片字段也以本次（后导入）记录为准；无图片时清空旧值。
    q_fields["image_url"] = image_urls or None

    # knowledge_points 不再进入 Question ORM 列，转写关联表。
    kp_names = q_fields.pop("knowledge_points", None)

    stem = (result.get("normalized") or {}).get("stem", "")
    duplicates = await _find_duplicate_questions(
        db,
        qi.subject_id,
        stem,
        q_fields.get("options"),
    )
    if duplicates:
        retained, current_is_latest = await _retain_latest_duplicate(
            db, qi, duplicates, q_fields, kp_names
        )
        if current_is_latest:
            logger.info(
                "[DuplicateReplace] importId=%s retainedQuestionId=%s replacedByLaterImport=true",
                qi.id, retained.id,
            )
            return {
                "id": qi.id,
                "status": "published",
                "question_id": retained.id,
                "reason": "replaced_older_duplicate",
            }
        logger.info(
            "[DuplicateKeepLatest] importId=%s retainedQuestionId=%s newerImportAlreadyPublished=true",
            qi.id, retained.id,
        )
        return {
            "id": qi.id,
            "status": "duplicate",
            "question_id": retained.id,
            "reason": "newer_import_already_retained",
        }

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
    if kp_names is not None:
        from app.services.knowledge_point_service import (
            sync_question_knowledge_points,
        )

        await sync_question_knowledge_points(db, q, kp_names, source="imported")
    from app.services.question_revision_service import ensure_question_revision

    await ensure_question_revision(db, q, change_source="import_publish", edit_reason="initial publish")
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

    stmt = stmt.order_by(QuestionImport.id.asc()).limit(MAX_BATCH_SIZE)
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

    stmt = (
        select(QuestionImport)
        .where(QuestionImport.id.in_(question_ids))
        .order_by(QuestionImport.id.asc())
    )
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
            subject_code = None
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
                    "parsed_content": _clean_import_content(qi),
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
) -> PublishHistoryResponse:  # noqa: F821
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
