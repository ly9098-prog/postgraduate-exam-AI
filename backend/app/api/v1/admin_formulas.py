import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.core.time_utils import utcnow
from app.models.admin import AuditLog
from app.models.formula import (
    FormulaCard,
    FormulaCardTag,
    FormulaCardVersion,
    FormulaCategory,
    FormulaGraphAsset,
    FormulaImportItem,
    FormulaImportJob,
    FormulaTag,
    UserFormulaFavorite,
)
from app.services.formula_graph_asset_service import (
    MAX_IMAGE_SIZE,
    choose_effective_graph_asset,
    delete_asset_by_source_type,
    get_graph_assets_for_card,
    upload_graph_asset,
)
from app.schemas.common import paginated_response
from app.schemas.formula import (
    FormulaBatchReview,
    FormulaCardCreate,
    FormulaCardResponse,
    FormulaCardUpdate,
    FormulaCategoryCreate,
    FormulaCategoryUpdate,
    FormulaGraphAssetResponse,
    FormulaImportItemResponse,
    FormulaImportItemReview,
    FormulaImportJobResponse,
    FormulaReviewAction,
)

router = APIRouter(prefix="/api/admin/v1/formulas", tags=["admin-formulas"])


# ── Audit helper ──

async def _log_audit(
    db: AsyncSession,
    admin,
    request: Request,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict | None = None,
    severity: str = "normal",
):
    ip = request.client.host if request.client else "-"
    db.add(
        AuditLog(
            operator_id=admin.id,
            operator_name=admin.username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            severity=severity,
            detail=detail,
            ip=ip,
            user_agent=request.headers.get("user-agent", "-")[:256],
            status="success",
        )
    )


# ── Category helpers ──

def _build_category_tree(categories: list[FormulaCategory]) -> list[dict]:
    cat_map = {}
    for cat in categories:
        cat_map[cat.id] = {
            "id": cat.id,
            "parent_id": cat.parent_id,
            "exam_scope": cat.exam_scope,
            "node_type": cat.node_type,
            "code": cat.code,
            "name": cat.name,
            "description": cat.description,
            "sort_order": cat.sort_order,
            "is_active": cat.is_active,
            "created_at": cat.created_at.isoformat() if cat.created_at else None,
            "updated_at": cat.updated_at.isoformat() if cat.updated_at else None,
            "children": [],
        }
    roots = []
    for cat_id, cat_dict in cat_map.items():
        pid = cat_dict["parent_id"]
        if pid is None:
            roots.append(cat_dict)
        elif pid in cat_map:
            cat_map[pid]["children"].append(cat_dict)

    def _sort(nodes):
        nodes.sort(key=lambda n: n["sort_order"])
        for n in nodes:
            _sort(n["children"])
        return nodes

    return _sort(roots)


# ════════════════════════════════════════════════════════════
# Category CRUD
# ════════════════════════════════════════════════════════════

@router.get("/categories")
async def list_formula_categories(
    _=Depends(require_permissions("formula-category:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormulaCategory).order_by(FormulaCategory.sort_order.asc())
    )
    categories = list(result.scalars().all())
    return {"items": _build_category_tree(categories)}


@router.post("/categories")
async def create_formula_category(
    data: FormulaCategoryCreate,
    request: Request,
    admin=Depends(require_permissions("formula-category:write")),
    db: AsyncSession = Depends(get_db),
):
    # Validate node_type
    if data.node_type not in ("subject", "chapter", "group"):
        raise HTTPException(status_code=422, detail="Invalid node_type")

    if data.parent_id:
        parent = await db.get(FormulaCategory, data.parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent category not found")

        # Validate hierarchy
        allowed_children = {"subject": "chapter", "chapter": "group"}
        expected = allowed_children.get(parent.node_type)
        if expected and data.node_type != expected:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot create {data.node_type} under {parent.node_type}",
            )

    # Check code uniqueness under parent
    existing = await db.execute(
        select(FormulaCategory).where(
            FormulaCategory.parent_id == data.parent_id,
            FormulaCategory.code == data.code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Code already exists under this parent")

    category = FormulaCategory(**data.model_dump())
    db.add(category)
    await db.flush()
    await _log_audit(
        db, admin, request, "formula-category.create",
        "formula_category", str(category.id),
        {"code": category.code, "name": category.name},
    )
    await db.commit()
    await db.refresh(category)
    return {
        "id": category.id,
        "parent_id": category.parent_id,
        "exam_scope": category.exam_scope,
        "node_type": category.node_type,
        "code": category.code,
        "name": category.name,
        "description": category.description,
        "sort_order": category.sort_order,
        "is_active": category.is_active,
        "created_at": category.created_at,
        "updated_at": category.updated_at,
    }


@router.put("/categories/{category_id}")
async def update_formula_category(
    category_id: int,
    data: FormulaCategoryUpdate,
    request: Request,
    admin=Depends(require_permissions("formula-category:write")),
    db: AsyncSession = Depends(get_db),
):
    category = await db.get(FormulaCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=422, detail="No fields to update")

    for key, value in update_data.items():
        setattr(category, key, value)

    await _log_audit(
        db, admin, request, "formula-category.update",
        "formula_category", str(category_id),
        {"updates": update_data},
    )
    await db.commit()
    await db.refresh(category)
    return {"status": "ok"}


# ════════════════════════════════════════════════════════════
# Card CRUD
# ════════════════════════════════════════════════════════════

async def _card_to_dict(db: AsyncSession, card: FormulaCard) -> dict:
    tags_result = await db.execute(
        select(FormulaTag)
        .join(FormulaCardTag, FormulaCardTag.tag_id == FormulaTag.id)
        .where(FormulaCardTag.formula_card_id == card.id)
    )
    tags = [
        {"id": t.id, "code": t.code, "name": t.name, "sort_order": t.sort_order}
        for t in tags_result.scalars().all()
    ]

    # Batch-load graph assets
    from app.services.formula_graph_asset_service import (
        choose_effective_graph_asset,
        load_graph_assets_map,
    )
    assets_map = await load_graph_assets_map(db, [card.id])
    assets = assets_map.get(card.id, [])
    effective = choose_effective_graph_asset(assets)

    def _asset_to_min(a):
        if not a:
            return None
        return FormulaGraphAssetResponse.model_validate(a).model_dump(
            exclude={"template_type", "template_parameters", "viewport", "original_svg_url", "formula_card_id"},
        )

    return {
        "id": card.id,
        "exam_scope": card.exam_scope,
        "category_id": card.category_id,
        "title": card.title,
        "aliases": card.aliases,
        "search_text": card.search_text,
        "card_type": card.card_type,
        "summary": card.summary,
        "formula_blocks": card.formula_blocks,
        "conditions": card.conditions,
        "symbol_notes": card.symbol_notes,
        "secondary_conclusions": card.secondary_conclusions,
        "error_tips": card.error_tips,
        "examples": card.examples,
        "function_properties": card.function_properties,
        "sort_order": card.sort_order,
        "status": card.status,
        "tags": tags,
        "reviewed_by": card.reviewed_by,
        "reviewed_at": card.reviewed_at,
        "rejection_reason": card.rejection_reason,
        "published_at": card.published_at,
        "created_by": card.created_by,
        "updated_by": card.updated_by,
        "source_type": card.source_type,
        "source_title": card.source_title,
        "source_ref": card.source_ref,
        "content_hash": card.content_hash,
        "version": card.version,
        "deleted_at": card.deleted_at,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "graph_asset": _asset_to_min(effective),
        "graph_assets": [_asset_to_min(a) for a in assets],
    }


def _compute_content_hash(formula_blocks: list[dict]) -> str:
    raw = json.dumps(formula_blocks, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _create_version_snapshot(
    db: AsyncSession,
    card: FormulaCard,
    action: str,
    edited_by: int | None,
    edit_reason: str | None = None,
):
    snapshot = await _card_to_dict(db, card)
    version = FormulaCardVersion(
        formula_card_id=card.id,
        version=card.version,
        snapshot=snapshot,
        action=action,
        edited_by=edited_by,
        edit_reason=edit_reason,
    )
    db.add(version)


@router.get("")
async def list_formula_cards(
    status: str | None = Query(None),
    category_id: int | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _=Depends(require_permissions("formula:read")),
    db: AsyncSession = Depends(get_db),
):
    query = select(FormulaCard).where(FormulaCard.deleted_at.is_(None))

    if status:
        query = query.where(FormulaCard.status == status)
    if category_id:
        query = query.where(FormulaCard.category_id == category_id)
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                FormulaCard.title.ilike(like),
                FormulaCard.search_text.ilike(like),
            )
        )

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(FormulaCard.updated_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    cards = list(result.scalars().all())

    items = []
    for card in cards:
        items.append(await _card_to_dict(db, card))

    return paginated_response(items, total, page, page_size)


# ── Tags (read-only, before /{card_id} to avoid route conflict) ──


@router.get("/tags")
async def list_formula_tags(
    _=Depends(require_permissions("formula:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormulaTag).order_by(FormulaTag.sort_order.asc())
    )
    tags = result.scalars().all()
    return {
        "items": [
            {"id": t.id, "code": t.code, "name": t.name, "sort_order": t.sort_order}
            for t in tags
        ]
    }


@router.get("/{card_id}")
async def get_formula_card(
    card_id: int,
    _=Depends(require_permissions("formula:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == card_id, FormulaCard.deleted_at.is_(None)
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    return await _card_to_dict(db, card)


@router.post("")
async def create_formula_card(
    data: FormulaCardCreate,
    request: Request,
    admin=Depends(require_permissions("formula:create")),
    db: AsyncSession = Depends(get_db),
):
    # Verify category exists
    category = await db.get(FormulaCategory, data.category_id)
    if not category or not category.is_active:
        raise HTTPException(status_code=422, detail="Invalid or inactive category")

    # Compute content hash
    blocks_dicts = [b.model_dump() for b in data.formula_blocks]
    content_hash = _compute_content_hash(blocks_dicts)

    tag_ids = data.tag_ids or []

    card = FormulaCard(
        exam_scope=category.exam_scope,
        category_id=data.category_id,
        title=data.title,
        aliases=data.aliases,
        search_text=data.search_text,
        card_type=data.card_type,
        summary=data.summary,
        formula_blocks=blocks_dicts,
        conditions=data.conditions,
        symbol_notes=data.symbol_notes,
        secondary_conclusions=data.secondary_conclusions,
        error_tips=data.error_tips,
        examples=[e.model_dump() for e in data.examples] if data.examples else None,
        function_properties=data.function_properties,
        sort_order=data.sort_order,
        status="draft",
        created_by=admin.id,
        updated_by=admin.id,
        source_type=data.source_type,
        source_title=data.source_title,
        source_ref=data.source_ref,
        content_hash=content_hash,
        version=1,
    )
    db.add(card)
    await db.flush()

    # Create tags
    for tag_id in tag_ids:
        db.add(FormulaCardTag(formula_card_id=card.id, tag_id=tag_id))

    # Version snapshot
    await _create_version_snapshot(db, card, "create", admin.id)

    await _log_audit(
        db, admin, request, "formula.create",
        "formula_card", str(card.id),
        {"title": card.title},
    )
    await db.commit()
    await db.refresh(card)
    return await _card_to_dict(db, card)


@router.put("/{card_id}")
async def update_formula_card(
    card_id: int,
    data: FormulaCardUpdate,
    request: Request,
    admin=Depends(require_permissions("formula:update")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == card_id, FormulaCard.deleted_at.is_(None)
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    update_data = data.model_dump(exclude_unset=True)
    tag_ids = update_data.pop("tag_ids", None)

    if not update_data and tag_ids is None:
        raise HTTPException(status_code=422, detail="No fields to update")

    # Update formula blocks → recalc content hash
    if "formula_blocks" in update_data and update_data["formula_blocks"] is not None:
        update_data["content_hash"] = _compute_content_hash(update_data["formula_blocks"])

    # Update category scope
    if "category_id" in update_data:
        category = await db.get(FormulaCategory, update_data["category_id"])
        if category:
            update_data["exam_scope"] = category.exam_scope

    update_data["updated_by"] = admin.id
    update_data["version"] = card.version + 1

    for key, value in update_data.items():
        setattr(card, key, value)

    # Update tags
    if tag_ids is not None:
        await db.execute(
            FormulaCardTag.__table__.delete().where(
                FormulaCardTag.formula_card_id == card.id
            )
        )
        for tag_id in tag_ids:
            db.add(FormulaCardTag(formula_card_id=card.id, tag_id=tag_id))

    # Reset status to draft on content update
    if card.status in ("approved", "rejected"):
        card.status = "draft"

    # Version snapshot
    await _create_version_snapshot(db, card, "update", admin.id)

    await _log_audit(
        db, admin, request, "formula.update",
        "formula_card", str(card.id),
        {"title": card.title, "fields": list(update_data.keys())},
    )
    await db.commit()
    await db.refresh(card)
    return await _card_to_dict(db, card)


@router.delete("/{card_id}")
async def soft_delete_formula_card(
    card_id: int,
    request: Request,
    admin=Depends(require_permissions("formula:delete")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == card_id, FormulaCard.deleted_at.is_(None)
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    # Only published formulas must be taken offline first
    if card.status == "published":
        raise HTTPException(
            status_code=422,
            detail="Must take formula offline before deleting",
        )

    card.deleted_at = utcnow()
    await _create_version_snapshot(db, card, "delete", admin.id)
    await _log_audit(
        db, admin, request, "formula.delete",
        "formula_card", str(card.id),
        {"title": card.title},
    )
    await db.commit()
    return {"status": "ok"}


# ════════════════════════════════════════════════════════════
# State Machine
# ════════════════════════════════════════════════════════════

_VALID_TRANSITIONS = {
    "draft": ["restore", "approve"],
    "pending_review": ["approve", "reject"],
    "rejected": ["restore"],
    "approved": ["publish"],
    "published": ["offline"],
    "offline": ["publish"],
}


@router.post("/{card_id}/review")
async def review_formula_card(
    card_id: int,
    data: FormulaReviewAction,
    request: Request,
    admin=Depends(require_permissions("formula:review")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == card_id, FormulaCard.deleted_at.is_(None)
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    allowed = _VALID_TRANSITIONS.get(card.status, [])
    if data.action not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot transition from {card.status} with action {data.action}. Allowed: {allowed}",
        )

    # Save original status before any mutation
    old_status = card.status

    # Map action to new status
    action_map = {
        "approve": "approved",
        "reject": "rejected",
        "publish": "published",
        "offline": "offline",
        "restore": "draft",
    }
    # From draft, "approve" means submit for review → pending_review
    if card.status == "draft" and data.action == "approve":
        new_status = "pending_review"
    else:
        new_status = action_map.get(data.action)

    if data.action == "reject" and not data.rejection_reason:
        raise HTTPException(status_code=422, detail="Rejection reason required")

    card.status = new_status
    card.updated_by = admin.id
    card.version = card.version + 1

    if data.action in ("approve", "reject"):
        card.reviewed_by = admin.id
        card.reviewed_at = utcnow()
        if data.action == "reject":
            card.rejection_reason = data.rejection_reason

    if data.action == "publish":
        card.published_at = utcnow()
        card.reviewed_by = admin.id
        card.reviewed_at = utcnow()

    if data.action in ("offline", "restore"):
        card.reviewed_by = None
        card.reviewed_at = None
        card.published_at = None

    await _create_version_snapshot(db, card, data.action, admin.id, data.rejection_reason)
    await db.flush()
    await _log_audit(
        db, admin, request, f"formula.{data.action}",
        "formula_card", str(card.id),
        {
            "from_status": old_status,
            "to_status": new_status,
            "rejection_reason": data.rejection_reason,
        },
    )
    await db.commit()
    await db.refresh(card)
    return {"status": "ok", "new_status": card.status}


@router.post("/batch-review")
async def batch_review_formulas(
    data: FormulaBatchReview,
    request: Request,
    admin=Depends(require_permissions("formula:review")),
    db: AsyncSession = Depends(get_db),
):
    results = []
    for card_id in data.card_ids:
        try:
            card = await db.get(FormulaCard, card_id)
            if not card or card.deleted_at:
                results.append({"id": card_id, "status": "not_found"})
                continue

            allowed = _VALID_TRANSITIONS.get(card.status, [])
            if data.action not in allowed:
                results.append({"id": card_id, "status": "invalid_transition"})
                continue

            action_map = {
                "approve": "approved",
                "reject": "rejected",
                "publish": "published",
                "offline": "offline",
                "restore": "draft",
            }
            # From draft, "approve" means submit for review → pending_review
            if card.status == "draft" and data.action == "approve":
                new_status = "pending_review"
            else:
                new_status = action_map.get(data.action)

            if data.action == "reject" and not data.rejection_reason:
                results.append({"id": card_id, "status": "missing_reason"})
                continue

            card.status = new_status
            card.updated_by = admin.id
            card.version = card.version + 1

            if data.action in ("approve", "reject"):
                card.reviewed_by = admin.id
                card.reviewed_at = utcnow()
                if data.action == "reject":
                    card.rejection_reason = data.rejection_reason

            if data.action == "publish":
                card.published_at = utcnow()
                card.reviewed_by = admin.id
                card.reviewed_at = utcnow()

            results.append({"id": card_id, "status": new_status})
        except Exception as exc:
            results.append({"id": card_id, "status": "error", "detail": str(exc)})

    await db.commit()
    await _log_audit(
        db, admin, request, f"formula.batch-{data.action}",
        "formula_card", None,
        {"card_ids": data.card_ids, "results": results},
    )
    return {"items": results}


# ════════════════════════════════════════════════════════════
# Versions
# ════════════════════════════════════════════════════════════

@router.get("/{card_id}/versions")
async def get_formula_card_versions(
    card_id: int,
    _=Depends(require_permissions("formula:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormulaCardVersion)
        .where(FormulaCardVersion.formula_card_id == card_id)
        .order_by(FormulaCardVersion.version.desc())
    )
    versions = result.scalars().all()
    return {
        "items": [
            {
                "id": v.id,
                "version": v.version,
                "action": v.action,
                "edited_by": v.edited_by,
                "edit_reason": v.edit_reason,
                "snapshot": v.snapshot,
                "created_at": v.created_at,
            }
            for v in versions
        ]
    }


# ════════════════════════════════════════════════════════════
# Duplicate Check
# ════════════════════════════════════════════════════════════

@router.post("/{card_id}/check-duplicate")
async def check_formula_duplicate(
    card_id: int,
    _=Depends(require_permissions("formula:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == card_id, FormulaCard.deleted_at.is_(None)
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    # Strong duplicate: same category + same content hash
    if card.content_hash:
        strong = await db.execute(
            select(FormulaCard).where(
                FormulaCard.id != card.id,
                FormulaCard.category_id == card.category_id,
                FormulaCard.content_hash == card.content_hash,
                FormulaCard.deleted_at.is_(None),
            )
        )
        strong_dups = strong.scalars().all()
    else:
        strong_dups = []

    return {
        "strong_duplicates": [
            {"id": d.id, "title": d.title} for d in strong_dups
        ],
    }


# ════════════════════════════════════════════════════════════
# LaTeX Validation (basic)
# ════════════════════════════════════════════════════════════

import re

_LATEX_DANGEROUS = re.compile(
    r"\\(?:input|include|write|read|def|edef|xdef|gdef|let|futurelet|csname|"
    r"endcsname|immediate|directlua|write18|verbatim|lstinputlisting|begin\s*\{document\})",
    re.IGNORECASE,
)
_LATEX_BRACKET_RE = re.compile(r"[{}]")
_LATEX_ENV_RE = re.compile(r"\\begin\s*\{(\w+)\}|\\end\s*\{(\w+)\}")


def _validate_latex(formula_blocks: list[dict]) -> dict:
    """Basic server-side LaTeX validation."""
    errors = []
    for i, block in enumerate(formula_blocks):
        latex = block.get("latex", "")
        if not latex.strip():
            continue

        # Check dangerous commands
        dangerous = _LATEX_DANGEROUS.findall(latex)
        if dangerous:
            errors.append({"block_index": i, "type": "dangerous_command", "detail": dangerous[0]})

        # Check balanced braces
        opens = len(_LATEX_BRACKET_RE.findall(latex.replace("\\{", "").replace("\\}", "")))
        if opens % 2 != 0:
            errors.append({"block_index": i, "type": "unbalanced_braces"})

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


@router.post("/validate-latex")
async def validate_formula_latex(
    data: FormulaCardCreate,
    _=Depends(require_permissions("formula:read")),
    db: AsyncSession = Depends(get_db),
):
    blocks = [b.model_dump() for b in data.formula_blocks]
    result = _validate_latex(blocks)
    return result


# ════════════════════════════════════════════════════════════
# Import Jobs
# ════════════════════════════════════════════════════════════

@router.get("/import-jobs")
async def list_formula_import_jobs(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _=Depends(require_permissions("formula:import")),
    db: AsyncSession = Depends(get_db),
):
    query = select(FormulaImportJob)
    if status:
        query = query.where(FormulaImportJob.status == status)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(FormulaImportJob.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    jobs = result.scalars().all()

    return paginated_response(
        [
            {
                "id": j.id,
                "source_type": j.source_type,
                "status": j.status,
                "progress": j.progress,
                "stage": j.stage,
                "error_message": j.error_message,
                "source_filename": j.source_filename,
                "total_items": j.total_items,
                "processed_items": j.processed_items,
                "failed_items": j.failed_items,
                "retry_of": j.retry_of,
                "metadata_json": j.metadata_json,
                "created_by": j.created_by,
                "created_at": j.created_at,
                "updated_at": j.updated_at,
            }
            for j in jobs
        ],
        total, page, page_size,
    )


@router.get("/import-jobs/{job_id}")
async def get_formula_import_job(
    job_id: int,
    _=Depends(require_permissions("formula:import")),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(FormulaImportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "source_type": job.source_type,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error_message": job.error_message,
        "source_filename": job.source_filename,
        "total_items": job.total_items,
        "processed_items": job.processed_items,
        "failed_items": job.failed_items,
        "retry_of": job.retry_of,
        "metadata_json": job.metadata_json,
        "created_by": job.created_by,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("/import-jobs/{job_id}/items")
async def get_formula_import_items(
    job_id: int,
    review_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _=Depends(require_permissions("formula:import")),
    db: AsyncSession = Depends(get_db),
):
    query = select(FormulaImportItem).where(FormulaImportItem.job_id == job_id)
    if review_status:
        query = query.where(FormulaImportItem.review_status == review_status)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(FormulaImportItem.id.asc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return paginated_response(
        [
            {
                "id": item.id,
                "job_id": item.job_id,
                "source_locator": item.source_locator,
                "raw_text": item.raw_text,
                "raw_image_url": item.raw_image_url,
                "generated_content": item.generated_content,
                "card_type": item.card_type,
                "confidence": item.confidence,
                "risk_flags": item.risk_flags,
                "latex_valid": item.latex_valid,
                "latex_errors": item.latex_errors,
                "scope_check": item.scope_check,
                "duplicate_check": item.duplicate_check,
                "review_status": item.review_status,
                "rejection_reason": item.rejection_reason,
                "result_card_id": item.result_card_id,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in items
        ],
        total, page, page_size,
    )


@router.put("/import-items/{item_id}/review")
async def review_formula_import_item(
    item_id: int,
    data: FormulaImportItemReview,
    request: Request,
    admin=Depends(require_permissions("formula:import")),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(FormulaImportItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Import item not found")

    item.review_status = data.review_status
    item.reviewed_by = admin.id
    item.reviewed_at = utcnow()
    item.rejection_reason = data.rejection_reason

    await _log_audit(
        db, admin, request, f"formula.import-item.{data.review_status}",
        "formula_import_item", str(item_id),
    )
    await db.commit()
    return {"status": "ok"}


# ════════════════════════════════════════════════════════════
# Graph Assets
# ════════════════════════════════════════════════════════════


def _graph_asset_to_dict(asset: FormulaGraphAsset) -> dict:
    return FormulaGraphAssetResponse.model_validate(asset).model_dump()


@router.get("/{card_id}/graph-assets")
async def list_graph_assets(
    card_id: int,
    _=Depends(require_permissions("formula:read")),
    db: AsyncSession = Depends(get_db),
):
    """List all graph assets for a card, plus the effective one."""
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == card_id, FormulaCard.deleted_at.is_(None)
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    assets = await get_graph_assets_for_card(db, card_id)
    effective = choose_effective_graph_asset(assets)

    return {
        "items": [_graph_asset_to_dict(a) for a in assets],
        "effective": _graph_asset_to_dict(effective) if effective else None,
    }


@router.post("/{card_id}/graph-assets/upload")
async def upload_graph_asset_endpoint(
    card_id: int,
    request: Request,
    admin=Depends(require_permissions("formula:update")),
    db: AsyncSession = Depends(get_db),
):
    """Upload or replace a graph image for a function_graph card."""
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == card_id, FormulaCard.deleted_at.is_(None)
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    if card.card_type != "function_graph":
        raise HTTPException(
            status_code=422,
            detail="仅函数图像类型卡片支持上传图像。当前卡片类型为「纯公式」",
        )

    # Read file from multipart
    form = await request.form()
    file_field = form.get("file")
    if not file_field:
        raise HTTPException(status_code=422, detail="未提供文件（字段名: file）")

    try:
        file_data = await file_field.read()
    except Exception:
        raise HTTPException(status_code=422, detail="文件读取失败")

    # Validate
    if not file_data:
        raise HTTPException(status_code=422, detail="文件为空")
    if len(file_data) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail=f"文件大小超过 {MAX_IMAGE_SIZE // (1024 * 1024)}MB 限制")

    filename = getattr(file_field, "filename", "image.png") or "image.png"

    try:
        asset, is_new = await upload_graph_asset(db, card, file_data, filename, admin.id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Audit log
    old_cs = None
    if not is_new:
        # Check if this was a replace (asset existed before)
        old_assets = await get_graph_assets_for_card(db, card_id)
        for a in old_assets:
            if a.id == asset.id and a.checksum != asset.checksum:
                old_cs = a.checksum
                break

    action = "formula.graph_asset.replace" if not is_new and old_cs else "formula.graph_asset.upload"
    await _log_audit(
        db, admin, request, action, "formula_graph_asset", str(asset.id),
        detail={
            "formula_card_id": card_id,
            "source_type": "uploaded",
            "old_checksum": old_cs,
            "new_checksum": asset.checksum,
            "width": asset.width,
            "height": asset.height,
        },
    )

    await db.commit()
    await db.refresh(asset)
    return _graph_asset_to_dict(asset)


@router.delete("/{card_id}/graph-assets/{source_type}")
async def delete_graph_asset(
    card_id: int,
    source_type: str,
    request: Request,
    admin=Depends(require_permissions("formula:update")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a graph asset by source_type (uploaded|template)."""
    if source_type not in ("uploaded", "template"):
        raise HTTPException(status_code=422, detail=f"不支持的来源类型: {source_type}")

    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == card_id, FormulaCard.deleted_at.is_(None)
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    deleted = await delete_asset_by_source_type(db, card, source_type)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"未找到 {source_type} 类型资产")

    await _log_audit(
        db, admin, request, "formula.graph_asset.delete",
        "formula_graph_asset", None,
        detail={
            "formula_card_id": card_id,
            "source_type": source_type,
        },
    )

    await db.commit()
    return {"status": "ok"}

