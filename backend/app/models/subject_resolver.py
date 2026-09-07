"""Strict subject resolution helpers.

``subjects.id`` is the primary business identity and ``subjects.code`` is the
stable machine-readable identifier. Runtime resolution deliberately performs no
legacy alias, suffix, or display-name fallback. Historical subject codes belong
only in Alembic migrations.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Subject


def subject_info(subject: Subject | None) -> dict | None:
    if subject is None:
        return None
    return {
        "subject_id": subject.id,
        "subject_code": subject.code,
        "subject_name": subject.name,
        "subject_path": subject.path,
    }


async def resolve_subject(db: AsyncSession, subject_id: int) -> Subject | None:
    return await db.get(Subject, subject_id)


async def resolve_subject_id_by_code(db: AsyncSession, code: str) -> int | None:
    """Resolve an exact canonical subject code to its subject id."""
    raw = str(code or "").strip().lower()
    if not raw:
        return None
    result = await db.execute(
        select(Subject.id).where(Subject.code == raw).limit(1)
    )
    return result.scalar_one_or_none()
