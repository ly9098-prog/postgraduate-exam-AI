"""Sequential reservation queries and retries, without owning the transaction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class SelectionPorts:
    select: Callable
    delete: Callable
    exists: Callable
    and_: Callable
    literal: Callable
    func: Any
    selectinload: Callable
    question: Any
    reservation: Any


@dataclass(frozen=True)
class ReservationScope:
    user_id: int
    subject_id: int
    scope_key: str
    start_request_id: str
    now: datetime
    expires_at: datetime


def expired_reservations(scope: ReservationScope, ports: SelectionPorts):
    model = ports.reservation
    return ports.delete(model).where(
        model.user_id == scope.user_id,
        model.subject_id == scope.subject_id,
        model.scope_key == scope.scope_key,
        model.expires_at <= scope.now,
    )


async def read_request_reservations(
    db: AsyncSession,
    scope: ReservationScope,
    get_ports: Callable[[], SelectionPorts],
) -> list[int]:
    ports = get_ports()
    model = ports.reservation
    rows = await db.execute(
        ports.select(model.question_id)
        .where(
            model.user_id == scope.user_id,
            model.subject_id == scope.subject_id,
            model.scope_key == scope.scope_key,
            model.start_request_id == scope.start_request_id,
            model.expires_at > scope.now,
        )
        .order_by(model.question_id.asc())
    )
    return [int(question_id) for question_id in rows.scalars().all()]


def candidate_conditions(
    scope: ReservationScope, conditions: list, answered_ids, ports: SelectionPorts
):
    model, question = ports.reservation, ports.question
    active = ports.exists(
        ports.select(1).where(
            model.user_id == scope.user_id,
            model.subject_id == scope.subject_id,
            model.scope_key == scope.scope_key,
            model.question_id == question.id,
            model.expires_at > scope.now,
        )
    )
    return [ports.and_(*conditions), question.id.notin_(answered_ids), ~active]


def reservation_source(
    scope: ReservationScope,
    conditions: list,
    remaining: int,
    ports: SelectionPorts,
):
    return (
        ports.select(
            ports.literal(scope.user_id).label("user_id"),
            ports.literal(scope.subject_id).label("subject_id"),
            ports.question.id.label("question_id"),
            ports.literal(scope.scope_key).label("scope_key"),
            ports.literal(scope.start_request_id).label("start_request_id"),
            ports.literal(scope.now).label("created_at"),
            ports.literal(scope.expires_at).label("expires_at"),
        )
        .where(*conditions)
        .order_by(ports.question.id.asc())
        .limit(remaining)
    )


def reservation_insert(
    source, dialect: str, insert_factory: Callable, ports: SelectionPorts
):
    model = ports.reservation
    statement = insert_factory(model).from_select(
        [
            "user_id",
            "subject_id",
            "question_id",
            "scope_key",
            "start_request_id",
            "created_at",
            "expires_at",
        ],
        source,
    )
    if dialect == "postgresql":
        return statement.on_conflict_do_nothing(
            constraint="uq_sequential_reservation_question",
        ).returning(model.question_id)
    return statement.on_conflict_do_nothing(
        index_elements=[
            model.user_id,
            model.subject_id,
            model.scope_key,
            model.question_id,
        ],
    ).returning(model.question_id)


async def fill_reservations(
    db: AsyncSession,
    scope: ReservationScope,
    *,
    count: int,
    conditions: list,
    answered_ids,
    dialect: str,
    insert_factory: Callable,
    get_ports: Callable[[], SelectionPorts],
) -> list[int]:
    selected: list[int] = []
    while len(selected) < count:
        ports = get_ports()
        source_conditions = candidate_conditions(scope, conditions, answered_ids, ports)
        source = reservation_source(
            scope, source_conditions, count - len(selected), ports
        )
        statement = reservation_insert(source, dialect, insert_factory, ports)
        rows = await db.execute(statement)
        inserted = [int(question_id) for question_id in rows.scalars().all()]
        inserted.sort()
        if not inserted:
            same_request_ids = await read_request_reservations(db, scope, get_ports)
            if same_request_ids:
                return same_request_ids
            # Recheck under READ COMMITTED after a competing claim has committed.
            ports = get_ports()
            candidate = await db.scalar(
                ports.select(ports.question.id).where(*source_conditions).limit(1)
            )
            if candidate is not None:
                continue
            break
        selected.extend(inserted)
    return selected


async def count_sequential_progress(
    db: AsyncSession,
    conditions: list,
    answered_ids,
    get_ports: Callable[[], SelectionPorts],
) -> tuple[int, int]:
    ports = get_ports()
    total = int(
        (
            await db.scalar(
                ports.select(ports.func.count(ports.question.id)).where(
                    ports.and_(*conditions)
                )
            )
        )
        or 0
    )
    ports = get_ports()
    completed = int(
        (
            await db.scalar(
                ports.select(ports.func.count(ports.question.id)).where(
                    ports.and_(*conditions),
                    ports.question.id.in_(answered_ids),
                )
            )
        )
        or 0
    )
    return total, completed


async def load_reserved_questions(
    db: AsyncSession,
    reserved_ids: list[int],
    conditions: list,
    ports: SelectionPorts,
) -> list:
    if not reserved_ids:
        return []
    question = ports.question
    rows = await db.execute(
        ports.select(question)
        .where(question.id.in_(reserved_ids), ports.and_(*conditions))
        .options(ports.selectinload(question.subject_ref))
        .order_by(question.id.asc())
    )
    by_id = {int(item.id): item for item in rows.scalars().all()}
    return [by_id[qid] for qid in reserved_ids if qid in by_id]


def sequential_progress(
    subject_id: int, total: int, completed: int, questions: list
) -> dict:
    remaining = max(0, total - completed)
    return {
        "subject_id": subject_id,
        "total_questions": total,
        "completed_questions": completed,
        "remaining_questions": remaining,
        "cycle_completed": total > 0 and remaining == 0,
        "next_question_id": questions[0].id if questions else None,
    }
