import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal, require_permissions
from app.core.database import get_db
from app.features.sync_merge_service import (
    MAX_QUESTIONS_PER_SYNC,
    MAX_TAGS_PER_SYNC,
    merge_sync_package,
)
from app.schemas.sync import SyncPackage, SyncReportResponse

logger = logging.getLogger("postgraduate-ai.sync")

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("/import", response_model=SyncReportResponse)
async def import_sync_package(
    package: SyncPackage,
    db: AsyncSession = Depends(get_db),
    admin: AdminPrincipal = Depends(require_permissions("sync:write")),
):
    if package.manifest.question_count != len(package.questions):
        raise HTTPException(status_code=422, detail="manifest question_count 与实际数据不一致")
    if package.manifest.tag_count != len(package.tags):
        raise HTTPException(status_code=422, detail="manifest tag_count 与实际数据不一致")
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

    report = await merge_sync_package(db, package.model_dump())

    if report.errors:
        await db.rollback()
        return SyncReportResponse(
            success=False,
            questions_new=report.questions_new,
            questions_updated=report.questions_updated,
            questions_skipped=report.questions_skipped,
            questions_conflict=report.questions_conflict,
            tags_new=report.tags_new,
            tags_skipped=report.tags_skipped,
            conflicts=report.conflicts,
            errors=report.errors,
        )

    await db.commit()
    logger.info(
        "Sync import complete: new=%d updated=%d skipped=%d conflicts=%d",
        report.questions_new, report.questions_updated,
        report.questions_skipped, report.questions_conflict,
    )
    return SyncReportResponse(
        success=True,
        questions_new=report.questions_new,
        questions_updated=report.questions_updated,
        questions_skipped=report.questions_skipped,
        questions_conflict=report.questions_conflict,
        tags_new=report.tags_new,
        tags_skipped=report.tags_skipped,
        conflicts=report.conflicts,
        errors=report.errors,
    )
