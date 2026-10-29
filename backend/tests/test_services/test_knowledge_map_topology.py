"""Parent priority, cycle rejection and syllabus tree ordering contracts."""

from types import SimpleNamespace

from app.services import knowledge_map_service as service


def _point(point_id):
    return SimpleNamespace(id=point_id, name=f"point {point_id}")


def _edge(parent, child, source="manual", confidence=0.8, weight=1.0):
    return SimpleNamespace(
        source_knowledge_point_id=parent,
        target_knowledge_point_id=child,
        relation_type="parent",
        is_active=True,
        source=source,
        confidence=confidence,
        weight=weight,
    )


def test_parent_priority_rejects_cycles_and_external_endpoints():
    points = [_point(i) for i in range(1, 5)]
    edges = [
        _edge(1, 2, "ai", 1.0),
        _edge(3, 2, "manual", 0.1),
        _edge(2, 3),
        _edge(2, 4),
        _edge(4, 4),
        _edge(99, 1),
    ]
    assert service._build_parent_map(points, edges) == {3: 2, 4: 2, 2: 1}


def test_tree_uses_snapshot_order_and_clamps_display_depth():
    points = [_point(i) for i in range(1, 13)]
    parents = {i: i - 1 for i in range(3, 13)}
    members = {
        1: SimpleNamespace(sort_order=20, name_snapshot="a"),
        2: SimpleNamespace(sort_order=10, name_snapshot="z"),
    }
    rows = service._ordered_tree_rows(points, parents, members)
    assert [row[0].id for row in rows] == [*range(2, 13), 1]
    assert [row[1] for row in rows] == [*range(9), 8, 8, 0]
    assert rows[-1][2:] == (None, 0)


def test_tree_fallback_visits_cyclic_legacy_fragment_once():
    rows = service._ordered_tree_rows([_point(1), _point(2)], {1: 2, 2: 1})
    assert [(point.id, depth) for point, depth, _, _ in rows] == [(1, 0), (2, 1)]
