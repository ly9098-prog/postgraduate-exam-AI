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

from app.core.time_utils import normalize_to_naive_utc, serialize_utc_datetime
from app.models.question import Question
from app.models.tag import Tag

logger = logging.getLogger("postgraduate-ai.sync")

MAX_QUESTIONS_PER_SYNC = 5000
MAX_TAGS_PER_SYNC = 1000

_QUESTION_FIELDS = (
    "subject_id",
    "question_type",
    "content",
    "options",
    "answer",
    "question_hash",
    "analysis",
    "difficulty",
    "source",
    "source_type",
    "source_file",
    "import_batch_id",
    "raw_content",
    "image_url",
    "year",
)

# 审核生命周期字段：仅持有 question:review 的调用方可通过同步变更。
_LIFECYCLE_FIELDS = ("review_status", "is_active")

_TAG_FIELDS = ("name", "subject_id", "parent_id", "sort_order")


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
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return normalize_to_naive_utc(dt)


def _build_tag(data: dict) -> Tag:
    tag = Tag()
    tag.sync_uuid = data["sync_uuid"]
    for f in _TAG_FIELDS:
        if f in data:
            setattr(tag, f, data[f])
    if data.get("created_at"):
        tag.created_at = _parse_datetime(data["created_at"])
    return tag


def _build_question(
    data: dict, *, allow_lifecycle: bool = False
) -> tuple[Question, list | None]:
    q = Question()
    q.sync_uuid = data["sync_uuid"]
    q.sync_version = data.get("sync_version", 0)
    kp_names = data.get("knowledge_points")
    for f in _QUESTION_FIELDS:
        if f in data:
            setattr(q, f, data[f])
    if allow_lifecycle:
        for f in _LIFECYCLE_FIELDS:
            if f in data:
                setattr(q, f, data[f])
    else:
        q.review_status = "re_pending"
        q.is_active = False
    if data.get("updated_at"):
        q.updated_at = _parse_datetime(data["updated_at"])
    if data.get("created_at"):
        q.created_at = _parse_datetime(data["created_at"])
    return q, kp_names


def _apply_lifecycle(existing: Question, data: dict) -> None:
    """Apply review_status/is_active under the admin review transition rules."""
    from app.services.admin_question_service import _REVIEW_ALLOWED_TRANSITIONS

    target = data.get("review_status")
    current = str(existing.review_status or "")
    if (
        target is not None
        and target != current
        and target in _REVIEW_ALLOWED_TRANSITIONS.get(current, ())
    ):
        existing.review_status = target
    if "is_active" in data:
        wanted = bool(data["is_active"])
        if not wanted or existing.review_status == "approved":
            existing.is_active = wanted


def _update_question(
    existing: Question, data: dict, *, allow_lifecycle: bool = False
) -> list | None:
    kp_names = data.get("knowledge_points")
    for f in _QUESTION_FIELDS:
        if f in data:
            setattr(existing, f, data[f])
    if allow_lifecycle:
        _apply_lifecycle(existing, data)
    existing.sync_version = data.get("sync_version", existing.sync_version)
    if data.get("updated_at"):
        existing.updated_at = _parse_datetime(data["updated_at"])
    return kp_names


async def merge_sync_package(
    db: AsyncSession, package: dict, *, allow_lifecycle: bool = False
) -> SyncReport:
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
            batch = q_uuids[i : i + 500]
            result = await db.execute(
                select(Question).where(Question.sync_uuid.in_(batch))
            )
            for q in result.scalars().all():
                existing_questions[q.sync_uuid] = q

    # Build (subject_id, question_hash) → sync_uuid index from ALL active questions
    # whose hash matches any incoming question, to catch content duplicates
    # that have different sync_uuids (e.g. re-imported locally).
    hash_index: dict[tuple[int, str], str] = {}
    incoming_hashes = [
        (q.get("subject_id"), q.get("question_hash"))
        for q in questions_data
        if q.get("subject_id") and q.get("question_hash")
    ]
    if incoming_hashes:
        all_hashes = list({h for _, h in incoming_hashes})
        for i in range(0, len(all_hashes), 500):
            batch = all_hashes[i : i + 500]
            result = await db.execute(
                select(
                    Question.subject_id, Question.question_hash, Question.sync_uuid
                ).where(
                    Question.question_hash.in_(batch),
                    Question.is_active == True,  # noqa: E712
                )
            )
            for subject_id, qhash, suuid in result.all():
                if subject_id and qhash and suuid:
                    hash_index[(subject_id, qhash)] = suuid

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
    pending_syncs: list[tuple[Question, list]] = []
    revision_questions: list[Question] = []
    for q_data in questions_data:
        sync_uuid = q_data.get("sync_uuid")
        if not sync_uuid:
            report.errors.append("question missing sync_uuid, skipped")
            continue

        existing = existing_questions.get(sync_uuid)

        if existing is None:
            subject_id = q_data.get("subject_id")
            q_hash = q_data.get("question_hash")
            if subject_id and q_hash and (subject_id, q_hash) in hash_index:
                existing_suuid = hash_index[(subject_id, q_hash)]
                if existing_suuid != sync_uuid:
                    report.questions_deduped += 1
                    continue
            q, kp_names = _build_question(q_data, allow_lifecycle=allow_lifecycle)
            db.add(q)
            revision_questions.append(q)
            report.questions_new += 1
            if kp_names is not None:
                pending_syncs.append((q, kp_names))
        else:
            local_updated = _parse_datetime(q_data.get("updated_at"))
            cloud_updated = (
                normalize_to_naive_utc(existing.updated_at)
                if existing.updated_at is not None
                else None
            )

            if local_updated and cloud_updated and local_updated > cloud_updated:
                prev_subject_id = existing.subject_id
                kp_names = _update_question(
                    existing, q_data, allow_lifecycle=allow_lifecycle
                )
                revision_questions.append(existing)
                if kp_names is not None:
                    pending_syncs.append((existing, kp_names))
                elif "subject_id" in q_data and q_data["subject_id"] != prev_subject_id:
                    # 仅改科目、未携带知识点：用当前展示名在新科目下重建映射，
                    # 否则关联表会残留指向旧科目 KP 的行（违反 subject 不变量）。
                    from app.services.knowledge_point_service import load_question_kps

                    old_kp_map = await load_question_kps(db, [existing.id])
                    old_kps = old_kp_map.get(existing.id, [])
                    if old_kps:
                        pending_syncs.append((existing, old_kps))
                report.questions_updated += 1
            elif local_updated and cloud_updated and local_updated < cloud_updated:
                report.questions_conflict += 1
                report.conflicts.append(
                    {
                        "sync_uuid": sync_uuid,
                        "reason": "cloud_newer",
                        "cloud_updated_at": serialize_utc_datetime(existing.updated_at),
                        "local_updated_at": q_data.get("updated_at"),
                    }
                )
            else:
                report.questions_skipped += 1

    try:
        await db.flush()

        # flush 成功后同步知识点关联（replace 语义，subject 取更新后值）。
        # 与上面的 flush 共用守卫：KP 同步异常同样回滚整个 package 并记入 report，
        # 避免静默丢失半同步状态。
        if pending_syncs:
            from app.services.knowledge_point_service import (
                sync_question_knowledge_points,
            )

            for q, kp_names in pending_syncs:
                await sync_question_knowledge_points(
                    db, q, kp_names, source="sync", replace=True
                )
            await db.flush()

        if revision_questions:
            from app.services.question_revision_service import ensure_question_revision

            seen: set[int] = set()
            for question in revision_questions:
                if question.id in seen:
                    continue
                seen.add(int(question.id))
                await ensure_question_revision(
                    db, question, change_source="sync", edit_reason="sync merge"
                )
    except IntegrityError as e:
        await db.rollback()
        report.errors.append(f"数据库约束冲突（可能重复 sync_uuid）: {e}")
        return report

    return report
