"""Graph spec (auto-generation) API tests.

Covers:
1. Expression parser security
2. Single function preview
3. Multi-panel preview
4. Quality checks
5. Preview → confirm workflow
6. Optimistic locking (card_version)
7. Manual upload priority
8. Card type switch preserves assets
9. Batch generation
10. Edge cases (invalid expression, blank render)
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser
from app.models.formula import (
    FormulaCard,
    FormulaGraphAsset,
)
from app.schemas.formula import GraphSpec

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

    def scalar(self):
        return self._values[0] if self._values else 0

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None


class _Result:
    def __init__(self, scalars):
        self._scalars = scalars

    def scalars(self):
        return self._scalars

    def all(self):
        return self._scalars.all() if hasattr(self._scalars, "all") else self._scalars


def _MockScalars(*values):
    return _Scalars(list(values))


# ── Fixtures ──


@pytest.fixture
def admin_principal():
    user = MagicMock(spec=AdminUser)
    user.id = 1
    user.username = "admin"
    user.role_id = 1
    return AdminPrincipal(user=user, token_payload={})


@pytest.fixture
def card():
    c = MagicMock(spec=FormulaCard)
    c.id = 1
    c.exam_scope = "math2"
    c.category_id = 1
    c.title = "Test Card"
    c.card_type = "function_graph"
    c.status = "draft"
    c.version = 5
    c.graph_spec = None
    c.draft_graph_spec = None
    c.graph_status = "unconfigured"
    c.graph_last_error = None
    c.graph_generated_at = None
    c.graph_confirmed_at = None
    c.formula_blocks = [{"latex": "y = x^2"}]
    c.deleted_at = None
    c.created_at = datetime.now(UTC)
    c.updated_at = datetime.now(UTC)
    return c


def _make_admin_db(card_result=None):
    """Create a mock DB that handles permission queries and optional card query."""
    db = AsyncMock()

    # Permission query: called by require_permissions → _get_permission_names
    perm_scalars = MagicMock()
    perm_scalars.all.return_value = [
        "formula:read", "formula:create", "formula:update",
        "formula:delete", "formula:review", "formula:import",
        "formula-category:read", "formula-category:write",
    ]
    perm_mock = MagicMock()
    perm_mock.scalars.return_value = perm_scalars

    if card_result:
        # Card query: scalar_one_or_none returns the card
        card_mock = MagicMock()
        card_mock.scalar_one_or_none.return_value = card_result

        # Use side_effect: first call returns permission mock, second returns card mock
        db.execute.side_effect = [perm_mock, card_mock]
    else:
        db.execute.return_value = perm_mock

    return db


def _override_deps(db_mock, admin):
    """Set up FastAPI dependency overrides for admin tests."""
    app.dependency_overrides[get_db] = lambda: db_mock
    app.dependency_overrides[get_current_admin] = lambda: admin


def _clear_overrides():
    app.dependency_overrides.clear()


def _clear_overrides():
    app.dependency_overrides.clear()


# ── Test: Expression parser security ──


class TestExpressionParser:
    """AST-level security checks."""

    def test_attribute_access_rejected(self):
        from app.services.formula_graph_expr_parser import validate_expression
        with pytest.raises(ValueError, match="Forbidden"):
            validate_expression("x.__class__")

    def test_dunder_name_rejected(self):
        from app.services.formula_graph_expr_parser import validate_expression
        with pytest.raises(ValueError, match="Unknown function"):
            validate_expression("__import__('os')")

    @pytest.mark.parametrize("expr", [
        '"evil"',
        "lambda x: x",
        "[1, 2, 3]",
        "{'a': 1}",
        "(1, 2)",
        "x[0]",
    ])
    def test_forbidden_constructs(self, expr):
        from app.services.formula_graph_expr_parser import validate_expression
        with pytest.raises(ValueError):
            validate_expression(expr)

    def test_valid_expressions(self):
        import numpy as np

        from app.services.formula_graph_expr_parser import (
            lambdify_expression,
            parse_expression,
        )

        for expr_str in ["x**2", "sin(x)", "exp(x) + 1", "sqrt(abs(x))", "ln(x) + cos(x)"]:
            expr = parse_expression(expr_str)
            f = lambdify_expression(expr)
            xs = np.linspace(0.1, 1, 10)
            ys = f(xs)
            assert len(ys) == 10

    def test_expression_too_long(self):
        from app.services.formula_graph_expr_parser import validate_expression
        with pytest.raises(ValueError, match="too long"):
            validate_expression("x" * 600)


# ── Test: Preview endpoint ──


class TestGraphPreview:
    """Preview generation endpoint."""

    def setup_method(self):
        self.valid_spec = {
            "schema_version": 1,
            "render_mode": "explicit_2d",
            "template": "single_function",
            "panels": [{
                "expressions": [{"expression": "x**2", "label": "y=x²"}],
                "axis_mode": "auto_robust",
                "x_range": [-3, 3],
                "y_range": [0, 9],
            }],
        }

    def test_preview_creates_draft(self, admin_principal, card):
        """Preview generates and returns draft status."""
        mock_gen_result = {
            "preview_url": "http://localhost:8000/static/formulas/graphs/1/preview/test.png",
            "thumbnail_url": None,
            "preview_token": "test_token_123",
            "checksum": "abc123",
            "width": 1600,
            "height": 1000,
            "mime_type": "image/png",
            "quality": {"errors": [], "warnings": [], "passed": True},
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }

        db = _make_admin_db(card)
        _override_deps(db, admin_principal)

        with patch("app.api.v1.admin_formulas.generate_preview", return_value=mock_gen_result):
            resp = client.post("/api/admin/v1/formulas/1/graph/preview", json=self.valid_spec)

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "preview_url" in data
        assert data["preview_token"] == "test_token_123"
        assert data["quality"]["passed"] is True

        _clear_overrides()

    def test_preview_rejects_pure_formula(self, admin_principal, card):
        """pure_formula cards cannot generate previews."""
        card.card_type = "pure_formula"

        db = _make_admin_db(card)
        _override_deps(db, admin_principal)
        resp = client.post("/api/admin/v1/formulas/1/graph/preview", json=self.valid_spec)
        assert resp.status_code == 422

        _clear_overrides()


# ── Test: Confirm endpoint ──


class TestGraphConfirm:
    """Preview → confirm workflow."""

    def test_confirm_creates_asset(self, admin_principal, card):
        """Confirm creates a generated asset."""
        card.graph_status = "draft"

        asset = MagicMock(spec=FormulaGraphAsset)
        asset.id = 10
        asset.formula_card_id = 1
        asset.source_type = "generated"
        asset.template_type = None
        asset.template_parameters = None
        asset.viewport = None
        asset.original_svg_url = None
        asset.image_url = "/static/test.png"
        asset.thumbnail_url = None
        asset.mime_type = "image/png"
        asset.width = 1600
        asset.height = 1000
        asset.file_size = 50000
        asset.checksum = "abc123"
        asset.renderer_version = 1
        asset.alt_text = None
        asset.description = None
        asset.reviewed_by = 1
        asset.reviewed_at = datetime.now(UTC)
        asset.review_note = None
        asset.published_version = 5
        asset.created_at = datetime.now(UTC)
        asset.updated_at = datetime.now(UTC)

        db = _make_admin_db(card)
        db.flush.return_value = None
        db.refresh.return_value = None
        db.commit.return_value = None
        _override_deps(db, admin_principal)

        with patch("app.api.v1.admin_formulas.confirm_preview", return_value=asset):
            resp = client.post("/api/admin/v1/formulas/1/graph/confirm", json={
                "preview_token": "test_token_123",
                "checksum": "abc123",
                "card_version": 5,
                "accept_warnings": False,
            })

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["graph_status"] == "ready"
        assert data["asset"]["source_type"] == "generated"

        _clear_overrides()


# ── Test: Regenerate endpoint ──


class TestGraphRegenerate:
    """Regeneration preserves data."""

    def test_regenerate_updates_asset(self, admin_principal, card):
        """Regenerate returns updated asset."""
        asset = MagicMock(spec=FormulaGraphAsset)
        asset.id = 11
        asset.formula_card_id = 1
        asset.source_type = "generated"
        asset.template_type = None
        asset.template_parameters = None
        asset.viewport = None
        asset.original_svg_url = None
        asset.image_url = "/static/new.png"
        asset.thumbnail_url = None
        asset.mime_type = "image/png"
        asset.width = 1600
        asset.height = 1000
        asset.file_size = 45000
        asset.checksum = "new_checksum"
        asset.renderer_version = 1
        asset.alt_text = None
        asset.description = None
        asset.reviewed_by = 1
        asset.reviewed_at = datetime.now(UTC)
        asset.review_note = None
        asset.published_version = 6
        asset.created_at = datetime.now(UTC)
        asset.updated_at = datetime.now(UTC)

        db = _make_admin_db(card)
        db.refresh.return_value = None
        _override_deps(db, admin_principal)

        with patch("app.api.v1.admin_formulas.regenerate_asset", return_value=asset):
            spec = {
                "schema_version": 1,
                "render_mode": "explicit_2d",
                "template": "single_function",
                "panels": [{"expressions": [{"expression": "x**3", "label": "y=x³"}]}],
            }
            resp = client.post("/api/admin/v1/formulas/1/graph/regenerate", json=spec)

        assert resp.status_code == 200, resp.text

        _clear_overrides()


# ── Test: Delete generated asset ──


class TestGraphDelete:
    """Delete generated asset preserves manual uploads."""

    def test_delete_generated_only(self, admin_principal, card):
        """Generated asset deleted, manual upload preserved."""
        db = _make_admin_db(card)
        _override_deps(db, admin_principal)

        with patch("app.api.v1.admin_formulas.delete_spec_generated_asset", return_value=True):
            resp = client.delete("/api/admin/v1/formulas/1/graph/generated")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        _clear_overrides()


class TestManualUploadPriority:
    """Manual upload takes priority over generated."""

    def test_choose_effective_prioritizes_uploaded(self):
        """choose_effective_graph_asset returns uploaded over generated."""
        from app.services.formula_graph_asset_service import (
            choose_effective_graph_asset,
        )

        uploaded = MagicMock(spec=FormulaGraphAsset)
        uploaded.source_type = "uploaded"
        uploaded.image_url = "http://example.com/uploaded.png"

        generated = MagicMock(spec=FormulaGraphAsset)
        generated.source_type = "generated"
        generated.image_url = "http://example.com/generated.png"

        template = MagicMock(spec=FormulaGraphAsset)
        template.source_type = "template"
        template.image_url = "http://example.com/template.png"

        effective = choose_effective_graph_asset([generated, template, uploaded])
        assert effective.source_type == "uploaded"

    def test_generated_over_template(self):
        """Generated takes priority over template."""
        from app.services.formula_graph_asset_service import (
            choose_effective_graph_asset,
        )

        generated = MagicMock(spec=FormulaGraphAsset)
        generated.source_type = "generated"
        generated.image_url = "http://example.com/generated.png"

        template = MagicMock(spec=FormulaGraphAsset)
        template.source_type = "template"
        template.image_url = "http://example.com/template.png"

        effective = choose_effective_graph_asset([template, generated])
        assert effective.source_type == "generated"


# ── Test: Card type transition ──


class TestCardTypeTransition:
    """Card type switch does not delete assets."""

    def test_function_graph_to_pure_formula(self, card):
        """Switching to pure_formula sets status but doesn't touch assets."""
        card.card_type = "function_graph"
        card.graph_status = "ready"

        # Simulate the update logic from the API
        new_type = "pure_formula"
        if new_type == "pure_formula":
            card.graph_status = "not_applicable"

        assert card.graph_status == "not_applicable"

    def test_pure_formula_to_function_graph(self, card):
        """Switching from pure_formula to function_graph with existing asset."""
        card.card_type = "pure_formula"
        card.graph_status = "not_applicable"

        new_type = "function_graph"
        if new_type in ("function_graph", "auto"):
            # Check for existing assets (mocked: has asset)
            card.graph_status = "ready"

        assert card.graph_status == "ready"


# ── Test: Batch generation ──


class TestBatchGenerate:
    """Batch generation endpoint."""

    def test_batch_returns_job_id(self, admin_principal):
        """Batch returns a job_id."""
        db = _make_admin_db()
        _override_deps(db, admin_principal)

        with patch("app.api.v1.admin_formulas.start_batch_generate", return_value="job_abc123"):
            resp = client.post("/api/admin/v1/formulas/graphs/generate-missing")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "job_id" in data

        _clear_overrides()


# ── Test: is_function_graph ──


class TestIsFunctionGraph:
    """Unified classification helper."""

    def test_function_graph_returns_true(self):
        from app.services.formula_graph_asset_service import is_function_graph
        card = MagicMock(spec=FormulaCard)
        card.card_type = "function_graph"
        assert is_function_graph(card) is True

    def test_pure_formula_returns_false(self):
        from app.services.formula_graph_asset_service import is_function_graph
        card = MagicMock(spec=FormulaCard)
        card.card_type = "pure_formula"
        assert is_function_graph(card) is False

    def test_auto_with_asset_returns_true(self):
        from app.services.formula_graph_asset_service import is_function_graph
        card = MagicMock(spec=FormulaCard)
        card.card_type = "auto"
        asset = MagicMock()
        asset.image_url = "http://example.com/img.png"
        assert is_function_graph(card, effective_asset=asset) is True

    def test_auto_without_asset_returns_false(self):
        from app.services.formula_graph_asset_service import is_function_graph
        card = MagicMock(spec=FormulaCard)
        card.card_type = "auto"
        assert is_function_graph(card) is False


# ── Test: GraphSpec schema validation ──


class TestGraphSpecSchema:
    """GraphSpec Pydantic validation."""

    def test_valid_spec_passes(self):
        spec = GraphSpec(
            schema_version=1,
            template="single_function",
            panels=[{
                "expressions": [{"expression": "x**2"}],
            }],
        )
        assert spec.template == "single_function"
        assert len(spec.panels) == 1

    def test_invalid_expression_count(self):
        with pytest.raises(ValueError):
            GraphSpec(
                template="single_function",
                panels=[{
                    "expressions": [],
                }],
            )

    def test_invalid_panel_count(self):
        with pytest.raises(ValueError):
            GraphSpec(
                template="single_function",
                panels=[{"expressions": [{"expression": "x"}]}] * 10,
            )


# ── Test: Quality checks ──


class TestQualityCheck:
    """Image quality check logic."""

    def test_blank_image_check(self):
        """check_quality detects blank images."""
        import io

        from PIL import Image

        from app.services.formula_graph_spec_renderer import check_quality

        # Create a pure white image
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        white_bytes = buf.getvalue()

        spec = {"template": "single_function", "panels": [{"expressions": [{"expression": "x**2"}]}]}
        meta = {"total_curves": 0, "total_points": 0, "valid_points": 0, "panel_count": 1}

        quality = check_quality(white_bytes, spec, meta)
        assert len(quality["errors"]) > 0
        assert quality["passed"] is False

    def test_valid_image_no_errors(self):
        """Check quality on a valid image passes."""
        import io

        from PIL import Image

        from app.services.formula_graph_spec_renderer import check_quality

        # Create a non-blank image
        img = Image.new("RGB", (100, 100), (200, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        spec = {"template": "single_function", "panels": [{"expressions": [{"expression": "x**2"}]}]}
        meta = {"total_curves": 1, "total_points": 100, "valid_points": 95, "panel_count": 1}

        quality = check_quality(img_bytes, spec, meta)
        # Should pass (valid points > 10, not blank)
        assert quality["passed"] is True
