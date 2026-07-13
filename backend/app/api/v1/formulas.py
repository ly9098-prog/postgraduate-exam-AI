import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.formula import (
    FormulaCard,
    FormulaCardTag,
    FormulaCategory,
    FormulaTag,
    UserFormulaFavorite,
)
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.formula import FormulaCardResponse, FormulaCategoryResponse, FormulaTagResponse

router = APIRouter(prefix="/api/v1/formulas", tags=["formulas"])


def _build_category_tree(categories: list[FormulaCategory]) -> list[dict]:
    """Build nested category tree from flat list."""
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
            "children": [],
        }
    roots = []
    for cat_id, cat_dict in cat_map.items():
        parent_id = cat_dict["parent_id"]
        if parent_id is None:
            roots.append(cat_dict)
        elif parent_id in cat_map:
            cat_map[parent_id]["children"].append(cat_dict)
    # Sort children at each level
    def _sort_tree(nodes):
        nodes.sort(key=lambda n: n["sort_order"])
        for node in nodes:
            _sort_tree(node["children"])
        return nodes
    return _sort_tree(roots)


async def _get_active_categories(db: AsyncSession) -> list[FormulaCategory]:
    result = await db.execute(
        select(FormulaCategory)
        .where(FormulaCategory.is_active == True)
        .order_by(FormulaCategory.sort_order.asc())
    )
    return list(result.scalars().all())


async def _card_to_response(db: AsyncSession, card: FormulaCard) -> dict:
    """Convert a formula card to the user-facing response dict."""
    tags_result = await db.execute(
        select(FormulaTag)
        .join(FormulaCardTag, FormulaCardTag.tag_id == FormulaTag.id)
        .where(FormulaCardTag.formula_card_id == card.id)
    )
    tags = [
        {"id": t.id, "code": t.code, "name": t.name, "sort_order": t.sort_order}
        for t in tags_result.scalars().all()
    ]

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
        "published_at": card.published_at,
        "version": card.version,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    }


# ── Catalog ──

@router.get("/catalog")
async def get_formula_catalog(
    db: AsyncSession = Depends(get_db),
):
    """Get the active category tree."""
    categories = await _get_active_categories(db)
    return {"items": _build_category_tree(categories)}


# ── Tags ──

@router.get("/tags")
async def get_formula_tags(
    db: AsyncSession = Depends(get_db),
):
    """Get available fixed tags."""
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


# ── List ──

@router.get("")
async def list_formulas(
    subject_code: str | None = Query(None, alias="subject_code"),
    chapter_id: int | None = Query(None, alias="chapter_id"),
    category_id: int | None = Query(None, alias="category_id"),
    tags: str | None = Query(None),
    q: str | None = Query(None),
    favorite_only: bool = Query(False, alias="favorite_only"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List published formula cards with filtering."""
    base_query = select(FormulaCard).where(
        FormulaCard.status == "published",
        FormulaCard.deleted_at.is_(None),
    )

    # Category filtering: find group-level IDs first
    if subject_code:
        groups_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.is_active == True,
                FormulaCategory.code == subject_code,
                FormulaCategory.node_type == "subject",
            )
            .cte("subject_cte")
        )
        chapters_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.parent_id == groups_subq.c.id,
                FormulaCategory.is_active == True,
            )
            .cte("chapters_cte")
        )
        group_ids_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.parent_id == chapters_subq.c.id,
                FormulaCategory.is_active == True,
            )
        )
        base_query = base_query.where(FormulaCard.category_id.in_(group_ids_subq))

    if chapter_id:
        group_ids_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.parent_id == chapter_id,
                FormulaCategory.is_active == True,
            )
        )
        base_query = base_query.where(FormulaCard.category_id.in_(group_ids_subq))

    if category_id:
        base_query = base_query.where(FormulaCard.category_id == category_id)

    # Tag filtering
    if tags:
        tag_codes = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_codes:
            matching_card_ids = (
                select(FormulaCardTag.formula_card_id)
                .join(FormulaTag, FormulaCardTag.tag_id == FormulaTag.id)
                .where(FormulaTag.code.in_(tag_codes))
                .group_by(FormulaCardTag.formula_card_id)
                .having(func.count(FormulaCardTag.formula_card_id) == len(tag_codes))
            )
            base_query = base_query.where(FormulaCard.id.in_(matching_card_ids))

    # Search: only match title and aliases (search_text)
    if q:
        like_pattern = f"%{q}%"
        base_query = base_query.where(
            or_(
                FormulaCard.title.ilike(like_pattern),
                FormulaCard.search_text.ilike(like_pattern),
            )
        )

    # Favorite only
    if favorite_only and current_user:
        fav_card_ids = (
            select(UserFormulaFavorite.formula_card_id)
            .where(UserFormulaFavorite.user_id == current_user.id)
        )
        base_query = base_query.where(FormulaCard.id.in_(fav_card_ids))

    # Count
    count_q = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Pagination
    offset = (page - 1) * page_size
    query = base_query.order_by(FormulaCard.sort_order.asc(), FormulaCard.id.asc())
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    cards = list(result.scalars().all())

    items = []
    for card in cards:
        items.append(await _card_to_response(db, card))

    return paginated_response(items, total, page, page_size)


# ── Detail ──

@router.get("/{formula_id}")
async def get_formula_detail(
    formula_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single published formula card."""
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == formula_id,
            FormulaCard.status == "published",
            FormulaCard.deleted_at.is_(None),
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    return await _card_to_response(db, card)


# ── Favorites ──

@router.get("/favorites/list")
async def list_favorite_formulas(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List formulas favorited by the current user."""
    fav_q = (
        select(UserFormulaFavorite.formula_card_id)
        .where(UserFormulaFavorite.user_id == current_user.id)
    )

    base_query = select(FormulaCard).where(
        FormulaCard.id.in_(fav_q),
        FormulaCard.status == "published",
        FormulaCard.deleted_at.is_(None),
    )

    count_q = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    query = base_query.order_by(FormulaCard.sort_order.asc(), FormulaCard.id.asc())
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    cards = list(result.scalars().all())

    items = []
    for card in cards:
        items.append(await _card_to_response(db, card))

    return paginated_response(items, total, page, page_size)


# ── Random ──

@router.get("/random/next")
async def get_random_formula(
    subject_code: str | None = Query(None, alias="subject_code"),
    chapter_id: int | None = Query(None, alias="chapter_id"),
    category_id: int | None = Query(None, alias="category_id"),
    tags: str | None = Query(None),
    exclude_ids: str | None = Query(None, alias="exclude_ids"),
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a random published formula card with optional filters.

    When the candidate pool is exhausted, clear exclude_ids and retry once.
    """
    base_query = select(FormulaCard).where(
        FormulaCard.status == "published",
        FormulaCard.deleted_at.is_(None),
    )

    # Apply same filters as list
    if subject_code:
        groups_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.is_active == True,
                FormulaCategory.code == subject_code,
                FormulaCategory.node_type == "subject",
            )
            .cte("random_subject_cte")
        )
        chapters_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.parent_id == groups_subq.c.id,
                FormulaCategory.is_active == True,
            )
            .cte("random_chapters_cte")
        )
        group_ids_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.parent_id == chapters_subq.c.id,
                FormulaCategory.is_active == True,
            )
        )
        base_query = base_query.where(FormulaCard.category_id.in_(group_ids_subq))

    if chapter_id:
        group_ids_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.parent_id == chapter_id,
                FormulaCategory.is_active == True,
            )
        )
        base_query = base_query.where(FormulaCard.category_id.in_(group_ids_subq))

    if category_id:
        base_query = base_query.where(FormulaCard.category_id == category_id)

    if tags:
        tag_codes = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_codes:
            matching_card_ids = (
                select(FormulaCardTag.formula_card_id)
                .join(FormulaTag, FormulaCardTag.tag_id == FormulaTag.id)
                .where(FormulaTag.code.in_(tag_codes))
                .group_by(FormulaCardTag.formula_card_id)
                .having(func.count(FormulaCardTag.formula_card_id) == len(tag_codes))
            )
            base_query = base_query.where(FormulaCard.id.in_(matching_card_ids))

    # Exclude IDs (parse comma-separated string)
    if exclude_ids:
        try:
            excluded = [int(x.strip()) for x in exclude_ids.split(",") if x.strip()]
            if excluded:
                base_query = base_query.where(FormulaCard.id.notin_(excluded))
        except ValueError:
            pass

    count_q = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    if total == 0 and exclude_ids:
        # Retry once without exclude_ids
        return await get_random_formula(
            subject_code=subject_code,
            chapter_id=chapter_id,
            category_id=category_id,
            tags=tags if tags else None,
            exclude_ids=None,
            current_user=current_user,
            db=db,
        )

    if total == 0:
        raise HTTPException(status_code=404, detail="No formulas available")

    random_card = (
        base_query.order_by(func.random()).limit(1)
    )
    result = await db.execute(random_card)
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="No formulas available")

    return await _card_to_response(db, card)


# ── Favorite Toggle ──

@router.put("/{formula_id}/favorite")
async def add_formula_favorite(
    formula_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a formula to favorites (idempotent)."""
    # Verify card exists and is published
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.id == formula_id,
            FormulaCard.status == "published",
            FormulaCard.deleted_at.is_(None),
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Formula not found")

    # Check if already favorited
    existing = await db.execute(
        select(UserFormulaFavorite).where(
            UserFormulaFavorite.user_id == current_user.id,
            UserFormulaFavorite.formula_card_id == formula_id,
        )
    )
    if not existing.scalar_one_or_none():
        fav = UserFormulaFavorite(
            user_id=current_user.id, formula_card_id=formula_id
        )
        db.add(fav)
        await db.commit()

    return {"status": "ok"}


@router.delete("/{formula_id}/favorite")
async def remove_formula_favorite(
    formula_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a formula from favorites (idempotent)."""
    result = await db.execute(
        select(UserFormulaFavorite).where(
            UserFormulaFavorite.user_id == current_user.id,
            UserFormulaFavorite.formula_card_id == formula_id,
        )
    )
    fav = result.scalar_one_or_none()
    if fav:
        await db.delete(fav)
        await db.commit()

    return {"status": "ok"}
