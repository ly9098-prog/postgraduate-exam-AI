"""水印规则服务 — 加载、缓存和匹配水印规则。"""

import re
import time

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.models.watermark_rule import WatermarkRule
from app.services.admin_audit_service import write_admin_audit

_cache: dict[str, list[re.Pattern]] = {}
_cache_ts: float = 0.0
_CACHE_TTL = 300  # 5 minutes

_MAX_PATTERN_LENGTH = 200
_NESTED_QUANTIFIER_RE = re.compile(r"[+*}]\)?[+*?{]")


async def load_rules(db: AsyncSession) -> list[re.Pattern]:
    """从数据库加载活跃水印规则，返回编译后的正则列表。"""
    global _cache, _cache_ts

    now = time.monotonic()
    if _cache.get("rules") and (now - _cache_ts) < _CACHE_TTL:
        return _cache["rules"]

    stmt = select(WatermarkRule).where(WatermarkRule.is_active)
    result = await db.execute(stmt)
    rules = result.scalars().all()

    compiled: list[re.Pattern] = []
    for rule in rules:
        try:
            if rule.rule_type == "exact":
                compiled.append(re.compile(r"^" + re.escape(rule.pattern) + r"$"))
            else:
                compiled.append(re.compile(rule.pattern))
        except re.error:
            continue

    _cache["rules"] = compiled
    _cache_ts = now
    return compiled


def invalidate_cache() -> None:
    """清除缓存，下次调用 load_rules 时重新加载。"""
    global _cache, _cache_ts
    _cache.clear()
    _cache_ts = 0.0


def match_watermark(text: str, patterns: list[re.Pattern]) -> bool:
    """判断文本是否匹配任一水印规则。"""
    stripped = text.strip()
    if not stripped:
        return False
    for pat in patterns:
        if pat.search(stripped):
            return True
    return False


async def get_all_rules(db: AsyncSession) -> list[dict]:
    """获取所有水印规则。"""
    stmt = select(WatermarkRule).order_by(WatermarkRule.id)
    result = await db.execute(stmt)
    rules = result.scalars().all()
    return [
        {
            "id": r.id,
            "pattern": r.pattern,
            "rule_type": r.rule_type,
            "description": r.description,
            "is_active": r.is_active,
        }
        for r in rules
    ]


def _validate_pattern(pattern: str) -> None:
    """校验正则模式：语法 + 长度 + ReDoS 风险。"""
    if len(pattern) > _MAX_PATTERN_LENGTH:
        raise ValueError(f"正则表达式过长（最大 {_MAX_PATTERN_LENGTH} 字符）")
    if _NESTED_QUANTIFIER_RE.search(pattern):
        raise ValueError("正则表达式含嵌套量词，存在 ReDoS 风险")
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"无效的正则表达式: {e}")


async def create_rule(
    db: AsyncSession,
    pattern: str,
    rule_type: str = "regex",
    description: str = "",
    operator: AdminPrincipal | None = None,
    request: Request | None = None,
) -> dict:
    """创建新的水印规则。"""
    if rule_type == "regex":
        _validate_pattern(pattern)

    rule = WatermarkRule(
        pattern=pattern,
        rule_type=rule_type,
        description=description,
        is_active=True,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    await write_admin_audit(
        db,
        operator,
        "watermark_rule.create",
        "watermark_rule",
        rule.id,
        detail={"pattern": rule.pattern, "rule_type": rule.rule_type},
        request=request,
    )
    await db.commit()
    invalidate_cache()
    return {"id": rule.id, "pattern": rule.pattern, "rule_type": rule.rule_type}


async def update_rule(
    db: AsyncSession,
    rule_id: int,
    pattern: str | None = None,
    rule_type: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    operator: AdminPrincipal | None = None,
    request: Request | None = None,
) -> dict | None:
    """更新水印规则。"""
    stmt = select(WatermarkRule).where(WatermarkRule.id == rule_id)
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        return None

    before = {
        "pattern": rule.pattern,
        "rule_type": rule.rule_type,
        "description": rule.description,
        "is_active": rule.is_active,
    }

    if pattern is not None:
        if (rule_type or rule.rule_type) == "regex":
            _validate_pattern(pattern)
        rule.pattern = pattern
    if rule_type is not None:
        rule.rule_type = rule_type
    if description is not None:
        rule.description = description
    if is_active is not None:
        rule.is_active = is_active

    after = {
        "pattern": rule.pattern,
        "rule_type": rule.rule_type,
        "description": rule.description,
        "is_active": rule.is_active,
    }

    await write_admin_audit(
        db,
        operator,
        "watermark_rule.update",
        "watermark_rule",
        rule.id,
        detail={"before": before, "after": after},
        request=request,
    )
    await db.commit()
    invalidate_cache()
    return {
        "id": rule.id,
        "pattern": rule.pattern,
        "rule_type": rule.rule_type,
        "is_active": rule.is_active,
    }


async def delete_rule(
    db: AsyncSession,
    rule_id: int,
    operator: AdminPrincipal | None = None,
    request: Request | None = None,
) -> bool:
    """删除水印规则。"""
    stmt = select(WatermarkRule).where(WatermarkRule.id == rule_id)
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        return False

    await write_admin_audit(
        db,
        operator,
        "watermark_rule.delete",
        "watermark_rule",
        rule.id,
        detail={"pattern": rule.pattern, "rule_type": rule.rule_type},
        request=request,
    )
    await db.delete(rule)
    await db.commit()
    invalidate_cache()
    return True


# Default built-in patterns (used when DB has no rules)
DEFAULT_WATERMARK_PATTERNS: list[str] = [
    r"^(仅供参考|内部资料|版权所有|绝密|试读版|电子版|扫描版).*$",
    r"^第\s*\d+\s*页\s*[/／]\s*共\s*\d+\s*页$",
    r"^共\s*\d+\s*页$",
    r"^第\s*\d+\s*页$",
]


def get_default_patterns() -> list[re.Pattern]:
    """返回默认内置水印模式。"""
    return [re.compile(p) for p in DEFAULT_WATERMARK_PATTERNS]
