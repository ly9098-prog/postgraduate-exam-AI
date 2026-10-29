"""Public formula-library catalog responsibilities, with live caller ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.formula import (
        FormulaCategory,
    )
    from app.models.user import User


def _build_category_tree(categories: list[FormulaCategory], *, ports) -> list[dict]:
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

    def _sort_tree(nodes):
        nodes.sort(key=lambda n: n["sort_order"])
        for node in nodes:
            _sort_tree(node["children"])
        return nodes

    return _sort_tree(roots)


async def _get_active_categories(
    db: AsyncSession, exam_scope: str | None, subject_code: str | None, *, ports
) -> list[FormulaCategory]:
    query = ports("select")(ports("FormulaCategory")).where(
        ports("FormulaCategory").is_active
    )
    scope_values = ports("_exam_scope_values")(exam_scope)
    if scope_values:
        query = query.where(ports("FormulaCategory").exam_scope.in_(scope_values))
    category_ids = ports("formula_catalog_category_ids")(subject_code)
    if category_ids is not None:
        query = query.where(ports("FormulaCategory").id.in_(category_ids))
    result = await db.execute(
        query.order_by(
            ports("FormulaCategory").sort_order.asc(), ports("FormulaCategory").id.asc()
        )
    )
    return ports("list")(result.scalars().all())


async def get_formula_catalog(
    subject_code: str | None,
    library_type: str | None,
    study_card_type: str | None,
    favorite_only: bool,
    exam_scope: str | None,
    current_user: User | None,
    db: AsyncSession,
    *,
    ports,
):
    categories = await ports("_get_active_categories")(db, exam_scope, subject_code)
    tree = ports("_build_category_tree")(categories)
    count_query = ports("select")(
        ports("FormulaCard").category_id,
        ports("func").count(ports("FormulaCard").id).label("cnt"),
    ).where(
        ports("FormulaCard").status == "published",
        ports("FormulaCard").deleted_at.is_(None),
    )
    scope_values = ports("_exam_scope_values")(exam_scope)
    if scope_values:
        count_query = count_query.where(
            ports("FormulaCard").exam_scope.in_(scope_values)
        )
    if library_type:
        count_query = ports("_apply_library_type_filter")(count_query, library_type)
    count_query = ports("_apply_study_card_type_filter")(count_query, study_card_type)
    count_query = ports("apply_formula_subject_filter")(count_query, subject_code)
    if favorite_only and current_user:
        fav_subq = ports("select")(ports("UserFormulaFavorite").formula_card_id).where(
            ports("UserFormulaFavorite").user_id == current_user.id
        )
        count_query = count_query.where(ports("FormulaCard").id.in_(fav_subq))
    count_query = count_query.group_by(ports("FormulaCard").category_id)
    count_result = await db.execute(count_query)
    counts_by_cat = {row[0]: row[1] for row in count_result.all()}
    inject_catalog_counts(tree, counts_by_cat, 0, ports)
    for subject in tree:
        if subject.get("children"):
            subject["children"] = [
                ch for ch in subject["children"] if ch.get("available_count", 0) > 0
            ]
    return {"items": ports("collapse_formula_catalog_subjects")(tree, subject_code)}


def inject_catalog_counts(nodes, counts_by_cat, parent_accumulator, ports):
    for node in nodes:
        node_cards = counts_by_cat.get(node["id"], 0)
        if node.get("children"):
            child_accumulator = inject_catalog_counts(
                node["children"], counts_by_cat, 0, ports
            )
            node_cards += child_accumulator
        node["available_count"] = node_cards
        parent_accumulator += node_cards
    return parent_accumulator


async def get_formula_tags(db: AsyncSession, *, ports):
    result = await db.execute(
        ports("select")(ports("FormulaTag")).order_by(
            ports("FormulaTag").sort_order.asc()
        )
    )
    tags = result.scalars().all()
    return {
        "items": [
            {"id": t.id, "code": t.code, "name": t.name, "sort_order": t.sort_order}
            for t in tags
        ]
    }
