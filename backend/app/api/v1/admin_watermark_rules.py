"""水印规则管理 API（管理后台）。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.admin_security import require_permissions
from app.services import watermark_service

router = APIRouter(prefix="/api/admin/v1/watermark-rules")


class WatermarkRuleCreate(BaseModel):
    pattern: str
    rule_type: str = "regex"
    description: str = ""


class WatermarkRuleUpdate(BaseModel):
    pattern: str | None = None
    rule_type: str | None = None
    description: str | None = None
    is_active: bool | None = None


@router.get("")
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permissions("import:read")),
):
    """获取所有水印规则。"""
    rules = await watermark_service.get_all_rules(db)
    return {"rules": rules}


@router.post("")
async def create_rule(
    data: WatermarkRuleCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permissions("import:write")),
):
    """创建水印规则。"""
    try:
        rule = await watermark_service.create_rule(
            db, pattern=data.pattern, rule_type=data.rule_type, description=data.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return rule


@router.put("/{rule_id}")
async def update_rule(
    rule_id: int,
    data: WatermarkRuleUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permissions("import:write")),
):
    """更新水印规则。"""
    try:
        result = await watermark_service.update_rule(
            db, rule_id,
            pattern=data.pattern,
            rule_type=data.rule_type,
            description=data.description,
            is_active=data.is_active,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="规则不存在")
    return result


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permissions("import:write")),
):
    """删除水印规则。"""
    deleted = await watermark_service.delete_rule(db, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True}


