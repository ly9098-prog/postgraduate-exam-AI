from app.services.practice.session_scope import (
    build_practice_session_scope,
    public_practice_session_scope,
)

def _exact_context():
    return {
        "v": 2,
        "practice_mode": "knowledge_chapter",
        "root_id": 12,
        "root_name": "线性表",
        "subject_id": 7,
        "syllabus_version_id": 1,
        "scope_ids": [12, 13, 25, 19, 128, 17],
        "served_ids": [13, 19, 17],
        "include_descendants": True,
        "scope_count": 6,
        "served_count": 3,
        "baseline": {
            "root": [62.5, 0.55, 4, 10, 18],
            "points": [[13, 55.0, 0.5, 3], [19, None, 0.0, 0], [17, 40.0, 0.6, 2]],
        },
    }


def test_exact_scope_snapshot_is_complete_and_drops_mastery_baseline():
    snapshot = build_practice_session_scope(_exact_context(), fallback_subject_id=99)
    assert snapshot is not None
    assert snapshot["practice_mode"] == "knowledge_chapter"
    assert snapshot["subject_id"] == 7
    assert snapshot["syllabus_version_id"] == 1
    assert snapshot["root_knowledge_point_id"] == 12
    assert snapshot["resolved_knowledge_point_ids"] == [12, 13, 25, 19, 128, 17]
    assert snapshot["served_knowledge_point_ids"] == [13, 19, 17]
    assert snapshot["resolved_ids_complete"] is True
    assert snapshot["served_ids_complete"] is True
    assert "baseline" not in snapshot


def test_legacy_stage5_context_is_accepted_without_inventing_resolved_ids():
    context = {
        "v": 1,
        "practice_mode": "knowledge_chapter",
        "root_id": 12,
        "root_name": "线性表",
        "include_descendants": True,
        "scope_count": 18,
        "baseline": {
            "root": [62.5, 0.55, 4, 10, 18],
            "points": [[13, 55.0, 0.5, 3], [25, None, 0.0, 0]],
        },
    }
    snapshot = build_practice_session_scope(context, fallback_subject_id=7)
    assert snapshot is not None
    assert snapshot["subject_id"] == 7
    assert snapshot["resolved_knowledge_point_count"] == 18
    assert snapshot["resolved_knowledge_point_ids"] == []
    assert snapshot["resolved_ids_complete"] is False
    assert snapshot["served_knowledge_point_ids"] == [13, 25]
    assert snapshot["served_ids_complete"] is True


def test_public_scope_normalizes_ids_and_keeps_historical_name():
    snapshot = build_practice_session_scope(_exact_context())
    public = public_practice_session_scope(snapshot)
    assert public is not None
    assert public["root_name"] == "线性表"
    assert public["resolved_knowledge_point_count"] == 6
    assert public["served_knowledge_point_count"] == 3
    assert public["resolved_ids_complete"] is True
