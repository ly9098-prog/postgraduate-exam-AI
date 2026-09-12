from datetime import datetime, timedelta

from app.services.knowledge_diagnosis_logic import (
    aggregate_session_stats,
    rank_chapter_recommendations,
)


def _node(kp_id, name, *, depth=0, ancestors=None, coverage=0.5, mastery=60, weak=1):
    return {
        "knowledge_point_id": kp_id,
        "name": name,
        "depth": depth,
        "ancestor_ids": ancestors or [],
        "has_children": True,
        "subtree_trainable_knowledge_points": 8,
        "subtree_reliable_knowledge_points": round(8 * coverage),
        "subtree_weak_knowledge_points": weak,
        "subtree_coverage_ratio": coverage,
        "subtree_status": "weak" if mastery is not None and mastery < 70 else "good",
        "subtree_mastery_score": mastery,
    }


def test_recommendations_prefer_distinct_weak_branches():
    now = datetime(2026, 9, 9, 12, 0, 0)
    nodes = [
        _node(10, "线性表", coverage=0.4, mastery=50, weak=4),
        _node(11, "链表", depth=1, ancestors=[10], coverage=0.2, mastery=40, weak=3),
        _node(20, "树与二叉树", coverage=0.3, mastery=48, weak=3),
        _node(30, "图", coverage=0.45, mastery=55, weak=2),
    ]
    result = rank_chapter_recommendations(nodes, {}, subject_id=7, now=now)
    ids = [item["knowledge_point_id"] for item in result]
    assert 11 in ids
    assert 20 in ids
    assert 30 in ids
    assert 10 not in ids  # ancestor/descendant overlap is suppressed on first pass
    assert result[0]["route_params"]["include_descendants"] == 1


def test_recent_practice_reduces_priority_against_stale_peer():
    now = datetime(2026, 9, 9, 12, 0, 0)
    nodes = [
        _node(20, "树与二叉树", coverage=0.6, mastery=64, weak=1),
        _node(30, "图", coverage=0.6, mastery=64, weak=1),
    ]
    stats = {
        20: {"session_count": 1, "last_practiced_at": now - timedelta(days=1)},
        30: {"session_count": 1, "last_practiced_at": now - timedelta(days=20)},
    }
    result = rank_chapter_recommendations(nodes, stats, subject_id=7, now=now, limit=2)
    assert [item["knowledge_point_id"] for item in result] == [30, 20]


def test_low_coverage_is_build_recommendation():
    now = datetime(2026, 9, 9, 12, 0, 0)
    nodes = [_node(20, "树与二叉树", coverage=0.1, mastery=None, weak=0)]
    nodes[0]["subtree_status"] = "insufficient"
    result = rank_chapter_recommendations(nodes, {}, subject_id=7, now=now, limit=1)
    assert result[0]["kind"] == "build"
    assert result[0]["action_label"] == "开始建立覆盖"


def test_nested_chapter_session_rolls_up_to_current_ancestor():
    finished = datetime(2026, 9, 9, 12, 0, 0)
    nodes = [
        {"knowledge_point_id": 10, "ancestor_ids": []},
        {"knowledge_point_id": 11, "ancestor_ids": [10]},
    ]
    sessions = [{
        "root_knowledge_point_id": 11,
        "question_count": 10,
        "correct_count": 7,
        "served_ids": {101, 102, 103},
        "finished_at": finished,
    }]
    stats, totals = aggregate_session_stats(nodes, sessions)
    assert stats[11]["session_count"] == 1
    assert stats[10]["session_count"] == 1
    assert stats[10]["question_count"] == 10
    assert totals["served_ids"] == {101, 102, 103}
