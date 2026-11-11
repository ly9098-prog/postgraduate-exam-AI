"""Admin API for versioned 408 syllabus governance."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.models.syllabus import SyllabusKnowledgePoint, SyllabusVersion
from app.schemas.syllabus import (
    SyllabusCatalogResponse,
    SyllabusCoverageResponse,
    SyllabusMappingCreate,
    SyllabusMappingItem,
    SyllabusMembershipReplace,
    SyllabusVersionCreate,
    SyllabusVersionDetail,
    SyllabusVersionSummary,
    SyllabusVersionUpdate,
)
from app.services import syllabus_service
from app.services.admin_audit_service import write_admin_audit
from app.core.runtime_paths import API_ADMIN_V1_PREFIX
router = APIRouter(prefix=f"{API_ADMIN_V1_PREFIX}/knowledge/syllabus", tags=["admin-syllabus"])


def _http_error(exc: syllabus_service.SyllabusError) -> HTTPException:
    message = str(exc)
    if "不存在" in message:
        return HTTPException(status_code=404, detail=message)
    if (
        "已存在" in message
        or "只有" in message
        or "不能" in message
        or "至少" in message
    ):
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=message)


@router.get("/versions", response_model=list[SyllabusVersionSummary])
async def list_versions(
    _=Depends(require_permissions("knowledge:read")),
    db: AsyncSession = Depends(get_db),
):
    return [
        SyllabusVersionSummary(**item)
        for item in await syllabus_service.list_versions(db)
    ]


@router.post("/versions", response_model=SyllabusVersionDetail, status_code=201)
async def create_version(
    data: SyllabusVersionCreate,
    request: Request,
    current_admin=Depends(require_permissions("knowledge:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        version = await syllabus_service.create_version(
            db,
            code=data.code,
            name=data.name,
            effective_year=data.effective_year,
            description=data.description,
            admin_id=current_admin.id,
        )
        await write_admin_audit(
            db,
            current_admin,
            "syllabus.create",
            "syllabus_version",
            version.id,
            detail={"code": version.code, "effective_year": version.effective_year},
            request=request,
        )
        await db.commit()
        detail = await syllabus_service.get_version_detail(db, int(version.id))
        return SyllabusVersionDetail(**detail)
    except syllabus_service.SyllabusError as exc:
        await db.rollback()
        raise _http_error(exc) from exc


@router.get("/versions/{version_id}", response_model=SyllabusVersionDetail)
async def get_version(
    version_id: int,
    _=Depends(require_permissions("knowledge:read")),
    db: AsyncSession = Depends(get_db),
):
    detail = await syllabus_service.get_version_detail(db, version_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="考纲版本不存在")
    return SyllabusVersionDetail(**detail)


@router.patch("/versions/{version_id}", response_model=SyllabusVersionDetail)
async def update_version(
    version_id: int,
    data: SyllabusVersionUpdate,
    request: Request,
    current_admin=Depends(require_permissions("knowledge:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        values = data.model_dump(exclude_unset=True)
        await syllabus_service.update_version(
            db, version_id, values=values, admin_id=current_admin.id
        )
        await write_admin_audit(
            db,
            current_admin,
            "syllabus.update",
            "syllabus_version",
            version_id,
            detail={"fields": sorted(values)},
            request=request,
        )
        await db.commit()
        return SyllabusVersionDetail(
            **(await syllabus_service.get_version_detail(db, version_id))
        )
    except syllabus_service.SyllabusError as exc:
        await db.rollback()
        raise _http_error(exc) from exc


@router.get("/versions/{version_id}/catalog", response_model=SyllabusCatalogResponse)
async def get_catalog(
    version_id: int,
    _=Depends(require_permissions("knowledge:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return SyllabusCatalogResponse(
            **await syllabus_service.get_catalog(db, version_id)
        )
    except syllabus_service.SyllabusError as exc:
        raise _http_error(exc) from exc


@router.put(
    "/versions/{version_id}/knowledge-points", response_model=SyllabusVersionDetail
)
async def replace_memberships(
    version_id: int,
    data: SyllabusMembershipReplace,
    request: Request,
    current_admin=Depends(require_permissions("knowledge:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        detail = await syllabus_service.replace_memberships(
            db, version_id, data.knowledge_point_ids, current_admin.id
        )
        await write_admin_audit(
            db,
            current_admin,
            "syllabus.replace_knowledge_points",
            "syllabus_version",
            version_id,
            detail={"knowledge_point_count": len(data.knowledge_point_ids)},
            request=request,
        )
        await db.commit()
        return SyllabusVersionDetail(**detail)
    except syllabus_service.SyllabusError as exc:
        await db.rollback()
        raise _http_error(exc) from exc


@router.post("/versions/{version_id}/activate", response_model=SyllabusVersionDetail)
async def activate_version(
    version_id: int,
    request: Request,
    current_admin=Depends(require_permissions("knowledge:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        version = await syllabus_service.activate_version(
            db, version_id, current_admin.id
        )
        await write_admin_audit(
            db,
            current_admin,
            "syllabus.activate",
            "syllabus_version",
            version_id,
            severity="critical",
            detail={"code": version.code, "effective_year": version.effective_year},
            request=request,
        )
        await db.commit()
        return SyllabusVersionDetail(
            **(await syllabus_service.get_version_detail(db, version_id))
        )
    except syllabus_service.SyllabusError as exc:
        await db.rollback()
        raise _http_error(exc) from exc


@router.post("/versions/{version_id}/archive", response_model=SyllabusVersionDetail)
async def archive_version(
    version_id: int,
    request: Request,
    current_admin=Depends(require_permissions("knowledge:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await syllabus_service.archive_version(db, version_id, current_admin.id)
        await write_admin_audit(
            db,
            current_admin,
            "syllabus.archive",
            "syllabus_version",
            version_id,
            detail={},
            request=request,
        )
        await db.commit()
        return SyllabusVersionDetail(
            **(await syllabus_service.get_version_detail(db, version_id))
        )
    except syllabus_service.SyllabusError as exc:
        await db.rollback()
        raise _http_error(exc) from exc


@router.get("/versions/{version_id}/mappings", response_model=list[SyllabusMappingItem])
async def list_mappings(
    version_id: int,
    _=Depends(require_permissions("knowledge:read")),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(SyllabusVersion, version_id) is None:
        raise HTTPException(status_code=404, detail="考纲版本不存在")
    return [
        SyllabusMappingItem(**item)
        for item in await syllabus_service.list_mappings(db, version_id)
    ]


@router.post("/mappings", response_model=SyllabusMappingItem, status_code=201)
async def create_mapping(
    data: SyllabusMappingCreate,
    request: Request,
    current_admin=Depends(require_permissions("knowledge:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await syllabus_service.add_mapping(
            db,
            from_id=data.from_syllabus_knowledge_point_id,
            to_id=data.to_syllabus_knowledge_point_id,
            relation_type=data.relation_type,
            note=data.note,
            admin_id=current_admin.id,
        )
        await write_admin_audit(
            db,
            current_admin,
            "syllabus.create_mapping",
            "syllabus_knowledge_point_mapping",
            item.id,
            detail={"relation_type": item.relation_type},
            request=request,
        )
        await db.commit()
        # Return via a compact payload without another N+1 lookup.
        all_rows = await syllabus_service.list_mappings(
            db,
            int(
                (
                    await db.get(
                        SyllabusKnowledgePoint,
                        data.to_syllabus_knowledge_point_id
                        or data.from_syllabus_knowledge_point_id,
                    )
                ).syllabus_version_id
            ),
        )
        payload = next(row for row in all_rows if row["id"] == int(item.id))
        return SyllabusMappingItem(**payload)
    except syllabus_service.SyllabusError as exc:
        await db.rollback()
        raise _http_error(exc) from exc


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(
    mapping_id: int,
    request: Request,
    current_admin=Depends(require_permissions("knowledge:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await syllabus_service.delete_mapping(db, mapping_id)
        await write_admin_audit(
            db,
            current_admin,
            "syllabus.delete_mapping",
            "syllabus_knowledge_point_mapping",
            mapping_id,
            detail={"relation_type": item.relation_type},
            request=request,
        )
        await db.commit()
        return {"success": True, "id": mapping_id}
    except syllabus_service.SyllabusError as exc:
        await db.rollback()
        raise _http_error(exc) from exc


@router.get("/versions/{version_id}/coverage", response_model=SyllabusCoverageResponse)
async def get_coverage(
    version_id: int,
    _=Depends(require_permissions("knowledge:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return SyllabusCoverageResponse(
            **await syllabus_service.get_coverage(db, version_id)
        )
    except syllabus_service.SyllabusError as exc:
        raise _http_error(exc) from exc
