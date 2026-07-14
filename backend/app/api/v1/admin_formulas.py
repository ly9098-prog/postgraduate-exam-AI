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
    is_function_graph,
    upload_graph_asset,
)
from app.services.formula_graph_spec_service import (
    confirm_preview,
    delete_generated_asset as delete_spec_generated_asset,
    generate_preview,
    get_batch_status,
    regenerate_asset,
    start_batch_generate,
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
    GraphConfirmRequest,
    GraphConfirmResponse,
    GraphPreviewResponse,
    GraphSpec,
    QualityCheckResult,
    GraphAssetUpdate,
    GraphBatchGenerateResponse,
    GraphBatchJobStatus,
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

def _json_safe(v):
    """Convert non-JSON-safe types for JSON column storage."""
    if isinstance(v, datetime):
        return v.isoformat()
    return v


async def _card_to_dict(db: AsyncSession, card: FormulaCard) -> dict:
    # Read ALL scalar ORM attributes BEFORE any await point.
    # If the card is dirty, the first await triggers auto-flush → expires
    # server-default columns (e.g. updated_at), causing MissingGreenlet.
    base = {
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
        "reviewed_by": card.reviewed_by,
        "reviewed_at": _json_safe(card.reviewed_at),
        "rejection_reason": card.rejection_reason,
        "published_at": _json_safe(card.published_at),
        "created_by": card.created_by,
        "updated_by": card.updated_by,
        "source_type": card.source_type,
        "source_title": card.source_title,
        "source_ref": card.source_ref,
        "content_hash": card.content_hash,
        "graph_spec": card.graph_spec,
        "draft_graph_spec": card.draft_graph_spec,
        "graph_status": card.graph_status or "not_applicable",
        "graph_last_error": card.graph_last_error,
        "graph_generated_at": _json_safe(card.graph_generated_at),
        "graph_confirmed_at": _json_safe(card.graph_confirmed_at),
        "version": card.version,
        "deleted_at": _json_safe(card.deleted_at),
        "created_at": _json_safe(card.created_at),
        "updated_at": _json_safe(card.updated_at),
    }

    # Async-load relationships (safe to trigger auto-flush now — base is captured)
    tags_result = await db.execute(
        select(FormulaTag)
        .join(FormulaCardTag, FormulaCardTag.tag_id == FormulaTag.id)
        .where(FormulaCardTag.formula_card_id == card.id)
    )
    base["tags"] = [
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
            mode="json",
            exclude={"template_type", "template_parameters", "viewport", "original_svg_url", "formula_card_id"},
        )

    base["graph_asset"] = _asset_to_min(effective)
    base["graph_assets"] = [_asset_to_min(a) for a in assets]
    base["graph_image_url"] = effective.image_url if effective else None
    base["graph_thumbnail_url"] = effective.thumbnail_url if effective else None
    base["is_function_graph"] = is_function_graph(card, effective_asset=effective)

    return base


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
    library_type: str | None = Query(None),
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

    if library_type == "function_graph":
        exists_subq = (
            select(FormulaGraphAsset.id)
            .where(
                FormulaGraphAsset.formula_card_id == FormulaCard.id,
                FormulaGraphAsset.image_url.isnot(None),
            )
        ).exists()
        query = query.where(
            or_(
                FormulaCard.card_type == "function_graph",
                and_(
                    ~FormulaCard.card_type.in_(["function_graph", "pure_formula"]),
                    exists_subq,
                ),
            )
        )
    elif library_type == "pure_formula":
        exists_subq = (
            select(FormulaGraphAsset.id)
            .where(
                FormulaGraphAsset.formula_card_id == FormulaCard.id,
                FormulaGraphAsset.image_url.isnot(None),
            )
        ).exists()
        query = query.where(
            and_(
                FormulaCard.card_type != "function_graph",
                ~exists_subq,
            )
        )
    elif library_type is not None and library_type not in ("formula",):
        raise HTTPException(
            status_code=400,
            detail=f"无效的 library_type: '{library_type}'，允许的值: formula, function_graph, pure_formula",
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

    # Card type switch → update graph_status (never delete assets)
    if "card_type" in update_data and update_data["card_type"] != card.card_type:
        old_type = card.card_type
        new_type = update_data["card_type"]

        if old_type == "pure_formula" and new_type in ("function_graph", "auto"):
            # Transitioning into function_graph-capable type
            # Check if there's an existing graph asset
            from app.services.formula_graph_asset_service import get_graph_assets_for_card
            existing_assets = await get_graph_assets_for_card(db, card.id)
            has_asset = any(a.image_url for a in existing_assets)
            update_data["graph_status"] = "ready" if has_asset else "unconfigured"

        elif new_type == "pure_formula":
            update_data["graph_status"] = "not_applicable"

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
    "approved": ["publish"],            # compat for legacy data
    "published": ["offline"],
    "offline": ["publish"],
}

# Normal business transitions (not exhaustive — compat paths exist)
_NEW_STATUS_MAP = {
    ("draft", "approve"): "pending_review",         # submit for review
    ("pending_review", "approve"): "published",      # approve → auto-publish
    ("pending_review", "reject"): "rejected",
    ("rejected", "restore"): "draft",
    ("published", "offline"): "offline",
    ("offline", "publish"): "published",
    ("approved", "publish"): "published",            # legacy compat
}


def _apply_formula_action(
    card: FormulaCard,
    action: str,
    admin_id: int,
    now: datetime | None = None,
    rejection_reason: str | None = None,
) -> str:
    """Apply a state-machine action to a formula card in-place.

    Returns the new status.
    Raises HTTPException on invalid transition or missing rejection reason.
    """
    allowed = _VALID_TRANSITIONS.get(card.status, [])
    if action not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot transition from {card.status} with action {action}. Allowed: {allowed}",
        )

    if now is None:
        now = utcnow()

    # ── Resolve new status ──
    key = (card.status, action)
    new_status = _NEW_STATUS_MAP.get(key)
    if new_status is None:
        # fallback: direct action→status mapping (legacy)
        fallback = {"approve": "approved", "reject": "rejected", "publish": "published",
                    "offline": "offline", "restore": "draft"}
        new_status = fallback[action]

    # ── Rejection reason validation ──
    if action == "reject":
        trimmed = (rejection_reason or "").strip()
        if not trimmed:
            raise HTTPException(status_code=422, detail="Rejection reason required")
        rejection_reason = trimmed

    # ── Field updates per action ──
    card.status = new_status
    card.updated_by = admin_id
    card.version += 1

    if action == "approve" and card.status == "published":
        # approve → auto-publish (pending_review → published)
        card.reviewed_by = admin_id
        card.reviewed_at = now
        card.published_at = now
        card.rejection_reason = None

    elif action == "approve" and card.status == "pending_review":
        # draft → pending_review (submit for review, not a real review)
        card.reviewed_by = None
        card.reviewed_at = None
        card.published_at = None
        card.rejection_reason = None

    elif action == "reject":
        card.reviewed_by = admin_id
        card.reviewed_at = now
        card.rejection_reason = rejection_reason
        card.published_at = None

    elif action == "publish":
        # offline→published or legacy approved→published
        card.published_at = now
        card.reviewed_by = admin_id
        card.reviewed_at = now

    elif action in ("offline", "restore"):
        card.reviewed_by = None
        card.reviewed_at = None
        card.published_at = None

    return new_status


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

    old_status = card.status
    now = utcnow()

    new_status = _apply_formula_action(
        card, data.action, admin.id,
        now=now, rejection_reason=data.rejection_reason,
    )

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
    # Deduplicate IDs
    unique_ids = list(dict.fromkeys(data.card_ids))

    # Pre-validate rejection reason for reject action
    if data.action == "reject":
        trimmed = (data.rejection_reason or "").strip()
        if not trimmed:
            raise HTTPException(status_code=422, detail="Rejection reason required")
        data.rejection_reason = trimmed

    now = utcnow()
    results = []

    for card_id in unique_ids:
        try:
            card = await db.get(FormulaCard, card_id)
            if not card or card.deleted_at:
                results.append({"id": card_id, "status": "not_found"})
                continue

            old_status = card.status
            try:
                new_status = _apply_formula_action(
                    card, data.action, admin.id,
                    now=now, rejection_reason=data.rejection_reason,
                )
            except HTTPException as e:
                if "Cannot transition" in str(e.detail):
                    results.append({"id": card_id, "status": "invalid_transition"})
                elif "Rejection reason required" in str(e.detail):
                    results.append({"id": card_id, "status": "missing_reason"})
                else:
                    results.append({"id": card_id, "status": "error"})
                continue

            await _create_version_snapshot(db, card, data.action, admin.id, data.rejection_reason)
            results.append({"id": card_id, "status": new_status})
        except Exception:
            results.append({"id": card_id, "status": "error"})

    await _log_audit(
        db, admin, request, f"formula.batch-{data.action}",
        "formula_card", None,
        {"card_ids": data.card_ids, "results": results},
    )
    await db.commit()
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


@router.put("/{card_id}/graph-assets/{asset_id}/metadata")
async def update_graph_asset_metadata(
    card_id: int,
    asset_id: int,
    data: GraphAssetUpdate,
    request: Request,
    admin=Depends(require_permissions("formula:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update alt_text and description for a graph asset (no image regeneration)."""
    result = await db.execute(
        select(FormulaGraphAsset).where(
            FormulaGraphAsset.id == asset_id,
            FormulaGraphAsset.formula_card_id == card_id,
        )
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Graph asset not found")

    if data.alt_text is not None:
        asset.alt_text = data.alt_text
    if data.description is not None:
        asset.description = data.description

    await _log_audit(
        db, admin, request, "formula.graph_asset.metadata",
        "formula_graph_asset", str(asset.id),
        detail={"formula_card_id": card_id, "updated_fields": []},
    )

    await db.commit()
    await db.refresh(asset)
    return _graph_asset_to_dict(asset)


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

    if card.card_type == "pure_formula":
        raise HTTPException(
            status_code=422,
            detail="纯公式类型卡片不支持上传图像。如需上传，请将卡片类型改为「自动」或「函数图像」",
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


# ════════════════════════════════════════════════════════════
# Graph Spec Generation
# ════════════════════════════════════════════════════════════


async def _get_card_or_404(db: AsyncSession, card_id: int) -> FormulaCard:
    """Get a non-deleted card or raise 404."""
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == card_id, FormulaCard.deleted_at.is_(None)
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")
    return card


@router.post("/{card_id}/graph/preview")
async def preview_formula_graph(
    card_id: int,
    spec: GraphSpec,
    request: Request,
    admin=Depends(require_permissions("formula:update")),
    db: AsyncSession = Depends(get_db),
):
    """Generate a preview image from a graph_spec.

    Does NOT create an official asset. Sets ``graph_status = \"draft\"``.
    """
    card = await _get_card_or_404(db, card_id)

    if card.card_type == "pure_formula":
        raise HTTPException(
            status_code=422,
            detail="纯公式类型不支持自动生成函数图像",
        )

    try:
        result = await generate_preview(db, card, spec.model_dump(), admin.id)
    except ValueError as e:
        status_code = 422
        if len(e.args) > 1 and e.args[1] == "429":
            status_code = 429
        raise HTTPException(status_code=status_code, detail=str(e.args[0] if e.args else e))

    await _log_audit(
        db, admin, request, "formula.graph.generate",
        "formula_card", str(card_id),
        detail={"template": spec.template},
    )
    await db.commit()
    return result


@router.post("/{card_id}/graph/confirm")
async def confirm_formula_graph(
    card_id: int,
    data: GraphConfirmRequest,
    request: Request,
    admin=Depends(require_permissions("formula:update")),
    db: AsyncSession = Depends(get_db),
):
    """Promote a preview to an official generated asset.

    Requires ``preview_token``, ``card_version`` for optimistic locking.
    Set ``accept_warnings=True`` to bypass quality warnings.
    """
    card = await _get_card_or_404(db, card_id)

    try:
        asset = await confirm_preview(
            db, card,
            preview_token=data.preview_token,
            card_version=data.card_version,
            accept_warnings=data.accept_warnings,
            admin_id=admin.id,
            alt_text=data.alt_text,
            description=data.description,
        )
    except ValueError as e:
        status_code = int(e.args[1]) if len(e.args) > 1 else 422
        raise HTTPException(status_code=status_code, detail=str(e.args[0] if e.args else e))

    audit_action = "formula.graph.confirm.warn_accepted" if data.accept_warnings else "formula.graph.confirm"
    await _log_audit(
        db, admin, request, audit_action,
        "formula_graph_asset", str(asset.id),
        detail={
            "formula_card_id": card_id,
            "checksum": data.checksum,
            "version": data.card_version,
            "accept_warnings": data.accept_warnings,
        },
    )
    await db.commit()
    await db.refresh(asset)
    return {
        "asset": _graph_asset_to_dict(asset),
        "graph_status": "ready",
    }


@router.post("/{card_id}/graph/regenerate")
async def regenerate_formula_graph(
    card_id: int,
    request: Request,
    admin=Depends(require_permissions("formula:update")),
    db: AsyncSession = Depends(get_db),
    spec: GraphSpec | None = None,
):
    """Regenerate and replace the official generated asset.

    Optional ``spec`` body updates the graph_spec before regenerating.
    """
    card = await _get_card_or_404(db, card_id)
    spec_dict = spec.model_dump() if spec else None

    try:
        asset = await regenerate_asset(db, card, spec_dict, admin.id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e.args[0] if e.args else e))

    await _log_audit(
            db, admin, request, "formula.graph.replace",
            "formula_graph_asset", str(asset.id),
            detail={"formula_card_id": card_id},
        )

    await db.commit()
    await db.refresh(asset)
    return {
        "asset": _graph_asset_to_dict(asset),
        "graph_status": "ready",
    }


@router.delete("/{card_id}/graph/generated")
async def delete_generated_graph(
    card_id: int,
    request: Request,
    admin=Depends(require_permissions("formula:update")),
    db: AsyncSession = Depends(get_db),
):
    """Delete only the generated graph asset (preserves manual uploads)."""
    card = await _get_card_or_404(db, card_id)

    deleted = await delete_spec_generated_asset(db, card)
    if not deleted:
        raise HTTPException(status_code=404, detail="No generated asset found")

    await _log_audit(
        db, admin, request, "formula.graph.delete",
        "formula_graph_asset", None,
        detail={"formula_card_id": card_id},
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/graphs/generate-missing")
async def batch_generate_missing_graphs(
    request: Request,
    admin=Depends(require_permissions("formula:update")),
    db: AsyncSession = Depends(get_db),
):
    """Batch-generate graphs for cards with ``graph_status`` in (missing, failed).

    Returns a ``job_id`` for polling. Actual generation runs in background.
    """
    try:
        job_id = await start_batch_generate(db, admin.id)
    except ValueError as e:
        status_code = int(e.args[1]) if len(e.args) > 1 else 422
        raise HTTPException(status_code=status_code, detail=str(e.args[0] if e.args else e))

    await _log_audit(
        db, admin, request, "formula.graph.batch_generate",
        "formula_card", None,
        detail={"job_id": job_id},
    )
    return {"job_id": job_id}


@router.get("/graphs/generate-missing/{job_id}")
async def get_batch_generate_status(
    job_id: str,
    _=Depends(require_permissions("formula:read")),
):
    """Get batch generation job status."""
    job = await get_batch_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return job

