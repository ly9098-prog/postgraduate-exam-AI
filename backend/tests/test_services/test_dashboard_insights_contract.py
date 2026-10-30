"""Characterize the existing insights entry points, including legacy edge cases."""

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.core.cache import cache
from app.services import dashboard_insights_service as svc
from app.services import stats_service


def result(*, one=None, rows=(), scalar=None):
    return SimpleNamespace(one=lambda: one, all=lambda: rows, scalar=lambda: scalar)


def database(*results):
    db = SimpleNamespace(execute=AsyncMock(side_effect=results))
    db.connection = AsyncMock(
        return_value=SimpleNamespace(
            sync_connection=SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
        )
    )
    return db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ((4, 4, 60), None),
        ((20, 20, 60), (100, "优秀", 1.0, 60)),
        ((10, 8, 0), (77, "良好", 0.8, 0.0)),
        ((5, 1, 300), (16, "需要加油", 0.2, 300)),
    ],
)
async def test_today_thresholds(row, expected):
    db = database(result(one=row))
    actual = await svc.compute_today_quality(db, 17)
    if expected is None:
        assert actual is None
    else:
        score, label, accuracy, avg = expected
        assert actual == {
            "data_available": True,
            "score": score,
            "label": label,
            "questions": row[0],
            "accuracy": accuracy,
            "avg_time_sec": avg,
        }
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_weekly_zero_fill_and_original_unbounded_query(monkeypatch):
    monkeypatch.setattr(svc, "shanghai_today", lambda: date(2026, 10, 30))
    db = database(result(rows=[("2026-10-29", 10, 8)]))
    actual = await svc.compute_weekly_consistency(db, 17, 2)
    assert actual == {
        "data_available": True,
        "score": 59,
        "label": "波动较大",
        "active_days": 1,
        "days": 2,
        "total_questions": 10,
        "day_breakdown": [
            {"date": "2026-10-29", "questions": 10, "accuracy": 0.8},
            {"date": "2026-10-30", "questions": 0, "accuracy": 0},
        ],
    }
    statement = db.execute.await_args.args[0]
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        sql = str(statement.compile(dialect=dialect))
        assert "practice_records.answered_at >=" in sql
        assert "practice_records.answered_at <" not in sql


@pytest.mark.asyncio
async def test_weak_topics_state_and_frozen_fallback(monkeypatch):
    serialize = MagicMock(return_value="serialized")
    monkeypatch.setattr(svc, "serialize_utc_datetime", serialize)
    due = AsyncMock(return_value={9: 4})
    monkeypatch.setattr(svc, "_compute_kp_due_review_counts", due)
    stamp = object()
    db = database(
        result(rows=[(9, "topic", None, None, None, 12.34, 5, 3, None, stamp)])
    )
    actual = await svc.compute_weak_topic_ranking(db, 17)
    assert actual["items"] == [
        {
            "knowledge_point_id": 9,
            "name": "topic",
            "subject_id": None,
            "subject_code": "",
            "subject_name": "",
            "mastery_score": 12.3,
            "attempt_count": 5,
            "wrong_count": 3,
            "recent_wrong_count": 0,
            "due_review_count": 4,
            "last_practiced_at": "serialized",
        }
    ]
    serialize.assert_called_once_with(stamp)
    due.assert_awaited_once_with(db, 17)
    db = database(result(), result(rows=[("frozen", 8)]))
    actual = await svc.compute_weak_topic_ranking(db, 17)
    item = actual["items"][0]
    assert item["name"] == "frozen" and item["mastery_score"] == 0
    assert item["knowledge_point_id"] == 0 and item["due_review_count"] == 0
    statement = db.execute.await_args.args[0]
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        sql = str(statement.compile(dialect=dialect))
        assert "FROM knowledge_points JOIN question_version_knowledge_points" in sql
    due.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("count", "label", "high"),
    [(3, "较低", False), (6, "中等", False), (7, "偏高", True)],
)
async def test_repeat_wrong_strict_boundaries(count, label, high):
    db = database(result(scalar=20), result(scalar=count), result(rows=[("frozen", 2)]))
    assert await svc.compute_repeat_wrong_analysis(db, 17) == {
        "data_available": True,
        "repeat_wrong_count": count,
        "total_wrong_count": 20,
        "repeat_rate": count / 20,
        "is_high": high,
        "status_label": label,
        "top_repeat_topics": [{"name": "frozen", "count": 2}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("averages", "counts", "status"),
    [
        ((30, 60, 10), (8, 8), "knowledge_gap"),
        ((30, 30, 10), (4, 4), "hasty"),
        ((30, 30, 10), (0, 4), "unfamiliar"),
        ((30, 30, 5), (4, 4), "normal"),
    ],
)
async def test_speed_priority_and_subject_thresholds(averages, counts, status):
    db = database(
        result(one=averages),
        result(one=counts),
        result(rows=[(1, None, None, 10, 16, 3), (2, "x", "x", 10, 20, 2)]),
    )
    actual = await svc.compute_speed_accuracy(db, 17)
    assert actual["overall_status"] == status
    assert actual["by_subject"] == [
        {
            "subject_id": 1,
            "subject_code": "",
            "subject_name": "",
            "avg_time_correct_sec": 10,
            "avg_time_wrong_sec": 16,
            "questions": 3,
            "status_label": "知识点不熟",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rows", "label", "summary"),
    [
        (
            [("new", 5, 2), ("review", 5, 4)],
            "复习效果较好",
            "复习题正确率高出40%，复习效果明显",
        ),
        (
            [("new", 5, 4), ("review", 5, 2)],
            "新题表现更佳",
            "新题正确率更高，可以适当增加新题练习",
        ),
        ([("new", 5, 4)], "侧重刷题", "新题练习较多，建议增加复习巩固"),
        ([("review", 5, 4)], "侧重复习", ""),
    ],
)
async def test_new_review_labels(rows, label, summary):
    actual = await svc.compute_new_vs_review(database(result(rows=rows)), 17)
    assert actual["label"] == label and actual["summary"] == summary


@pytest.mark.asyncio
async def test_input_output_filters_orders_and_overrides():
    db = database(
        result(
            rows=[
                (1, "a", "A", 10, 5, 1000),
                (2, "b", "B", 10, 9, 100),
                (3, "c", "C", 2, 2, 1),
            ]
        )
    )
    actual = await svc.compute_input_output(db, 17)
    assert actual["global_avg_time_sec"] == 55
    assert [(x["subject_id"], x["efficiency_score"]) for x in actual["items"]] == [
        (1, 0.28),
        (2, 4.95),
    ]
    assert (
        actual["items"][0]["suggestion"] == "正确率偏低，建议减少盲目刷题，优先复盘错题"
    )
    assert actual["items"][1]["suggestion"] == "掌握良好，可以保持节奏"


@pytest.mark.asyncio
async def test_action_plan_order_and_default():
    actual = await svc.compute_action_plan(
        object(),
        17,
        overview={"due_review_count": 2},
        repeat_wrong={"is_high": True, "repeat_wrong_count": 3, "repeat_rate": 0.4},
        weak_topics={
            "items": [{"name": "topic", "mastery_score": 12, "wrong_count": 8}]
        },
        new_vs_review={"label": "复习效果较好"},
    )
    assert [x["priority"] for x in actual["items"]] == [1, 2, 3, 4]
    assert [x["type"] for x in actual["items"]] == [
        "review",
        "wrong",
        "wrong",
        "practice",
    ]
    default = await svc.compute_action_plan(object(), 17)
    assert default["items"][0]["title"] == "保持练习节奏"


METRICS = [
    "compute_today_quality",
    "compute_weekly_consistency",
    "compute_weak_topic_ranking",
    "compute_repeat_wrong_analysis",
    "compute_speed_accuracy",
    "compute_new_vs_review",
    "compute_input_output",
]
OUTPUTS = [
    "today_quality",
    "weekly_consistency",
    "weak_topic_ranking",
    "repeat_wrong_analysis",
    "speed_accuracy",
    "new_vs_review",
    "input_output",
    "action_plan",
]


def patch_metrics(monkeypatch, failure=None):
    calls = []
    for name in METRICS:

        async def metric(*args, _name=name):
            calls.append((_name, args))
            if _name == "compute_speed_accuracy" and failure:
                raise failure
            return {"metric": _name}

        monkeypatch.setattr(svc, name, metric)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("subjects", [False, True])
@pytest.mark.parametrize("topics", [False, True])
async def test_aggregator_flags_order_session_cache_and_partial_error(
    monkeypatch, subjects, topics
):
    calls = patch_metrics(monkeypatch, ValueError("metric"))
    monkeypatch.setattr(cache, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(cache, "set", AsyncMock(side_effect=RuntimeError("cache")))
    overview = AsyncMock(return_value={"due_review_count": 0})
    monkeypatch.setattr(stats_service, "get_overview", overview)
    action = AsyncMock(return_value={"plan": True})
    monkeypatch.setattr(svc, "compute_action_plan", action)
    db = object()
    actual = await svc.get_dashboard_insights(
        db, 17, days=3, include_subjects=subjects, include_topics=topics
    )
    expected = [
        n
        for n in METRICS
        if (topics or n != METRICS[2]) and (subjects or n != METRICS[6])
    ]
    assert [n for n, _ in calls] == expected
    assert all(args[:2] == (db, 17) for _, args in calls)
    assert next(args for n, args in calls if n == METRICS[1]) == (db, 17, 3)
    assert list(actual) == OUTPUTS
    assert actual["speed_accuracy"] is None
    assert actual["weak_topic_ranking"] == ({"metric": METRICS[2]} if topics else None)
    assert actual["input_output"] == ({"metric": METRICS[6]} if subjects else None)
    overview.assert_awaited_once_with(db, 17)
    assert action.await_args.kwargs["weak_topics"] is actual["weak_topic_ranking"]
    cache.set.assert_awaited_once_with(
        f"stats:insights:17:3:{subjects}:{topics}", actual, ttl=120
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [{}, {"existing": True}])
async def test_cache_hit_returns_same_object_without_work(monkeypatch, cached):
    monkeypatch.setattr(cache, "get", AsyncMock(return_value=cached))
    monkeypatch.setattr(cache, "set", AsyncMock())
    metric = AsyncMock()
    monkeypatch.setattr(svc, "compute_today_quality", metric)
    assert await svc.get_dashboard_insights(object(), 17) is cached
    metric.assert_not_awaited()
    cache.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_metric_cancellation_is_preserved_as_value(monkeypatch):
    patch_metrics(monkeypatch, asyncio.CancelledError())
    monkeypatch.setattr(cache, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(cache, "set", AsyncMock())
    monkeypatch.setattr(stats_service, "get_overview", AsyncMock(return_value={}))
    actual = await svc.get_dashboard_insights(object(), 17)
    assert isinstance(actual["speed_accuracy"], asyncio.CancelledError)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_site", ["get", "overview", "set-cancel"])
async def test_non_metric_failures_propagate(monkeypatch, failure_site):
    patch_metrics(monkeypatch)
    error = (
        asyncio.CancelledError()
        if failure_site == "set-cancel"
        else RuntimeError("upstream")
    )
    monkeypatch.setattr(
        cache,
        "get",
        AsyncMock(
            side_effect=error if failure_site == "get" else None, return_value=None
        ),
    )
    monkeypatch.setattr(
        cache,
        "set",
        AsyncMock(side_effect=error if failure_site == "set-cancel" else None),
    )
    monkeypatch.setattr(
        stats_service,
        "get_overview",
        AsyncMock(
            side_effect=error if failure_site == "overview" else None, return_value={}
        ),
    )
    with pytest.raises(type(error)):
        await svc.get_dashboard_insights(object(), 17)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "results", "queries"),
    [
        ("compute_today_quality", [result(one=(None, None, None))], 1),
        ("compute_weekly_consistency", [result()], 1),
        ("compute_weak_topic_ranking", [result(), result()], 2),
        ("compute_repeat_wrong_analysis", [result(scalar=2)], 1),
        ("compute_speed_accuracy", [result(one=(None, None, None))], 1),
        ("compute_new_vs_review", [result(rows=[("new", 4, 4)])], 1),
        ("compute_input_output", [result(rows=[(1, None, None, 2, 2, 20)])], 1),
    ],
)
async def test_insufficient_data_stops_at_original_query(name, results, queries):
    db = database(*results)
    assert await getattr(svc, name)(db, 17) is None
    assert db.execute.await_count == queries


@pytest.mark.asyncio
async def test_serializer_lookup_remains_live_between_rows(monkeypatch):
    stamp = object()

    def first(value):
        monkeypatch.setattr(svc, "serialize_utc_datetime", lambda value: "second")
        return "first"

    monkeypatch.setattr(svc, "serialize_utc_datetime", first)
    monkeypatch.setattr(
        svc, "_compute_kp_due_review_counts", AsyncMock(return_value={})
    )
    rows = [(i, "topic", 1, "x", "X", 20, 3, 1, 0, stamp) for i in (1, 2)]
    actual = await svc.compute_weak_topic_ranking(database(result(rows=rows)), 17)
    assert [x["last_practiced_at"] for x in actual["items"]] == ["first", "second"]


@pytest.mark.asyncio
async def test_parent_cancellation_reaches_running_metric_tasks(monkeypatch):
    started = asyncio.Event()
    cancelled = []

    async def blocked(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    patch_metrics(monkeypatch)
    monkeypatch.setattr(svc, "compute_today_quality", blocked)
    monkeypatch.setattr(cache, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(cache, "set", AsyncMock())
    overview = AsyncMock()
    monkeypatch.setattr(stats_service, "get_overview", overview)
    task = asyncio.create_task(svc.get_dashboard_insights(object(), 17))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == [True]
    overview.assert_not_awaited()
    cache.set.assert_not_awaited()
