"""Subject resolution — subject identity flows use subject_id.

The `subjects` table (Subject.id) is the single source of truth for
subject_id / code / name / path.  Legacy string codes are resolved through the
subjects table (exact code / name match) or a small alias map, and are only
intended for migration and explicit external-compatibility boundaries.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Subject

# Legacy aliases -> canonical subjects.code.  Used ONLY at migration /
# external-compatibility boundaries, never as the primary subject data source.
_LEGACY_ALIAS_TO_CODE: dict[str, str] = {
    "math": "math", "math2": "math", "数学": "math", "数学二": "math",
    "computer": "computer", "exam408": "computer", "408": "computer",
    "计算机": "computer", "408计算机综合": "computer",
    "english": "english", "英语": "english",
    "politics": "politics", "pol": "politics", "political": "politics", "政治": "politics",
    "advanced_math": "advanced_math", "calculus": "advanced_math",
    "math2-calculus": "advanced_math", "高数": "advanced_math", "高等数学": "advanced_math",
    "linear_algebra": "linear_algebra", "linalg": "linear_algebra",
    "math2-linalg": "linear_algebra", "线代": "linear_algebra", "线性代数": "linear_algebra",
    "ds": "ds", "data_structure": "ds", "exam408-ds": "ds", "数据结构": "ds",
    "co": "co", "computer_organization": "co", "exam408-co": "co",
    "组成原理": "co", "计算机组成原理": "co",
    "os": "os", "operating_system": "os", "exam408-os": "os", "操作系统": "os",
    "cn": "cn", "computer_network": "cn", "exam408-cn": "cn",
    "计网": "cn", "计算机网络": "cn",
}


def subject_info(subject: Subject | None) -> dict | None:
    """Structured subject payload for API responses."""
    if subject is None:
        return None
    return {
        "subject_id": subject.id,
        "subject_code": subject.code,
        "subject_name": subject.name,
        "subject_path": subject.path,
    }


async def resolve_subject(db: AsyncSession, subject_id: int) -> Subject | None:
    """Load a Subject by id from the subjects table."""
    return await db.get(Subject, subject_id)


async def resolve_subject_id_by_code(db: AsyncSession, code: str) -> int | None:
    """Resolve a canonical subject code string to a subject id."""
    if not code:
        return None
    result = await db.execute(select(Subject.id).where(Subject.code == code).limit(1))
    return result.scalar_one_or_none()


async def resolve_subject_id_from_legacy(db: AsyncSession, value: str | None) -> int | None:
    """Resolve a legacy subject string (code / name / alias) to a subject id.

    Intended for migration and external-compatibility boundaries only; normal
    business flows must pass subject_id directly.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    # exact code match
    sid = await resolve_subject_id_by_code(db, raw)
    if sid is not None:
        return sid
    # name match
    result = await db.execute(select(Subject.id).where(Subject.name == raw).limit(1))
    sid = result.scalar_one_or_none()
    if sid is not None:
        return sid
    # alias map -> canonical code
    code = _LEGACY_ALIAS_TO_CODE.get(raw.lower())
    if code is None:
        return None
    return await resolve_subject_id_by_code(db, code)
