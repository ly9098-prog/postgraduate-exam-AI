"""Canonical subject lookup shared by public, admin and import workflows."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Subject


async def resolve_subject_id(db: AsyncSession, subject: str | int | None) -> int | None:
    """Resolve an existing id or exact canonical code, without alias fallback."""
    if subject is None:
        return None
    if isinstance(subject, int):
        subj = await db.get(Subject, subject)
        return subject if subj else None

    key = str(subject).strip().lower()
    if not key:
        return None
    return (
        await db.execute(select(Subject.id).where(Subject.code == key).limit(1))
    ).scalar_one_or_none()


async def resolve_subject_ids(
    db: AsyncSession,
    subject: str | int | None,
    include_descendants: bool = True,
) -> list[int]:
    """Resolve a canonical subject and optionally all descendants, including inactive ones."""
    sid = await resolve_subject_id(db, subject)
    if sid is None:
        return []
    if not include_descendants:
        return [sid]

    all_subjs = (
        (
            await db.execute(
                select(Subject).order_by(
                    Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    children: dict[int | None, list[Subject]] = {}
    for item in all_subjs:
        children.setdefault(item.parent_id, []).append(item)

    descendant_ids = {sid}
    stack = list(children.get(sid, []))
    while stack:
        node = stack.pop()
        descendant_ids.add(node.id)
        stack.extend(children.get(node.id, []))

    return list(descendant_ids)
