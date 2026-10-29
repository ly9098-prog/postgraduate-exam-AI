"""Public formula-library access responsibilities, with live caller ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User


async def get_random_formula(
    subject_code: str | None,
    chapter_id: int | None,
    category_id: int | None,
    tags: str | None,
    exclude_ids: str | None,
    library_type: str | None,
    study_card_type: str | None,
    exam_scope: str | None,
    current_user: User | None,
    db: AsyncSession,
    *,
    ports,
):
    base_query = build_random_query(
        subject_code,
        chapter_id,
        category_id,
        tags,
        exclude_ids,
        library_type,
        study_card_type,
        exam_scope,
        ports,
    )
    count_q = ports("select")(ports("func").count()).select_from(base_query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0
    if total == 0 and exclude_ids:
        return await ports("get_random_formula")(
            subject_code=subject_code,
            chapter_id=chapter_id,
            category_id=category_id,
            tags=tags if tags else None,
            library_type=library_type,
            study_card_type=study_card_type,
            exam_scope=exam_scope,
            exclude_ids=None,
            current_user=current_user,
            db=db,
        )
    if total == 0:
        raise ports("HTTPException")(status_code=404, detail="No formulas available")
    return await pick_random_card(db, base_query, total, ports)


def build_random_query(
    subject_code,
    chapter_id,
    category_id,
    tags,
    exclude_ids,
    library_type,
    study_card_type,
    exam_scope,
    ports,
):
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
        base_query, subject_code, chapter_id, category_id, tags, None
    )
    if exclude_ids:
        try:
            excluded = [
                ports("int")(x.strip()) for x in exclude_ids.split(",") if x.strip()
            ]
            if excluded:
                base_query = base_query.where(ports("FormulaCard").id.notin_(excluded))
        except ports("ValueError"):
            pass
    return base_query


async def get_formula_detail(
    formula_id: int, exam_scope: str | None, db: AsyncSession, *, ports
):
    query = ports("select")(ports("FormulaCard")).where(
        ports("FormulaCard").id == formula_id,
        ports("FormulaCard").status == "published",
        ports("FormulaCard").deleted_at.is_(None),
    )
    scope_values = ports("_exam_scope_values")(exam_scope)
    if scope_values:
        query = query.where(ports("FormulaCard").exam_scope.in_(scope_values))
    result = await db.execute(query)
    card = result.scalar_one_or_none()
    if not card:
        raise ports("HTTPException")(status_code=404, detail="Formula not found")
    return await ports("_card_to_response")(db, card)


async def add_formula_favorite(
    formula_id: int, current_user: User, db: AsyncSession, *, ports
):
    result = await db.execute(
        ports("select")(ports("FormulaCard")).where(
            ports("FormulaCard").id == formula_id,
            ports("FormulaCard").status == "published",
            ports("FormulaCard").deleted_at.is_(None),
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise ports("HTTPException")(status_code=404, detail="Formula not found")
    existing = await db.execute(
        ports("select")(ports("UserFormulaFavorite")).where(
            ports("UserFormulaFavorite").user_id == current_user.id,
            ports("UserFormulaFavorite").formula_card_id == formula_id,
        )
    )
    if not existing.scalar_one_or_none():
        fav = ports("UserFormulaFavorite")(
            user_id=current_user.id, formula_card_id=formula_id
        )
        db.add(fav)
        await db.commit()
    return {"status": "ok"}


async def remove_formula_favorite(
    formula_id: int, current_user: User, db: AsyncSession, *, ports
):
    result = await db.execute(
        ports("select")(ports("UserFormulaFavorite")).where(
            ports("UserFormulaFavorite").user_id == current_user.id,
            ports("UserFormulaFavorite").formula_card_id == formula_id,
        )
    )
    fav = result.scalar_one_or_none()
    if fav:
        await db.delete(fav)
        await db.commit()
    return {"status": "ok"}


async def pick_random_card(db, base_query, total, ports):
    random_card = (
        base_query.order_by(ports("FormulaCard").id.asc())
        .offset(ports("random").randint(0, total - 1))
        .limit(1)
    )
    result = await db.execute(random_card)
    card = result.scalar_one_or_none()
    if not card:
        raise ports("HTTPException")(status_code=404, detail="No formulas available")
    return await ports("_card_to_response")(db, card)
