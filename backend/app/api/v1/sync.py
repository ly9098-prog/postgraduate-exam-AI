import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import (
    AdminPrincipal,
    _get_permission_names,
    require_permissions,
)
from app.core.database import get_db
from app.features.sync_merge_service import (
    MAX_QUESTIONS_PER_SYNC,
    MAX_TAGS_PER_SYNC,
    merge_sync_package,
)
from app.schemas.sync import SyncPackage, SyncReportResponse
from app.services.admin_audit_service import write_admin_audit
from app.core.runtime_paths import API_V1_PREFIX
logger = logging.getLogger("postgraduate-ai.sync")

router = APIRouter(prefix=f"{API_V1_PREFIX}/sync", tags=["sync"])


@router.post("/import", response_model=SyncReportResponse)
async def import_sync_package(
    package: SyncPackage,
    db: AsyncSession = Depends(get_db),
    admin: AdminPrincipal = Depends(require_permissions("sync:write")),
):
    if package.manifest.question_count != len(package.questions):
        raise HTTPException(
            status_code=422, detail="manifest question_count 与实际数据不一致"
        )
    if package.manifest.tag_count != len(package.tags):
        raise HTTPException(
            status_code=422, detail="manifest tag_count 与实际数据不一致"
        )
    if len(package.questions) > MAX_QUESTIONS_PER_SYNC:
        raise HTTPException(
            status_code=422,
            detail=f"单次同步最多 {MAX_QUESTIONS_PER_SYNC} 道题，请分批上传",
        )
    if len(package.tags) > MAX_TAGS_PER_SYNC:
        raise HTTPException(
            status_code=422,
            detail=f"单次同步最多 {MAX_TAGS_PER_SYNC} 个标签",
        )

    granted = await _get_permission_names(db, admin.role_id)
    allow_lifecycle = "question:review" in granted
    report = await merge_sync_package(
        db, package.model_dump(), allow_lifecycle=allow_lifecycle
    )

    if report.errors:
        await db.rollback()
        return SyncReportResponse(
            success=False,
            questions_new=report.questions_new,
            questions_updated=report.questions_updated,
            questions_skipped=report.questions_skipped,
            questions_conflict=report.questions_conflict,
            questions_deduped=report.questions_deduped,
            tags_new=report.tags_new,
            tags_skipped=report.tags_skipped,
            conflicts=report.conflicts,
            errors=report.errors,
        )

    await write_admin_audit(
        db,
        admin,
        "sync.import",
        "question_batch",
        package.manifest.checksum or "unknown",
        severity="important",
        detail={
            "questions_new": report.questions_new,
            "questions_updated": report.questions_updated,
            "questions_conflict": report.questions_conflict,
            "questions_deduped": report.questions_deduped,
            "tags_new": report.tags_new,
            "lifecycle_applied": allow_lifecycle,
        },
    )
    await db.commit()
    logger.info(
        "Sync import complete: new=%d updated=%d skipped=%d conflicts=%d deduped=%d",
        report.questions_new,
        report.questions_updated,
        report.questions_skipped,
        report.questions_conflict,
        report.questions_deduped,
    )
    return SyncReportResponse(
        success=True,
        questions_new=report.questions_new,
        questions_updated=report.questions_updated,
        questions_skipped=report.questions_skipped,
        questions_conflict=report.questions_conflict,
        questions_deduped=report.questions_deduped,
        tags_new=report.tags_new,
        tags_skipped=report.tags_skipped,
        conflicts=report.conflicts,
        errors=report.errors,
    )
