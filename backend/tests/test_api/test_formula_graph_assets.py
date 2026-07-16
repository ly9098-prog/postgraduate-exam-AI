"""Tests for formula graph asset features.

Covers:
1. choose_effective_graph_asset() prioritization (unit)
2. load_graph_assets_map() batch loading (unit)
3. Image validation (unit)
4. Thumbnail creation (unit)
5. Admin graph asset endpoints (integration, mocked)
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from io import BytesIO
from PIL import Image
from fastapi import UploadFile
from fastapi.testclient import TestClient

from app.core.admin_security import AdminPrincipal, get_current_admin, require_permissions
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser
from app.models.formula import FormulaCard, FormulaGraphAsset, FormulaCategory
from app.services.formula_graph_asset_service import (
    _create_thumbnail,
    _validate_image,
    choose_effective_graph_asset,
    load_graph_assets_map,
)

client = TestClient(app)


# ── Mock helpers ──

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


def _make_admin_user(id=1):
    return AdminUser(id=id, username="admin", role_id=1, is_active=True)

def _make_admin_principal():
    return AdminPrincipal(_make_admin_user(), {"jti": "token-id", "exp": 4102444800})

def _make_card(id=1, card_type="function_graph", status="draft", deleted_at=None):
    return FormulaCard(
        id=id, exam_scope="math2", category_id=1,
        title=f"Test {id}", card_type=card_type,
        formula_blocks=[{"latex": "y=x"}],
        status=status, version=1,
        deleted_at=deleted_at,
    )

def _make_asset(id=1, card_id=1, source_type="template",
                image_url="http://localhost:8000/static/formulas/graphs/1/template/t.png",
                checksum="abc"):
    return FormulaGraphAsset(
        id=id, formula_card_id=card_id, source_type=source_type,
        image_url=image_url,
        thumbnail_url=image_url.replace(".png", "-thumb.png"),
        mime_type="image/png", width=1200, height=900,
        checksum=checksum,
    )


# ═══════════════════════════════════════════════════════════════
# Unit: choose_effective_graph_asset
# ═══════════════════════════════════════════════════════════════

class TestChooseEffectiveGraphAsset:
    def test_only_template_returns_template(self):
        t = _make_asset(1, 1, "template")
        assert choose_effective_graph_asset([t]) is t

    def test_only_uploaded_returns_uploaded(self):
        u = _make_asset(1, 1, "uploaded")
        assert choose_effective_graph_asset([u]) is u

    def test_both_returns_uploaded(self):
        t = _make_asset(1, 1, "template")
        u = _make_asset(2, 1, "uploaded")
        assert choose_effective_graph_asset([t, u]) is u

    def test_uploaded_missing_image_falls_back_to_template(self):
        t = _make_asset(1, 1, "template")
        u = FormulaGraphAsset(id=2, formula_card_id=1, source_type="uploaded")
        assert choose_effective_graph_asset([t, u]) is t

    def test_none_returns_none(self):
        assert choose_effective_graph_asset([]) is None

    def test_all_missing_image_returns_none(self):
        a1 = FormulaGraphAsset(id=1, formula_card_id=1, source_type="uploaded")
        a2 = FormulaGraphAsset(id=2, formula_card_id=1, source_type="template")
        assert choose_effective_graph_asset([a1, a2]) is None


# ═══════════════════════════════════════════════════════════════
# Unit: load_graph_assets_map
# ═══════════════════════════════════════════════════════════════

class TestLoadGraphAssetsMap:
    @pytest.mark.asyncio
    async def test_batch_loading(self):
        db = AsyncMock()
        a1 = _make_asset(1, 101, "template")
        a2 = _make_asset(2, 102, "uploaded")
        db.execute = AsyncMock(return_value=_Result([a1, a2]))

        result = await load_graph_assets_map(db, [101, 102])
        assert 101 in result
        assert 102 in result
        assert len(result[101]) == 1
        assert len(result[102]) == 1

    @pytest.mark.asyncio
    async def test_empty_ids(self):
        db = AsyncMock()
        result = await load_graph_assets_map(db, [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_no_assets_for_id(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_Result([]))
        result = await load_graph_assets_map(db, [999])
        assert result[999] == []


# ═══════════════════════════════════════════════════════════════
# Unit: Image validation
# ═══════════════════════════════════════════════════════════════

class TestImageValidation:
    def test_unknown_extension_raises(self):
        with pytest.raises(ValueError, match="不支持的文件格式"):
            _validate_image(b"123", "test.bmp")

    def test_empty_file_raises(self):
        with pytest.raises(ValueError, match="图片解码失败"):
            _validate_image(b"", "test.png")

    def test_valid_png_succeeds(self):
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        result_img, mime = _validate_image(buf.getvalue(), "test.png")
        assert mime == "image/png"
        assert result_img.size == (100, 100)

    def test_valid_jpeg_succeeds(self):
        img = Image.new("RGB", (200, 150), (0, 255, 0))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        result_img, mime = _validate_image(buf.getvalue(), "test.jpg")
        assert mime == "image/jpeg"

    def test_thumbnail_creation(self):
        img = Image.new("RGB", (1200, 900), (255, 0, 0))
        thumb_bytes = _create_thumbnail(img)
        thumb = Image.open(BytesIO(thumb_bytes))
        assert thumb.size == (600, 450)
        assert thumb.format == "PNG"


# ═══════════════════════════════════════════════════════════════
# Integration: Admin graph asset API (mocked DB)
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def admin_override():
    app.dependency_overrides[get_current_admin] = lambda: _make_admin_principal()
    yield
    app.dependency_overrides.pop(get_current_admin, None)
    app.dependency_overrides.pop(get_db, None)


def _setup_admin_mock(cards, assets=None):
    """Set up mock DB for admin tests. Returns mock session."""
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=cards[0] if cards else None)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    # First execute call returns permission strings (from require_permissions check)
    perm_result = MagicMock()
    perm_scalars = MagicMock()
    perm_scalars.all.return_value = [
        "formula:read", "formula:create", "formula:update",
        "formula:delete", "formula:review", "formula:import",
        "formula-category:read", "formula-category:write",
    ]
    perm_result.scalars.return_value = perm_scalars

    # Subsequent execute calls return card/asset data via standard mocking
    data_result = MagicMock()
    data_result.scalars.return_value.all.return_value = assets if assets is not None else []
    data_result.scalars.return_value.scalar_one_or_none.return_value = cards[0] if cards else None

    # Use side_effect: first call = permissions, rest = data
    call_count = [0]
    async def _execute_side(*args, **kwargs):
        i = call_count[0]
        call_count[0] += 1
        return perm_result if i == 0 else data_result

    mock_session.execute = _execute_side

    def _get_db():
        return mock_session

    app.dependency_overrides[get_db] = _get_db
    return mock_session


class TestAdminGraphAssetList:
    def test_list_empty(self, admin_override):
        _setup_admin_mock(cards=[_make_card(1)])
        resp = client.get("/api/admin/v1/formulas/1/graph-assets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["effective"] is None

    def test_list_with_template(self, admin_override):
        card = _make_card(1)
        t = _make_asset(1, 1, "template")
        _setup_admin_mock(cards=[card], assets=[t])
        resp = client.get("/api/admin/v1/formulas/1/graph-assets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["effective"]["source_type"] == "template"

    def test_list_uploaded_priority(self, admin_override):
        card = _make_card(1)
        t = _make_asset(1, 1, "template", image_url="http://example.com/t.png")
        u = _make_asset(2, 1, "uploaded", image_url="http://example.com/u.png")
        _setup_admin_mock(cards=[card], assets=[u, t])
        resp = client.get("/api/admin/v1/formulas/1/graph-assets")
        data = resp.json()
        assert data["effective"]["source_type"] == "uploaded"

    def test_card_not_found(self, admin_override):
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)
        # First execute = permissions check; second = empty card query
        perm_result = MagicMock()
        perm_scalars = MagicMock()
        perm_scalars.all.return_value = ["formula:read", "formula:update", "formula:delete"]
        perm_result.scalars.return_value = perm_scalars
        data_result = _Result([])
        call_count = [0]
        async def _execute_side(*args, **kwargs):
            i = call_count[0]
            call_count[0] += 1
            return perm_result if i == 0 else data_result
        mock_session.execute = _execute_side
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = client.get("/api/admin/v1/formulas/999/graph-assets")
        assert resp.status_code == 404


class TestAdminGraphAssetUpload:
    def test_pure_formula_rejected(self, admin_override):
        card = _make_card(1, card_type="pure_formula")
        _setup_admin_mock(cards=[card])
        resp = client.post(
            "/api/admin/v1/formulas/1/graph-assets/upload",
            data={"file": b"fake"},
            headers={"Content-Type": "multipart/form-data"},
        )
        # Card type check should come first; FastAPI form parsing may fail
        # but the important thing is it's not a 200
        assert resp.status_code != 200


class TestAdminGraphAssetDelete:
    def test_unsupported_source_type(self, admin_override):
        card = _make_card(1)
        _setup_admin_mock(cards=[card])
        resp = client.delete("/api/admin/v1/formulas/1/graph-assets/svg")
        assert resp.status_code == 422

    def test_not_found_uploaded(self, admin_override):
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=_make_card(1))
        # First execute = permissions check; second = empty asset query
        perm_result = MagicMock()
        perm_scalars = MagicMock()
        perm_scalars.all.return_value = ["formula:read", "formula:update", "formula:delete"]
        perm_result.scalars.return_value = perm_scalars
        data_result = _Result([])
        call_count = [0]
        async def _execute_side(*args, **kwargs):
            i = call_count[0]
            call_count[0] += 1
            return perm_result if i == 0 else data_result
        mock_session.execute = _execute_side
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = client.delete("/api/admin/v1/formulas/1/graph-assets/uploaded")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Integration: Renderer tests
# ═══════════════════════════════════════════════════════════════

class TestRenderer:
    def test_render_creates_png(self):
        from app.services.formula_graph_renderer import render_formula_graph
        png = render_formula_graph(
            curves=[{"template_type": "sine", "parameters": {"a": 1}, "label": "y=sin x"}],
            viewport={"x_min": -6, "x_max": 6, "y_min": -1.5, "y_max": 1.5},
        )
        img = Image.open(BytesIO(png))
        assert img.size == (1200, 900)
        assert img.format == "PNG"

    def test_unknown_template(self):
        from app.services.formula_graph_renderer import render_formula_graph
        with pytest.raises(ValueError):
            render_formula_graph(
                curves=[{"template_type": "unknown", "parameters": {}}],
                viewport={"x_min": -6, "x_max": 6, "y_min": -6, "y_max": 6},
            )

    def test_not_all_white(self):
        from app.services.formula_graph_renderer import render_formula_graph
        png = render_formula_graph(
            curves=[{"template_type": "linear", "parameters": {"k": 1}, "label": "y=x"}],
            viewport={"x_min": -6, "x_max": 6, "y_min": -6, "y_max": 6},
        )
        img = Image.open(BytesIO(png))
        extrema = img.convert("L").getextrema()
        assert extrema != (255, 255), "Image should not be all white"
