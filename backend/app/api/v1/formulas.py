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
    FormulaGraphAsset,
    FormulaGraphSpec,
    FormulaTag,
    UserFormulaFavorite,
)
from app.services.formula_graph_asset_service import (
    choose_effective_graph_asset,
    is_function_graph,
    load_graph_assets_map,
)
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.formula import FormulaCardResponse, FormulaCategoryResponse, FormulaGraphAssetResponse, FormulaTagResponse

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


async def _card_to_response(db: AsyncSession, card: FormulaCard, graph_asset: FormulaGraphAsset | None = None) -> dict:
    """Convert a formula card to the user-facing response dict.

    Args:
        graph_asset: Pre-resolved effective graph asset (pass None for single-card calls).
    """
    tags_result = await db.execute(
        select(FormulaTag)
        .join(FormulaCardTag, FormulaCardTag.tag_id == FormulaTag.id)
        .where(FormulaCardTag.formula_card_id == card.id)
    )
    tags = [
        {"id": t.id, "code": t.code, "name": t.name, "sort_order": t.sort_order}
        for t in tags_result.scalars().all()
    ]

    # Graph asset response (never expose file paths)
    graph_asset_resp = None
    if graph_asset:
        graph_asset_resp = FormulaGraphAssetResponse.model_validate(graph_asset)
    elif card.card_type != "pure_formula":
        # Single-card fallback: load the effective asset (for function_graph or auto)
        from app.services.formula_graph_asset_service import (
            get_effective_graph_asset_for_card,
        )
        effective = await get_effective_graph_asset_for_card(db, card.id)
        if effective:
            graph_asset_resp = FormulaGraphAssetResponse.model_validate(effective)

    # Load multi-graph specs (FormulaGraphSpec)
    specs_result = await db.execute(
        select(FormulaGraphSpec).where(
            FormulaGraphSpec.formula_card_id == card.id
        ).order_by(FormulaGraphSpec.sort_order, FormulaGraphSpec.id)
    )
    graph_specs = [_graph_spec_to_dict(s) for s in specs_result.scalars().all()]

    return {
        "id": card.id,
        "exam_scope": card.exam_scope,
        "category_id": card.category_id,
        "title": card.title,
        "aliases": card.aliases,
        "search_text": card.search_text,
        "card_type": card.card_type,
        "is_function_graph": is_function_graph(card, effective_asset=graph_asset),
        "summary": card.summary,
        "formula_blocks": card.formula_blocks,
        "conditions": card.conditions,
        "symbol_notes": card.symbol_notes,
        "secondary_conclusions": card.secondary_conclusions,
        "error_tips": card.error_tips,
        "examples": card.examples,
        "function_properties": card.function_properties,
        "graph_asset": graph_asset_resp,
        # Flat legacy fields for miniprogram compatibility
        "graph_image_url": graph_asset_resp.image_url if graph_asset_resp else None,
        "graph_thumbnail_url": graph_asset_resp.thumbnail_url if graph_asset_resp else None,
        "sort_order": card.sort_order,
        "status": card.status,
        "tags": tags,
        "published_at": card.published_at,
        "version": card.version,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        # Multi-graph support: stable graph specs with independent assets
        "graph_specs": graph_specs,
    }


def _graph_spec_to_dict(spec: FormulaGraphSpec) -> dict:
    """Convert a FormulaGraphSpec to a dict for API response."""
    d = {
        "slug": spec.slug,
        "title": spec.title,
        "source_ref": spec.source_ref,
        "status": spec.status,
        "sort_order": spec.sort_order,
        "alt_text": spec.alt_text,
        "description": spec.description,
    }
    # Include confirmed asset info if available
    if spec.confirmed_asset_id:
        d["asset_id"] = spec.confirmed_asset_id
    return d


# ── Shared library_type filter ──


def _apply_library_type_filter(query, library_type: str | None):
    """Apply library_type filter to a FormulaCard query.

    Not provided / ``"formula"`` — no filtering (show all published cards).
    ``"function_graph"`` — only cards where ``is_function_graph()`` is true.
    """
    if library_type is None or library_type == "formula":
        return query

    if library_type == "function_graph":
        exists_subq = (
            select(FormulaGraphAsset.id)
            .where(
                FormulaGraphAsset.formula_card_id == FormulaCard.id,
                FormulaGraphAsset.image_url.isnot(None),
            )
        ).exists()
        return query.where(
            or_(
                FormulaCard.card_type == "function_graph",
                and_(
                    ~FormulaCard.card_type.in_(["function_graph", "pure_formula"]),
                    exists_subq,
                ),
            )
        )

    raise HTTPException(
        status_code=400,
        detail=f"无效的 library_type: '{library_type}'，允许的值: formula, function_graph",
    )


# ── Catalog ──

@router.get("/catalog")
async def get_formula_catalog(
    library_type: str | None = Query(None),
    favorite_only: bool = Query(False, alias="favorite_only"),
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the active category tree with available card counts.

    Only includes chapters that have at least one published, non-deleted card
    matching the optional library_type and favorite_only filters.
    """
    categories = await _get_active_categories(db)
    tree = _build_category_tree(categories)

    # Count published + non-deleted cards per category_id
    count_query = (
        select(
            FormulaCard.category_id,
            func.count(FormulaCard.id).label("cnt"),
        )
        .where(
            FormulaCard.status == "published",
            FormulaCard.deleted_at.is_(None),
        )
    )

    if library_type:
        count_query = _apply_library_type_filter(count_query, library_type)

    if favorite_only and current_user:
        fav_subq = (
            select(UserFormulaFavorite.formula_card_id)
            .where(UserFormulaFavorite.user_id == current_user.id)
        )
        count_query = count_query.where(FormulaCard.id.in_(fav_subq))

    count_query = count_query.group_by(FormulaCard.category_id)
    count_result = await db.execute(count_query)
    counts_by_cat = {row[0]: row[1] for row in count_result.all()}

    # Walk the tree: compute total available_count per chapter (lineage → group descendants)
    def _inject_counts(nodes, parent_accumulator=0):
        for node in nodes:
            node_cards = counts_by_cat.get(node["id"], 0)
            if node.get("children"):
                child_accumulator = _inject_counts(node["children"], 0)
                node_cards += child_accumulator
            node["available_count"] = node_cards
            parent_accumulator += node_cards
        return parent_accumulator

    _inject_counts(tree, 0)

    # Prune empty chapters from subject-level children
    for subject in tree:
        if subject.get("children"):
            subject["children"] = [
                ch for ch in subject["children"]
                if ch.get("available_count", 0) > 0
            ]

    return {"items": tree}


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


async def _validate_chapter(db: AsyncSession, chapter_id: int, subject_code: str | None) -> None:
    """Validate that chapter_id is a valid chapter node and belongs to the specified subject."""
    result = await db.execute(
        select(FormulaCategory).where(
            FormulaCategory.id == chapter_id,
            FormulaCategory.is_active == True,
            FormulaCategory.node_type == "chapter",
        )
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(
            status_code=400,
            detail=f"章节 ID {chapter_id} 不存在或不是章节目录",
        )

    # Verify chapter belongs to the specified subject
    if subject_code:
        subject_result = await db.execute(
            select(FormulaCategory).where(
                FormulaCategory.is_active == True,
                FormulaCategory.code == subject_code,
                FormulaCategory.node_type == "subject",
            )
        )
        subject = subject_result.scalar_one_or_none()
        if subject and chapter.parent_id != subject.id:
            raise HTTPException(
                status_code=400,
                detail=f"章节 ID {chapter_id} 不属于学科 {subject_code}",
            )


def _apply_list_filters(query, subject_code, chapter_id, category_id, tags, q):
    """Apply shared formula list filters (subject, chapter, category, tags, search) to a query.

    Used by both /formulas and /formulas/favorites/list.
    """
    if subject_code:
        groups_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.is_active == True,
                FormulaCategory.code == subject_code,
                FormulaCategory.node_type == "subject",
            )
            .cte("list_subject_cte")
        )
        chapters_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.parent_id == groups_subq.c.id,
                FormulaCategory.is_active == True,
            )
            .cte("list_chapters_cte")
        )
        group_ids_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.parent_id == chapters_subq.c.id,
                FormulaCategory.is_active == True,
            )
        )
        query = query.where(FormulaCard.category_id.in_(group_ids_subq))

    if chapter_id:
        group_ids_subq = (
            select(FormulaCategory.id)
            .where(
                FormulaCategory.parent_id == chapter_id,
                FormulaCategory.is_active == True,
            )
        )
        query = query.where(FormulaCard.category_id.in_(group_ids_subq))

    if category_id:
        query = query.where(FormulaCard.category_id == category_id)

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
            query = query.where(FormulaCard.id.in_(matching_card_ids))

    if q:
        like_pattern = f"%{q}%"
        query = query.where(
            or_(
                FormulaCard.title.ilike(like_pattern),
                FormulaCard.search_text.ilike(like_pattern),
            )
        )
    return query


@router.get("")
async def list_formulas(
    subject_code: str | None = Query(None, alias="subject_code"),
    chapter_id: int | None = Query(None, alias="chapter_id"),
    category_id: int | None = Query(None, alias="category_id"),
    tags: str | None = Query(None),
    q: str | None = Query(None),
    favorite_only: bool = Query(False, alias="favorite_only"),
    library_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List published formula cards with filtering."""
    # Validate chapter_id belongs to subject before querying
    if chapter_id is not None:
        await _validate_chapter(db, chapter_id, subject_code)

    base_query = select(FormulaCard).where(
        FormulaCard.status == "published",
        FormulaCard.deleted_at.is_(None),
    )

    base_query = _apply_library_type_filter(base_query, library_type)
    base_query = _apply_list_filters(base_query, subject_code, chapter_id, category_id, tags, q)

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

    # Batch-load graph assets
    card_ids = [c.id for c in cards]
    assets_map = await load_graph_assets_map(db, card_ids)

    items = []
    for card in cards:
        effective = choose_effective_graph_asset(assets_map.get(card.id, []))
        items.append(await _card_to_response(db, card, graph_asset=effective))

    return paginated_response(items, total, page, page_size)


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
    subject_code: str | None = Query(None, alias="subject_code"),
    chapter_id: int | None = Query(None, alias="chapter_id"),
    category_id: int | None = Query(None, alias="category_id"),
    tags: str | None = Query(None),
    q: str | None = Query(None),
    library_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List formulas favorited by the current user.

    Supports the same filters as /formulas but implicitly scoped to favorites.
    """
    fav_q = (
        select(UserFormulaFavorite.formula_card_id)
        .where(UserFormulaFavorite.user_id == current_user.id)
    )

    base_query = select(FormulaCard).where(
        FormulaCard.id.in_(fav_q),
        FormulaCard.status == "published",
        FormulaCard.deleted_at.is_(None),
    )

    base_query = _apply_library_type_filter(base_query, library_type)

    # Reuse shared filter logic via _apply_list_filters
    base_query = _apply_list_filters(base_query, subject_code, chapter_id, category_id, tags, q)

    count_q = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    query = base_query.order_by(FormulaCard.sort_order.asc(), FormulaCard.id.asc())
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    cards = list(result.scalars().all())

    # Batch-load graph assets
    card_ids = [c.id for c in cards]
    assets_map = await load_graph_assets_map(db, card_ids)

    items = []
    for card in cards:
        effective = choose_effective_graph_asset(assets_map.get(card.id, []))
        items.append(await _card_to_response(db, card, graph_asset=effective))

    return paginated_response(items, total, page, page_size)


# ── Random ──

@router.get("/random/next")
async def get_random_formula(
    subject_code: str | None = Query(None, alias="subject_code"),
    chapter_id: int | None = Query(None, alias="chapter_id"),
    category_id: int | None = Query(None, alias="category_id"),
    tags: str | None = Query(None),
    exclude_ids: str | None = Query(None, alias="exclude_ids"),
    library_type: str | None = Query(None),
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

    base_query = _apply_library_type_filter(base_query, library_type)

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
            library_type=library_type,
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
