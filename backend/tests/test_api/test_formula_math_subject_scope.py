"""Integration coverage for the logical ``math`` formula subject scope."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.formulas import (
    _validate_chapter,
    get_formula_catalog,
    get_random_formula,
    list_favorite_formulas,
    list_formulas,
)
from app.core.database import Base
from app.main import app  # noqa: F401  # load all model metadata before create_all
from app.models.formula import FormulaCard, FormulaCategory, UserFormulaFavorite
from app.models.user import User
from app.services.formula_subject_scope import (
    FORMULA_MATH_SOURCE_CODES,
    expand_formula_subject_code,
)


def _card(category_id: int, title: str, sort_order: int, **overrides) -> FormulaCard:
    values = {
        "exam_scope": "math2",
        "category_id": category_id,
        "title": title,
        "search_text": title,
        "formula_blocks": [{"latex": "x"}],
        "sort_order": sort_order,
        "status": "published",
        "published_at": datetime(2026, 9, 1),
    }
    values.update(overrides)
    return FormulaCard(**values)


@pytest_asyncio.fixture
async def formula_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'formulas.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: sync_connection.exec_driver_sql(
                "PRAGMA foreign_keys=OFF"
            )
        )
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        elementary = FormulaCategory(
            exam_scope="math2",
            node_type="subject",
            code="elementary_math",
            name="初等数学",
            sort_order=20,
            is_active=True,
        )
        high_math = FormulaCategory(
            exam_scope="math2",
            node_type="subject",
            code="math2_high_math",
            name="高等数学",
            sort_order=10,
            is_active=True,
        )
        linear_algebra = FormulaCategory(
            exam_scope="math2",
            node_type="subject",
            code="math2_linear_algebra",
            name="线性代数",
            sort_order=30,
            is_active=True,
        )
        session.add_all([elementary, high_math, linear_algebra])
        await session.flush()

        elementary_chapter = FormulaCategory(
            parent_id=elementary.id,
            exam_scope="math2",
            node_type="chapter",
            code="elementary_trigonometry",
            name="初等三角",
            sort_order=20,
            is_active=True,
        )
        high_math_chapter = FormulaCategory(
            parent_id=high_math.id,
            exam_scope="math2",
            node_type="chapter",
            code="high_math_limit",
            name="极限与连续",
            sort_order=10,
            is_active=True,
        )
        linear_chapter = FormulaCategory(
            parent_id=linear_algebra.id,
            exam_scope="math2",
            node_type="chapter",
            code="linear_matrix",
            name="矩阵",
            sort_order=30,
            is_active=True,
        )
        session.add_all([elementary_chapter, high_math_chapter, linear_chapter])
        await session.flush()

        elementary_group = FormulaCategory(
            parent_id=elementary_chapter.id,
            exam_scope="math2",
            node_type="group",
            code="elementary_group",
            name="初等公式",
            sort_order=20,
            is_active=True,
        )
        high_math_group = FormulaCategory(
            parent_id=high_math_chapter.id,
            exam_scope="math2",
            node_type="group",
            code="high_math_group",
            name="高数公式",
            sort_order=10,
            is_active=True,
        )
        linear_group = FormulaCategory(
            parent_id=linear_chapter.id,
            exam_scope="math2",
            node_type="group",
            code="linear_group",
            name="线代公式",
            sort_order=30,
            is_active=True,
        )
        session.add_all([elementary_group, high_math_group, linear_group])
        await session.flush()

        cards = [
            _card(high_math_group.id, "高数诱导公式", 10),
            _card(elementary_group.id, "初等诱导公式", 20),
            _card(high_math_group.id, "高数极限公式", 30),
            _card(elementary_group.id, "初等恒等式", 40),
            _card(linear_group.id, "线性代数公式", 5),
            _card(elementary_group.id, "未发布初等公式", 1, status="draft"),
            _card(
                high_math_group.id,
                "已删除高数公式",
                2,
                deleted_at=datetime(2026, 9, 2),
            ),
        ]
        session.add_all(cards)
        await session.flush()
        session.add_all(
            [
                UserFormulaFavorite(user_id=1, formula_card_id=cards[0].id),
                UserFormulaFavorite(user_id=1, formula_card_id=cards[1].id),
                UserFormulaFavorite(user_id=1, formula_card_id=cards[4].id),
            ]
        )
        await session.commit()

        yield {
            "session": session,
            "cards": cards,
            "chapters": {
                "elementary": elementary_chapter,
                "high_math": high_math_chapter,
                "linear": linear_chapter,
            },
        }

    await engine.dispose()


async def _list(session: AsyncSession, subject_code: str, **overrides):
    params = {
        "subject_code": subject_code,
        "chapter_id": None,
        "category_id": None,
        "tags": None,
        "q": None,
        "favorite_only": False,
        "library_type": None,
        "study_card_type": None,
        "exam_scope": None,
        "page": 1,
        "page_size": 20,
        "current_user": None,
        "db": session,
    }
    params.update(overrides)
    return await list_formulas(**params)


@pytest.mark.asyncio
async def test_subject_expansion_keeps_existing_codes_exact():
    assert expand_formula_subject_code("elementary_math") == ("elementary_math",)
    assert expand_formula_subject_code("math2_high_math") == ("math2_high_math",)
    assert expand_formula_subject_code("math") == FORMULA_MATH_SOURCE_CODES
    assert expand_formula_subject_code("math2_linear_algebra") == (
        "math2_linear_algebra",
    )


@pytest.mark.asyncio
async def test_math_list_is_one_globally_sorted_paginated_result(formula_db):
    session = formula_db["session"]

    elementary = await _list(session, "elementary_math")
    high_math = await _list(session, "math2_high_math")
    other = await _list(session, "math2_linear_algebra")
    page_one = await _list(session, "math", page=1, page_size=2)
    page_two = await _list(session, "math", page=2, page_size=2)

    assert [item["title"] for item in elementary["items"]] == [
        "初等诱导公式",
        "初等恒等式",
    ]
    assert [item["title"] for item in high_math["items"]] == [
        "高数诱导公式",
        "高数极限公式",
    ]
    assert [item["title"] for item in other["items"]] == ["线性代数公式"]
    assert page_one["total"] == page_two["total"] == 4
    assert [item["title"] for item in page_one["items"]] == [
        "高数诱导公式",
        "初等诱导公式",
    ]
    assert [item["title"] for item in page_two["items"]] == [
        "高数极限公式",
        "初等恒等式",
    ]
    assert {item["id"] for item in page_one["items"]}.isdisjoint(
        {item["id"] for item in page_two["items"]}
    )


@pytest.mark.asyncio
async def test_math_search_hits_both_stored_subjects(formula_db):
    result = await _list(formula_db["session"], "math", q="诱导公式")

    assert result["total"] == 2
    assert [item["title"] for item in result["items"]] == [
        "高数诱导公式",
        "初等诱导公式",
    ]


@pytest.mark.asyncio
async def test_math_catalog_returns_one_logical_subject(formula_db):
    result = await get_formula_catalog(
        subject_code="math",
        library_type=None,
        study_card_type=None,
        favorite_only=False,
        exam_scope=None,
        current_user=None,
        db=formula_db["session"],
    )

    assert len(result["items"]) == 1
    subject = result["items"][0]
    assert subject["code"] == "math"
    assert subject["name"] == "数学"
    assert subject["available_count"] == 4
    assert {chapter["name"] for chapter in subject["children"]} == {
        "初等三角",
        "极限与连续",
    }
    assert {chapter["parent_id"] for chapter in subject["children"]} == {0}


@pytest.mark.asyncio
async def test_math_random_favorites_and_chapter_validation_share_scope(
    formula_db, monkeypatch
):
    session = formula_db["session"]
    monkeypatch.setattr("app.api.v1.formulas.random.randint", lambda _start, _end: 0)

    random_card = await get_random_formula(
        subject_code="math",
        chapter_id=None,
        category_id=None,
        tags=None,
        exclude_ids=None,
        library_type=None,
        study_card_type=None,
        exam_scope=None,
        current_user=None,
        db=session,
    )
    favorites = await list_favorite_formulas(
        subject_code="math",
        chapter_id=None,
        category_id=None,
        tags=None,
        q=None,
        library_type=None,
        study_card_type=None,
        exam_scope=None,
        page=1,
        page_size=20,
        current_user=MagicMock(spec=User, id=1),
        db=session,
    )

    assert random_card["title"] in {
        "高数诱导公式",
        "初等诱导公式",
        "高数极限公式",
        "初等恒等式",
    }
    assert favorites["total"] == 2
    assert {item["title"] for item in favorites["items"]} == {
        "高数诱导公式",
        "初等诱导公式",
    }

    await _validate_chapter(session, formula_db["chapters"]["elementary"].id, "math")
    await _validate_chapter(session, formula_db["chapters"]["high_math"].id, "math")
    with pytest.raises(HTTPException) as exc_info:
        await _validate_chapter(session, formula_db["chapters"]["linear"].id, "math")
    assert exc_info.value.status_code == 400
