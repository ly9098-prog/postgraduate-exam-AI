"""Resolve the subject and knowledge scopes of a practice request."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import practice_service
from app.services.practice.request_filters import (
    PracticeRequestFilterError,
    parse_knowledge_point_names,
)


class PracticeScopeNotFoundError(ValueError):
    """The requested subject or knowledge point is unavailable."""


@dataclass
class PracticeSubjectScope:
    code: str
    name: str
    has_enabled_children: bool
    subject_ids: list[int]


@dataclass
class PracticeKnowledgeFilter:
    scope: dict | None
    point_ids: list[int] | None
    names: list[str] | None


async def resolve_subject_scope(
    db: AsyncSession,
    *,
    subject_id: int,
    include_children: bool,
    mode: str,
) -> PracticeSubjectScope:
    """Resolve an enabled subject before applying the sequential leaf rule."""
    resolved = await practice_service.resolve_subject_id_to_code(db, subject_id)
    if resolved is None:
        raise PracticeScopeNotFoundError(f"科目不存在: subject_id={subject_id}")
    has_children, subject_ids = await practice_service.resolve_practice_subject_scope(
        db,
        subject_id,
        include_children,
    )
    if not subject_ids:
        raise PracticeScopeNotFoundError("科目不可用或已停用，请重新选择科目")
    if has_children and mode == "sequential":
        raise PracticeRequestFilterError(
            "顺序练习仅支持具体科目，不支持父级科目聚合刷题"
        )
    code, name = resolved
    return PracticeSubjectScope(code, name, has_children, subject_ids)


async def resolve_knowledge_filter(
    db: AsyncSession,
    *,
    knowledge_point: str | None,
    knowledge_point_id: int | None,
    include_descendants: bool,
    subject_ids: list[int],
) -> PracticeKnowledgeFilter:
    """Retain canonical ids alongside the legacy name-filter contract."""
    if knowledge_point_id is None:
        return PracticeKnowledgeFilter(
            None,
            None,
            parse_knowledge_point_names(knowledge_point),
        )
    scope = await practice_service.resolve_practice_knowledge_scope(
        db,
        knowledge_point_id=knowledge_point_id,
        subject_ids=subject_ids,
        include_descendants=include_descendants,
    )
    if scope is None:
        raise PracticeScopeNotFoundError(
            "知识点不存在、不属于当前科目范围或不在当前大纲"
        )
    point_ids = list(scope["knowledge_point_ids"])
    names = [str(scope["root_name"])] if not include_descendants else None
    return PracticeKnowledgeFilter(scope, point_ids, names)
