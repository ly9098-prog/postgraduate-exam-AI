from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.tag import TagCreate, TagResponse, TagSubjectGroup, TagTreeNode
from app.services import knowledge_service as svc

router = APIRouter(prefix="/api/v1/knowledge-points")


@router.get("", response_model=list[TagSubjectGroup])
async def list_knowledge_points(
    subject: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """按科目分组返回知识点列表"""
    cache_key = f"kp:list:{subject or 'all'}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    tags = await svc.list_tags(db, subject)
    groups: dict[str, list[TagResponse]] = {}
    for t in tags:
        groups.setdefault(t.subject, []).append(TagResponse(
            id=t.id, name=t.name, subject=t.subject,
            parent_id=t.parent_id, sort_order=t.sort_order,
        ))
    result = [TagSubjectGroup(subject=s, tags=ts) for s, ts in groups.items()]
    await cache.set(cache_key, [g.model_dump() for g in result], ttl=3600)
    return result


@router.get("/tree")
async def get_knowledge_tree(
    subject: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """按科目返回知识点树形结构"""
    cache_key = f"kp:tree:{subject or 'all'}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    tags = await svc.list_tags(db, subject)
    result = svc.build_tree(tags)
    await cache.set(cache_key, result, ttl=3600)
    return result


@router.post("", response_model=TagResponse, status_code=201)
async def create_knowledge_point(
    data: TagCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tag = await svc.create_tag(db, data.name, data.subject, data.parent_id)
    return TagResponse(
        id=tag.id, name=tag.name, subject=tag.subject,
        parent_id=tag.parent_id, sort_order=tag.sort_order,
    )


@router.delete("/{tag_id}")
async def delete_knowledge_point(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ok = await svc.delete_tag(db, tag_id)
    if not ok:
        raise HTTPException(status_code=404, detail="知识点不存在")
    return {"status": "deleted"}
