"""Admin formula API tests.

Covers:
1. Category CRUD (list, create, update, hierarchy validation)
2. Card CRUD (list, create, get, update, soft delete)
3. State machine transitions (draft → pending_review → approved → published → offline)
4. Batch review
5. Duplicate check
6. LaTeX validation
7. Permission enforcement
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser
from app.models.formula import FormulaCard, FormulaCardTag, FormulaCardVersion, FormulaCategory, FormulaTag

client = TestClient(app)


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
    """Mock DB with a queue of results per execute call."""

    def __init__(self, *results):
        self._queue = list(results)
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()
        self.add = MagicMock()
        self.delete = MagicMock()
        self.flush = AsyncMock()
        self.get = AsyncMock()

    async def execute(self, _statement):
        if self._queue:
            return _Result(self._queue.pop(0))
        return _Result([])


def _admin_user():
    return AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=1)


async def _override_current_admin():
    return AdminPrincipal(_admin_user(), {"jti": "token-id", "exp": 4102444800})


def _override_db(*results):
    """Create a mock _Db with wrapped queue items."""
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


def _permissions():
    """Return all formula permissions so require_permissions passes."""
    return [
        "formula:read", "formula:create", "formula:update", "formula:review",
        "formula:publish", "formula:delete", "formula:import",
        "formula-category:read", "formula-category:write",
    ]


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
        sort_order=0, status="draft", reviewed_by=None, reviewed_at=None,
        rejection_reason=None, published_at=None, created_by=1, updated_by=1,
        source_type="manual", source_title=None, source_ref=None,
        content_hash="abc123", version=1, deleted_at=None,
        created_at=datetime(2026, 7, 1), updated_at=datetime(2026, 7, 1),
    )
    defaults.update(kw)
    return FormulaCard(**defaults)


def _tag(**kw):
    defaults = dict(id=1, code="basic", name="基础", sort_order=0)
    defaults.update(kw)
    return FormulaTag(**defaults)


# ── Category Tests ──


class TestCategoryList:
    def test_list_categories(self):
        cat = _category()
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), cat)
        try:
            resp = client.get("/api/admin/v1/formulas/categories")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == 1

    def test_list_categories_empty(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.get("/api/admin/v1/formulas/categories")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json() == {"items": []}

    def test_list_categories_no_permission(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda([])  # no permissions
        try:
            resp = client.get("/api/admin/v1/formulas/categories")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestCategoryCreate:
    def test_create_subject(self):
        # Queue: permissions (for require_permissions), [] (no duplicate)
        db = _Db(_permissions(), [])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post(
                "/api/admin/v1/formulas/categories",
                json={"node_type": "subject", "code": "math2_high_math", "name": "高等数学"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "math2_high_math"

    def test_create_chapter_under_subject(self):
        """subject → chapter is allowed."""
        parent = _category(id=10, node_type="subject")
        db = _Db(_permissions(), [])  # permissions + no duplicate
        db.get = AsyncMock(return_value=parent)
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post(
                "/api/admin/v1/formulas/categories",
                json={"parent_id": 10, "node_type": "chapter", "code": "chapter1", "name": "第一章"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_create_invalid_node_type(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.post(
                "/api/admin/v1/formulas/categories",
                json={"node_type": "invalid", "code": "x", "name": "X"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_create_invalid_hierarchy(self):
        """Cannot create subject under chapter."""
        parent = _category(id=10, node_type="chapter")
        db = _Db(_permissions(), [])
        db.get = AsyncMock(return_value=parent)
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post(
                "/api/admin/v1/formulas/categories",
                json={"parent_id": 10, "node_type": "subject", "code": "x", "name": "X"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 422
        assert "Cannot create" in resp.json()["detail"]

    def test_create_duplicate_code_under_parent(self):
        existing = _category(id=2, parent_id=1, code="dup")
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), existing)
        try:
            resp = client.post(
                "/api/admin/v1/formulas/categories",
                json={"parent_id": 1, "node_type": "chapter", "code": "dup", "name": "Dup"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_create_no_permission(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda([])
        try:
            resp = client.post(
                "/api/admin/v1/formulas/categories",
                json={"node_type": "subject", "code": "x", "name": "X"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestCategoryUpdate:
    def test_update_name(self):
        cat = _category()
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), cat)
        try:
            resp = client.put(
                "/api/admin/v1/formulas/categories/1",
                json={"name": "新名称"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_update_not_found(self):
        """get returns None for nonexistent category."""
        db = _Db(_permissions())
        db.get = AsyncMock(return_value=None)
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = lambda: db
        try:
            resp = client.put(
                "/api/admin/v1/formulas/categories/999",
                json={"name": "X"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_update_empty_fields(self):
        cat = _category()
        # Data with exclude_unset: no fields → 422
        # But model has all fields as optional, so sending an empty body is allowed.
        # The API checks update_data after model_dump(exclude_unset=True).
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), cat)
        try:
            resp = client.put(
                "/api/admin/v1/formulas/categories/1",
                json={},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 422
        assert "No fields" in resp.json()["detail"]


# ── Tags Tests ──


class TestTags:
    def test_list_tags(self):
        tag = _tag()
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), tag)
        try:
            resp = client.get("/api/admin/v1/formulas/tags")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
        assert resp.json()["items"][0]["code"] == "basic"

    def test_list_tags_empty(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.get("/api/admin/v1/formulas/tags")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json() == {"items": []}

    def test_list_tags_no_permission(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda([])
        try:
            resp = client.get("/api/admin/v1/formulas/tags")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403


# ── Card CRUD Tests ──


class TestCardCreate:
    def test_create_card(self):
        card = _card()
        # Queue: permissions, get(category) for validity, then the created card
        cat = _category(id=1, is_active=True)
        db = _Db(_permissions())
        db.get = AsyncMock(side_effect=[cat, card])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = lambda: db
        try:
            resp = client.post(
                "/api/admin/v1/formulas",
                json={
                    "category_id": 1,
                    "title": "测试公式",
                    "formula_blocks": [{"latex": "y = x^2"}],
                    "tag_ids": [1],
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "测试公式"
        assert data["status"] == "draft"
        assert data["version"] == 1

    def test_create_card_inactive_category(self):
        cat = _category(id=1, is_active=False)
        db = _Db(_permissions())
        db.get = AsyncMock(return_value=cat)
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = lambda: db
        try:
            resp = client.post(
                "/api/admin/v1/formulas",
                json={
                    "category_id": 1,
                    "title": "测试",
                    "formula_blocks": [{"latex": "y = x"}],
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 422
        assert "Invalid or inactive" in resp.json()["detail"]

    def test_create_card_no_blocks(self):
        """formula_blocks must have at least 1 block."""
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.post(
                "/api/admin/v1/formulas",
                json={"category_id": 1, "title": "测试", "formula_blocks": []},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_create_card_too_many_blocks(self):
        """formula_blocks max 8."""
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.post(
                "/api/admin/v1/formulas",
                json={
                    "category_id": 1, "title": "测试",
                    "formula_blocks": [{"latex": str(i)} for i in range(9)],
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_create_card_no_permission(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda([])
        try:
            resp = client.post(
                "/api/admin/v1/formulas",
                json={
                    "category_id": 1, "title": "测试",
                    "formula_blocks": [{"latex": "y = x"}],
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestCardList:
    def test_list_cards(self):
        card = _card()
        app.dependency_overrides[get_current_admin] = _override_current_admin
        # Queue: permissions, count (1), then card list, then card_to_dict needs tags
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), 1, card)
        try:
            resp = client.get("/api/admin/v1/formulas")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "测试公式"

    def test_list_cards_empty(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), 0)
        try:
            resp = client.get("/api/admin/v1/formulas")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_cards_filter_by_status(self):
        card = _card(status="published")
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), 1, card)
        try:
            resp = client.get("/api/admin/v1/formulas?status=published")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_cards_no_permission(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda([])
        try:
            resp = client.get("/api/admin/v1/formulas")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestCardGet:
    def test_get_card(self):
        card = _card()
        app.dependency_overrides[get_current_admin] = _override_current_admin
        # Permissions, then card query, then tags for _card_to_dict
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), card)
        try:
            resp = client.get("/api/admin/v1/formulas/1")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    def test_get_card_not_found(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.get("/api/admin/v1/formulas/999")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_get_card_no_permission(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda([])
        try:
            resp = client.get("/api/admin/v1/formulas/1")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestCardUpdate:
    def test_update_title(self):
        card = _card()
        # Queue: permissions, card (for SELECT), tags (for _card_to_dict in snapshot), tags (for response)
        db = _Db(_permissions(), [card], [], [])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.put(
                "/api/admin/v1/formulas/1",
                json={"title": "新标题"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_update_not_found(self):
        db = _Db(_permissions())  # only permissions, no card result → not found
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.put(
                "/api/admin/v1/formulas/999",
                json={"title": "X"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_update_resets_status_to_draft(self):
        card = _card(status="approved")
        db = _Db(_permissions(), [card], [], [])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.put(
                "/api/admin/v1/formulas/1",
                json={"title": "新标题"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_update_no_fields(self):
        card = _card()
        db = _Db(_permissions(), [card])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.put("/api/admin/v1/formulas/1", json={})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 422


class TestCardDelete:
    def test_soft_delete_draft(self):
        card = _card(status="draft")
        # Queue: permissions, card (for SELECT), tags (for snapshot _card_to_dict)
        db = _Db(_permissions(), [card], [])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.delete("/api/admin/v1/formulas/1")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_soft_delete_published_fails(self):
        card = _card(status="published")
        db = _Db(_permissions(), [card])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.delete("/api/admin/v1/formulas/1")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 422
        assert "offline" in resp.json()["detail"]

    def test_soft_delete_not_found(self):
        db = _Db(_permissions())
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.delete("/api/admin/v1/formulas/999")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404


# ── State Machine Tests ──


class TestStateMachine:
    """Test all valid and invalid transitions defined in _VALID_TRANSITIONS."""

    def _setup_card(self, status, card_id=1):
        card = _card(id=card_id, status=status)
        # Queue: permissions, card (for SELECT), tags (for _card_to_dict in snapshot)
        db = _Db(_permissions(), [card], [])
        return db, card

    def _review(self, card_id, action, body=None):
        data = {"action": action}
        if body:
            data.update(body)
        return client.post(f"/api/admin/v1/formulas/{card_id}/review", json=data)

    def _check_transition(self, from_status, action):
        db, _ = self._setup_card(from_status)
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            return self._review(1, action)
        finally:
            app.dependency_overrides.clear()

    def test_draft_to_pending_review(self):
        resp = self._check_transition("draft", "restore")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_pending_review_approve(self):
        resp = self._check_transition("pending_review", "approve")
        assert resp.status_code == 200

    def test_pending_review_reject(self):
        resp = self._check_transition("pending_review", "reject")
        # Should fail because no rejection_reason
        assert resp.status_code == 422

    def test_pending_review_reject_with_reason(self):
        db, _ = self._setup_card("pending_review")
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = lambda: db
        try:
            resp = self._review(1, "reject", {"rejection_reason": "内容不完整"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_approved_to_published(self):
        resp = self._check_transition("approved", "publish")
        assert resp.status_code == 200

    def test_published_to_offline(self):
        resp = self._check_transition("published", "offline")
        assert resp.status_code == 200

    def test_offline_to_published(self):
        resp = self._check_transition("offline", "publish")
        assert resp.status_code == 200

    def test_invalid_transition(self):
        resp = self._check_transition("draft", "publish")
        assert resp.status_code == 422

    def test_invalid_transition_from_pending_review(self):
        resp = self._check_transition("pending_review", "publish")
        assert resp.status_code == 422

    def test_not_found(self):
        db = _Db(_permissions())  # permissions + no card → 404
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post("/api/admin/v1/formulas/999/review", json={"action": "approve"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_no_permission(self):
        db = _Db([])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post("/api/admin/v1/formulas/1/review", json={"action": "approve"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403


# ── Batch Review Tests ──


class TestBatchReview:
    def test_batch_approve(self):
        card1 = _card(id=1, status="pending_review")
        card2 = _card(id=2, status="pending_review")
        db = _Db(_permissions())
        db.get = AsyncMock(side_effect=[card1, card2])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post(
                "/api/admin/v1/formulas/batch-review",
                json={"card_ids": [1, 2], "action": "approve"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(i["status"] == "approved" for i in items)

    def test_batch_mixed_results(self):
        card1 = _card(id=1, status="pending_review")
        card2 = _card(id=2, status="published")  # can't approve published
        db = _Db(_permissions())
        db.get = AsyncMock(side_effect=[card1, card2])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post(
                "/api/admin/v1/formulas/batch-review",
                json={"card_ids": [1, 2], "action": "approve"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        items = resp.json()["items"]
        statuses = {i["id"]: i["status"] for i in items}
        assert statuses[1] == "approved"
        assert statuses[2] == "invalid_transition"

    def test_batch_reject_without_reason_fails(self):
        card = _card(id=1, status="pending_review")
        db = _Db(_permissions())
        db.get = AsyncMock(return_value=card)
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post(
                "/api/admin/v1/formulas/batch-review",
                json={"card_ids": [1], "action": "reject"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["items"][0]["status"] == "missing_reason"

    def test_batch_reject_with_reason(self):
        card = _card(id=1, status="pending_review")
        db = _Db(_permissions())
        db.get = AsyncMock(return_value=card)
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post(
                "/api/admin/v1/formulas/batch-review",
                json={"card_ids": [1], "action": "reject", "rejection_reason": "不合格"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["items"][0]["status"] == "rejected"

    def test_batch_empty_ids(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.post(
                "/api/admin/v1/formulas/batch-review",
                json={"card_ids": [], "action": "approve"},
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 422


# ── Versions Tests ──


class TestVersions:
    def test_list_versions(self):
        ver = FormulaCardVersion(
            id=1, formula_card_id=1, version=1,
            snapshot={"title": "test"}, action="create",
            edited_by=1, edit_reason=None,
            created_at=datetime(2026, 7, 1),
        )
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions(), ver)
        try:
            resp = client.get("/api/admin/v1/formulas/1/versions")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
        assert resp.json()["items"][0]["action"] == "create"

    def test_list_versions_empty(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.get("/api/admin/v1/formulas/1/versions")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["items"] == []


# ── Duplicate Check Tests ──


class TestDuplicateCheck:
    def test_no_duplicate(self):
        card = _card()
        # Queue: permissions, card (SELECT), [] (no duplicates)
        db = _Db(_permissions(), [card], [])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post("/api/admin/v1/formulas/1/check-duplicate")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["strong_duplicates"] == []

    def test_strong_duplicate_found(self):
        card = _card(id=1)
        dup = _card(id=2, title="重复公式")
        # Queue: permissions, card, [dup]
        db = _Db(_permissions(), [card], [dup])
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post("/api/admin/v1/formulas/1/check-duplicate")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert len(resp.json()["strong_duplicates"]) == 1
        assert resp.json()["strong_duplicates"][0]["id"] == 2

    def test_check_not_found(self):
        db = _Db(_permissions())  # permissions, card query returns nothing
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(db)
        try:
            resp = client.post("/api/admin/v1/formulas/999/check-duplicate")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404


# ── LaTeX Validation Tests ──


class TestLatexValidation:
    def test_valid_latex(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.post(
                "/api/admin/v1/formulas/validate-latex",
                json={
                    "category_id": 1, "title": "test",
                    "formula_blocks": [{"latex": "y = \\int_{a}^{b} x^2 \\, dx"}],
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_unbalanced_braces(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.post(
                "/api/admin/v1/formulas/validate-latex",
                json={
                    "category_id": 1, "title": "test",
                    "formula_blocks": [{"latex": "y = {x^2"}],
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["valid"] is False
        assert any(e["type"] == "unbalanced_braces" for e in resp.json()["errors"])

    def test_dangerous_command(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.post(
                "/api/admin/v1/formulas/validate-latex",
                json={
                    "category_id": 1, "title": "test",
                    "formula_blocks": [{"latex": "\\input{/etc/passwd}"}],
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["valid"] is False
        assert any(e["type"] == "dangerous_command" for e in resp.json()["errors"])

    def test_multiple_blocks_validation(self):
        app.dependency_overrides[get_current_admin] = _override_current_admin
        app.dependency_overrides[get_db] = _db_lambda(_permissions())
        try:
            resp = client.post(
                "/api/admin/v1/formulas/validate-latex",
                json={
                    "category_id": 1, "title": "test",
                    "formula_blocks": [
                        {"latex": "\\begin{document}"},
                        {"latex": "y = x"},
                    ],
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["valid"] is False
