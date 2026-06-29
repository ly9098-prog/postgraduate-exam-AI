"""本地→云端增量同步：合并服务。

职责：接收序列化的 sync package（questions + tags），按 sync_uuid 匹配
云端记录，执行 INSERT / UPDATE / SKIP，永不 DELETE。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.models.tag import Tag

logger = logging.getLogger("postgraduate-ai.sync")

MAX_QUESTIONS_PER_SYNC = 5000
MAX_TAGS_PER_SYNC = 1000

_QUESTION_FIELDS = (
    "subject", "question_type", "content", "options", "answer",
    "question_hash", "analysis", "knowledge_points", "difficulty",
    "source", "source_type", "source_file", "import_batch_id",
    "raw_content", "image_url", "year", "review_status", "is_active",
)

_TAG_FIELDS = ("name", "subject", "parent_id", "sort_order")


@dataclass
class SyncReport:
    questions_new: int = 0
    questions_updated: int = 0
    questions_skipped: int = 0
    questions_conflict: int = 0
    questions_deduped: int = 0
    tags_new: int = 0
    tags_skipped: int = 0
    conflicts: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1]
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _build_tag(data: dict) -> Tag:
    tag = Tag()
    tag.sync_uuid = data["sync_uuid"]
    for f in _TAG_FIELDS:
        if f in data:
            setattr(tag, f, data[f])
    if data.get("created_at"):
        tag.created_at = _parse_datetime(data["created_at"])
    return tag


def _build_question(data: dict) -> Question:
    q = Question()
    q.sync_uuid = data["sync_uuid"]
    q.sync_version = data.get("sync_version", 0)
    for f in _QUESTION_FIELDS:
        if f in data:
            setattr(q, f, data[f])
    if data.get("updated_at"):
        q.updated_at = _parse_datetime(data["updated_at"])
    if data.get("created_at"):
        q.created_at = _parse_datetime(data["created_at"])
    return q


def _update_question(existing: Question, data: dict) -> None:
    for f in _QUESTION_FIELDS:
        if f in data:
            setattr(existing, f, data[f])
    existing.sync_version = data.get("sync_version", existing.sync_version)
    if data.get("updated_at"):
        existing.updated_at = _parse_datetime(data["updated_at"])


async def merge_sync_package(db: AsyncSession, package: dict) -> SyncReport:
    report = SyncReport()

    tags_data = package.get("tags", [])
    questions_data = package.get("questions", [])

    # --- 预加载已有 sync_uuid 映射，避免 N+1 查询 ---
    tag_uuids = [t["sync_uuid"] for t in tags_data if t.get("sync_uuid")]
    q_uuids = [q["sync_uuid"] for q in questions_data if q.get("sync_uuid")]

    existing_tags: dict[str, Tag] = {}
    if tag_uuids:
        result = await db.execute(select(Tag).where(Tag.sync_uuid.in_(tag_uuids)))
        existing_tags = {t.sync_uuid: t for t in result.scalars().all()}

    existing_questions: dict[str, Question] = {}
    if q_uuids:
        for i in range(0, len(q_uuids), 500):
            batch = q_uuids[i:i + 500]
            result = await db.execute(select(Question).where(Question.sync_uuid.in_(batch)))
            for q in result.scalars().all():
                existing_questions[q.sync_uuid] = q

    # Build (subject, question_hash) → sync_uuid index from ALL active questions
    # whose hash matches any incoming question, to catch content duplicates
    # that have different sync_uuids (e.g. re-imported locally).
    hash_index: dict[tuple[str, str], str] = {}
    incoming_hashes = [
        (q.get("subject"), q.get("question_hash"))
        for q in questions_data
        if q.get("subject") and q.get("question_hash")
    ]
    if incoming_hashes:
        all_hashes = list({h for _, h in incoming_hashes})
        for i in range(0, len(all_hashes), 500):
            batch = all_hashes[i:i + 500]
            result = await db.execute(
                select(Question.subject_id, Question.question_hash, Question.sync_uuid).where(
                    Question.question_hash.in_(batch),
                    Question.is_active == True,  # noqa: E712
                )
            )
            for subject, qhash, suuid in result.all():
                if subject and qhash and suuid:
                    hash_index[(subject, qhash)] = suuid

    # --- Tags (先于 questions，保证引用关系) ---
    for tag_data in tags_data:
        sync_uuid = tag_data.get("sync_uuid")
        if not sync_uuid:
            report.errors.append("tag missing sync_uuid, skipped")
            continue
        if sync_uuid not in existing_tags:
            db.add(_build_tag(tag_data))
            report.tags_new += 1
        else:
            report.tags_skipped += 1

    # --- Questions ---
    for q_data in questions_data:
        sync_uuid = q_data.get("sync_uuid")
        if not sync_uuid:
            report.errors.append("question missing sync_uuid, skipped")
            continue

        existing = existing_questions.get(sync_uuid)

        if existing is None:
            subject = q_data.get("subject")
            q_hash = q_data.get("question_hash")
            if subject and q_hash and (subject, q_hash) in hash_index:
                existing_suuid = hash_index[(subject, q_hash)]
                if existing_suuid != sync_uuid:
                    report.questions_deduped += 1
                    continue
            db.add(_build_question(q_data))
            report.questions_new += 1
        else:
            local_updated = _parse_datetime(q_data.get("updated_at"))
            cloud_updated = existing.updated_at
            if cloud_updated and cloud_updated.tzinfo is not None:
                cloud_updated = cloud_updated.replace(tzinfo=None)

            if local_updated and cloud_updated and local_updated > cloud_updated:
                _update_question(existing, q_data)
                report.questions_updated += 1
            elif local_updated and cloud_updated and local_updated < cloud_updated:
                report.questions_conflict += 1
                report.conflicts.append({
                    "sync_uuid": sync_uuid,
                    "reason": "cloud_newer",
                    "cloud_updated_at": existing.updated_at.isoformat(),
                    "local_updated_at": q_data.get("updated_at"),
                })
            else:
                report.questions_skipped += 1

    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        report.errors.append(f"数据库约束冲突（可能重复 sync_uuid）: {e}")

    return report
