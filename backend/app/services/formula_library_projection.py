"""Public formula-library projection responsibilities, with live caller ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.formula import FormulaCard, FormulaGraphAsset, FormulaGraphSpec


async def _card_to_response(
    db: AsyncSession,
    card: FormulaCard,
    graph_asset: FormulaGraphAsset | None,
    *,
    tags_map: dict[int, list[dict]] | None,
    specs_map: dict[int, list[dict]] | None,
    ports,
) -> dict:
    tags = await load_card_tags(db, card, tags_map, ports)
    graph_asset_resp = await load_card_graph_asset(db, card, graph_asset, ports)
    graph_specs = await load_card_specs(db, card, specs_map, ports)
    return {
        **project_core_fields(card, graph_asset, graph_asset_resp, ports),
        **project_related_fields(card, graph_asset_resp, tags, graph_specs, ports),
    }


async def load_card_tags(db, card, tags_map, ports):
    tags = (tags_map or {}).get(card.id)
    if tags is None:
        tags_result = await db.execute(
            ports("select")(ports("FormulaTag"))
            .join(
                ports("FormulaCardTag"),
                ports("FormulaCardTag").tag_id == ports("FormulaTag").id,
            )
            .where(ports("FormulaCardTag").formula_card_id == card.id)
        )
        tags = [
            {"id": t.id, "code": t.code, "name": t.name, "sort_order": t.sort_order}
            for t in tags_result.scalars().all()
        ]
    return tags


async def load_card_graph_asset(db, card, graph_asset, ports):
    graph_asset_resp = None
    if graph_asset:
        graph_asset_resp = ports("FormulaGraphAssetResponse").model_validate(
            graph_asset
        )
    elif card.card_type != "pure_formula":
        from app.services.formula_graph_asset_service import (
            get_effective_graph_asset_for_card,
        )

        effective = await get_effective_graph_asset_for_card(db, card.id)
        if effective:
            graph_asset_resp = ports("FormulaGraphAssetResponse").model_validate(
                effective
            )
    if graph_asset_resp:
        graph_asset_resp.image_url = ports("resolve_graph_asset_public_url")(
            graph_asset_resp.image_url
        )
        graph_asset_resp.thumbnail_url = ports("resolve_graph_asset_public_url")(
            graph_asset_resp.thumbnail_url
        )
        graph_asset_resp.original_svg_url = ports("resolve_graph_asset_public_url")(
            graph_asset_resp.original_svg_url
        )
    return graph_asset_resp


async def load_card_specs(db, card, specs_map, ports):
    graph_specs = (specs_map or {}).get(card.id)
    if graph_specs is None:
        specs_result = await db.execute(
            ports("select")(ports("FormulaGraphSpec"))
            .where(ports("FormulaGraphSpec").formula_card_id == card.id)
            .order_by(
                ports("FormulaGraphSpec").sort_order, ports("FormulaGraphSpec").id
            )
        )
        graph_specs = [
            ports("_graph_spec_to_dict")(s) for s in specs_result.scalars().all()
        ]
    return graph_specs


def project_core_fields(card, graph_asset, graph_asset_resp, ports):
    return {
        "id": card.id,
        "exam_scope": card.exam_scope,
        "category_id": card.category_id,
        "title": card.title,
        "aliases": card.aliases,
        "search_text": card.search_text,
        "card_type": card.card_type,
        "study_card_type": card.study_card_type or "formula",
        "template_type": card.template_type or "standard",
        "is_function_graph": ports("is_function_graph")(
            card, effective_asset=graph_asset
        ),
        "summary": card.summary,
        "formula_blocks": card.formula_blocks,
        "conditions": card.conditions,
        "symbol_notes": card.symbol_notes,
        "secondary_conclusions": card.secondary_conclusions,
        "error_tips": card.error_tips,
        "examples": card.examples,
        "function_properties": card.function_properties,
        "graph_asset": graph_asset_resp,
        "graph_image_url": graph_asset_resp.image_url if graph_asset_resp else None,
    }


def project_related_fields(card, graph_asset_resp, tags, graph_specs, ports):
    return {
        "graph_thumbnail_url": graph_asset_resp.thumbnail_url
        if graph_asset_resp
        else None,
        "sort_order": card.sort_order,
        "status": card.status,
        "tags": tags,
        "published_at": ports("serialize_utc_datetime")(card.published_at)
        if card.published_at
        else None,
        "version": card.version,
        "created_at": ports("serialize_utc_datetime")(card.created_at)
        if card.created_at
        else None,
        "updated_at": ports("serialize_utc_datetime")(card.updated_at)
        if card.updated_at
        else None,
        "graph_specs": graph_specs,
    }


def _graph_spec_to_dict(spec: FormulaGraphSpec, *, ports) -> dict:
    d = {
        "slug": spec.slug,
        "title": spec.title,
        "source_ref": spec.source_ref,
        "status": spec.status,
        "sort_order": spec.sort_order,
        "alt_text": spec.alt_text,
        "description": spec.description,
    }
    if spec.confirmed_asset_id:
        d["asset_id"] = spec.confirmed_asset_id
    return d


async def _batch_load_tags(
    db: AsyncSession, card_ids: list[int], *, ports
) -> dict[int, list[dict]]:
    if not card_ids:
        return {}
    result = await db.execute(
        ports("select")(
            ports("FormulaCardTag").formula_card_id,
            ports("FormulaTag").id,
            ports("FormulaTag").code,
            ports("FormulaTag").name,
            ports("FormulaTag").sort_order,
        )
        .join(
            ports("FormulaTag"),
            ports("FormulaCardTag").tag_id == ports("FormulaTag").id,
        )
        .where(ports("FormulaCardTag").formula_card_id.in_(card_ids))
    )
    tags_by_card: dict[int, list[dict]] = {}
    for row in result.all():
        cid = row.formula_card_id
        if cid not in tags_by_card:
            tags_by_card[cid] = []
        tags_by_card[cid].append(
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "sort_order": row.sort_order,
            }
        )
    return tags_by_card


async def _batch_load_specs(
    db: AsyncSession, card_ids: list[int], *, ports
) -> dict[int, list[dict]]:
    if not card_ids:
        return {}
    result = await db.execute(
        ports("select")(ports("FormulaGraphSpec"))
        .where(ports("FormulaGraphSpec").formula_card_id.in_(card_ids))
        .order_by(ports("FormulaGraphSpec").sort_order, ports("FormulaGraphSpec").id)
    )
    specs_by_card: dict[int, list[dict]] = {}
    for spec in result.scalars().all():
        cid = spec.formula_card_id
        if cid not in specs_by_card:
            specs_by_card[cid] = []
        specs_by_card[cid].append(ports("_graph_spec_to_dict")(spec))
    return specs_by_card
