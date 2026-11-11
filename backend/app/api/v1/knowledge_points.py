from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db
from app.core.security import get_current_user, require_app_permission
from app.models.admin import Subject
from app.models.user import User
from app.schemas.tag import TagCreate, TagResponse, TagSubjectGroup
from app.services import knowledge_point_service as svc
from app.core.runtime_paths import API_V1_PREFIX
router = APIRouter(prefix=f"{API_V1_PREFIX}/knowledge-points")


@router.get("", response_model=list[TagSubjectGroup])
async def list_knowledge_points(
    subject_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """按科目分组返回知识点列表"""
    cache_key = f"kp:list:{subject_id or 'all'}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    tags = await svc.list_tags(db, subject_id)
    subject_map = await svc.get_subject_map(db, {t.subject_id for t in tags})
    groups: dict[int, list[TagResponse]] = {}
    for t in tags:
        subj = subject_map.get(t.subject_id)
        groups.setdefault(t.subject_id, []).append(
            TagResponse(
                id=t.id,
                name=t.name,
                subject_id=t.subject_id,
                subject_name=subj.name if subj else "",
                parent_id=t.parent_id,
                sort_order=t.sort_order,
            )
        )
    result = [
        TagSubjectGroup(
            subject_id=sid,
            subject_code=subject_map.get(sid).code if subject_map.get(sid) else "",
            subject_name=subject_map.get(sid).name if subject_map.get(sid) else "",
            tags=ts,
        )
        for sid, ts in groups.items()
    ]
    await cache.set(cache_key, [g.model_dump() for g in result], ttl=3600)
    return result


@router.get("/tree")
async def get_knowledge_tree(
    subject_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """按科目返回知识点树形结构"""
    cache_key = f"kp:tree:{subject_id or 'all'}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    tags = await svc.list_tags(db, subject_id)
    result = svc.build_tree(tags)
    await cache.set(cache_key, result, ttl=3600)
    return result


@router.post("", response_model=TagResponse, status_code=201)
async def create_knowledge_point(
    data: TagCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("question:write")),
):
    tag = await svc.create_tag(db, data.name, data.subject_id, data.parent_id)
    subj = await db.get(Subject, data.subject_id) if data.subject_id else None
    return TagResponse(
        id=tag.id,
        name=tag.name,
        subject_id=tag.subject_id,
        subject_name=subj.name if subj else "",
        parent_id=tag.parent_id,
        sort_order=tag.sort_order,
    )


@router.delete("/{tag_id}")
async def delete_knowledge_point(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_app_permission("question:write")),
):
    ok = await svc.delete_tag(db, tag_id)
    if not ok:
        raise HTTPException(status_code=404, detail="知识点不存在")
    return {"status": "deleted"}
