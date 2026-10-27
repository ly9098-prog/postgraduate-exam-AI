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


def test_scope_rejects_non_dict_missing_root_and_unknown_mode_without_reads():
    class Context(dict):
        def __init__(self, value=None):
            super().__init__(value or {})
            self.reads = []

        def get(self, key, default=None):
            self.reads.append(key)
            return super().get(key, default)

    assert build_practice_session_scope(None) is None
    assert build_practice_session_scope([]) is None
    missing = Context()
    assert build_practice_session_scope(missing) is None
    assert missing.reads == ["root_id"]

    defaulted = build_practice_session_scope({"root_id": 1})
    assert defaulted["practice_mode"] == "knowledge_point"
    assert defaulted["resolved_knowledge_point_count"] == 1

    invalid_mode = Context({"root_id": 1, "practice_mode": "unknown"})
    assert build_practice_session_scope(invalid_mode) is None
    assert invalid_mode.reads == ["root_id", "practice_mode"]


def test_scope_identity_conversion_and_subject_fallback_boundaries():
    class Value:
        def __init__(self, value):
            self.value = value

        def __int__(self):
            return self.value

    context = {
        "root_id": Value(12),
        "practice_mode": "knowledge_point",
        "subject_id": Value(0),
        "syllabus_version_id": Value(3),
        "v": "4",
    }
    snapshot = build_practice_session_scope(context, fallback_subject_id=7)
    assert snapshot["subject_id"] == 7
    assert snapshot["syllabus_version_id"] == 3
    assert snapshot["source_context_version"] == 4

    context["subject_id"] = Value(9)
    context["v"] = None
    assert build_practice_session_scope(context)["subject_id"] == 9
    assert build_practice_session_scope(context)["source_context_version"] == 1


def test_scope_id_normalization_dedupes_and_preserves_first_positive_order():
    context = {
        "root_id": 1,
        "scope_ids": ("2", 2, 0, -1, None, "3"),
        "served_ids": ["3", "bad", 3],
        "scope_count": 3,
    }
    snapshot = build_practice_session_scope(context)
    assert snapshot["resolved_knowledge_point_ids"] == [2, 3]
    assert snapshot["served_knowledge_point_ids"] == [3]
    assert snapshot["resolved_knowledge_point_count"] == 3
    assert snapshot["served_knowledge_point_count"] == 1
    assert snapshot["resolved_ids_complete"] is False
    assert snapshot["served_ids_complete"] is True


def test_exact_scope_filters_served_ids_after_legacy_fallback():
    context = {
        "root_id": 1,
        "scope_ids": [1, 2],
        "scope_count": 2,
        "served_ids": None,
        "baseline": {"points": [[2], [3], ["bad"], []]},
    }
    snapshot = build_practice_session_scope(context)
    assert snapshot["resolved_ids_complete"] is True
    assert snapshot["served_knowledge_point_ids"] == [2]
    assert snapshot["served_ids_complete"] is True


def test_scope_snapshot_field_order_is_exact():
    context = {
        "v": 2,
        "practice_mode": "knowledge_chapter",
        "root_id": 1,
        "subject_id": 7,
        "root_name": "root",
        "include_descendants": True,
        "scope_ids": [1],
        "scope_count": 1,
        "served_ids": [1],
    }
    assert list(build_practice_session_scope(context)) == [
        "v",
        "source_context_version",
        "practice_mode",
        "subject_id",
        "syllabus_version_id",
        "root_knowledge_point_id",
        "root_name",
        "include_descendants",
        "resolved_knowledge_point_ids",
        "served_knowledge_point_ids",
        "resolved_knowledge_point_count",
        "served_knowledge_point_count",
        "resolved_ids_complete",
        "served_ids_complete",
    ]
