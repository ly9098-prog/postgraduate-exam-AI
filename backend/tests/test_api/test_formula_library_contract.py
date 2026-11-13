"""Compatibility contracts for the complete mini-program formula API chain."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.v1 import formulas as api
from app.core.database import get_db
from app.models import formula as models
from tests.test_api.test_formulas import _card, _category, _Db


def sql(statement):
    return str(
        statement.compile(
            dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def params(db, **changes):
    value = dict(
        subject_code=None,
        chapter_id=None,
        category_id=None,
        tags=None,
        q=None,
        favorite_only=False,
        library_type=None,
        study_card_type=None,
        exam_scope=None,
        page=1,
        page_size=20,
        current_user=None,
        db=db,
    )
    value.update(changes)
    return value


def random_params(db, **changes):
    value = params(db, **changes)
    for key in ("q", "favorite_only", "page", "page_size"):
        value.pop(key)
    value.setdefault("exclude_ids", None)
    return value


@pytest_asyncio.fixture
async def populated_formula_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            for model in (
                models.FormulaCategory, models.FormulaCard, models.FormulaTag,
                models.FormulaCardTag, models.UserFormulaFavorite,
                models.FormulaGraphSpec, models.FormulaGraphAsset,
            ):
                await connection.run_sync(model.__table__.create)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            db.add(_category())
            db.add_all([_card(), _card(id=2, content_hash="second")])
            db.add_all([
                models.UserFormulaFavorite(user_id=1, formula_card_id=1),
                models.UserFormulaFavorite(user_id=2, formula_card_id=2),
            ])
            await db.commit()
            yield db
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_anonymous_favorite_filter_returns_empty_list_with_public_content(
    populated_formula_db,
):
    ordinary = await api.list_formulas(**params(populated_formula_db))
    assert [item["id"] for item in ordinary["items"]] == [1, 2]
    first_page = await api.list_formulas(
        **params(populated_formula_db, favorite_only=True)
    )
    assert first_page["items"] == []
    assert first_page["total"] == 0
    favorites = await api.list_formulas(
        **params(populated_formula_db, favorite_only=True, page=3, page_size=7)
    )
    assert favorites == {
        "items": [], "total": 0, "page": 3, "page_size": 7, "total_pages": 0,
    }


@pytest.mark.asyncio
async def test_anonymous_favorite_filter_returns_empty_catalog_with_public_content(
    populated_formula_db,
):
    options = dict(
        subject_code=None, library_type=None, study_card_type=None, exam_scope=None,
        current_user=None, db=populated_formula_db,
    )
    ordinary = await api.get_formula_catalog(favorite_only=False, **options)
    assert ordinary["items"][0]["available_count"] == 2
    assert await api.get_formula_catalog(favorite_only=True, **options) == {"items": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [1, 2])
async def test_authenticated_favorites_remain_scoped_to_the_current_user(
    populated_formula_db, user_id,
):
    user = NS(id=user_id)
    favorites = await api.list_formulas(
        **params(populated_formula_db, favorite_only=True, current_user=user)
    )
    assert [item["id"] for item in favorites["items"]] == [user_id]
    catalog = await api.get_formula_catalog(
        subject_code=None, library_type=None, study_card_type=None, exam_scope=None,
        current_user=user, db=populated_formula_db, favorite_only=True,
    )
    assert catalog["items"][0]["available_count"] == 1


@pytest.mark.asyncio
async def test_anonymous_favorite_http_reads_with_populated_public_content(
    populated_formula_db,
):
    application = FastAPI()
    application.include_router(api.router)
    application.dependency_overrides[get_db] = lambda: populated_formula_db
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test",
    ) as client:
        ordinary = await client.get("/api/v1/formulas")
        assert ordinary.status_code == 200
        assert [item["id"] for item in ordinary.json()["items"]] == [1, 2]
        filtered = await client.get("/api/v1/formulas?favorite_only=true")
        assert filtered.status_code == 200
        assert filtered.json() == {
            "items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 0,
        }
        catalog = await client.get("/api/v1/formulas/catalog?favorite_only=true")
        assert catalog.status_code == 200
        assert catalog.json() == {"items": []}
        protected = await client.get("/api/v1/formulas/favorites/list")
        # FastAPI's HTTPBearer rejects missing credentials with 401.
        assert protected.status_code == 401


@pytest.mark.parametrize(
    "scope,expected",
    [
        (None, None),
        ("  ", None),
        (" EXAM408 ", ("exam408",)),
        ("408", ("408",)),
        ("Math2", ("math2",)),
    ],
)
def test_scope_is_strict_and_normalized(scope, expected):
    assert api._exam_scope_values(scope) == expected


def test_category_tree_keeps_duplicate_position_and_omits_orphans():
    categories = [
        _category(id=1, sort_order=8),
        _category(id=2, parent_id=1, sort_order=2),
        _category(id=3, parent_id=1, sort_order=2),
        _category(id=4, parent_id=99),
        _category(id=1, sort_order=1),
    ]
    tree = api._build_category_tree(categories)
    assert len(tree) == 1 and tree[0]["sort_order"] == 1
    assert [n["id"] for n in tree[0]["children"]] == [2, 3]


@pytest.mark.parametrize("value", ["", "bogus"])
def test_invalid_library_type_preserves_http_error(value):
    with pytest.raises(HTTPException) as caught:
        api._apply_library_type_filter(select(api.FormulaCard), value)
    assert caught.value.status_code == 400
    assert (
        caught.value.detail
        == f"无效的 library_type: '{value}'，允许的值: formula, function_graph"
    )


@pytest.mark.asyncio
async def test_list_chapter_validation_precedes_filter_errors(monkeypatch):
    error = HTTPException(400, "chapter-first")
    validator = AsyncMock(side_effect=error)
    monkeypatch.setattr(api, "_validate_chapter", validator)
    with pytest.raises(HTTPException) as caught:
        await api.list_formulas(**params(_Db(), chapter_id=7, library_type="invalid"))
    assert caught.value is error
    validator.assert_awaited_once()


@pytest.mark.asyncio
async def test_favorites_and_random_keep_no_extra_chapter_validation(monkeypatch):
    monkeypatch.setattr(
        api, "_validate_chapter", AsyncMock(side_effect=AssertionError("extra"))
    )
    favorite = params(_Db([0], []), current_user=NS(id=4), chapter_id=7)
    favorite.pop("favorite_only")
    assert (await api.list_favorite_formulas(**favorite))["items"] == []
    with pytest.raises(HTTPException) as caught:
        await api.get_random_formula(**random_params(_Db([0]), chapter_id=7))
    assert caught.value.detail == "No formulas available"


@pytest.mark.asyncio
async def test_list_query_and_live_batch_projection_order(monkeypatch):
    db = _Db([2], [_card(id=3), _card(id=4)])
    trace = []
    execute = db.execute

    async def execute_query(statement):
        trace.append(("sql", sql(statement)))
        return await execute(statement)

    async def load_specs(db_arg, ids):
        trace.append(("specs", ids))
        return {3: [], 4: []}

    async def load_tags(db_arg, ids):
        trace.append(("tags", ids))
        monkeypatch.setattr(api, "_batch_load_specs", load_specs)
        return {3: [], 4: []}

    async def load_assets(db_arg, ids):
        assert db_arg is db
        trace.append(("assets", ids))
        monkeypatch.setattr(api, "_batch_load_tags", load_tags)
        return {}

    async def project(db_arg, card, **kwargs):
        trace.append(("card", card.id, kwargs))
        return {"id": card.id}

    db.execute = execute_query
    monkeypatch.setattr(api, "load_graph_assets_map", load_assets)
    monkeypatch.setattr(api, "_card_to_response", project)
    result = await api.list_formulas(**params(db, page=2, page_size=2))
    assert [event[0] for event in trace] == [
        "sql",
        "sql",
        "assets",
        "tags",
        "specs",
        "card",
        "card",
    ]
    assert "ORDER BY formula_cards.sort_order ASC, formula_cards.id ASC" in trace[1][1]
    assert "LIMIT 2 OFFSET 2" in trace[1][1]
    assert result["items"] == [{"id": 3}, {"id": 4}]
    assert trace[-1][2]["tags_map"] is trace[-2][2]["tags_map"]
    assert trace[-1][2]["specs_map"] is trace[-2][2]["specs_map"]
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_random_exhaustion_calls_current_route_once_and_clears_exclusions(
    monkeypatch,
):
    db = _Db([0])
    original = api.get_random_formula
    replacement = AsyncMock(return_value={"retry": True})
    execute = db.execute

    async def count(statement):
        monkeypatch.setattr(api, "get_random_formula", replacement)
        return await execute(statement)

    db.execute = count
    user = NS(id=9)
    result = await original(
        **random_params(db, exclude_ids="1,2", tags="", current_user=user)
    )
    assert result == {"retry": True}
    kwargs = replacement.await_args.kwargs
    assert kwargs["db"] is db and kwargs["current_user"] is user
    assert kwargs["exclude_ids"] is None and kwargs["tags"] is None
    replacement.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("excluded,has_filter", [("1,2", True), ("1,bad", False)])
async def test_random_exclusion_parse_remains_all_or_nothing(
    monkeypatch, excluded, has_filter
):
    seen = []
    db = _Db([0])
    execute = db.execute

    async def count(statement):
        seen.append(sql(statement))
        return await execute(statement)

    db.execute = count
    original = api.get_random_formula
    monkeypatch.setattr(api, "get_random_formula", AsyncMock(return_value={}))
    await original(**random_params(db, exclude_ids=excluded))
    assert ("NOT IN" in seen[0]) is has_filter


@pytest.mark.asyncio
async def test_card_maps_empty_lists_avoid_queries_and_keep_references(monkeypatch):
    card = _card()
    tags, specs = [], []
    db = _Db()
    db.execute = AsyncMock(side_effect=AssertionError("unexpected query"))
    result = await api._card_to_response(
        db, card, tags_map={1: tags}, specs_map={1: specs}
    )
    assert result["tags"] is tags and result["graph_specs"] is specs
    assert result["formula_blocks"] is card.formula_blocks
    assert (
        result["study_card_type"] == "formula" and result["template_type"] == "standard"
    )
    assert result["graph_asset"] is None


@pytest.mark.asyncio
async def test_graph_fallback_keeps_original_effective_argument(monkeypatch):
    from app.services import formula_graph_asset_service as assets

    card = _card(card_type="mixed")
    graph = NS(image_url="i", thumbnail_url="t", original_svg_url="s")
    monkeypatch.setattr(
        assets, "get_effective_graph_asset_for_card", AsyncMock(return_value=graph)
    )
    monkeypatch.setattr(
        api, "FormulaGraphAssetResponse", NS(model_validate=lambda value: value)
    )
    monkeypatch.setattr(
        api, "resolve_graph_asset_public_url", lambda value: "public:" + value
    )
    calls = []
    monkeypatch.setattr(
        api, "is_function_graph", lambda value, **kw: calls.append((value, kw)) or True
    )
    result = await api._card_to_response(
        _Db(), card, tags_map={1: []}, specs_map={1: []}
    )
    assert result["graph_asset"] is graph
    assert result["graph_image_url"] == "public:i"
    assert calls == [(card, {"effective_asset": None})]


@pytest.mark.asyncio
async def test_graph_url_error_keeps_partial_mutation_and_propagates(monkeypatch):
    graph = NS(image_url="i", thumbnail_url="t", original_svg_url="s")
    error = ValueError("url")
    monkeypatch.setattr(
        api, "FormulaGraphAssetResponse", NS(model_validate=lambda value: value)
    )

    def resolve(value):
        if value == "t":
            raise error
        return "public:" + value

    monkeypatch.setattr(api, "resolve_graph_asset_public_url", resolve)
    with pytest.raises(ValueError) as caught:
        await api._card_to_response(
            _Db(), _card(), graph, tags_map={1: []}, specs_map={1: []}
        )
    assert caught.value is error
    assert (graph.image_url, graph.thumbnail_url, graph.original_svg_url) == (
        "public:i",
        "t",
        "s",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,existing",
    [("add", False), ("add", True), ("remove", False), ("remove", True)],
)
async def test_favorites_preserve_idempotent_transaction_boundary(operation, existing):
    favorite = NS(id=8) if existing else None
    db = _Db([_card()], [favorite]) if operation == "add" else _Db([favorite])
    if operation == "add":
        assert await api.add_formula_favorite(1, NS(id=3), db) == {"status": "ok"}
        assert db.add.call_count == (0 if existing else 1)
    else:
        assert await api.remove_formula_favorite(1, NS(id=3), db) == {"status": "ok"}
        assert db.delete.await_count == (1 if existing else 0)
    assert db.commit.await_count == int((operation == "add") != existing)
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("commit"), asyncio.CancelledError()])
async def test_favorite_commit_failure_does_not_add_rollback(monkeypatch, error):
    db = _Db([_card()], [])
    db.commit.side_effect = error
    with pytest.raises(type(error)) as caught:
        await api.add_formula_favorite(1, NS(id=3), db)
    assert caught.value is error
    db.add.assert_called_once()
    db.rollback.assert_not_awaited()


def test_public_openapi_keeps_operations_descriptions_and_authentication():
    from fastapi import FastAPI

    application = FastAPI()
    application.include_router(api.router)
    paths = application.openapi()["paths"]
    base = "/api/v1/formulas"
    assert {
        path.removeprefix(base): set(operations) for path, operations in paths.items()
    } == {
        "/catalog": {"get"},
        "/card-types": {"get"},
        "/tags": {"get"},
        "": {"get"},
        "/{formula_id}": {"get"},
        "/favorites/list": {"get"},
        "/random/next": {"get"},
        "/{formula_id}/favorite": {"put", "delete"},
    }
    assert (
        paths[base]["get"]["description"]
        == "List published formula cards with filtering."
    )
    assert paths[base + "/random/next"]["get"]["description"] == (
        "Get a random published formula card with optional filters.\n\n"
        "When the candidate pool is exhausted, clear exclude_ids and retry once."
    )
    for suffix in ("/catalog", "", "/favorites/list", "/random/next"):
        assert paths[base + suffix]["get"]["security"]
    for suffix in ("/tags", "/card-types", "/{formula_id}"):
        assert "security" not in paths[base + suffix]["get"]


def test_public_openapi_keeps_distinct_page_limits_and_filter_aliases():
    from fastapi import FastAPI

    application = FastAPI()
    application.include_router(api.router)
    paths = application.openapi()["paths"]
    for suffix, maximum in (("", 100), ("/favorites/list", 200)):
        parameters = {
            p["name"]: p
            for p in paths["/api/v1/formulas" + suffix]["get"]["parameters"]
        }
        assert parameters["page_size"]["schema"]["maximum"] == maximum
        assert parameters["page_size"]["schema"]["minimum"] == 1
        assert parameters["page"]["schema"]["minimum"] == 1
        assert {
            "subject_code",
            "chapter_id",
            "category_id",
            "study_card_type",
            "exam_scope",
        } <= parameters.keys()
