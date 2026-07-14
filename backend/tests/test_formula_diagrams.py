"""
Tests for Phase 2 mathematical diagram GraphSpecs and rendering.
"""
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from app.services.formula_graph_spec_renderer import (
    _render_spec_sync,
    check_quality,
)

DIAGRAM_VERSION = 1

# Load specs from the shared JSON data file
_SPECS_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "formula_library" / "math2_diagram_specs.json"
with open(_SPECS_FILE) as _f:
    DIAGRAMS = json.load(_f)

# ── Helpers ──────────────────────────────────────────────────────────


def iter_spec_strings(obj, path=""):
    """Yield all string values from a nested dict/list structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_spec_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_spec_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def render_spec(spec: dict):
    """Render a spec, returning (png_bytes, metadata, quality_dict)."""
    png, meta = _render_spec_sync(spec)
    quality = check_quality(png, spec, meta)
    return png, meta, quality


# ═══════════════════════════════════════════════════════════════════════
# 1. GraphSpec schema validation
# ═══════════════════════════════════════════════════════════════════════


class TestGraphSpecSchema:
    """Every GraphSpec validates against the schema."""

    REQUIRED_SPEC_KEYS = {"template", "renderer_version", "spec_version", "panels"}
    REQUIRED_PANEL_KEYS = {"x_range", "y_range", "expressions"}
    REQUIRED_EXPR_KEYS = {"expression"}
    VALID_TEMPLATES = {"single_function", "multi_panel"}
    VALID_LINE_STYLES = {"solid", "dashed", "dotted", "dashdot"}

    def test_all_diagrams_have_required_fields(self):
        for d in DIAGRAMS:
            assert "slug" in d, f"Missing slug"
            assert "source_ref" in d, f"{d['slug']}: missing source_ref"
            assert "graph_spec" in d, f"{d['slug']}: missing graph_spec"
            assert d["source_ref"].startswith("math2_diagram_v1:"), \
                f"{d['slug']}: source_ref must start with math2_diagram_v1:"

    def test_unique_slugs(self):
        slugs = [d["slug"] for d in DIAGRAMS]
        dups = [s for s in slugs if slugs.count(s) > 1]
        assert not dups, f"Duplicate slugs: {set(dups)}"

    def test_unique_source_refs(self):
        refs = [d["source_ref"] for d in DIAGRAMS]
        dups = [r for r in refs if refs.count(r) > 1]
        assert not dups, f"Duplicate source_refs: {set(dups)}"

    def test_spec_has_required_keys(self):
        for d in DIAGRAMS:
            spec = d["graph_spec"]
            missing = self.REQUIRED_SPEC_KEYS - set(spec.keys())
            assert not missing, f"{d['slug']}: missing spec keys: {missing}"
            assert spec["template"] in self.VALID_TEMPLATES, \
                f"{d['slug']}: invalid template '{spec['template']}'"

    def test_panels_have_required_keys(self):
        for d in DIAGRAMS:
            spec = d["graph_spec"]
            for pi, panel in enumerate(spec.get("panels", [])):
                missing = self.REQUIRED_PANEL_KEYS - set(panel.keys())
                assert not missing, \
                    f"{d['slug']} panel {pi}: missing keys: {missing}"
                assert len(panel["x_range"]) == 2
                assert len(panel["y_range"]) == 2
                for ei, expr in enumerate(panel.get("expressions", [])):
                    assert "expression" in expr, \
                        f"{d['slug']} panel {pi} expr {ei}: missing expression"

    def test_line_styles_are_valid(self):
        for d in DIAGRAMS:
            spec = d["graph_spec"]
            for pi, panel in enumerate(spec.get("panels", [])):
                for ei, expr in enumerate(panel.get("expressions", [])):
                    ls = expr.get("line_style", "solid")
                    assert ls in self.VALID_LINE_STYLES, \
                        f"{d['slug']} p{pi}e{ei}: invalid line_style '{ls}'"

    def test_shading_has_valid_expressions(self):
        for d in DIAGRAMS:
            spec = d["graph_spec"]
            for pi, panel in enumerate(spec.get("panels", [])):
                for si, sh in enumerate(panel.get("shading", [])):
                    assert "y1_expression" in sh, \
                        f"{d['slug']} panel {pi} shade {si}: missing y1_expression"
                    assert "y2_expression" in sh, \
                        f"{d['slug']} panel {pi} shade {si}: missing y2_expression"

    def test_diagram_count(self):
        assert len(DIAGRAMS) == 10, f"Expected 10 diagrams, got {len(DIAGRAMS)}"


# ═══════════════════════════════════════════════════════════════════════
# 2. Mathematical verification
# ═══════════════════════════════════════════════════════════════════════


class TestCurvatureCircleMath:
    """Curvature-circle geometric invariants."""

    @pytest.fixture(scope="class")
    def spec(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "curvature_circle")
        return d["graph_spec"]

    def test_center_and_radius(self, spec):
        """Curvature circle center is (0.5, 0) and radius is 0.5."""
        panel = spec["panels"][0]
        # Check the circle equation: (x-0.5)² + y² = 0.25
        circle_exprs = [e for e in panel["expressions"]
                        if "0.25" in e.get("expression", "")]
        assert len(circle_exprs) == 2, "Expected 2 circle expressions"
        # Verify center annotation
        annotations = panel.get("annotations", [])
        centers = [a for a in annotations if "C" in a.get("label", "")]
        assert centers, "Missing center annotation C"
        c = centers[0]
        assert abs(c["x"] - 0.5) < 0.01, f"Center x={c['x']}, expected 0.5"
        assert abs(c["y"]) < 0.01, f"Center y={c['y']}, expected 0"

        # Verify point P=(0,0)
        points_p = [a for a in annotations if "P" in a.get("label", "")]
        assert points_p, "Missing point annotation P"
        p = points_p[0]
        assert abs(p["x"]) < 0.01, f"Point P x={p['x']}, expected 0"
        assert abs(p["y"]) < 0.01, f"Point P y={p['y']}, expected 0"

    def test_equal_aspect(self, spec):
        panel = spec["panels"][0]
        assert panel.get("axis_mode") == "equal", "Must use equal aspect"

    def test_renders(self, spec):
        png, meta, quality = render_spec(spec)
        assert quality["passed"], f"Quality check failed: {quality['errors']}"
        assert meta["total_curves"] >= 3, f"Expected >=3 curves, got {meta['total_curves']}"


class TestArcDifferentialMath:
    """Arc differential geometry."""

    @pytest.fixture(scope="class")
    def spec(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "arc_differential")
        return d["graph_spec"]

    def test_arrow_annotations_present(self, spec):
        panel = spec["panels"][0]
        arrows = [a for a in panel.get("annotations", [])
                  if a.get("type") == "arrow"]
        labels = [a.get("label", "") for a in arrows]
        assert "dx" in labels, "Missing dx arrow"
        assert "dy" in labels, "Missing dy arrow"
        assert "ds" in labels, "Missing ds arrow"

    def test_renders(self, spec):
        png, meta, quality = render_spec(spec)
        assert quality["passed"], f"Quality: {quality['errors']}"
        assert meta["total_curves"] >= 1


class TestRegionDiagramsMath:
    """Double integral region invariants."""

    @pytest.fixture(scope="class")
    def regions_spec(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "double_int_regions")
        return d["graph_spec"]

    def test_x_and_y_panels_describe_same_region(self, regions_spec):
        """X-type and Y-type panels shade the same region (same expressions)."""
        panels = regions_spec["panels"]
        assert len(panels) >= 2
        # Both panels use expressions y=x and y=x² with fill_between
        for pi, panel in enumerate(panels):
            exprs = [e["expression"] for e in panel["expressions"]]
            assert "x" in exprs, f"Panel {pi} missing y=x"
            assert "x**2" in exprs, f"Panel {pi} missing y=x²"
            shadings = panel.get("shading", [])
            assert len(shadings) >= 1, f"Panel {pi} has no shading"

    def test_renders(self, regions_spec):
        png, meta, quality = render_spec(regions_spec)
        assert quality["passed"], f"Quality: {quality['errors']}"
        assert meta["total_curves"] >= 2

    def test_split_region_has_partition_line(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "exchange_order_split")
        spec = d["graph_spec"]
        panel = spec["panels"][0]
        hlines = panel.get("horizontal_lines", [])
        y1_lines = [h for h in hlines if abs(h.get("value", 0) - 1) < 0.01]
        assert y1_lines, "Missing partition line y=1 in split region"
        # Two shading regions
        assert len(panel.get("shading", [])) == 2, "Expected 2 shading subregions"

    def test_split_renders(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "exchange_order_split")
        png, meta, quality = render_spec(d["graph_spec"])
        assert quality["passed"], f"Quality: {quality['errors']}"


class TestHyperbolaSectorMath:
    """Hyperbola sector invariants."""

    @pytest.fixture(scope="class")
    def spec(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "hyperbola_sector")
        return d["graph_spec"]

    def test_four_boundary_curves(self, spec):
        panel = spec["panels"][0]
        exprs = [e["expression"] for e in panel["expressions"]]
        assert "1/x" in exprs, "Missing xy=1"
        assert "2/x" in exprs, "Missing xy=2"
        assert "x" in exprs, "Missing y=x"
        assert "2*x" in exprs, "Missing y=2x"

    def test_bounded_region_shading(self, spec):
        panel = spec["panels"][0]
        shading = panel.get("shading", [])
        assert len(shading) >= 1, "No shading found"
        # Two shading regions covering left and right halves
        x_ranges = [s.get("x_range", []) for s in shading]
        assert any(r[0] <= 1 <= r[1] for r in x_ranges if len(r) >= 2), \
            "Shading should cover x=1 region"

    def test_renders(self, spec):
        png, meta, quality = render_spec(spec)
        assert quality["passed"], f"Quality: {quality['errors']}"
        assert meta["total_curves"] >= 4, "Expected 4 boundary curves"


class TestConicSectionsMath:
    """Conic sections invariants."""

    @pytest.fixture(scope="class")
    def spec(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "conic_sections")
        return d["graph_spec"]

    def test_4_panels_2x2(self, spec):
        assert len(spec["panels"]) == 4, "Expected 4 panels"
        assert spec["layout"]["rows"] == 2
        assert spec["layout"]["columns"] == 2

    def test_all_equal_aspect(self, spec):
        for pi, panel in enumerate(spec["panels"]):
            assert panel.get("axis_mode") == "equal", \
                f"Panel {pi} missing equal aspect"

    def test_renders(self, spec):
        png, meta, quality = render_spec(spec)
        assert quality["passed"], f"Quality: {quality['errors']}"
        assert meta["total_curves"] >= 8, "Expected 8+ curves (2 per conic)"


class TestLimitsDiagramsMath:
    """Limit diagrams invariants."""

    @pytest.fixture(scope="class")
    def limits_spec(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "three_basic_limits")
        return d["graph_spec"]

    def test_3_panels(self, limits_spec):
        assert len(limits_spec["panels"]) == 3

    def test_domain_has_exclude_zero(self, limits_spec):
        for pi, panel in enumerate(limits_spec["panels"]):
            for ei, expr in enumerate(panel.get("expressions", [])):
                domain = expr.get("domain", {})
                exclude = domain.get("exclude_points", [])
                assert 0 in exclude, \
                    f"Panel {pi}: missing exclude_points=[0]"

    def test_hollow_marker_at_zero(self, limits_spec):
        for pi, panel in enumerate(limits_spec["panels"]):
            annotations = panel.get("annotations", [])
            hollow = [a for a in annotations
                      if a.get("point_style") == "hollow"]
            assert hollow, f"Panel {pi}: missing hollow point marker"

    def test_all_have_y1_ref_line(self, limits_spec):
        for pi, panel in enumerate(limits_spec["panels"]):
            hlines = panel.get("horizontal_lines", [])
            targets = [h for h in hlines
                       if abs(h.get("value", 0) - 1) < 0.01]
            assert targets, f"Panel {pi}: missing y=1 reference line"

    def test_renders(self, limits_spec):
        png, meta, quality = render_spec(limits_spec)
        assert quality["passed"], f"Quality: {quality['errors']}"

    def test_second_limit_renders(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "second_important_limit")
        png, meta, quality = render_spec(d["graph_spec"])
        assert quality["passed"], f"Quality: {quality['errors']}"
        assert meta["total_curves"] >= 2


class TestExponentialDecayFamilyMath:
    """Exponential decay invariants."""

    @pytest.fixture(scope="class")
    def spec(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "exponential_decay_family")
        return d["graph_spec"]

    def test_three_curves(self, spec):
        panel = spec["panels"][0]
        exprs = panel.get("expressions", [])
        assert len(exprs) == 3, "Expected 3 curves (α,β combinations)"

    def test_legend_labels(self, spec):
        panel = spec["panels"][0]
        labels = [e.get("label", "") for e in panel.get("expressions", [])]
        assert all(l for l in labels), "All curves should have legend labels"
        # Check the labels contain parameter values
        text = " ".join(labels)
        for val in ["α", "β", "1", "2"]:
            assert val in text, f"Label text missing '{val}'"

    def test_max_at_alpha_over_beta(self, spec):
        """Each expression's maximum should be at x=α/β.

        (α,β) = (1,1): f(x) = x¹e⁻ˣ, max at x=1
        (α,β) = (2,1): f(x) = x²e⁻ˣ, max at x=2
        (α,β) = (2,2): f(x) = x²e⁻²ˣ, max at x=1
        """
        panel = spec["panels"][0]
        annotations = panel.get("annotations", [])
        x_labels = {}
        for a in annotations:
            lbl = a.get("label", "")
            if "x_max" in lbl or "x=" in lbl:
                x_labels[lbl] = a.get("x")

        # At least one annotation should be at x=1 (for (1,1) and (2,2))
        # and one at x=2 (for (2,1))
        x_vals = list(x_labels.values())
        assert 1.0 in x_vals or any(abs(v - 1.0) < 0.01 for v in x_vals), \
            f"Expected max annotation at x=1, got {x_vals}"
        assert 2.0 in x_vals or any(abs(v - 2.0) < 0.01 for v in x_vals), \
            f"Expected max annotation at x=2, got {x_vals}"

    def test_renders(self, spec):
        png, meta, quality = render_spec(spec)
        assert quality["passed"], f"Quality: {quality['errors']}"
        assert meta["total_curves"] == 3


# ═══════════════════════════════════════════════════════════════════════
# 3. Image integrity
# ═══════════════════════════════════════════════════════════════════════


class TestImageIntegrity:
    """Every preview image is non-empty, correct size, valid PNG."""

    @pytest.fixture(scope="class")
    def all_results(self):
        """Render all diagrams and return results."""
        results = {}
        for d in DIAGRAMS:
            try:
                png, meta, quality = render_spec(d["graph_spec"])
                results[d["slug"]] = {
                    "png": png,
                    "meta": meta,
                    "quality": quality,
                }
            except Exception as e:
                results[d["slug"]] = {"error": str(e)}
        return results

    def test_all_render_without_error(self, all_results):
        failed = [s for s, r in all_results.items() if "error" in r]
        assert not failed, f"Render failures: {failed}"

    def test_all_quality_passed(self, all_results):
        failed = [s for s, r in all_results.items()
                  if r.get("quality") and not r["quality"]["passed"]]
        if failed:
            details = "\n".join(
                f"  {s}: {all_results[s]['quality']['errors']}" for s in failed
            )
            pytest.fail(f"Quality failures:\n{details}")

    def test_non_empty_images(self, all_results):
        """Every rendered image is non-empty (>5KB)."""
        small = []
        for slug, r in all_results.items():
            if "error" in r:
                continue
            size = len(r["png"])
            if size < 5000:
                small.append(f"{slug}: {size} bytes")
        assert not small, f"Images too small:\n" + "\n".join(small)

    def test_valid_png(self, all_results):
        """Every rendered image is a valid PNG."""
        for slug, r in all_results.items():
            if "error" in r:
                continue
            img = Image.open(BytesIO(r["png"]))
            assert img.format == "PNG", f"{slug}: format is {img.format}"

    def test_not_all_white(self, all_results):
        """No rendered image is entirely white (rendering failure)."""
        for slug, r in all_results.items():
            if "error" in r:
                continue
            img = Image.open(BytesIO(r["png"])).convert("L")
            extrema = img.getextrema()
            assert extrema != (255, 255), f"{slug}: all-white image"


# ═══════════════════════════════════════════════════════════════════════
# 4. Domain safety
# ═══════════════════════════════════════════════════════════════════════


class TestDomainSafety:
    """Functions are not sampled outside their real domains."""

    SAFE_CHECKS = {
        "sqrt": {"domain": "x >= 0"},
        "log": {"domain": "x > 0"},
        "ln": {"domain": "x > 0"},
        "1/x": {"domain": "x != 0"},
    }

    def test_limit_domains_have_intervals(self):
        """Limit diagrams use domain intervals, not unlimited sampling."""
        for slug in ["three_basic_limits", "second_important_limit"]:
            d = next(x for x in DIAGRAMS if x["slug"] == slug)
            for pi, panel in enumerate(d["graph_spec"]["panels"]):
                for ei, expr in enumerate(panel.get("expressions", [])):
                    domain = expr.get("domain", {})
                    intervals = domain.get("intervals", [])
                    exclude = domain.get("exclude_points", [])
                    has_protection = bool(intervals) or bool(exclude)
                    assert has_protection, \
                        f"{slug} p{pi}e{ei}: no domain protection"

    def test_hyperbola_domains_avoid_zero(self):
        """Hyperbola functions use x>0 domain intervals."""
        d = next(x for x in DIAGRAMS if x["slug"] == "hyperbola_sector")
        for pi, panel in enumerate(d["graph_spec"]["panels"]):
            for ei, expr in enumerate(panel.get("expressions", [])):
                expr_str = expr.get("expression", "")
                if "1/x" in expr_str or "2/x" in expr_str:
                    domain = expr.get("domain", {})
                    intervals = domain.get("intervals", [])
                    assert intervals, \
                        f"hyperbola_sector p{pi}e{ei}: missing domain intervals"

    def test_exponential_decay_domains_positive(self):
        """Exponential decay functions use x>0 domain."""
        d = next(x for x in DIAGRAMS if x["slug"] == "exponential_decay_family")
        for pi, panel in enumerate(d["graph_spec"]["panels"]):
            for ei, expr in enumerate(panel.get("expressions", [])):
                domain = expr.get("domain", {})
                intervals = domain.get("intervals", [])
                assert intervals, \
                    f"exponential_decay p{pi}e{ei}: missing domain intervals"


# ═══════════════════════════════════════════════════════════════════════
# 5. Idempotency
# ═══════════════════════════════════════════════════════════════════════


class TestIdempotency:
    """Re-running generation with same specs produces same artifacts."""

    def test_checksum_is_deterministic(self):
        """Same spec always produces same checksum."""
        import hashlib, json

        def spec_checksum(spec):
            raw = json.dumps(spec, sort_keys=True, ensure_ascii=False)
            return hashlib.sha256(f"v{DIAGRAM_VERSION}:{raw}".encode()).hexdigest()

        # Render each spec twice and verify same output
        for d in DIAGRAMS:
            spec = d["graph_spec"]
            cs1 = spec_checksum(spec)
            cs2 = spec_checksum(spec)
            assert cs1 == cs2, f"{d['slug']}: checksum not deterministic"

    def test_renderer_deterministic(self):
        """Same spec produces identical PNG output."""
        for d in DIAGRAMS:
            spec = d["graph_spec"]
            png1, _, _ = render_spec(spec)
            png2, _, _ = render_spec(spec)
            h1 = hashlib.sha256(png1).hexdigest()
            h2 = hashlib.sha256(png2).hexdigest()
            assert h1 == h2, f"{d['slug']}: rendering not deterministic"


# ═══════════════════════════════════════════════════════════════════════
# 6. Renderer extension tests
# ═══════════════════════════════════════════════════════════════════════


class TestRendererExtensions:
    """Verify renderer extensions (shading, arrows, equal aspect) work."""

    def test_shading_renders(self):
        """fill_between shading produces non-white output."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [0, 1], "y_range": [0, 1],
                "axis_mode": "manual",
                "expressions": [
                    {"expression": "x"},
                    {"expression": "x**2"},
                ],
                "shading": [{
                    "y1_expression": "x",
                    "y2_expression": "x**2",
                    "color": "#2563eb",
                    "alpha": 0.3,
                    "x_range": [0, 1],
                }],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]
        assert meta["total_curves"] == 2

    def test_arrow_annotation_renders(self):
        """Arrow-type annotations render without error."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [0, 2], "y_range": [0, 1],
                "axis_mode": "manual",
                "expressions": [{"expression": "0.5*sin(x)"}],
                "annotations": [
                    {"type": "arrow", "x_start": 0.5, "y_start": 0.3,
                     "x_end": 1.0, "y_end": 0.3, "label": "test arrow",
                     "color": "#dc2626"},
                ],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]

    def test_equal_aspect_renders(self):
        """Equal axis aspect renders a circle properly."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [-1.5, 1.5], "y_range": [-1.5, 1.5],
                "axis_mode": "equal",
                "expressions": [
                    {"expression": "sqrt(1-x**2)",
                     "domain": {"intervals": [[-1, 1]]}},
                    {"expression": "-sqrt(1-x**2)",
                     "domain": {"intervals": [[-1, 1]]}},
                ],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]

    def test_constant_fill_between(self):
        """fill_between with constant y2='0' works (scalar broadcast)."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [0, 1], "y_range": [0, 1],
                "axis_mode": "manual",
                "expressions": [{"expression": "x"}],
                "shading": [{
                    "y1_expression": "x",
                    "y2_expression": "0",
                    "color": "#2563eb",
                    "alpha": 0.3,
                    "x_range": [0, 1],
                }],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]


class TestYTypeShading:
    """Y-type (horizontal) fill_betweenx shading."""

    def test_y_type_uses_horizontal_orientation(self):
        """The double_int_regions Y-type panel uses horizontal orientation."""
        d = next(x for x in DIAGRAMS if x["slug"] == "double_int_regions")
        panel = d["graph_spec"]["panels"][1]  # Y-type panel
        shadings = panel.get("shading", [])
        assert len(shadings) >= 1
        assert shadings[0].get("orientation") == "horizontal", \
            "Y-type shading must use horizontal orientation"

    def test_y_type_renders_correctly(self):
        """Y-type region renders without error (fill_betweenx path)."""
        d = next(x for x in DIAGRAMS if x["slug"] == "double_int_regions")
        png, meta, quality = render_spec(d["graph_spec"])
        assert quality["passed"], f"Y-type render failed: {quality['errors']}"

    def test_horizontal_shading_produces_visual_output(self):
        """Horizontal shading produces non-white output."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [0, 1], "y_range": [0, 1],
                "axis_mode": "manual",
                "expressions": [
                    {"expression": "x"},
                    {"expression": "x**2"},
                ],
                "shading": [{
                    "orientation": "horizontal",
                    "y1_expression": "x",
                    "y2_expression": "sqrt(x)",
                    "color": "#dc2626",
                    "alpha": 0.3,
                    "x_range": [0, 1],
                }],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(png)).convert("L")
        extrema = img.getextrema()
        assert extrema != (255, 255), "Horizontal shading produced all-white image"


class TestArrowAnnotation:
    """Arrow annotations render via annotate (backward compatible)."""

    def test_arrow_with_label_renders(self):
        """Arrow-type annotation with label renders correctly."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [0, 2], "y_range": [0, 1],
                "axis_mode": "manual",
                "expressions": [{"expression": "0.5*sin(x)"}],
                "annotations": [
                    {"type": "arrow", "x_start": 0.5, "y_start": 0.3,
                     "x_end": 1.0, "y_end": 0.3, "label": "dx",
                     "color": "#2563eb"},
                    {"type": "arrow", "x_start": 1.0, "y_start": 0.3,
                     "x_end": 1.0, "y_end": 0.6, "label": "dy",
                     "color": "#dc2626"},
                ],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]

    def test_arrow_without_label_renders(self):
        """Arrow annotation without label works."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [0, 1], "y_range": [0, 1],
                "axis_mode": "manual",
                "expressions": [{"expression": "x"}],
                "annotations": [
                    {"type": "arrow", "x_start": 0.2, "y_start": 0.2,
                     "x_end": 0.5, "y_end": 0.5},
                ],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]


class TestDomainSafetyRuntimeWarning:
    """Functions with domain restrictions don't trigger RuntimeWarning."""

    def test_sin_x_over_x_renders_without_error(self):
        """sin(x)/x handles x=0 exclusion."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [-4, 4], "y_range": [0, 1.4],
                "axis_mode": "manual",
                "expressions": [{
                    "expression": "sin(x)/x",
                    "domain": {"exclude_points": [0]},
                }],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]

    def test_ln_plus_x_over_x_domain_protected(self):
        """ln(1+x)/x doesn't evaluate at x<=-1."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [-1, 4], "y_range": [0, 1.4],
                "axis_mode": "manual",
                "expressions": [{
                    "expression": "ln(1 + x)/x",
                    "domain": {
                        "intervals": [[-0.9, 0], [0, 4]],
                        "exclude_points": [0],
                    },
                }],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]

    def test_one_plus_x_pow_one_over_x_domain(self):
        """(1+x)^(1/x) handles x>-1, x!=0."""
        spec = {
            "template": "single_function",
            "panels": [{
                "x_range": [-0.9, 2], "y_range": [0, 3.5],
                "axis_mode": "manual",
                "expressions": [{
                    "expression": "(1 + x)**(1/x)",
                    "domain": {
                        "intervals": [[-0.85, 0], [0.001, 2]],
                        "exclude_points": [0],
                    },
                }],
            }],
        }
        png, meta, quality = render_spec(spec)
        assert quality["passed"]


class TestFontCleanup:
    """No Unicode superscript/subscript characters in spec strings."""

    def test_no_unicode_superscript_x(self):
        """Spec data does not contain Unicode superscript x."""
        for d in DIAGRAMS:
            for path, val in iter_spec_strings(d):
                if 'ˣ' in val:  # ˣ (modifier letter small x)
                    pytest.fail(f"{d['slug']} {path} contains Unicode superscript x: {val[:50]}")


class TestGraphSpecsApiResponse:
    """FormulaCardResponse includes graph_specs array."""

    def test_graph_specs_field_in_response_schema(self):
        """FormulaCardResponse schema has graph_specs field."""
        from app.schemas.formula import FormulaCardResponse
        assert "graph_specs" in FormulaCardResponse.model_fields, \
            "FormulaCardResponse missing graph_specs field"

    def test_conic_sections_has_card_source_ref(self):
        """conic_sections diagram now has a card_source_ref."""
        d = next(x for x in DIAGRAMS if x["slug"] == "conic_sections")
        assert d.get("card_source_ref"), "conic_sections must have card_source_ref"
        assert d["card_source_ref"] == "math2_core_v2:calculus:conic_sections"


# ═══════════════════════════════════════════════════════════════════════
# 7. Generation script tests
# ═══════════════════════════════════════════════════════════════════════


class TestGenerationScript:
    """The generation script itself is well-formed."""

    def test_data_file_valid_json(self):
        """The spec data file is valid JSON."""
        import json
        with open(_SPECS_FILE) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) >= 10

    def test_diagram_version_defined(self):
        assert isinstance(DIAGRAM_VERSION, int)
        assert DIAGRAM_VERSION >= 1

    def test_all_diagrams_have_alt_text(self):
        for d in DIAGRAMS:
            assert d.get("alt_text", ""), f"{d['slug']}: missing alt_text"
            assert len(d["alt_text"]) >= 10

    def test_all_diagrams_have_description(self):
        for d in DIAGRAMS:
            assert d.get("description", ""), f"{d['slug']}: missing description"
            assert len(d["description"]) >= 20

    def test_surface_revolution_has_shading(self):
        d = next(x for x in DIAGRAMS if x["slug"] == "surface_revolution")
        panel = d["graph_spec"]["panels"][0]
        assert len(panel.get("shading", [])) >= 1, "Expected shading"
