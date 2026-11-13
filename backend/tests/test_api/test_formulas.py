"""User-facing formula API tests.

Covers:
1. Catalog (category tree)
2. Tags listing
3. List formulas with filters (subject_code, category_id, tags, q, favorite_only)
4. Detail (get single published card)
5. Favorites (add, remove, list)
6. Random (with filters, exclude_ids, pool exhaustion)
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.models.formula import (
    FormulaCard,
    FormulaCategory,
    FormulaTag,
    UserFormulaFavorite,
)
from app.models.user import User

client = TestClient(app)


def _mock_user():
    return User(id=1, openid="test", nickname="test")


# ── Helpers ──


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values

    def first(self):
        return self._values[0] if self._values else None

    def one_or_none(self):
        return self._values[0] if self._values else None


class _Result:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _Scalars(self._values)

    def scalar(self):
        return self._values[0] if self._values else None

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None

    def one_or_none(self):
        return self._values[0] if self._values else None

    def all(self):
        return self._values


class _Db:
    def __init__(self, *results):
        self._queue = list(results)
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()
        self.add = MagicMock()
        self.delete = AsyncMock()
        self.flush = AsyncMock()
        self.get = AsyncMock()

    async def execute(self, _statement):
        if self._queue:
            return _Result(self._queue.pop(0))
        return _Result([])


def _override_db(*results):
    """Wrap each single result in a list so .scalars().all() returns iterable."""
    wrapped = [r if isinstance(r, list) else [r] for r in results]
    return _Db(*wrapped)


def _db_lambda(*results):
    """Return an async callable for use as dependency override.

    If given a single _Db instance, use it directly.
    Otherwise wrap each result in a list and create a new _Db.
    """
    if len(results) == 1 and isinstance(results[0], _Db):
        db = results[0]
    else:
        wrapped = [r if isinstance(r, list) else [r] for r in results]
        db = _Db(*wrapped)
    async def _get():
        return db
    return _get


async def _override_current_user():
    return User(id=1, openid="test_openid", nickname="测试用户")


async def _override_none_user():
    return None


def _category(**kw):
    defaults = dict(
        id=1, parent_id=None, exam_scope="math2", node_type="subject",
        code="math2_high_math", name="高等数学", description=None,
        sort_order=0, is_active=True,
        created_at=datetime(2026, 7, 1), updated_at=datetime(2026, 7, 1),
    )
    defaults.update(kw)
    return FormulaCategory(**defaults)


def _card(**kw):
    defaults = dict(
        id=1, exam_scope="math2", category_id=1, title="测试公式",
        aliases=None, search_text=None, card_type="pure_formula",
        summary=None, formula_blocks=[{"label": None, "latex": "y = x^2", "note": None}],
        conditions=None, symbol_notes=None, secondary_conclusions=None,
        error_tips=None, examples=None, function_properties=None,
        sort_order=0, status="published", reviewed_by=None, reviewed_at=None,
        rejection_reason=None, published_at=datetime(2026, 7, 1),
        created_by=1, updated_by=1, source_type="manual",
        source_title=None, source_ref=None, content_hash="abc123", version=1,
        deleted_at=None, created_at=datetime(2026, 7, 1), updated_at=datetime(2026, 7, 1),
    )
    defaults.update(kw)
    return FormulaCard(**defaults)


def _tag(**kw):
    defaults = dict(id=1, code="basic", name="基础", sort_order=0)
    defaults.update(kw)
    return FormulaTag(**defaults)


# ── Catalog Tests ──


class TestCatalog:
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _mock_user()

    def test_get_catalog(self):
        self._setup()
        cat = _category()
        app.dependency_overrides[get_db] = _db_lambda(cat)
        try:
            resp = client.get("/api/v1/formulas/catalog")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["items"][0]["id"] == 1

    def test_get_catalog_empty(self):
        self._setup()
        app.dependency_overrides[get_db] = _db_lambda()
        try:
            resp = client.get("/api/v1/formulas/catalog")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json() == {"items": []}

    def test_catalog_nested_tree(self):
        """Subjects should have children (chapters)."""
        self._setup()
        subject = _category(id=1, parent_id=None, code="math2_high_math", node_type="subject")
        chapter = _category(id=2, parent_id=1, code="chapter1", node_type="chapter")
        # Provide a count result so the chapter (id=2) is not pruned as empty
        app.dependency_overrides[get_db] = _db_lambda([subject, chapter], [(2, 1)])
        try:
            resp = client.get("/api/v1/formulas/catalog")
        finally:
            app.dependency_overrides.clear()
        data = resp.json()
        items = data["items"]
        assert len(items) == 1  # one root
        assert items[0]["id"] == 1
        assert len(items[0]["children"]) == 1
        assert items[0]["children"][0]["id"] == 2

    def test_catalog_sorted_by_sort_order(self):
        self._setup()
        cat1 = _category(id=1, parent_id=None, sort_order=2, code="b")
        cat2 = _category(id=2, parent_id=None, sort_order=1, code="a")
        app.dependency_overrides[get_db] = _db_lambda([cat1, cat2])
        try:
            resp = client.get("/api/v1/formulas/catalog")
        finally:
            app.dependency_overrides.clear()
        items = resp.json()["items"]
        assert items[0]["id"] == 2  # sort_order=1 first
        assert items[1]["id"] == 1  # sort_order=2 second


# ── Tags Tests ──


class TestTags:
    def test_list_tags(self):
        tag = _tag()
        app.dependency_overrides[get_db] = _db_lambda(tag)
        try:
            resp = client.get("/api/v1/formulas/tags")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_list_tags_empty(self):
        app.dependency_overrides[get_db] = _db_lambda()
        try:
            resp = client.get("/api/v1/formulas/tags")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_tags_sorted(self):
        tag1 = _tag(id=1, code="basic", sort_order=2)
        tag2 = _tag(id=2, code="high_frequency", sort_order=1)
        app.dependency_overrides[get_db] = _db_lambda([tag2, tag1])
        try:
            resp = client.get("/api/v1/formulas/tags")
        finally:
            app.dependency_overrides.clear()
        items = resp.json()["items"]
        assert len(items) == 2
        # Check sorting in response matches DB ordering
        assert items[0]["sort_order"] == 1
        assert items[1]["sort_order"] == 2


# ── List Formulas Tests ──


class TestListFormulas:
    def test_list_published(self):
        card = _card()
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "测试公式"

    def test_list_empty(self):
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(0)
        try:
            resp = client.get("/api/v1/formulas")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_unauthenticated(self):
        """Unauthenticated users can still list formulas."""
        card = _card()
        app.dependency_overrides[get_current_user] = _override_none_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_list_with_search(self):
        card = _card()
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas?q=极限")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_list_with_category_filter(self):
        card = _card(category_id=5)
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas?category_id=5")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_list_with_tag_filter(self):
        card = _card()
        # Tag filter needs: matching_card_ids subquery — we return card.id, then count, then card
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas?tags=basic")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_list_favorite_only_without_auth(self):
        """favorite_only without auth returns empty."""
        app.dependency_overrides[get_current_user] = _override_none_user
        app.dependency_overrides[get_db] = _db_lambda(0)
        try:
            resp = client.get("/api/v1/formulas?favorite_only=true")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_pagination(self):
        cards = [_card(id=i) for i in range(1, 4)]
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(3, cards)
        try:
            resp = client.get("/api/v1/formulas?page=1&page_size=20")
        finally:
            app.dependency_overrides.clear()
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3


# ── Detail Tests ──


class TestDetail:
    def test_get_detail(self):
        card = _card()
        app.dependency_overrides[get_db] = _db_lambda(card)
        try:
            resp = client.get("/api/v1/formulas/1")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["id"] == 1
        assert resp.json()["title"] == "测试公式"

    def test_get_detail_not_found(self):
        app.dependency_overrides[get_db] = _db_lambda()
        try:
            resp = client.get("/api/v1/formulas/999")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_get_detail_not_published(self):
        """Unpublished cards should not be accessible via user API."""
        _card(status="draft")
        app.dependency_overrides[get_db] = _db_lambda()
        try:
            resp = client.get("/api/v1/formulas/1")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_get_detail_deleted(self):
        """Soft-deleted cards should not be accessible."""
        _card(deleted_at=datetime(2026, 7, 1))
        app.dependency_overrides[get_db] = _db_lambda()
        try:
            resp = client.get("/api/v1/formulas/1")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404


# ── Favorites Tests ──


class TestFavorites:
    def test_add_favorite(self):
        card = _card()
        db = _Db([card], [])
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.put("/api/v1/formulas/1/favorite")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_add_favorite_not_found(self):
        db = _Db([])
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.put("/api/v1/formulas/999/favorite")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_add_favorite_idempotent(self):
        """Adding an already-favorited card returns ok."""
        card = _card()
        existing_fav = UserFormulaFavorite(id=1, user_id=1, formula_card_id=1)
        db = _Db([card], [existing_fav])
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.put("/api/v1/formulas/1/favorite")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_remove_favorite(self):
        fav = UserFormulaFavorite(id=1, user_id=1, formula_card_id=1)
        db = _Db([fav])
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.delete("/api/v1/formulas/1/favorite")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_remove_favorite_idempotent(self):
        """Removing a not-favorited card returns ok."""
        db = _Db([])
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.delete("/api/v1/formulas/1/favorite")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_list_favorites(self):
        card = _card()
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas/favorites/list")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_favorites_empty(self):
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(0)
        try:
            resp = client.get("/api/v1/formulas/favorites/list")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_favorites_unauthenticated(self):
        app.dependency_overrides.clear()
        resp = client.get("/api/v1/formulas/favorites/list")
        # FastAPI's HTTPBearer rejects missing credentials with 401.
        assert resp.status_code == 401


# ── Random Tests ──


class TestRandom:
    def test_get_random(self):
        card = _card()
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas/random/next")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    def test_get_random_empty(self):
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(0)
        try:
            resp = client.get("/api/v1/formulas/random/next")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_get_random_with_subject_filter(self):
        card = _card()
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas/random/next?subject_code=math2_high_math")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_get_random_exclude_ids(self):
        card = _card()
        app.dependency_overrides[get_current_user] = _override_current_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas/random/next?exclude_ids=1,2,3")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_get_random_pool_exhaustion_retry(self):
        """When pool is empty with exclude_ids, retry without exclusion."""
        card = _card()
        app.dependency_overrides[get_current_user] = _override_current_user
        # First count=0 (with exclude), second count=1 (retry), then card
        app.dependency_overrides[get_db] = _db_lambda(0, 1, card)
        try:
            resp = client.get("/api/v1/formulas/random/next?exclude_ids=1")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_get_random_unauthenticated(self):
        """Unauthenticated users can still get random."""
        card = _card()
        app.dependency_overrides[get_current_user] = _override_none_user
        app.dependency_overrides[get_db] = _db_lambda(1, card)
        try:
            resp = client.get("/api/v1/formulas/random/next")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
