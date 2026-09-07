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
from app.models.user_knowledge_state import UserKnowledgeState

_ANSWERABLE_TYPES = (
    QT_SINGLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_TRUE_FALSE,
    QT_MULTI_BLANK_CHOICE,
)

_MIN_RELIABLE_CONFIDENCE = 0.30
_WEAK_THRESHOLD = 40.0
_GOOD_THRESHOLD = 70.0
_MASTERED_THRESHOLD = 85.0


def _state_status(*, attempts: int, mastery: float | None, confidence: float) -> str:
    if attempts <= 0:
        return "no_data"
    if confidence < _MIN_RELIABLE_CONFIDENCE or mastery is None:
        return "insufficient"
    if mastery < _WEAK_THRESHOLD:
        return "weak"
    if mastery < _GOOD_THRESHOLD:
        return "developing"
    if mastery < _MASTERED_THRESHOLD:
        return "good"
    return "mastered"


async def _load_core_subjects(db: AsyncSession) -> tuple[Subject | None, list[Subject]]:
    rows = list((await db.scalars(
        select(Subject).where(Subject.code.in_(EXAM408_ALL_CODES))
    )).all())
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
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id)
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


def _build_subject_summary(
    subject: Subject,
    points: list[KnowledgePoint],
    states: dict[int, UserKnowledgeState],
    trainable_counts: dict[int, int],
) -> dict:
    point_ids = [int(point.id) for point in points]
    subject_states = [states[kp_id] for kp_id in point_ids if kp_id in states]
    observed = [state for state in subject_states if int(state.attempt_count or 0) > 0]
    reliable = [
        state for state in observed
        if float(state.confidence or 0.0) >= _MIN_RELIABLE_CONFIDENCE
    ]
    trainable_count = sum(1 for kp_id in point_ids if trainable_counts.get(kp_id, 0) > 0)
    required_reliable = min(3, trainable_count) if trainable_count > 0 else 0

    attempt_count = sum(int(state.attempt_count or 0) for state in observed)
    correct_count = sum(int(state.correct_count or 0) for state in observed)
    weak_count = sum(
        1 for state in reliable
        if float(state.mastery_score if state.mastery_score is not None else 50.0) < _WEAK_THRESHOLD
    )

    mastery_score: float | None = None
    confidence = 0.0
    status = "no_data"
    if observed:
        status = "insufficient"
    if reliable and len(reliable) >= max(1, required_reliable):
        total_weight = sum(float(state.confidence or 0.0) for state in reliable)
        if total_weight > 0:
            mastery_score = sum(
                float(state.mastery_score if state.mastery_score is not None else 50.0)
                * float(state.confidence or 0.0)
                for state in reliable
            ) / total_weight
            confidence = sum(float(state.confidence or 0.0) for state in reliable) / len(reliable)
            status = _state_status(
                attempts=attempt_count,
                mastery=mastery_score,
                confidence=max(confidence, _MIN_RELIABLE_CONFIDENCE),
            )

    total_points = len(points)
    coverage_ratio = (
        len(reliable) / trainable_count if trainable_count > 0 else 0.0
    )
    return {
        "subject_id": int(subject.id),
        "subject_code": str(subject.code),
        "subject_name": str(subject.name),
        "status": status,
        "mastery_score": round(mastery_score, 1) if mastery_score is not None else None,
        "confidence": round(confidence, 3),
        "total_knowledge_points": total_points,
        "trainable_knowledge_points": trainable_count,
        "observed_knowledge_points": len(observed),
        "reliable_knowledge_points": len(reliable),
        "weak_knowledge_points": weak_count,
        "attempt_count": attempt_count,
        "correct_count": correct_count,
        "accuracy": round(correct_count / attempt_count, 4) if attempt_count > 0 else None,
        "coverage_ratio": round(coverage_ratio, 4),
    }


async def get_overview(db: AsyncSession, user_id: int) -> dict:
    root, core_subjects = await _load_core_subjects(db)
    if root is None or len(core_subjects) != len(EXAM408_CORE_CODES):
        return {"scope": EXAM408_ROOT_CODE, "scope_ready": False, "subjects": []}

    subject_ids = [int(subject.id) for subject in core_subjects]
    points = list((await db.scalars(
        select(KnowledgePoint)
        .where(
            KnowledgePoint.subject_id.in_(subject_ids),
            KnowledgePoint.is_active.is_(True),
        )
        .order_by(KnowledgePoint.subject_id.asc(), KnowledgePoint.id.asc())
    )).all())
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
    return {"scope": EXAM408_ROOT_CODE, "scope_ready": True, "subjects": summaries}


def _edge_source_rank(source: str | None) -> int:
    return {"manual": 0, "imported": 1, "ai": 2, "inferred": 3}.get(str(source or ""), 4)


def _would_cycle(child_id: int, parent_id: int, parent_map: dict[int, int]) -> bool:
    cursor = parent_id
    seen: set[int] = set()
    while cursor in parent_map and cursor not in seen:
        if cursor == child_id:
            return True
        seen.add(cursor)
        cursor = parent_map[cursor]
    return cursor == child_id


def _build_parent_map(points: list[KnowledgePoint], edges: list[KnowledgeEdge]) -> dict[int, int]:
    point_ids = {int(point.id) for point in points}
    candidates = [
        edge for edge in edges
        if edge.relation_type == "parent"
        and edge.is_active
        and int(edge.source_knowledge_point_id) in point_ids
        and int(edge.target_knowledge_point_id) in point_ids
        and int(edge.source_knowledge_point_id) != int(edge.target_knowledge_point_id)
    ]
    candidates.sort(key=lambda edge: (
        _edge_source_rank(edge.source),
        -float(edge.confidence or 0.0),
        -float(edge.weight or 0.0),
        int(edge.source_knowledge_point_id),
        int(edge.target_knowledge_point_id),
    ))
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


def _ordered_tree_rows(points: list[KnowledgePoint], parent_map: dict[int, int]) -> list[tuple[KnowledgePoint, int, int | None, int]]:
    by_id = {int(point.id): point for point in points}
    children: dict[int | None, list[int]] = defaultdict(list)
    for point in points:
        point_id = int(point.id)
        children[parent_map.get(point_id)].append(point_id)
    for ids in children.values():
        ids.sort(key=lambda kp_id: (str(by_id[kp_id].name), kp_id))

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
    for point in sorted(points, key=lambda item: (str(item.name), int(item.id))):
        if int(point.id) not in visited:
            walk(int(point.id), 0)
    return rows


def _node_payload(
    point: KnowledgePoint,
    *,
    state: UserKnowledgeState | None,
    trainable_question_count: int,
    parent_id: int | None,
    depth: int,
    child_count: int,
) -> dict:
    attempts = int(state.attempt_count or 0) if state else 0
    correct = int(state.correct_count or 0) if state else 0
    wrong = int(state.wrong_count or 0) if state else 0
    mastery = float(state.mastery_score) if state and state.mastery_score is not None else None
    confidence = float(state.confidence or 0.0) if state else 0.0
    status = _state_status(attempts=attempts, mastery=mastery, confidence=confidence)
    return {
        "knowledge_point_id": int(point.id),
        "name": str(point.name),
        "description": point.description,
        "difficulty_level": int(point.difficulty_level or 3),
        "parent_id": parent_id,
        "depth": depth,
        "child_count": child_count,
        "trainable_question_count": int(trainable_question_count or 0),
        "status": status,
        "mastery_score": round(mastery, 1) if status not in {"no_data", "insufficient"} and mastery is not None else None,
        "confidence": round(confidence, 3),
        "attempt_count": attempts,
        "correct_count": correct,
        "wrong_count": wrong,
        "accuracy": round(correct / attempts, 4) if attempts > 0 else None,
        "recent_wrong_count": int(state.recent_wrong_count or 0) if state else 0,
        "last_practiced_at": serialize_utc_datetime(state.last_practiced_at) if state and state.last_practiced_at else None,
    }


async def get_subject_map(db: AsyncSession, user_id: int, subject_id: int) -> dict | None:
    _root, core_subjects = await _load_core_subjects(db)
    subject_map = {int(subject.id): subject for subject in core_subjects}
    subject = subject_map.get(int(subject_id))
    if subject is None:
        return None

    points = list((await db.scalars(
        select(KnowledgePoint)
        .where(
            KnowledgePoint.subject_id == subject.id,
            KnowledgePoint.is_active.is_(True),
        )
        .order_by(KnowledgePoint.id.asc())
    )).all())
    states = await _load_states(db, user_id, [int(subject.id)])
    trainable_counts = await _load_trainable_counts(db, [int(subject.id)])
    edges = list((await db.scalars(
        select(KnowledgeEdge).where(
            KnowledgeEdge.subject_id == subject.id,
            KnowledgeEdge.is_active.is_(True),
            KnowledgeEdge.relation_type == "parent",
        )
    )).all())
    parent_map = _build_parent_map(points, edges)
    ordered = _ordered_tree_rows(points, parent_map)
    nodes = [
        _node_payload(
            point,
            state=states.get(int(point.id)),
            trainable_question_count=trainable_counts.get(int(point.id), 0),
            parent_id=parent_id,
            depth=depth,
            child_count=child_count,
        )
        for point, depth, parent_id, child_count in ordered
    ]
    return {
        "scope": EXAM408_ROOT_CODE,
        "subject": _build_subject_summary(subject, points, states, trainable_counts),
        "nodes": nodes,
    }


async def _recent_answers(db: AsyncSession, user_id: int, knowledge_point_id: int) -> list[dict]:
    rows = await db.execute(
        select(PracticeRecord.is_correct, PracticeRecord.used_time, PracticeRecord.answered_at)
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.question_version_id == PracticeRecord.question_version_id,
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


async def _relation_payloads(db: AsyncSession, point: KnowledgePoint) -> tuple[list[dict], list[dict], list[dict]]:
    rows = list((await db.scalars(
        select(KnowledgeEdge).where(
            KnowledgeEdge.subject_id == point.subject_id,
            KnowledgeEdge.is_active.is_(True),
            (
                (KnowledgeEdge.source_knowledge_point_id == point.id)
                | (KnowledgeEdge.target_knowledge_point_id == point.id)
            ),
        )
    )).all())
    related_ids: set[int] = set()
    for edge in rows:
        related_ids.add(int(edge.source_knowledge_point_id))
        related_ids.add(int(edge.target_knowledge_point_id))
    related_ids.discard(int(point.id))
    names = {}
    if related_ids:
        names = {
            int(kp.id): str(kp.name)
            for kp in (await db.scalars(
                select(KnowledgePoint).where(
                    KnowledgePoint.id.in_(related_ids),
                    KnowledgePoint.is_active.is_(True),
                )
            )).all()
        }

    prerequisites: list[dict] = []
    next_nodes: list[dict] = []
    related_nodes: list[dict] = []
    for edge in rows:
        source_id = int(edge.source_knowledge_point_id)
        target_id = int(edge.target_knowledge_point_id)
        payload = None
        bucket = None
        if edge.relation_type == "prerequisite" and target_id == int(point.id) and source_id in names:
            payload = (source_id, names[source_id], "prerequisite")
            bucket = prerequisites
        elif edge.relation_type == "next" and source_id == int(point.id) and target_id in names:
            payload = (target_id, names[target_id], "next")
            bucket = next_nodes
        elif edge.relation_type == "related":
            other_id = target_id if source_id == int(point.id) else source_id
            if other_id in names:
                payload = (other_id, names[other_id], "related")
                bucket = related_nodes
        if payload and bucket is not None:
            bucket.append({
                "knowledge_point_id": payload[0],
                "name": payload[1],
                "relation_type": payload[2],
                "confidence": round(float(edge.confidence or 0.0), 3),
                "weight": round(float(edge.weight or 0.0), 3),
            })
    for items in (prerequisites, next_nodes, related_nodes):
        items.sort(key=lambda item: (-item["confidence"], -item["weight"], item["knowledge_point_id"]))
    return prerequisites[:8], next_nodes[:8], related_nodes[:8]


async def get_point_detail(db: AsyncSession, user_id: int, knowledge_point_id: int) -> dict | None:
    _root, core_subjects = await _load_core_subjects(db)
    core_map = {int(subject.id): subject for subject in core_subjects}
    point = (await db.execute(
        select(KnowledgePoint).where(
            KnowledgePoint.id == knowledge_point_id,
            KnowledgePoint.is_active.is_(True),
        )
    )).scalar_one_or_none()
    if point is None or int(point.subject_id) not in core_map:
        return None
    subject = core_map[int(point.subject_id)]
    states = await _load_states(db, user_id, [int(subject.id)])
    trainable = await _load_trainable_counts(db, [int(subject.id)])
    state = states.get(int(point.id))
    node = _node_payload(
        point,
        state=state,
        trainable_question_count=trainable.get(int(point.id), 0),
        parent_id=None,
        depth=0,
        child_count=0,
    )
    prerequisites, next_nodes, related_nodes = await _relation_payloads(db, point)
    return {
        "scope": EXAM408_ROOT_CODE,
        "subject_id": int(subject.id),
        "subject_code": str(subject.code),
        "subject_name": str(subject.name),
        "knowledge_point_id": int(point.id),
        "name": str(point.name),
        "description": point.description,
        "difficulty_level": int(point.difficulty_level or 3),
        "status": node["status"],
        "mastery_score": node["mastery_score"],
        "confidence": node["confidence"],
        "attempt_count": node["attempt_count"],
        "correct_count": node["correct_count"],
        "wrong_count": node["wrong_count"],
        "accuracy": node["accuracy"],
        "recent_wrong_count": node["recent_wrong_count"],
        "last_practiced_at": node["last_practiced_at"],
        "last_wrong_at": serialize_utc_datetime(state.last_wrong_at) if state and state.last_wrong_at else None,
        "trainable_question_count": node["trainable_question_count"],
        "recent_answers": await _recent_answers(db, user_id, int(point.id)),
        "prerequisites": prerequisites,
        "next_nodes": next_nodes,
        "related_nodes": related_nodes,
        "practice_route_params": {
            "subject_id": int(subject.id),
            "mode": "random",
            "count": min(10, max(1, int(node["trainable_question_count"] or 0))),
            "knowledge_point": str(point.name),
            "allow_repeat": 1,
            "autostart": 1,
            "source": "knowledge_map",
        } if int(node["trainable_question_count"] or 0) > 0 else {},
    }
