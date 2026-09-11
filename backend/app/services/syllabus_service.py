from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import EXAM408_CORE_CODES, EXAM408_ROOT_CODE
from app.core.time_utils import utcnow
from app.models.admin import Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.syllabus import (
    SyllabusKnowledgePoint,
    SyllabusKnowledgePointMapping,
    SyllabusVersion,
)


class SyllabusError(ValueError):
    pass


_MANUAL_MAPPING_TYPES = frozenset({"merged", "split", "replaced"})


async def _get_version(
    db: AsyncSession,
    version_id: int,
    *,
    lock: bool = False,
) -> SyllabusVersion | None:
    stmt = select(SyllabusVersion).where(SyllabusVersion.id == version_id)
    bind = db.get_bind()
    if lock and bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(stmt)


async def _lock_syllabus_switch(db: AsyncSession, root_subject_id: int) -> None:
    """Serialize active-version switches on the stable 408 root row."""
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    await db.scalar(
        select(Subject.id).where(Subject.id == root_subject_id).with_for_update()
    )


async def _root_and_core_subjects(db: AsyncSession) -> tuple[Subject, list[Subject]]:
    rows = list(
        (
            await db.scalars(
                select(Subject).where(
                    Subject.code.in_((EXAM408_ROOT_CODE, *EXAM408_CORE_CODES))
                )
            )
        ).all()
    )
    by_code = {str(row.code): row for row in rows}
    root = by_code.get(EXAM408_ROOT_CODE)
    cores = [by_code.get(code) for code in EXAM408_CORE_CODES]
    if root is None or any(item is None for item in cores):
        raise SyllabusError("408 canonical 科目尚未准备完成")
    return root, [item for item in cores if item is not None]


async def get_active_version(db: AsyncSession) -> SyllabusVersion | None:
    return (
        await db.execute(
            select(SyllabusVersion)
            .where(SyllabusVersion.status == "active")
            .order_by(SyllabusVersion.effective_year.desc(), SyllabusVersion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def active_summary(version: SyllabusVersion | None) -> dict | None:
    if version is None:
        return None
    return {
        "id": int(version.id),
        "code": str(version.code),
        "name": str(version.name),
        "effective_year": int(version.effective_year),
    }


async def active_memberships(
    db: AsyncSession, subject_ids: list[int] | None = None
) -> tuple[SyllabusVersion | None, dict[int, SyllabusKnowledgePoint]]:
    version = await get_active_version(db)
    if version is None:
        return None, {}
    stmt = select(SyllabusKnowledgePoint).where(
        SyllabusKnowledgePoint.syllabus_version_id == version.id
    )
    if subject_ids:
        stmt = stmt.where(SyllabusKnowledgePoint.subject_id.in_(subject_ids))
    items = list((await db.scalars(stmt)).all())
    return version, {int(item.knowledge_point_id): item for item in items}


async def active_membership_ids_for_kps(
    db: AsyncSession, knowledge_point_ids: list[int]
) -> dict[int, int]:
    if not knowledge_point_ids:
        return {}
    version = await get_active_version(db)
    if version is None:
        return {}
    rows = await db.execute(
        select(
            SyllabusKnowledgePoint.knowledge_point_id, SyllabusKnowledgePoint.id
        ).where(
            SyllabusKnowledgePoint.syllabus_version_id == version.id,
            SyllabusKnowledgePoint.knowledge_point_id.in_(knowledge_point_ids),
        )
    )
    return {int(kp_id): int(member_id) for kp_id, member_id in rows.all()}


async def list_versions(db: AsyncSession) -> list[dict]:
    rows = await db.execute(
        select(SyllabusVersion, func.count(SyllabusKnowledgePoint.id))
        .outerjoin(
            SyllabusKnowledgePoint,
            SyllabusKnowledgePoint.syllabus_version_id == SyllabusVersion.id,
        )
        .group_by(SyllabusVersion.id)
        .order_by(SyllabusVersion.effective_year.desc(), SyllabusVersion.id.desc())
    )
    return [_version_payload(version, int(count or 0)) for version, count in rows.all()]


def _version_payload(version: SyllabusVersion, count: int) -> dict:
    return {
        "id": int(version.id),
        "code": version.code,
        "name": version.name,
        "effective_year": int(version.effective_year),
        "status": version.status,
        "description": version.description,
        "knowledge_point_count": int(count),
        "activated_at": version.activated_at,
        "created_at": version.created_at,
        "updated_at": version.updated_at,
    }


async def get_version_detail(db: AsyncSession, version_id: int) -> dict | None:
    version = await db.get(SyllabusVersion, version_id)
    if version is None:
        return None
    rows = await db.execute(
        select(SyllabusKnowledgePoint, Subject)
        .join(Subject, Subject.id == SyllabusKnowledgePoint.subject_id)
        .where(SyllabusKnowledgePoint.syllabus_version_id == version_id)
        .order_by(
            Subject.sort_order.asc(),
            SyllabusKnowledgePoint.sort_order.asc(),
            SyllabusKnowledgePoint.id.asc(),
        )
    )
    items = [
        {
            "id": int(item.id),
            "knowledge_point_id": int(item.knowledge_point_id),
            "subject_id": int(item.subject_id),
            "subject_code": subject.code,
            "subject_name": subject.name,
            "name": item.name_snapshot,
            "normalized_name": item.normalized_name_snapshot,
            "description": item.description_snapshot,
            "difficulty_level": int(item.difficulty_level_snapshot or 3),
            "sort_order": int(item.sort_order or 0),
        }
        for item, subject in rows.all()
    ]
    payload = _version_payload(version, len(items))
    payload["knowledge_points"] = items
    return payload


async def create_version(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    effective_year: int,
    description: str | None,
    admin_id: int | None,
) -> SyllabusVersion:
    root, _ = await _root_and_core_subjects(db)
    normalized_code = code.strip().lower()
    existing = await db.scalar(
        select(SyllabusVersion.id).where(
            func.lower(SyllabusVersion.code) == normalized_code
        )
    )
    if existing:
        raise SyllabusError("考纲版本 code 已存在")
    version = SyllabusVersion(
        code=normalized_code,
        name=name.strip(),
        effective_year=effective_year,
        description=(description or "").strip() or None,
        status="draft",
        root_subject_id=int(root.id),
        created_by=admin_id,
        updated_by=admin_id,
    )
    try:
        # The pre-check is user-friendly but cannot prevent a concurrent create.
        # A savepoint converts the database uniqueness race into the same 409 path
        # without poisoning the outer admin/audit transaction.
        async with db.begin_nested():
            db.add(version)
            await db.flush()
    except IntegrityError as exc:
        raise SyllabusError("考纲版本 code 已存在") from exc

    # New drafts start from the current active syllabus scope so an administrator
    # edits a delta instead of rebuilding all 408 memberships by hand.  The
    # snapshots are refreshed from the current canonical KnowledgePoint rows;
    # this is what lets a same-id name change become a traceable ``renamed``
    # mapping when the draft is activated.
    active = await get_active_version(db)
    if active is not None and int(active.id) != int(version.id):
        active_kp_ids = list(
            (
                await db.scalars(
                    select(SyllabusKnowledgePoint.knowledge_point_id)
                    .join(
                        KnowledgePoint,
                        KnowledgePoint.id == SyllabusKnowledgePoint.knowledge_point_id,
                    )
                    .where(
                        SyllabusKnowledgePoint.syllabus_version_id == active.id,
                        KnowledgePoint.is_active.is_(True),
                    )
                )
            ).all()
        )
        if active_kp_ids:
            await replace_memberships(
                db, int(version.id), [int(kp_id) for kp_id in active_kp_ids], admin_id
            )
    return version


async def update_version(
    db: AsyncSession, version_id: int, *, values: dict, admin_id: int | None
) -> SyllabusVersion:
    version = await _get_version(db, version_id, lock=True)
    if version is None:
        raise SyllabusError("考纲版本不存在")
    if version.status != "draft":
        raise SyllabusError("只有 draft 考纲可以编辑")
    for field in ("name", "effective_year"):
        if field in values and values[field] is not None:
            setattr(
                version,
                field,
                values[field].strip()
                if isinstance(values[field], str)
                else values[field],
            )
    if "description" in values:
        raw_description = values.get("description")
        version.description = (
            raw_description.strip()
            if isinstance(raw_description, str) and raw_description.strip()
            else None
        )
    version.updated_by = admin_id
    await db.flush()
    return version


async def replace_memberships(
    db: AsyncSession,
    version_id: int,
    knowledge_point_ids: list[int],
    admin_id: int | None,
) -> dict:
    version = await _get_version(db, version_id, lock=True)
    if version is None:
        raise SyllabusError("考纲版本不存在")
    if version.status != "draft":
        raise SyllabusError("只有 draft 考纲可以修改知识点范围")
    _, cores = await _root_and_core_subjects(db)
    core_ids = {int(s.id) for s in cores}
    unique_ids = list(dict.fromkeys(int(x) for x in knowledge_point_ids))
    points = (
        list(
            (
                await db.scalars(
                    select(KnowledgePoint).where(
                        KnowledgePoint.id.in_(unique_ids) if unique_ids else False,
                        KnowledgePoint.subject_id.in_(core_ids),
                        KnowledgePoint.is_active.is_(True),
                    )
                )
            ).all()
        )
        if unique_ids
        else []
    )
    if len(points) != len(unique_ids):
        found = {int(p.id) for p in points}
        missing = [x for x in unique_ids if x not in found]
        raise SyllabusError(f"包含无效或非 408 active 知识点: {missing[:10]}")

    await db.execute(
        delete(SyllabusKnowledgePointMapping).where(
            (
                SyllabusKnowledgePointMapping.from_syllabus_knowledge_point_id.in_(
                    select(SyllabusKnowledgePoint.id).where(
                        SyllabusKnowledgePoint.syllabus_version_id == version_id
                    )
                )
            )
            | (
                SyllabusKnowledgePointMapping.to_syllabus_knowledge_point_id.in_(
                    select(SyllabusKnowledgePoint.id).where(
                        SyllabusKnowledgePoint.syllabus_version_id == version_id
                    )
                )
            )
        )
    )
    await db.execute(
        delete(SyllabusKnowledgePoint).where(
            SyllabusKnowledgePoint.syllabus_version_id == version_id
        )
    )
    order_by_subject: dict[int, int] = defaultdict(int)
    for point in sorted(
        points, key=lambda p: (int(p.subject_id), str(p.name), int(p.id))
    ):
        order_by_subject[int(point.subject_id)] += 10
        db.add(
            SyllabusKnowledgePoint(
                syllabus_version_id=version_id,
                knowledge_point_id=int(point.id),
                subject_id=int(point.subject_id),
                name_snapshot=str(point.name),
                normalized_name_snapshot=str(point.normalized_name),
                description_snapshot=point.description,
                difficulty_level_snapshot=int(point.difficulty_level or 3),
                sort_order=order_by_subject[int(point.subject_id)],
            )
        )
    version.updated_by = admin_id
    await db.flush()
    return await get_version_detail(db, version_id)


async def get_catalog(db: AsyncSession, version_id: int) -> dict:
    version = await db.get(SyllabusVersion, version_id)
    if version is None:
        raise SyllabusError("考纲版本不存在")
    _, cores = await _root_and_core_subjects(db)
    core_ids = [int(s.id) for s in cores]
    included_ids = {
        int(value)
        for value in (
            await db.scalars(
                select(SyllabusKnowledgePoint.knowledge_point_id).where(
                    SyllabusKnowledgePoint.syllabus_version_id == version_id
                )
            )
        ).all()
    }
    rows = await db.execute(
        select(KnowledgePoint, Subject)
        .join(Subject, Subject.id == KnowledgePoint.subject_id)
        .where(
            KnowledgePoint.subject_id.in_(core_ids), KnowledgePoint.is_active.is_(True)
        )
        .order_by(
            Subject.sort_order.asc(), KnowledgePoint.name.asc(), KnowledgePoint.id.asc()
        )
    )
    return {
        "syllabus_version_id": version_id,
        "items": [
            {
                "knowledge_point_id": int(kp.id),
                "subject_id": int(kp.subject_id),
                "subject_code": subject.code,
                "subject_name": subject.name,
                "name": kp.name,
                "description": kp.description,
                "difficulty_level": int(kp.difficulty_level or 3),
                "included": int(kp.id) in included_ids,
            }
            for kp, subject in rows.all()
        ],
    }


async def _auto_map_from_previous(
    db: AsyncSession, previous_id: int | None, target_id: int, admin_id: int | None
) -> None:
    target = list(
        (
            await db.scalars(
                select(SyllabusKnowledgePoint).where(
                    SyllabusKnowledgePoint.syllabus_version_id == target_id
                )
            )
        ).all()
    )
    if previous_id is None:
        db.add_all(
            [
                SyllabusKnowledgePointMapping(
                    to_syllabus_knowledge_point_id=int(item.id),
                    relation_type="added",
                    created_by=admin_id,
                )
                for item in target
            ]
        )
        return

    prev = list(
        (
            await db.scalars(
                select(SyllabusKnowledgePoint).where(
                    SyllabusKnowledgePoint.syllabus_version_id == previous_id
                )
            )
        ).all()
    )
    prev_ids = {int(item.id) for item in prev}
    target_ids = {int(item.id) for item in target}

    # Manual merge/split/replaced mappings override auto-added/removed inference
    # for the endpoints they explicitly govern.  Otherwise one semantic change
    # could be reported as both "merged" and "added", which is contradictory.
    manual_rows = (
        list(
            (
                await db.scalars(
                    select(SyllabusKnowledgePointMapping).where(
                        SyllabusKnowledgePointMapping.relation_type.in_(
                            _MANUAL_MAPPING_TYPES
                        ),
                        (
                            SyllabusKnowledgePointMapping.from_syllabus_knowledge_point_id.in_(
                                prev_ids
                            )
                            | SyllabusKnowledgePointMapping.to_syllabus_knowledge_point_id.in_(
                                target_ids
                            )
                        ),
                    )
                )
            ).all()
        )
        if prev_ids or target_ids
        else []
    )
    manual_from_ids = {
        int(row.from_syllabus_knowledge_point_id)
        for row in manual_rows
        if row.from_syllabus_knowledge_point_id is not None
    }
    manual_to_ids = {
        int(row.to_syllabus_knowledge_point_id)
        for row in manual_rows
        if row.to_syllabus_knowledge_point_id is not None
    }

    prev_by_kp = {int(x.knowledge_point_id): x for x in prev}
    target_by_kp = {int(x.knowledge_point_id): x for x in target}
    for kp_id in sorted(prev_by_kp.keys() | target_by_kp.keys()):
        old = prev_by_kp.get(kp_id)
        new = target_by_kp.get(kp_id)
        if old and new:
            if int(old.id) in manual_from_ids or int(new.id) in manual_to_ids:
                continue
            relation = (
                "unchanged" if old.name_snapshot == new.name_snapshot else "renamed"
            )
            db.add(
                SyllabusKnowledgePointMapping(
                    from_syllabus_knowledge_point_id=int(old.id),
                    to_syllabus_knowledge_point_id=int(new.id),
                    relation_type=relation,
                    created_by=admin_id,
                )
            )
        elif old:
            if int(old.id) in manual_from_ids:
                continue
            db.add(
                SyllabusKnowledgePointMapping(
                    from_syllabus_knowledge_point_id=int(old.id),
                    relation_type="removed",
                    created_by=admin_id,
                )
            )
        elif new:
            if int(new.id) in manual_to_ids:
                continue
            db.add(
                SyllabusKnowledgePointMapping(
                    to_syllabus_knowledge_point_id=int(new.id),
                    relation_type="added",
                    created_by=admin_id,
                )
            )


async def activate_version(
    db: AsyncSession, version_id: int, admin_id: int | None
) -> SyllabusVersion:
    version = await _get_version(db, version_id, lock=True)
    if version is None:
        raise SyllabusError("考纲版本不存在")
    if version.status != "draft":
        raise SyllabusError("只有 draft 考纲可以激活")
    # Per-version locking prevents edit-vs-activate races. Locking the stable 408
    # root additionally serializes two administrators activating different drafts.
    await _lock_syllabus_switch(db, int(version.root_subject_id))
    count = int(
        await db.scalar(
            select(func.count())
            .select_from(SyllabusKnowledgePoint)
            .where(SyllabusKnowledgePoint.syllabus_version_id == version_id)
        )
        or 0
    )
    if count <= 0:
        raise SyllabusError("考纲至少需要包含一个知识点")
    current = await get_active_version(db)
    previous_id = int(current.id) if current and int(current.id) != version_id else None
    if current and int(current.id) != version_id:
        current.status = "archived"
        current.updated_by = admin_id
        # The DB enforces a single active syllabus. Flush the archive first so
        # SQLite/PostgreSQL never observe two active rows during this switch.
        await db.flush()
    # Rebuild only auto mappings involving the target. Manual merged/split rows
    # are preserved and can coexist with the inferred direct mapping rows.
    target_ids = select(SyllabusKnowledgePoint.id).where(
        SyllabusKnowledgePoint.syllabus_version_id == version_id
    )
    await db.execute(
        delete(SyllabusKnowledgePointMapping).where(
            SyllabusKnowledgePointMapping.relation_type.in_(
                ("unchanged", "renamed", "added", "removed")
            ),
            SyllabusKnowledgePointMapping.to_syllabus_knowledge_point_id.in_(
                target_ids
            ),
        )
    )
    await _auto_map_from_previous(db, previous_id, version_id, admin_id)
    version.status = "active"
    version.activated_at = utcnow()
    version.updated_by = admin_id
    await db.flush()
    return version


async def archive_version(
    db: AsyncSession, version_id: int, admin_id: int | None
) -> SyllabusVersion:
    version = await _get_version(db, version_id, lock=True)
    if version is None:
        raise SyllabusError("考纲版本不存在")
    if version.status == "active":
        raise SyllabusError("当前 active 考纲不能直接归档，请先激活替代版本")
    version.status = "archived"
    version.updated_by = admin_id
    await db.flush()
    return version


async def add_mapping(
    db: AsyncSession,
    *,
    from_id: int | None,
    to_id: int | None,
    relation_type: str,
    note: str | None,
    admin_id: int | None,
) -> SyllabusKnowledgePointMapping:
    if relation_type not in _MANUAL_MAPPING_TYPES:
        raise SyllabusError("手工映射仅允许 merged / split / replaced")
    if from_id is None or to_id is None:
        raise SyllabusError("手工映射必须同时选择旧版与新版知识点")
    if int(from_id) == int(to_id):
        raise SyllabusError("新旧映射端点不能是同一版本成员")

    rows = list(
        (
            await db.scalars(
                select(SyllabusKnowledgePoint).where(
                    SyllabusKnowledgePoint.id.in_((from_id, to_id))
                )
            )
        ).all()
    )
    by_id = {int(item.id): item for item in rows}
    old = by_id.get(int(from_id))
    new = by_id.get(int(to_id))
    if old is None or new is None:
        raise SyllabusError("映射端点不存在")
    if int(old.syllabus_version_id) == int(new.syllabus_version_id):
        raise SyllabusError("跨版本映射不能连接同一考纲版本")
    target_version = await _get_version(db, int(new.syllabus_version_id), lock=True)
    if target_version is None or target_version.status != "draft":
        raise SyllabusError("手工映射只能写入 draft 目标考纲")
    # Membership replacement uses the same version lock. Re-read endpoints after
    # acquiring it so a concurrent replacement cannot leave us inserting FKs to
    # members that were deleted while this request was waiting.
    rows = list(
        (
            await db.scalars(
                select(SyllabusKnowledgePoint).where(
                    SyllabusKnowledgePoint.id.in_((from_id, to_id))
                )
            )
        ).all()
    )
    by_id = {int(item.id): item for item in rows}
    old = by_id.get(int(from_id))
    new = by_id.get(int(to_id))
    if (
        old is None
        or new is None
        or int(new.syllabus_version_id) != int(target_version.id)
    ):
        raise SyllabusError("映射端点已变化，请刷新后重试")

    duplicate = await db.scalar(
        select(SyllabusKnowledgePointMapping.id).where(
            SyllabusKnowledgePointMapping.from_syllabus_knowledge_point_id == from_id,
            SyllabusKnowledgePointMapping.to_syllabus_knowledge_point_id == to_id,
            SyllabusKnowledgePointMapping.relation_type == relation_type,
        )
    )
    if duplicate is not None:
        raise SyllabusError("相同跨版本映射已存在")

    item = SyllabusKnowledgePointMapping(
        from_syllabus_knowledge_point_id=from_id,
        to_syllabus_knowledge_point_id=to_id,
        relation_type=relation_type,
        note=(note or "").strip() or None,
        created_by=admin_id,
    )
    db.add(item)
    await db.flush()
    return item


async def delete_mapping(
    db: AsyncSession, mapping_id: int
) -> SyllabusKnowledgePointMapping:
    item = await db.get(SyllabusKnowledgePointMapping, mapping_id)
    if item is None:
        raise SyllabusError("跨版本映射不存在")
    if item.relation_type not in _MANUAL_MAPPING_TYPES:
        raise SyllabusError("自动映射不能手工删除")
    if item.to_syllabus_knowledge_point_id is None:
        raise SyllabusError("映射目标缺失")
    target_member = await db.get(
        SyllabusKnowledgePoint, int(item.to_syllabus_knowledge_point_id)
    )
    if target_member is None:
        raise SyllabusError("映射目标缺失")
    target_version = await _get_version(
        db, int(target_member.syllabus_version_id), lock=True
    )
    if target_version is None or target_version.status != "draft":
        raise SyllabusError("仅 draft 目标考纲的手工映射可删除")
    # The mapping may have been cascade-deleted by a membership replacement while
    # this request waited for the version lock. Re-read it before deleting.
    item = await db.get(
        SyllabusKnowledgePointMapping, mapping_id, populate_existing=True
    )
    if item is None:
        raise SyllabusError("跨版本映射不存在")
    await db.delete(item)
    await db.flush()
    return item


async def list_mappings(db: AsyncSession, version_id: int) -> list[dict]:
    member_ids = {
        int(value)
        for value in (
            await db.scalars(
                select(SyllabusKnowledgePoint.id).where(
                    SyllabusKnowledgePoint.syllabus_version_id == version_id
                )
            )
        ).all()
    }
    if not member_ids:
        return []
    rows = list(
        (
            await db.scalars(
                select(SyllabusKnowledgePointMapping)
                .where(
                    (
                        SyllabusKnowledgePointMapping.from_syllabus_knowledge_point_id.in_(
                            member_ids
                        )
                    )
                    | (
                        SyllabusKnowledgePointMapping.to_syllabus_knowledge_point_id.in_(
                            member_ids
                        )
                    )
                )
                .order_by(SyllabusKnowledgePointMapping.id.asc())
            )
        ).all()
    )
    endpoint_ids = {
        int(value)
        for row in rows
        for value in (
            row.from_syllabus_knowledge_point_id,
            row.to_syllabus_knowledge_point_id,
        )
        if value is not None
    }
    endpoint_members = (
        {
            int(item.id): item
            for item in (
                await db.scalars(
                    select(SyllabusKnowledgePoint).where(
                        SyllabusKnowledgePoint.id.in_(endpoint_ids)
                    )
                )
            ).all()
        }
        if endpoint_ids
        else {}
    )
    return [
        {
            "id": int(row.id),
            "from_syllabus_knowledge_point_id": int(
                row.from_syllabus_knowledge_point_id
            )
            if row.from_syllabus_knowledge_point_id
            else None,
            "to_syllabus_knowledge_point_id": int(row.to_syllabus_knowledge_point_id)
            if row.to_syllabus_knowledge_point_id
            else None,
            "relation_type": row.relation_type,
            "note": row.note,
            "from_name": endpoint_members.get(
                int(row.from_syllabus_knowledge_point_id)
            ).name_snapshot
            if row.from_syllabus_knowledge_point_id
            and int(row.from_syllabus_knowledge_point_id) in endpoint_members
            else None,
            "to_name": endpoint_members.get(
                int(row.to_syllabus_knowledge_point_id)
            ).name_snapshot
            if row.to_syllabus_knowledge_point_id
            and int(row.to_syllabus_knowledge_point_id) in endpoint_members
            else None,
            "created_at": row.created_at,
        }
        for row in rows
    ]


async def get_coverage(db: AsyncSession, version_id: int) -> dict:
    version = await db.get(SyllabusVersion, version_id)
    if version is None:
        raise SyllabusError("考纲版本不存在")
    rows = await db.execute(
        select(SyllabusKnowledgePoint, Subject)
        .join(Subject, Subject.id == SyllabusKnowledgePoint.subject_id)
        .where(SyllabusKnowledgePoint.syllabus_version_id == version_id)
        .order_by(Subject.sort_order.asc(), SyllabusKnowledgePoint.sort_order.asc())
    )
    members = rows.all()
    kp_ids = [int(item.knowledge_point_id) for item, _ in members]
    counts: dict[int, int] = {}
    if kp_ids:
        crows = await db.execute(
            select(
                QuestionKnowledgePoint.knowledge_point_id,
                func.count(func.distinct(Question.id)),
            )
            .join(Question, Question.id == QuestionKnowledgePoint.question_id)
            .where(
                QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids),
                Question.is_active.is_(True),
                Question.review_status == "approved",
            )
            .group_by(QuestionKnowledgePoint.knowledge_point_id)
        )
        counts = {int(k): int(c) for k, c in crows.all()}
    items = [
        {
            "syllabus_knowledge_point_id": int(item.id),
            "knowledge_point_id": int(item.knowledge_point_id),
            "subject_id": int(item.subject_id),
            "subject_code": subject.code,
            "subject_name": subject.name,
            "name": item.name_snapshot,
            "question_count": counts.get(int(item.knowledge_point_id), 0),
            "covered": counts.get(int(item.knowledge_point_id), 0) > 0,
        }
        for item, subject in members
    ]
    covered = sum(1 for item in items if item["covered"])
    return {
        "syllabus_version_id": version_id,
        "syllabus_code": version.code,
        "total_knowledge_points": len(items),
        "covered_knowledge_points": covered,
        "coverage_ratio": round(covered / len(items), 4) if items else 0.0,
        "items": items,
    }
