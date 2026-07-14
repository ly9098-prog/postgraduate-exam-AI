# Phase 2: Mathematical Diagrams and Function Graphs

**Status**: Pending (Phase 1 — formula card seed — complete)
**Parent task**: `prompts/tasks/current_task.md` section VIII

## Scope

11 mathematical diagram cards that cannot be represented as simple function plots. These require multi-element diagrams with annotations, labels, and geometric constructions.

## Diagram inventory

| # | Slug | Description | GraphSpec type | Acceptance criteria |
|---|------|-------------|----------------|-------------------|
| 1 | curvature_circle | 曲率圆示意图 — curve, tangent, normal, curvature circle, center, radius ρ | multi-panel, annotations | All 6 elements labeled; correct circle tangent at point |
| 2 | arc_differential | 弧长与弧微分示意图 — ds/dx/dy right triangle on curve | single panel, annotations | ds²=dx²+dy² triangle visible; correct labeling |
| 3 | surface_revolution | 旋转曲面侧面积示意图 — curve revolving around axis, ds element, radius r | single panel, annotation | dS=2πr·ds element shown; rotation axis labeled |
| 4 | double_int_x_region | 二重积分X型区域 — a≤x≤b, φ₁(x)≤y≤φ₂(x) | single panel, shaded | Region shading correct; boundary functions labeled |
| 5 | double_int_y_region | 二重积分Y型区域 — c≤y≤d, ψ₁(y)≤x≤ψ₂(y) | single panel, shaded | Region shading correct; boundary functions labeled |
| 6 | exchange_order_split | 需要分区才能换序的积分区域 — region requiring 2+ integrals after exchange | single panel, partitioned | Split regions clearly demarcated; each sub-region labeled |
| 7 | hyperbola_sector | 双曲线与射线围成的区域 — xy=c, y=kx, intersection points, bounded area | single panel, shaded | Both curves visible; bounded region shaded; intersection marked |
| 8 | conic_sections | 常见二次曲线组合 — circle, ellipse, parabola, hyperbola combined | multi-panel or single comparison | All 4 conics distinguishable; key features labeled |
| 9 | three_basic_limits | 三个基本极限辅助图 — sin(x)/x, (e^x-1)/x, ln(1+x)/x → 1 as x→0 | multi-panel (3 panels) | All three approach y=1 near origin; axis limits appropriate |
| 10 | second_important_limit | 第二重要极限图 — (1+x)^{1/x} and (1+1/x)^x | multi-panel (2 panels) | Correct domain handling; approach to e visible |
| 11 | exponential_decay_family | 指数衰减型函数族 — x^α e^{-βx} for multiple (α,β) | multi-curve, single panel | Peak x=α/β marked; legend with actual parameter values |

## Implementation approach

Each diagram is a `function_graph` card with a `GraphSpec`. Implementation pipeline:

1. Design GraphSpec JSON for each diagram (expressions, panels, annotations, shading, reference lines)
2. Generate previews via existing `formula_graph_spec_service.py` `generate_preview()`
3. Quality review (auto + manual)
4. Confirm via `confirm_preview()` to create generated asset
5. Fill alt_text and description
6. Verify thumbnail readability on mobile

## Technical constraints

- Renderer: matplotlib + sympy subprocess (`formula_graph_spec_renderer.py`)
- Non-function elements (shading, annotations) must use GraphSpec's `shading`, `annotations`, `reference_lines`, `vertical_lines` fields
- Some diagrams lack a closed-form expression → use `type: "custom"` or parametric plotting
- 曲率圆 diagram: requires separate computation of curvature center from a sample curve
- 二重积分 regions: use `fill_between` type shading in the spec
- 基本极限 diagrams: use `ymin=0, ymax=1.5, xmin=-2, xmax=2` near-origin viewport

## Dependency on renderer capabilities

Check `formula_graph_spec_renderer.py` for support of:
- Region shading / fill_between
- Multi-curve legend with parameter values
- Non-function curve elements (circle, parametric)
- Dashed/dotted reference lines
- Arrow annotations for geometric labels

If the renderer does not support a required feature, note it as a gap and propose a workaround (e.g., manual SVG upload).

## Status tracking

| # | Slug | GraphSpec designed | Preview generated | Review passed | Confirmed |
|---|------|-------------------|-------------------|---------------|-----------|
| 1 | curvature_circle | ✓ | ✓ | ☐ (preview) | ☐ |
| 2 | arc_differential | ✓ | ✓ | ☐ (preview) | ☐ |
| 3 | surface_revolution | ✓ | ✓ | ☐ (preview) | ☐ |
| 4 | double_int_x_region | ✓ (combined as double_int_regions, 2-panel) | ✓ | ☐ (preview) | ☐ |
| 5 | double_int_y_region | ✓ (combined with x_region as 2-panel) | ✓ | ☐ (preview) | ☐ |
| 6 | exchange_order_split | ✓ | ✓ | ☐ (preview) | ☐ |
| 7 | hyperbola_sector | ✓ | ✓ | ☐ (preview) | ☐ |
| 8 | conic_sections | ✓ | ✗ (no card to attach) | N/A | N/A |
| 9 | three_basic_limits | ✓ | ✓ | ☐ (preview) | ☐ |
| 10 | second_important_limit | ✓ | ✓ | ☐ (preview) | ☐ |
| 11 | exponential_decay_family | ✓ | ✓ | ☐ (preview) | ☐ |

## Renderer capability matrix

| Capability | Supported | Implementation | Extension |
|---|---|---|---|
| Multi-panel rendering | ✓ | `_render_multi_panel()` | — |
| Parametric curves | ✗ | — | Not needed after split into y=f(x) branches |
| Implicit curves | ✗ | — | Split into y=f(x) branches |
| Equal axis aspect | ✓ (added in Phase 2) | `axis_mode: "equal"` → `set_aspect("equal")` | Added |
| Region shading (fill_between) | ✓ (added in Phase 2) | `panel.shading[]` → `ax.fill_between()` | Added |
| Multiple shaded subregions | ✓ (added in Phase 2) | Multiple shading entries per panel | Added |
| Circle/ellipse primitives | ✗ | Split into y=±f(x) branches | Workaround |
| Arrow annotations | ✓ (added in Phase 2) | `annotation.type: "arrow"` → `ax.arrow()` | Added |
| Open-circle markers | ✓ | `point_style: "hollow"` | — |
| Domain masks | ✓ | `domain.intervals`, `domain.exclude_points` | — |
| Discontinuity-safe plotting | ✓ | `_discontinuity_gap()` | — |
| Mobile thumbnail export | ✓ | `_create_thumbnail()` → 600×450 | — |
