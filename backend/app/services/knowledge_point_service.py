"""知识点服务 — 规范化管理知识点 + 题目映射（关联表为唯一事实源）。"""

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.tag import Tag

from app.services.knowledge_point_resolution import (
    build_resolution_indexes as _build_resolution_indexes,
    normalize_knowledge_name,
    normalize_kp_input,
    resolve_from_indexes as _resolve_from_indexes,
)


logger = logging.getLogger(__name__)


async def _load_subject_knowledge_points(
    db: AsyncSession, subject_id: int
) -> list[KnowledgePoint]:
    result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.subject_id == subject_id)
    )
    return list(result.scalars().all())


async def _create_canonical_knowledge_point(
    db: AsyncSession,
    subject_id: int,
    display: str,
    normalized: str,
) -> KnowledgePoint:
    """Create a new canonical point with savepoint-based uniqueness protection."""
    for _attempt in range(3):
        new_kp = KnowledgePoint(
            subject_id=subject_id,
            name=display,
            normalized_name=normalized,
            aliases=[],
            is_active=True,
        )
        try:
            async with db.begin_nested():
                db.add(new_kp)
                await db.flush()
            return new_kp
        except IntegrityError:
            # A concurrent writer may have created either the canonical name or
            # an alias target. Re-resolve the entire subject rather than merely
            # re-selecting normalized_name so alias governance still applies.
            points = await _load_subject_knowledge_points(db, subject_id)
            active_names, active_aliases, inactive_terms = _build_resolution_indexes(
                points
            )
            resolved = _resolve_from_indexes(
                normalized,
                active_names,
                active_aliases,
                inactive_terms,
                block_inactive=True,
            )
            if resolved is not None:
                return resolved
    raise RuntimeError(
        f"并发创建知识点失败：subject_id={subject_id}, normalized={normalized}"
    )


async def resolve_knowledge_points(
    db: AsyncSession,
    subject_id: int,
    names,
    *,
    create_if_missing: bool = False,
) -> list[KnowledgePoint]:
    """Resolve user/AI/import names to active canonical KnowledgePoint rows.

    Resolution order for each input is deterministic:
    1. active canonical ``normalized_name`` exact match;
    2. active canonical ``aliases`` exact match after normalization;
    3. if the term belongs only to inactive data, writes are blocked;
    4. only when ``create_if_missing=True`` may a genuinely new canonical row be created.

    Multiple input spellings resolving to the same canonical point are collapsed
    while preserving first occurrence.  This prevents e.g. ``Catalan数`` and
    ``卡特兰数`` from creating duplicate question mappings in one import payload.
    """
    entries = normalize_kp_input(names)
    if not entries:
        return []
    if not subject_id:
        raise ValueError("subject_id 不能为空")

    points = await _load_subject_knowledge_points(db, int(subject_id))
    active_names, active_aliases, inactive_terms = _build_resolution_indexes(points)

    resolved_points: list[KnowledgePoint] = []
    seen_ids: set[int] = set()
    for display, normalized in entries:
        point = _resolve_from_indexes(
            normalized,
            active_names,
            active_aliases,
            inactive_terms,
            block_inactive=create_if_missing,
        )
        if point is None and create_if_missing:
            point = await _create_canonical_knowledge_point(
                db, int(subject_id), display, normalized
            )
            # Make the just-created point visible to later entries in this same
            # payload without another catalog query.
            active_names[normalized] = point
        if point is None:
            continue

        point_id = int(point.id)
        if point_id in seen_ids:
            continue
        seen_ids.add(point_id)
        resolved_points.append(point)

    return resolved_points


async def resolve_knowledge_point(
    db: AsyncSession,
    subject_id: int,
    name: str,
    *,
    create_if_missing: bool = False,
) -> KnowledgePoint | None:
    """Resolve one name/alias to its active canonical knowledge point."""
    points = await resolve_knowledge_points(
        db, subject_id, [name], create_if_missing=create_if_missing
    )
    return points[0] if points else None


async def get_or_create_knowledge_point(
    db: AsyncSession,
    subject_id: int,
    name: str,
) -> KnowledgePoint:
    """Compatibility wrapper: resolve aliases first, create only if truly new."""
    point = await resolve_knowledge_point(db, subject_id, name, create_if_missing=True)
    if point is None:  # Defensive; create_if_missing=True should always resolve.
        raise RuntimeError(f"知识点解析失败：subject_id={subject_id}, name={name!r}")
    return point


async def _load_mappings(
    db: AsyncSession, question_id: int
) -> list[QuestionKnowledgePoint]:
    result = await db.execute(
        select(QuestionKnowledgePoint).where(
            QuestionKnowledgePoint.question_id == question_id
        )
    )
    return list(result.scalars().all())


async def sync_question_knowledge_points(
    db: AsyncSession,
    question: Question,
    kp_names,
    *,
    source: str = "imported",
    replace: bool = False,
) -> dict:
    """把题目的知识点同步进 question_knowledge_points 关联表（唯一事实源）。

    语义（固定）：
    - ``kp_names is None``：字段未提供，不改动旧映射（no-op）。
    - ``kp_names == []`` 且 ``replace=True``：用户明确清空，删除全部映射。
    - 非空数组 + ``replace=True``：最终映射与新数组完全一致（顺序按 position）。
    - 非空数组 + ``replace=False``：additive/idempotent（用于回填等）。

    subject 不变量：get/create 一律使用 ``question.subject_id``；调用方在修改
    subject 后调用本函数，旧科目映射会在 replace 时被删除。

    返回: {"changed", "created", "updated", "deleted", "total"}
    """
    if kp_names is None:
        return {"changed": False, "created": 0, "updated": 0, "deleted": 0, "total": 0}

    # KP links are part of the immutable revision state. Serialize mutations on
    # the parent Question row so concurrent scalar/KP edits cannot produce a
    # revision assembled from two different transaction states.
    from app.services.question_revision_service import lock_question_for_revision

    question = await lock_question_for_revision(db, int(question.id))
    entries = normalize_kp_input(kp_names)
    subject_id = question.subject_id
    existing = await _load_mappings(db, question.id)
    existing_by_kp = {m.knowledge_point_id: m for m in existing}

    if not subject_id:
        # 无有效科目：无法 get/create；仅 replace 且要求清空时删除全部。
        if replace and existing:
            for m in existing:
                await db.delete(m)
            await db.flush()
            return {
                "changed": True,
                "created": 0,
                "updated": 0,
                "deleted": len(existing),
                "total": 0,
            }
        logger.warning(
            "sync_question_knowledge_points: qid=%d has no subject, skip", question.id
        )
        return {"changed": False, "created": 0, "updated": 0, "deleted": 0, "total": 0}

    resolved_points = await resolve_knowledge_points(
        db, subject_id, [display for display, _norm in entries], create_if_missing=True
    )
    # Position belongs to canonical distinct points, not raw aliases.  If one
    # payload contains both “Catalan数” and “卡特兰数”, they become one mapping.
    kp_entries: list[tuple[int, int]] = [
        (int(kp.id), position) for position, kp in enumerate(resolved_points)
    ]

    target_kp_ids = {kp_id for kp_id, _position in kp_entries}
    created = updated = deleted = 0

    if replace:
        # 先删后 flush：释放旧 position，避免后续 INSERT/UPDATE 与未删除行冲突。
        removed = [m for m in existing if m.knowledge_point_id not in target_kp_ids]
        for m in removed:
            await db.delete(m)
            deleted += 1
        if removed:
            await db.flush()
            existing = [m for m in existing if m.knowledge_point_id in target_kp_ids]
            existing_by_kp = {m.knowledge_point_id: m for m in existing}

        # 两阶段 position 更新：先把要改的行挪到唯一临时位，再落最终位。
        # SQLAlchemy 同表 flush 按 UPDATE→INSERT→DELETE 排序，逐条 UPDATE 会造成
        # 瞬时重复 (question_id, position)，违反 uq_qkp_question_position（swap 场景）。
        changed = [
            (kp_id, position)
            for kp_id, position in kp_entries
            if kp_id in existing_by_kp and existing_by_kp[kp_id].position != position
        ]
        if changed:
            offset = 1_000_000
            for i, (kp_id, _pos) in enumerate(changed):
                existing_by_kp[kp_id].position = offset + i
            await db.flush()
            for kp_id, position in changed:
                existing_by_kp[kp_id].position = position
                updated += 1
            await db.flush()

        for kp_id, position in kp_entries:
            if kp_id in existing_by_kp:
                continue
            db.add(
                QuestionKnowledgePoint(
                    question_id=question.id,
                    knowledge_point_id=kp_id,
                    role="main",
                    weight=1.0,
                    source=source,
                    position=position,
                )
            )
            created += 1
    else:
        # additive：仅补充缺失映射，追加到现有 position 之后，保持幂等（不动旧行）。
        base = max((m.position for m in existing), default=-1) + 1
        for position, (kp_id, _pos) in enumerate(kp_entries):
            if kp_id in existing_by_kp:
                continue
            db.add(
                QuestionKnowledgePoint(
                    question_id=question.id,
                    knowledge_point_id=kp_id,
                    role="main",
                    weight=1.0,
                    source=source,
                    position=base + position,
                )
            )
            created += 1

    await db.flush()
    return {
        "changed": bool(created or updated or deleted),
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "total": len(entries),
    }


async def replace_question_knowledge_points(
    db: AsyncSession,
    question: Question,
    kp_names,
    source: str,
) -> dict:
    """replace 语义封装（编辑/duplicate 覆盖用）。"""
    return await sync_question_knowledge_points(
        db, question, kp_names, source=source, replace=True
    )


async def load_question_kps(
    db: AsyncSession, question_ids: list[int]
) -> dict[int, list[str]]:
    """批量加载题目的知识点展示名列表（按 position,id 排序）。

    - 一次查询，无 N+1；去重 ids；空集返回 {}；无知识点的题返回 []。
    """
    if not question_ids:
        return {}
    ids = list(dict.fromkeys(question_ids))
    result = await db.execute(
        select(QuestionKnowledgePoint.question_id, KnowledgePoint.name)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
        )
        .where(QuestionKnowledgePoint.question_id.in_(ids))
        .order_by(
            QuestionKnowledgePoint.question_id,
            QuestionKnowledgePoint.position,
            QuestionKnowledgePoint.id,
        )
    )
    out: dict[int, list[str]] = {qid: [] for qid in ids}
    for qid, name in result.all():
        out[qid].append(name)
    return out


# ── 过滤 helper（基于 normalized_name 精确匹配 / contains 模糊，subject 约束）──


def kp_exact_conditions(names) -> list:
    """每个归一化名生成一个条件（调用方 AND 叠加）。用于练习的 AND 语义。"""
    out = []
    for _display, norm in normalize_kp_input(names):
        out.append(
            Question.id.in_(
                select(QuestionKnowledgePoint.question_id)
                .join(
                    KnowledgePoint,
                    KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
                )
                .join(Question, Question.id == QuestionKnowledgePoint.question_id)
                .where(
                    KnowledgePoint.subject_id == Question.subject_id,
                    KnowledgePoint.normalized_name == norm,
                )
            )
        )
    return out


def kp_any_condition(names):
    """单个 OR 条件（归一化名 in 列表）。用于薄弱点补齐等 OR 语义。"""
    norms = [norm for _display, norm in normalize_kp_input(names)]
    if not norms:
        return None
    return Question.id.in_(
        select(QuestionKnowledgePoint.question_id)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
        )
        .join(Question, Question.id == QuestionKnowledgePoint.question_id)
        .where(
            KnowledgePoint.subject_id == Question.subject_id,
            KnowledgePoint.normalized_name.in_(norms),
        )
    )


def kp_id_any_condition(knowledge_point_ids):
    """按 canonical knowledge_point_id 做 OR 过滤。

    章节专项练习会把父节点解析成 ``父节点 + 全部后代`` ID 集合，
    这里直接匹配关联表而不是再次走名称解析，避免 alias/重命名造成歧义。
    """
    ids = list(
        dict.fromkeys(
            int(value)
            for value in (knowledge_point_ids or [])
            if value is not None and int(value) > 0
        )
    )
    if not ids:
        return None
    return Question.id.in_(
        select(QuestionKnowledgePoint.question_id)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
        )
        .join(Question, Question.id == QuestionKnowledgePoint.question_id)
        .where(
            KnowledgePoint.subject_id == Question.subject_id,
            KnowledgePoint.is_active.is_(True),
            QuestionKnowledgePoint.knowledge_point_id.in_(ids),
        )
    )


def kp_fuzzy_condition(topic: str):
    """contains 模糊条件（name 原样 + normalized_name 归一化双查）。"""
    t = str(topic).strip()
    if not t:
        return None
    return Question.id.in_(
        select(QuestionKnowledgePoint.question_id)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
        )
        .join(Question, Question.id == QuestionKnowledgePoint.question_id)
        .where(
            KnowledgePoint.subject_id == Question.subject_id,
            or_(
                KnowledgePoint.name.contains(t),
                KnowledgePoint.normalized_name.contains(normalize_knowledge_name(t)),
            ),
        )
    )


async def get_knowledge_status(db: AsyncSession) -> dict:
    """返回知识点映射状态统计（区分 all / active 口径）。"""
    total_kp = (await db.execute(select(func.count(KnowledgePoint.id)))).scalar() or 0
    total_mappings = (
        await db.execute(select(func.count(QuestionKnowledgePoint.id)))
    ).scalar() or 0

    total_q_all = (await db.execute(select(func.count(Question.id)))).scalar() or 0
    total_q_active = (
        await db.execute(select(func.count(Question.id)).where(Question.is_active))
    ).scalar() or 0

    mapped_q_all = (
        await db.execute(
            select(func.count(func.distinct(QuestionKnowledgePoint.question_id)))
        )
    ).scalar() or 0
    mapped_q_active = (
        await db.execute(
            select(func.count(func.distinct(QuestionKnowledgePoint.question_id)))
            .join(Question, Question.id == QuestionKnowledgePoint.question_id)
            .where(Question.is_active)
        )
    ).scalar() or 0

    return {
        "total_knowledge_points": total_kp,
        "total_question_mappings": total_mappings,
        "mapped_questions_all": mapped_q_all,
        "mapped_questions_active": mapped_q_active,
        "total_questions_all": total_q_all,
        "total_questions_active": total_q_active,
        "unmapped_questions_all": max(0, total_q_all - mapped_q_all),
        "unmapped_questions_active": max(0, total_q_active - mapped_q_active),
    }


# ── 标签（知识点）CRUD ──────────────────────────────────────────────


async def list_tags(db: AsyncSession, subject_id: int | None = None) -> list[Tag]:
    q = select(Tag).order_by(Tag.subject_id, Tag.sort_order, Tag.id)
    if subject_id is not None:
        q = q.where(Tag.subject_id == subject_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def create_tag(
    db: AsyncSession,
    name: str,
    subject_id: int,
    parent_id: int | None = None,
) -> Tag:
    tag = Tag(name=name, subject_id=subject_id, parent_id=parent_id)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


async def delete_tag(db: AsyncSession, tag_id: int) -> bool:
    result = await db.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()
    if not tag:
        return False
    await db.delete(tag)
    await db.commit()
    return True


async def get_subject_map(
    db: AsyncSession, subject_ids: set[int]
) -> dict[int, Subject]:
    """Bulk-load Subject objects by ids (avoid N+1 subject lookups)."""
    if not subject_ids:
        return {}
    result = await db.execute(select(Subject).where(Subject.id.in_(subject_ids)))
    return {s.id: s for s in result.scalars().all()}


def build_tree(tags: list[Tag]) -> dict[int, list[dict]]:
    """将 tag 列表按 subject_id 分组并构建树形"""
    groups: dict[int, list[Tag]] = {}
    for t in tags:
        groups.setdefault(t.subject_id, []).append(t)

    result = {}
    for subject_id, subject_tags in groups.items():
        children = []
        root_nodes = [t for t in subject_tags if t.parent_id is None]
        for root in root_nodes:
            node = _node_to_dict(root, subject_tags)
            children.append(node)
        result[subject_id] = children
    return result


def _node_to_dict(tag: Tag, all_tags: list[Tag]) -> dict:
    children = [t for t in all_tags if t.parent_id == tag.id]
    return {
        "id": tag.id,
        "name": tag.name,
        "children": [
            _node_to_dict(c, all_tags)
            for c in sorted(children, key=lambda x: x.sort_order)
        ],
    }
