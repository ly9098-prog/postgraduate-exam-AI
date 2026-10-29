"""408 student-facing knowledge mastery map.

The map is a read model over the existing canonical knowledge state and graph
facts.  It deliberately does not maintain a second mastery score.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import (
    EXAM408_ALL_CODES,
    EXAM408_CORE_CODES,
    EXAM408_ROOT_CODE,
)
from app.core.time_utils import serialize_utc_datetime
from app.features.question_type import (
    QT_MULTI_BLANK_CHOICE,
    QT_MULTI_BLANK_MULTIPLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_TRUE_FALSE,
)
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.services import syllabus_service
from app.services.knowledge_map_hierarchy import _build_hierarchy_metadata
from app.services.knowledge_map_nodes import _node_payload
from app.services.knowledge_map_summary import _build_subject_summary
from app.services.knowledge_map_summary import _state_status as _state_status

_ANSWERABLE_TYPES = (
    QT_SINGLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_TRUE_FALSE,
    QT_MULTI_BLANK_CHOICE,
    QT_MULTI_BLANK_MULTIPLE_CHOICE,
)

async def _load_core_subjects(db: AsyncSession) -> tuple[Subject | None, list[Subject]]:
    rows = list(
        (
            await db.scalars(select(Subject).where(Subject.code.in_(EXAM408_ALL_CODES)))
        ).all()
    )
    by_code = {str(row.code): row for row in rows if row.is_active}
    root = by_code.get(EXAM408_ROOT_CODE)
    cores = [by_code.get(code) for code in EXAM408_CORE_CODES]
    if root is None or any(subject is None for subject in cores):
        return None, []
    if any(int(subject.parent_id or 0) != int(root.id) for subject in cores):
        return None, []
    return root, [subject for subject in cores if subject is not None]


async def _load_trainable_counts(
    db: AsyncSession,
    subject_ids: list[int],
) -> dict[int, int]:
    if not subject_ids:
        return {}
    rows = await db.execute(
        select(
            QuestionKnowledgePoint.knowledge_point_id,
            func.count(func.distinct(Question.id)),
        )
        .join(Question, Question.id == QuestionKnowledgePoint.question_id)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
        )
        .where(
            KnowledgePoint.subject_id.in_(subject_ids),
            KnowledgePoint.is_active.is_(True),
            Question.subject_id == KnowledgePoint.subject_id,
            Question.is_active.is_(True),
            Question.review_status == "approved",
            QuestionVersion.question_id == Question.id,
            QuestionVersion.subject_id == Question.subject_id,
            QuestionVersion.question_type == Question.question_type,
            QuestionVersion.question_type.in_(_ANSWERABLE_TYPES),
            QuestionVersion.is_active.is_(True),
        )
        .group_by(QuestionKnowledgePoint.knowledge_point_id)
    )
    return {int(kp_id): int(count or 0) for kp_id, count in rows.all()}


async def _load_states(
    db: AsyncSession,
    user_id: int,
    subject_ids: list[int],
) -> dict[int, UserKnowledgeState]:
    if not subject_ids:
        return {}
    rows = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id.in_(subject_ids),
        )
    )
    return {int(state.knowledge_point_id): state for state in rows.scalars().all()}



async def get_overview(db: AsyncSession, user_id: int) -> dict:
    root, core_subjects = await _load_core_subjects(db)
    if root is None or len(core_subjects) != len(EXAM408_CORE_CODES):
        return {
            "scope": EXAM408_ROOT_CODE,
            "syllabus_version": None,
            "scope_ready": False,
            "subjects": [],
        }

    subject_ids = [int(subject.id) for subject in core_subjects]
    syllabus_version, memberships = await syllabus_service.active_memberships(
        db, subject_ids
    )
    if syllabus_version is None:
        return {
            "scope": EXAM408_ROOT_CODE,
            "syllabus_version": None,
            "scope_ready": False,
            "subjects": [],
        }

    active_kp_ids = list(memberships)
    points = (
        list(
            (
                await db.scalars(
                    select(KnowledgePoint)
                    .where(
                        KnowledgePoint.subject_id.in_(subject_ids),
                        KnowledgePoint.id.in_(active_kp_ids)
                        if active_kp_ids
                        else False,
                    )
                    .order_by(KnowledgePoint.subject_id.asc(), KnowledgePoint.id.asc())
                )
            ).all()
        )
        if active_kp_ids
        else []
    )
    points_by_subject: dict[int, list[KnowledgePoint]] = defaultdict(list)
    for point in points:
        points_by_subject[int(point.subject_id)].append(point)

    states = await _load_states(db, user_id, subject_ids)
    trainable_counts = await _load_trainable_counts(db, subject_ids)
    summaries = [
        _build_subject_summary(
            subject,
            points_by_subject.get(int(subject.id), []),
            states,
            trainable_counts,
        )
        for subject in core_subjects
    ]
    return {
        "scope": EXAM408_ROOT_CODE,
        "syllabus_version": syllabus_service.active_summary(syllabus_version),
        "scope_ready": True,
        "subjects": summaries,
    }


def _edge_source_rank(source: str | None) -> int:
    return {"manual": 0, "imported": 1, "ai": 2, "inferred": 3}.get(
        str(source or ""), 4
    )


def _would_cycle(child_id: int, parent_id: int, parent_map: dict[int, int]) -> bool:
    cursor = parent_id
    seen: set[int] = set()
    while cursor in parent_map and cursor not in seen:
        if cursor == child_id:
            return True
        seen.add(cursor)
        cursor = parent_map[cursor]
    return cursor == child_id


def _build_parent_map(
    points: list[KnowledgePoint], edges: list[KnowledgeEdge]
) -> dict[int, int]:
    point_ids = {int(point.id) for point in points}
    candidates = [
        edge
        for edge in edges
        if edge.relation_type == "parent"
        and edge.is_active
        and int(edge.source_knowledge_point_id) in point_ids
        and int(edge.target_knowledge_point_id) in point_ids
        and int(edge.source_knowledge_point_id) != int(edge.target_knowledge_point_id)
    ]
    candidates.sort(
        key=lambda edge: (
            _edge_source_rank(edge.source),
            -float(edge.confidence or 0.0),
            -float(edge.weight or 0.0),
            int(edge.source_knowledge_point_id),
            int(edge.target_knowledge_point_id),
        )
    )
    parent_map: dict[int, int] = {}
    for edge in candidates:
        parent_id = int(edge.source_knowledge_point_id)
        child_id = int(edge.target_knowledge_point_id)
        if child_id in parent_map:
            continue
        if _would_cycle(child_id, parent_id, parent_map):
            continue
        parent_map[child_id] = parent_id
    return parent_map


def _ordered_tree_rows(
    points: list[KnowledgePoint],
    parent_map: dict[int, int],
    memberships: dict[int, SyllabusKnowledgePoint] | None = None,
) -> list[tuple[KnowledgePoint, int, int | None, int]]:
    by_id = {int(point.id): point for point in points}
    membership_map = memberships or {}

    def sort_key(kp_id: int) -> tuple[int, str, int]:
        member = membership_map.get(kp_id)
        return (
            int(member.sort_order or 0) if member is not None else 0,
            str(member.name_snapshot) if member is not None else str(by_id[kp_id].name),
            kp_id,
        )

    children: dict[int | None, list[int]] = defaultdict(list)
    for point in points:
        point_id = int(point.id)
        children[parent_map.get(point_id)].append(point_id)
    for ids in children.values():
        ids.sort(key=sort_key)

    rows: list[tuple[KnowledgePoint, int, int | None, int]] = []
    visited: set[int] = set()

    def walk(kp_id: int, depth: int) -> None:
        if kp_id in visited:
            return
        visited.add(kp_id)
        child_ids = children.get(kp_id, [])
        rows.append((by_id[kp_id], depth, parent_map.get(kp_id), len(child_ids)))
        for child_id in child_ids:
            walk(child_id, min(depth + 1, 8))

    for root_id in children.get(None, []):
        walk(root_id, 0)
    # Defensive fallback for malformed/cyclic legacy graph fragments.
    for point in sorted(points, key=lambda item: sort_key(int(item.id))):
        if int(point.id) not in visited:
            walk(int(point.id), 0)
    return rows




async def get_subject_map(
    db: AsyncSession, user_id: int, subject_id: int
) -> dict | None:
    _root, core_subjects = await _load_core_subjects(db)
    subject_map = {int(subject.id): subject for subject in core_subjects}
    subject = subject_map.get(int(subject_id))
    if subject is None:
        return None

    syllabus_version, memberships = await syllabus_service.active_memberships(
        db, [int(subject.id)]
    )
    if syllabus_version is None:
        return None
    active_kp_ids = list(memberships)
    points = (
        list(
            (
                await db.scalars(
                    select(KnowledgePoint)
                    .where(
                        KnowledgePoint.subject_id == subject.id,
                        KnowledgePoint.id.in_(active_kp_ids)
                        if active_kp_ids
                        else False,
                    )
                    .order_by(KnowledgePoint.id.asc())
                )
            ).all()
        )
        if active_kp_ids
        else []
    )
    states = await _load_states(db, user_id, [int(subject.id)])
    trainable_counts = await _load_trainable_counts(db, [int(subject.id)])
    edges = list(
        (
            await db.scalars(
                select(KnowledgeEdge).where(
                    KnowledgeEdge.subject_id == subject.id,
                    KnowledgeEdge.is_active.is_(True),
                    KnowledgeEdge.relation_type == "parent",
                )
            )
        ).all()
    )
    parent_map = _build_parent_map(points, edges)
    hierarchy_meta = _build_hierarchy_metadata(
        points, parent_map, states, trainable_counts
    )
    ordered = _ordered_tree_rows(points, parent_map, memberships)
    nodes = [
        _node_payload(
            point,
            state=states.get(int(point.id)),
            trainable_question_count=trainable_counts.get(int(point.id), 0),
            parent_id=parent_id,
            depth=depth,
            child_count=child_count,
            hierarchy_meta=hierarchy_meta.get(int(point.id)),
            syllabus_item=memberships.get(int(point.id)),
        )
        for point, depth, parent_id, child_count in ordered
    ]
    return {
        "scope": EXAM408_ROOT_CODE,
        "syllabus_version": syllabus_service.active_summary(syllabus_version),
        "subject": _build_subject_summary(subject, points, states, trainable_counts),
        "root_count": sum(1 for point in points if int(point.id) not in parent_map),
        "max_depth": max((int(node["depth"]) for node in nodes), default=0),
        "parented_knowledge_points": len(parent_map),
        "parent_coverage_ratio": round(len(parent_map) / len(points), 4)
        if points
        else 0.0,
        "nodes": nodes,
    }


async def _recent_answers(
    db: AsyncSession, user_id: int, knowledge_point_id: int
) -> list[dict]:
    rows = await db.execute(
        select(
            PracticeRecord.is_correct,
            PracticeRecord.used_time,
            PracticeRecord.answered_at,
        )
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.question_version_id
            == PracticeRecord.question_version_id,
        )
        .where(
            PracticeRecord.user_id == user_id,
            QuestionVersionKnowledgePoint.knowledge_point_id == knowledge_point_id,
        )
        .order_by(PracticeRecord.answered_at.desc(), PracticeRecord.id.desc())
        .limit(10)
    )
    return [
        {
            "is_correct": bool(row[0]),
            "used_time": int(row[1]) if row[1] is not None else None,
            "answered_at": serialize_utc_datetime(row[2]) if row[2] else None,
        }
        for row in rows.all()
    ]


async def _relation_payloads(
    db: AsyncSession,
    point: KnowledgePoint,
    memberships: dict[int, SyllabusKnowledgePoint],
) -> tuple[list[dict], list[dict], list[dict]]:
    allowed_ids = set(memberships)
    rows = list(
        (
            await db.scalars(
                select(KnowledgeEdge).where(
                    KnowledgeEdge.subject_id == point.subject_id,
                    KnowledgeEdge.is_active.is_(True),
                    (
                        (KnowledgeEdge.source_knowledge_point_id == point.id)
                        | (KnowledgeEdge.target_knowledge_point_id == point.id)
                    ),
                )
            )
        ).all()
    )
    names = {
        kp_id: str(member.name_snapshot)
        for kp_id, member in memberships.items()
        if kp_id != int(point.id)
    }

    prerequisites: list[dict] = []
    next_nodes: list[dict] = []
    related_nodes: list[dict] = []
    for edge in rows:
        source_id = int(edge.source_knowledge_point_id)
        target_id = int(edge.target_knowledge_point_id)
        if source_id not in allowed_ids or target_id not in allowed_ids:
            continue
        payload = None
        bucket = None
        if (
            edge.relation_type == "prerequisite"
            and target_id == int(point.id)
            and source_id in names
        ):
            payload = (source_id, names[source_id], "prerequisite")
            bucket = prerequisites
        elif (
            edge.relation_type == "next"
            and source_id == int(point.id)
            and target_id in names
        ):
            payload = (target_id, names[target_id], "next")
            bucket = next_nodes
        elif edge.relation_type == "related":
            other_id = target_id if source_id == int(point.id) else source_id
            if other_id in names:
                payload = (other_id, names[other_id], "related")
                bucket = related_nodes
        if payload and bucket is not None:
            bucket.append(
                {
                    "knowledge_point_id": payload[0],
                    "name": payload[1],
                    "relation_type": payload[2],
                    "confidence": round(float(edge.confidence or 0.0), 3),
                    "weight": round(float(edge.weight or 0.0), 3),
                }
            )
    for items in (prerequisites, next_nodes, related_nodes):
        items.sort(
            key=lambda item: (
                -item["confidence"],
                -item["weight"],
                item["knowledge_point_id"],
            )
        )
    return prerequisites[:8], next_nodes[:8], related_nodes[:8]


async def get_point_detail(
    db: AsyncSession, user_id: int, knowledge_point_id: int
) -> dict | None:
    _root, core_subjects = await _load_core_subjects(db)
    core_map = {int(subject.id): subject for subject in core_subjects}
    point = (
        await db.execute(
            select(KnowledgePoint).where(KnowledgePoint.id == knowledge_point_id)
        )
    ).scalar_one_or_none()
    if point is None or int(point.subject_id) not in core_map:
        return None
    subject = core_map[int(point.subject_id)]
    syllabus_version, memberships = await syllabus_service.active_memberships(
        db, [int(subject.id)]
    )
    syllabus_item = memberships.get(int(point.id))
    if syllabus_version is None or syllabus_item is None:
        return None

    states = await _load_states(db, user_id, [int(subject.id)])
    trainable = await _load_trainable_counts(db, [int(subject.id)])
    tree_points = (
        list(
            (
                await db.scalars(
                    select(KnowledgePoint).where(
                        KnowledgePoint.subject_id == subject.id,
                        KnowledgePoint.id.in_(list(memberships))
                        if memberships
                        else False,
                    )
                )
            ).all()
        )
        if memberships
        else []
    )
    tree_edges = list(
        (
            await db.scalars(
                select(KnowledgeEdge).where(
                    KnowledgeEdge.subject_id == subject.id,
                    KnowledgeEdge.is_active.is_(True),
                    KnowledgeEdge.relation_type == "parent",
                )
            )
        ).all()
    )
    parent_map = _build_parent_map(tree_points, tree_edges)
    hierarchy_meta = _build_hierarchy_metadata(
        tree_points, parent_map, states, trainable
    )
    point_meta = hierarchy_meta.get(int(point.id), {})
    point_depth = len(point_meta.get("ancestor_ids", []))
    state = states.get(int(point.id))
    node = _node_payload(
        point,
        state=state,
        trainable_question_count=trainable.get(int(point.id), 0),
        parent_id=parent_map.get(int(point.id)),
        depth=point_depth,
        child_count=int(point_meta.get("direct_child_count", 0) or 0),
        hierarchy_meta=point_meta,
        syllabus_item=syllabus_item,
    )
    by_id = {int(item.id): item for item in tree_points}
    child_ids = sorted(
        [
            child_id
            for child_id, parent_id in parent_map.items()
            if parent_id == int(point.id)
        ],
        key=lambda child_id: (
            int(memberships[child_id].sort_order or 0)
            if child_id in memberships
            else 0,
            str(memberships[child_id].name_snapshot)
            if child_id in memberships
            else str(by_id[child_id].name),
            child_id,
        ),
    )
    ancestors = [
        {
            "knowledge_point_id": ancestor_id,
            "name": str(memberships[ancestor_id].name_snapshot)
            if ancestor_id in memberships
            else str(by_id[ancestor_id].name),
            "depth": depth,
        }
        for depth, ancestor_id in enumerate(point_meta.get("ancestor_ids", []))
        if ancestor_id in by_id
    ]
    direct_children = [
        {
            "knowledge_point_id": child_id,
            "name": str(memberships[child_id].name_snapshot)
            if child_id in memberships
            else str(by_id[child_id].name),
            "depth": point_depth + 1,
        }
        for child_id in child_ids
        if child_id in by_id
    ]
    prerequisites, next_nodes, related_nodes = await _relation_payloads(
        db, point, memberships
    )
    return {
        "scope": EXAM408_ROOT_CODE,
        "syllabus_version": syllabus_service.active_summary(syllabus_version),
        "subject_id": int(subject.id),
        "subject_code": str(subject.code),
        "subject_name": str(subject.name),
        "knowledge_point_id": int(point.id),
        "name": node["name"],
        "description": node["description"],
        "difficulty_level": node["difficulty_level"],
        "status": node["status"],
        "mastery_score": node["mastery_score"],
        "confidence": node["confidence"],
        "attempt_count": node["attempt_count"],
        "correct_count": node["correct_count"],
        "wrong_count": node["wrong_count"],
        "accuracy": node["accuracy"],
        "recent_wrong_count": node["recent_wrong_count"],
        "last_practiced_at": node["last_practiced_at"],
        "last_wrong_at": serialize_utc_datetime(state.last_wrong_at)
        if state and state.last_wrong_at
        else None,
        "trainable_question_count": node["trainable_question_count"],
        "parent_id": node["parent_id"],
        "ancestors": ancestors,
        "direct_children": direct_children,
        "descendant_count": node["descendant_count"],
        "subtree_total_knowledge_points": node["subtree_total_knowledge_points"],
        "subtree_trainable_knowledge_points": node[
            "subtree_trainable_knowledge_points"
        ],
        "subtree_observed_knowledge_points": node["subtree_observed_knowledge_points"],
        "subtree_reliable_knowledge_points": node["subtree_reliable_knowledge_points"],
        "subtree_weak_knowledge_points": node["subtree_weak_knowledge_points"],
        "subtree_coverage_ratio": node["subtree_coverage_ratio"],
        "subtree_status": node["subtree_status"],
        "subtree_mastery_score": node["subtree_mastery_score"],
        "subtree_confidence": node["subtree_confidence"],
        "recent_answers": await _recent_answers(db, user_id, int(point.id)),
        "prerequisites": prerequisites,
        "next_nodes": next_nodes,
        "related_nodes": related_nodes,
        "practice_route_params": {
            "subject_id": int(subject.id),
            "mode": "random",
            "count": (
                10
                if int(node["direct_child_count"] or 0) > 0
                else min(10, max(1, int(node["trainable_question_count"] or 0)))
            ),
            "knowledge_point": node["name"],
            "knowledge_point_id": int(point.id),
            "include_descendants": 1 if int(node["direct_child_count"] or 0) > 0 else 0,
            "allow_repeat": 1,
            "autostart": 1,
            "source": "knowledge_map",
        }
        if (
            int(node["subtree_trainable_knowledge_points"] or 0) > 0
            if int(node["direct_child_count"] or 0) > 0
            else int(node["trainable_question_count"] or 0) > 0
        )
        else {},
    }
