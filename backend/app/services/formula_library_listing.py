"""Public formula-library listing responsibilities, with live caller ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User


async def list_formulas(
    subject_code: str | None,
    chapter_id: int | None,
    category_id: int | None,
    tags: str | None,
    q: str | None,
    favorite_only: bool,
    library_type: str | None,
    study_card_type: str | None,
    exam_scope: str | None,
    page: int,
    page_size: int,
    current_user: User | None,
    db: AsyncSession,
    *,
    ports,
):
    if chapter_id is not None:
        await ports("_validate_chapter")(db, chapter_id, subject_code)
    base_query = ports("select")(ports("FormulaCard")).where(
        ports("FormulaCard").status == "published",
        ports("FormulaCard").deleted_at.is_(None),
    )
    scope_values = ports("_exam_scope_values")(exam_scope)
    if scope_values:
        base_query = base_query.where(ports("FormulaCard").exam_scope.in_(scope_values))
    base_query = ports("_apply_library_type_filter")(base_query, library_type)
    base_query = ports("_apply_study_card_type_filter")(base_query, study_card_type)
    base_query = ports("_apply_list_filters")(
        base_query, subject_code, chapter_id, category_id, tags, q
    )
    if favorite_only and current_user is None:
        return ports("paginated_response")([], 0, page, page_size)
    if favorite_only and current_user:
        fav_card_ids = ports("select")(
            ports("UserFormulaFavorite").formula_card_id
        ).where(ports("UserFormulaFavorite").user_id == current_user.id)
        base_query = base_query.where(ports("FormulaCard").id.in_(fav_card_ids))
    return await paginate_formula_cards(db, base_query, page, page_size, ports)


async def list_favorite_formulas(
    subject_code: str | None,
    chapter_id: int | None,
    category_id: int | None,
    tags: str | None,
    q: str | None,
    library_type: str | None,
    study_card_type: str | None,
    exam_scope: str | None,
    page: int,
    page_size: int,
    current_user: User,
    db: AsyncSession,
    *,
    ports,
):
    fav_q = ports("select")(ports("UserFormulaFavorite").formula_card_id).where(
        ports("UserFormulaFavorite").user_id == current_user.id
    )
    base_query = ports("select")(ports("FormulaCard")).where(
        ports("FormulaCard").id.in_(fav_q),
        ports("FormulaCard").status == "published",
        ports("FormulaCard").deleted_at.is_(None),
    )
    scope_values = ports("_exam_scope_values")(exam_scope)
    if scope_values:
        base_query = base_query.where(ports("FormulaCard").exam_scope.in_(scope_values))
    base_query = ports("_apply_library_type_filter")(base_query, library_type)
    base_query = ports("_apply_study_card_type_filter")(base_query, study_card_type)
    base_query = ports("_apply_list_filters")(
        base_query, subject_code, chapter_id, category_id, tags, q
    )
    return await paginate_formula_cards(db, base_query, page, page_size, ports)


async def paginate_formula_cards(db, base_query, page, page_size, ports):
    count_q = ports("select")(ports("func").count()).select_from(base_query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0
    offset = (page - 1) * page_size
    query = base_query.order_by(
        ports("FormulaCard").sort_order.asc(), ports("FormulaCard").id.asc()
    )
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    cards = ports("list")(result.scalars().all())
    card_ids = [c.id for c in cards]
    assets_map = await ports("load_graph_assets_map")(db, card_ids)
    tags_map = await ports("_batch_load_tags")(db, card_ids)
    specs_map = await ports("_batch_load_specs")(db, card_ids)
    items = []
    for card in cards:
        effective = ports("choose_effective_graph_asset")(assets_map.get(card.id, []))
        items.append(
            await ports("_card_to_response")(
                db, card, graph_asset=effective, tags_map=tags_map, specs_map=specs_map
            )
        )
    return ports("paginated_response")(items, total, page, page_size)
