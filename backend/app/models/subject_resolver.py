"""Subject code ↔ label resolution.

Uses the subjects table (tree structure) to resolve codes to human-readable names.
Falls back to a hardcoded map for legacy codes if the table query fails.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Subject

_LEGACY_LABEL_MAP: dict[str, str] = {
    "math": "数学",
    "advanced_math": "高数",
    "linear_algebra": "线性代数",
    "computer": "计算机",
    "ds": "数据结构",
    "co": "计算机组成原理",
    "os": "操作系统",
    "cn": "计算机网络",
    "english": "英语",
    "politics": "政治",
    "math2": "数学二",
}


async def resolve_subject_label(db: AsyncSession, code: str) -> str:
    """Resolve subject code to human-readable label from the subjects table."""
    try:
        result = await db.execute(
            select(Subject.name).where(Subject.code == code).limit(1)
        )
        row = result.scalar_one_or_none()
        if row:
            return row
    except Exception:
        pass
    return _LEGACY_LABEL_MAP.get(code, code)


def get_subject_label(code: str) -> str:
    """Synchronous fallback — uses legacy map only.

    For table-backed resolution, use resolve_subject_label(db, code).
    """
    return _LEGACY_LABEL_MAP.get(code, code)
