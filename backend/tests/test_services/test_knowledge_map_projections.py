"""Characterize map projections independently of database loading."""

from types import SimpleNamespace

import pytest

from app.services import knowledge_map_service as service


def _point(point_id):
    return SimpleNamespace(
        id=point_id,
        name=f"point {point_id}",
        aliases=[],
        description=None,
        difficulty_level=0,
    )


def _state(mastery, confidence=0.8, attempts=4):
    return SimpleNamespace(
        mastery_score=mastery,
        confidence=confidence,
        attempt_count=attempts,
        correct_count=1,
        wrong_count=3,
        recent_wrong_count=2,
        last_practiced_at=None,
    )


@pytest.mark.parametrize(
    ("attempts", "mastery", "confidence", "expected"),
    [
        (0, 90, 1, "no_data"),
        (1, None, 1, "insufficient"),
        (1, 90, 0.299, "insufficient"),
        (1, 39.99, 0.3, "weak"),
        (1, 40, 0.3, "developing"),
        (1, 70, 0.3, "good"),
        (1, 85, 0.3, "mastered"),
    ],
)
def test_status_thresholds(attempts, mastery, confidence, expected):
    assert (
        service._state_status(
            attempts=attempts,
            mastery=mastery,
            confidence=confidence,
        )
        == expected
    )


def test_subject_and_subtree_keep_distinct_missing_mastery_semantics():
    points = [_point(1)]
    states = {1: _state(None)}
    subject = SimpleNamespace(id=10, code="data_structure", name="DS")
    summary = service._build_subject_summary(subject, points, states, {1: 1})
    subtree = service._build_hierarchy_metadata(points, {}, states, {1: 1})[1]
    assert summary["mastery_score"] == 50.0
    assert summary["reliable_knowledge_points"] == 1
    assert summary["status"] == "developing"
    assert subtree["subtree_mastery_score"] is None
    assert subtree["subtree_reliable_knowledge_points"] == 0
    assert subtree["subtree_status"] == "insufficient"


def test_subtree_requires_trainable_coverage_and_weights_question_counts():
    points = [_point(i) for i in range(1, 5)]
    parents = {2: 1, 3: 1, 4: 1}
    states = {2: _state(20), 3: _state(80), 4: _state(100)}
    counts = {2: 3, 3: 1}
    meta = service._build_hierarchy_metadata(points, parents, states, counts)
    root = meta[1]
    assert root["subtree_mastery_score"] == 35.0
    assert root["subtree_status"] == "weak"
    assert root["subtree_reliable_knowledge_points"] == 3
    assert root["subtree_coverage_ratio"] == 1.0
    assert meta[2]["ancestor_ids"] == [1]
    assert root["descendant_count"] == 3
    states.pop(3)
    root = service._build_hierarchy_metadata(points, parents, states, counts)[1]
    assert root["subtree_status"] == "insufficient"
    assert root["subtree_coverage_ratio"] == 0.5


def test_nontrainable_subtree_can_aggregate_reliable_observations():
    meta = service._build_hierarchy_metadata(
        [_point(1), _point(2)],
        {2: 1},
        {2: _state(85)},
        {},
    )
    assert meta[1]["subtree_status"] == "mastered"
    assert meta[1]["subtree_mastery_score"] == 85.0
    assert meta[1]["subtree_coverage_ratio"] == 0.0
    assert meta[1]["is_leaf"] is False


def test_node_snapshot_defaults_and_hierarchy_overrides():
    point = _point(1)
    point.aliases = [" alias ", None, "", 12]
    snapshot = SimpleNamespace(
        name_snapshot="snapshot",
        description_snapshot=None,
        difficulty_level_snapshot=0,
    )
    node = service._node_payload(
        point,
        state=_state(90, 0.2),
        trainable_question_count=0,
        parent_id=None,
        depth=8,
        child_count=3,
        hierarchy_meta={"direct_child_count": 0, "subtree_total_knowledge_points": 0},
        syllabus_item=snapshot,
    )
    assert node["name"] == "snapshot"
    assert node["aliases"] == ["alias", "12"]
    assert node["difficulty_level"] == 3
    assert node["child_count"] == 0
    assert node["is_leaf"] is True
    assert node["subtree_total_knowledge_points"] == 1
    assert node["mastery_score"] is None
    assert node["confidence"] == 0.2
    assert node["accuracy"] == 0.25
