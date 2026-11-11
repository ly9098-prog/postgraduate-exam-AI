from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_subjects import (
    AdminSubjectCreateRequest,
    AdminSubjectResponse,
    AdminSubjectTreeNode,
    AdminSubjectUpdateRequest,
)
from app.services.admin_subject_service import (
    SubjectConflictError,
    create_subject,
    delete_subject,
    get_subject,
    list_subject_tree,
    update_subject,
)
from app.services.subject_tree_cache import invalidate_subject_tree_cache
from app.core.runtime_paths import API_ADMIN_V1_PREFIX
router = APIRouter(prefix=f"{API_ADMIN_V1_PREFIX}/subjects", tags=["admin-subjects"])


def _raise_subject_error(exc: ValueError) -> None:
    if str(exc) == "科目不存在":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, SubjectConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


@router.get("")
async def list_subjects(
    include_inactive: bool = False,
    _=Depends(require_permissions("subject:read")),
    db: AsyncSession = Depends(get_db),
):
    tree = await list_subject_tree(db, include_inactive)
    return {"items": [AdminSubjectTreeNode.model_validate(item) for item in tree]}


@router.get("/{subject_id}", response_model=AdminSubjectResponse)
async def get_subject_detail(
    subject_id: int,
    _=Depends(require_permissions("subject:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_subject(db, subject_id)
    except ValueError as exc:
        _raise_subject_error(exc)


@router.post("", response_model=AdminSubjectResponse)
async def create_subject_endpoint(
    data: AdminSubjectCreateRequest,
    request: Request,
    current_admin=Depends(require_permissions("subject:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        subject = await create_subject(db, data, current_admin, request)
        await db.commit()
        await db.refresh(subject)
        await invalidate_subject_tree_cache()
        return subject
    except ValueError as exc:
        await db.rollback()
        _raise_subject_error(exc)


@router.patch("/{subject_id}", response_model=AdminSubjectResponse)
async def patch_subject(
    subject_id: int,
    data: AdminSubjectUpdateRequest,
    request: Request,
    current_admin=Depends(require_permissions("subject:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        subject = await update_subject(db, subject_id, data, current_admin, request)
        await db.commit()
        await db.refresh(subject)
        await invalidate_subject_tree_cache()
        return subject
    except ValueError as exc:
        await db.rollback()
        _raise_subject_error(exc)


@router.delete("/{subject_id}")
async def delete_subject_endpoint(
    subject_id: int,
    request: Request,
    current_admin=Depends(require_permissions("subject:delete")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_subject(db, subject_id, current_admin, request)
        await db.commit()
        await invalidate_subject_tree_cache()
        return {"deleted": True}
    except ValueError as exc:
        await db.rollback()
        _raise_subject_error(exc)
