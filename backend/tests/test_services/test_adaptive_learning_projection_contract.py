"""Contracts for the adaptive-learning projection split.

These tests pin the observable behaviour of the eight entry points that the
refactor decomposed into documented helpers: traversal/filtering semantics,
projection fields, rounding, counters, delegation order, statement shapes and
best-effort degradation.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.services import adaptive_learning_service as als

NOW = datetime(2026, 10, 28, 3, 4, 5, tzinfo=UTC)
USER = 7


class Row:
    """Row double supporting attribute access like SQLAlchemy rows."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class IndexRow:
    """Row double for statements read positionally (``row[0]``)."""

    def __init__(self, *values):
        self.values = values

    def __getitem__(self, index):
        return self.values[index]


class _Scalars:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


_UNSET = object()


class Result:
    def __init__(
        self, *, rows=(), one=None, scalar_one=_UNSET, scalar_one_or_none=_UNSET
    ):
        self._rows = list(rows)
        self._one = one
        self._scalar_one = scalar_one
        if scalar_one_or_none is _UNSET:
            self._scalar_one_or_none = self._rows[0] if self._rows else None
        else:
            self._scalar_one_or_none = scalar_one_or_none

    def all(self):
        return list(self._rows)

    def one(self):
        return self._one

    def scalar_one(self):
        if self._scalar_one is _UNSET:
            return self._rows[0]
        return self._scalar_one

    def scalar_one_or_none(self):
        return self._scalar_one_or_none

    def scalars(self):
        return _Scalars(self._rows)


class FakeDb:
    """Records statements and replays one prepared response per execute() call."""

    def __init__(self, responses=(), flush_error=None, fail_flushes=1):
        self.responses = list(responses)
        self.statements = []
        self.events = []
        self.added = []
        self.flush_error = flush_error
        self.fail_flushes = fail_flushes

    async def execute(self, statement):
        self.statements.append(statement)
        self.events.append("execute")
        if not self.responses:
            return Result()
        return self.responses.pop(0)

    async def flush(self):
        self.events.append("flush")
        if self.flush_error is not None and self.fail_flushes > 0:
            self.fail_flushes -= 1
            raise self.flush_error
        return None

    def add(self, obj):
        self._apply_column_defaults(obj)
        self.events.append("add")
        self.added.append(obj)

    @staticmethod
    def _apply_column_defaults(obj):
        """Mirror server-side scalar defaults a real flush would persist."""

        table = getattr(obj, "__table__", None)
        if table is None:
            return
        for column in table.columns:
            default = column.default
            if default is None or not getattr(default, "is_scalar", False):
                continue
            if getattr(obj, column.key, None) is None:
                setattr(obj, column.key, default.arg)

    def get_bind(self):
        return None

    @asynccontextmanager
    async def begin_nested(self):
        self.events.append("begin_nested")
        yield self


def sql(index, db):
    return " ".join(str(db.statements[index]).split())


def params(index, db):
    return dict(db.statements[index].compile().params)


def ordered(source, *fragments):
    for fragment in fragments:
        assert fragment in source, fragment
    indexes = [source.index(fragment) for fragment in fragments]
    assert indexes == sorted(indexes), fragments


@pytest.fixture
def patched(monkeypatch):
    """Patch settings/utcnow/spies used by the entry points under test."""

    class Ctl:
        def __init__(self):
            self.spies = {}
            self._saved = {}

        def flags(self, **values):
            defaults = {
                "ADAPTIVE_LEARNING_ENABLED": True,
                "ADAPTIVE_INTERVAL_ENABLED": True,
                "ADAPTIVE_DIFFICULTY_ENABLED": True,
                "ADAPTIVE_PATH_ENABLED": True,
                "ADAPTIVE_WEIGHT_ENABLED": True,
                "ADAPTIVE_DRY_RUN": False,
            }
            defaults.update(values)
            for key, value in defaults.items():
                monkeypatch.setattr(als.settings, key, value, raising=False)
            return self

        def now(self, value=NOW):
            monkeypatch.setattr(als, "utcnow", lambda: value)
            return self

        def spy(self, name, result=None, error=None):
            calls = []

            async def recorder(*args, **kwargs):
                calls.append({"args": args[1:], "kwargs": kwargs})
                if error is not None:
                    raise error
                return result

            monkeypatch.setattr(als, name, recorder)
            self.spies[name] = calls
            return calls

    return Ctl()


# ── graph helpers ────────────────────────────────────────────────────


def test_graph_origin_ids_dedups_and_skips_falsy():
    assert als._graph_origin_ids([3, 1, 3, 0, 2, 1]) == [3, 1, 2]
    assert als._graph_origin_ids([]) == []


@pytest.mark.parametrize(
    ("depth", "nodes", "expected"),
    [
        (None, None, (1, als.GRAPH_MAX_EXPANSION_NODES)),
        (0, 0, (1, als.GRAPH_MAX_EXPANSION_NODES)),
        (9, 0, (als.GRAPH_MAX_DEPTH, als.GRAPH_MAX_EXPANSION_NODES)),
        (1, 5, (1, 5)),
        (2, 24, (2, 24)),
        (2, 99, (2, 99)),
    ],
)
def test_bounded_graph_limits(depth, nodes, expected):
    assert als._bounded_graph_limits(depth, nodes) == expected


def test_empty_graph_context_is_three_empty_dicts():
    context = als._empty_graph_context()
    assert context == {
        "blocked_targets": {},
        "prerequisite_candidates": {},
        "prerequisites_by_target": {},
    }
    assert json.dumps(context) == (
        '{"blocked_targets": {}, "prerequisite_candidates": {}, '
        '"prerequisites_by_target": {}}'
    )


def test_graph_edge_conditions_add_subject_scope_only_when_asked():
    plain = als._graph_edge_conditions([5, 6], None)
    assert len(plain) == 3
    text = " ".join(str(condition) for condition in plain)
    assert "relation_type" in text and "is_active" in text
    assert "subject_id" not in text

    scoped = als._graph_edge_conditions([5, 6], [3, 3, 4])
    assert len(scoped) == 6
    scoped_sql = " ".join(str(condition) for condition in scoped)
    assert "knowledge_edges.subject_id IN" in scoped_sql
    assert "SELECT knowledge_points.id" in scoped_sql
    assert scoped_sql.count("knowledge_points.id") == 2


def test_graph_candidate_rank_and_current_rank_tuple_order():
    item = {"confirmed_gap": True, "path_quality": 0.5, "depth": 2}
    assert als._graph_candidate_rank(item) == (1, 0.5, -2)
    assert als._graph_current_rank(None) == (0, -1.0, -99)
    assert als._graph_current_rank(
        {"confirmed_gap": False, "path_quality": 0.4, "depth": 1}
    ) == (
        0,
        0.4,
        -1,
    )
    assert als._graph_current_rank({"path_quality": 0.4}) == (0, 0.4, -99)


def test_graph_candidate_eligible_requires_confirmed_or_direct_unknown():
    confirmed = {"confirmed_gap": True, "unknown_gap": False}
    unknown = {"confirmed_gap": False, "unknown_gap": True}
    neither = {"confirmed_gap": False, "unknown_gap": False}
    assert als._graph_candidate_eligible({"depth": 1}, confirmed) is True
    assert als._graph_candidate_eligible({"depth": 1}, unknown) is True
    assert als._graph_candidate_eligible({"depth": 2}, unknown) is False
    assert als._graph_candidate_eligible({"depth": 2}, neither) is False
    assert als._graph_candidate_eligible({"depth": 1}, neither) is False


# ── graph context: traversal and projection ──────────────────────────


def edge(id_, target, source, weight=1.0, confidence=1.0):
    return Row(
        id=id_,
        target_knowledge_point_id=target,
        source_knowledge_point_id=source,
        weight=weight,
        confidence=confidence,
        source="import",
    )


def kp(id_, name, subject_id):
    return Row(id=id_, name=name, subject_id=subject_id)


def mastery(kp_id, score, confidence):
    return Row(knowledge_point_id=kp_id, mastery_score=score, confidence=confidence)


@pytest.mark.asyncio
async def test_graph_context_blocked_targets_only_for_direct_confirmed_gaps():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[edge(2, 10, 5)]),
            Result(rows=[kp(20, "target", 1), kp(10, "mid", 1), kp(5, "base", 1)]),
            Result(
                rows=[
                    mastery(20, 80.0, 0.9),
                    mastery(10, 30.0, 0.9),
                    mastery(5, 20.0, 0.9),
                ]
            ),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=2)
    assert set(context["blocked_targets"]) == {20}
    blocked = context["blocked_targets"][20][0]
    assert blocked == {
        "knowledge_point_id": 10,
        "origin_knowledge_point_id": 20,
        "depth": 1,
        "edge_id": 1,
        "edge_weight": 1.0,
        "edge_confidence": 1.0,
        "edge_source": "import",
        "path_quality": 1.0,
        "name": "mid",
        "subject_id": 1,
        "mastery_score": 30.0,
        "mastery_confidence": 0.9,
        "origin_name": "target",
        "origin_mastery_score": 80.0,
        "origin_mastery_confidence": 0.9,
        "confirmed_gap": True,
        "unknown_gap": False,
    }
    assert list(context["prerequisites_by_target"]) == [20]
    assert [
        item["knowledge_point_id"] for item in context["prerequisites_by_target"][20]
    ] == [10, 5]
    assert set(context["prerequisite_candidates"]) == {10, 5}
    assert context["prerequisite_candidates"][5]["depth"] == 2
    assert len(db.statements) == 4


@pytest.mark.asyncio
async def test_graph_context_unknown_direct_prerequisite_is_soft_candidate():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[kp(20, "target", 2), kp(10, "base", 2)]),
            Result(rows=[]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=1)
    assert context["blocked_targets"] == {}
    item = context["prerequisite_candidates"][10]
    assert item["confirmed_gap"] is False
    assert item["unknown_gap"] is True
    assert item["mastery_score"] == 50.0
    assert item["mastery_confidence"] == 0.0
    assert context["prerequisites_by_target"][20][0] is item


@pytest.mark.asyncio
async def test_graph_context_depth_two_unknown_is_not_a_candidate():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[edge(2, 10, 5)]),
            Result(rows=[kp(20, "t", 1), kp(10, "m", 1), kp(5, "b", 1)]),
            Result(rows=[]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=2)
    assert set(context["prerequisite_candidates"]) == {10}
    assert set(context["prerequisites_by_target"]) == {20}
    assert [item["depth"] for item in context["prerequisites_by_target"][20]] == [1, 2]
    assert context["blocked_targets"] == {}


@pytest.mark.asyncio
async def test_graph_context_mastered_prerequisite_is_never_a_candidate():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[kp(20, "t", 1), kp(10, "m", 1)]),
            Result(rows=[mastery(10, 80.0, 0.9)]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=1)
    assert context["blocked_targets"] == {}
    assert context["prerequisite_candidates"] == {}
    assert context["prerequisites_by_target"][20][0]["confirmed_gap"] is False
    assert context["prerequisites_by_target"][20][0]["unknown_gap"] is False


@pytest.mark.asyncio
async def test_graph_context_depth_decay_and_cumulative_path_quality():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10, weight=1.0, confidence=1.0)]),
            Result(rows=[edge(2, 10, 5, weight=0.5, confidence=0.8)]),
            Result(rows=[kp(20, "t", 1), kp(10, "m", 1), kp(5, "b", 1)]),
            Result(rows=[mastery(10, 30.0, 0.9), mastery(5, 30.0, 0.9)]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=2)
    direct, deep = context["prerequisites_by_target"][20]
    assert direct["path_quality"] == 1.0
    assert deep["path_quality"] == pytest.approx(0.26)
    assert deep["depth"] == 2
    assert deep["edge_weight"] == 0.5
    assert deep["edge_confidence"] == 0.8


@pytest.mark.asyncio
async def test_graph_context_normalises_weights_above_one_and_clamps():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10, weight=5.0, confidence=1.4)]),
            Result(rows=[kp(20, "t", 1), kp(10, "m", 1)]),
            Result(rows=[]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=1)
    item = context["prerequisites_by_target"][20][0]
    assert item["edge_weight"] == 0.5
    assert item["edge_confidence"] == 1.0
    assert item["path_quality"] == 0.5

    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10, weight=25.0, confidence=1.0)]),
            Result(rows=[kp(20, "t", 1), kp(10, "m", 1)]),
            Result(rows=[]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=1)
    item = context["prerequisites_by_target"][20][0]
    assert item["edge_weight"] == 1.0
    assert item["path_quality"] == 1.0


@pytest.mark.asyncio
async def test_graph_context_visited_pairs_break_cycles():
    db = FakeDb(
        [
            Result(rows=[edge(1, 10, 20)]),
            Result(rows=[edge(2, 20, 10)]),
            Result(rows=[kp(10, "a", 1), kp(20, "b", 1)]),
            Result(rows=[]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [10], max_depth=2)
    assert set(context["prerequisites_by_target"]) == {10}
    assert [item["depth"] for item in context["prerequisites_by_target"][10]] == [1]
    assert len(db.statements) == 4


@pytest.mark.asyncio
async def test_graph_context_truncates_mid_layer_at_max_nodes():
    db = FakeDb(
        [
            Result(
                rows=[
                    edge(1, 20, 10),
                    edge(2, 20, 11),
                    edge(3, 30, 12),
                    edge(4, 30, 13),
                ]
            ),
            Result(
                rows=[
                    kp(20, "t", 1),
                    kp(30, "u", 1),
                    kp(10, "a", 1),
                    kp(11, "b", 1),
                    kp(12, "c", 1),
                    kp(13, "d", 1),
                ]
            ),
            Result(rows=[]),
        ]
    )
    context = await als.get_recommendation_graph_context(
        db, USER, [20, 30], max_depth=1, max_nodes=2
    )
    assert [
        item["knowledge_point_id"] for item in context["prerequisites_by_target"][20]
    ] == [10, 11]
    assert set(context["prerequisites_by_target"]) == {20}
    assert set(context["prerequisite_candidates"]) == {10, 11}


@pytest.mark.asyncio
async def test_graph_context_max_depth_one_skips_deeper_queries():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[kp(20, "t", 1), kp(10, "a", 1)]),
            Result(rows=[]),
        ]
    )
    await als.get_recommendation_graph_context(db, USER, [20], max_depth=1)
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_graph_context_without_edges_returns_empty_and_skips_projection_queries():
    db = FakeDb([Result(rows=[])])
    assert await als.get_recommendation_graph_context(db, USER, [20]) == {
        "blocked_targets": {},
        "prerequisite_candidates": {},
        "prerequisites_by_target": {},
    }
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_graph_context_skips_relations_with_missing_knowledge_points():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[kp(10, "a", 1)]),
            Result(rows=[]),
        ]
    )
    assert await als.get_recommendation_graph_context(db, USER, [20], max_depth=1) == {
        "blocked_targets": {},
        "prerequisite_candidates": {},
        "prerequisites_by_target": {},
    }
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_graph_context_subject_filter_drops_out_of_scope_relations():
    rows = [
        Result(rows=[edge(1, 20, 10)]),
        Result(rows=[kp(20, "t", 3), kp(10, "a", 3)]),
        Result(rows=[]),
    ]
    db = FakeDb(rows)
    assert await als.get_recommendation_graph_context(
        db, USER, [20], subject_ids=[1], max_depth=1
    ) == {
        "blocked_targets": {},
        "prerequisite_candidates": {},
        "prerequisites_by_target": {},
    }

    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[kp(20, "t", 3), kp(10, "a", 3)]),
            Result(rows=[mastery(10, 30.0, 0.9)]),
        ]
    )
    context = await als.get_recommendation_graph_context(
        db, USER, [20], subject_ids=[3], max_depth=1
    )
    assert set(context["blocked_targets"]) == {20}


@pytest.mark.asyncio
async def test_graph_context_default_mastery_is_confirmed_when_threshold_allows():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[kp(20, "t", 1), kp(10, "a", 1)]),
            Result(rows=[]),
        ]
    )
    context = await als.get_recommendation_graph_context(
        db, USER, [20], max_depth=1, min_confidence=0.0, min_mastery=60.0
    )
    assert set(context["blocked_targets"]) == {20}
    assert context["blocked_targets"][20][0]["mastery_score"] == 50.0
    assert context["blocked_targets"][20][0]["mastery_confidence"] == 0.0


@pytest.mark.asyncio
async def test_graph_context_keeps_strongest_relation_per_prerequisite():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10, weight=0.3), edge(2, 5, 10, weight=0.9)]),
            Result(rows=[kp(20, "t", 1), kp(5, "o", 1), kp(10, "a", 1)]),
            Result(rows=[mastery(10, 30.0, 0.9)]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20, 5], max_depth=1)
    candidate = context["prerequisite_candidates"][10]
    assert candidate["origin_knowledge_point_id"] == 5
    assert candidate["path_quality"] == 0.9
    assert set(context["blocked_targets"]) == {20, 5}

    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10, weight=0.3), edge(2, 30, 40)]),
            Result(rows=[edge(3, 40, 10)]),
            Result(
                rows=[
                    kp(20, "t", 1),
                    kp(30, "u", 1),
                    kp(10, "a", 1),
                    kp(40, "b", 1),
                ]
            ),
            Result(rows=[mastery(10, 30.0, 0.9)]),
        ]
    )
    context = await als.get_recommendation_graph_context(
        db, USER, [20, 30], max_depth=2
    )
    candidate = context["prerequisite_candidates"][10]
    assert candidate["origin_knowledge_point_id"] == 30
    assert candidate["depth"] == 2
    assert candidate["path_quality"] == pytest.approx(0.65)
    assert set(context["blocked_targets"]) == {20}
    assert set(context["prerequisite_candidates"]) == {10, 40}


@pytest.mark.asyncio
async def test_graph_context_statement_shapes_and_params():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[kp(20, "t", 1), kp(10, "a", 1)]),
            Result(rows=[]),
        ]
    )
    await als.get_recommendation_graph_context(
        db, USER, [20], subject_ids=[1], max_depth=1
    )

    edge_sql = sql(0, db)
    assert edge_sql.split(" FROM ")[0] == (
        "SELECT knowledge_edges.id, knowledge_edges.target_knowledge_point_id, "
        "knowledge_edges.source_knowledge_point_id, knowledge_edges.weight, "
        "knowledge_edges.confidence, knowledge_edges.source"
    )
    ordered(
        edge_sql,
        "knowledge_edges.target_knowledge_point_id IN",
        "knowledge_edges.relation_type = ",
        "knowledge_edges.is_active = ",
        "knowledge_edges.subject_id IN",
        "knowledge_edges.source_knowledge_point_id IN (SELECT knowledge_points.id",
        "knowledge_edges.target_knowledge_point_id IN (SELECT knowledge_points.id",
    )
    assert "ORDER BY" not in edge_sql
    edge_params = params(0, db)
    assert edge_params["target_knowledge_point_id_1"] == [20]
    assert edge_params["relation_type_1"] == "prerequisite"
    assert edge_params["subject_id_1"] == [1]
    assert edge_params["subject_id_2"] == [1]
    # is_active comparisons render inline, so the SQL text carries the filter.
    assert "knowledge_edges.is_active = true" in edge_sql
    assert edge_sql.count("knowledge_points.is_active = true") == 2

    name_sql = sql(1, db)
    ordered(
        name_sql,
        "knowledge_points.id, knowledge_points.name, knowledge_points.subject_id",
        "knowledge_points.id IN",
        "knowledge_points.is_active = ",
    )
    assert sorted(params(1, db)["id_1"]) == [10, 20]

    mastery_sql = sql(2, db)
    ordered(
        mastery_sql,
        "user_knowledge_states.knowledge_point_id",
        "user_knowledge_states.mastery_score",
        "user_knowledge_states.confidence",
        "user_knowledge_states.user_id = ",
        "user_knowledge_states.knowledge_point_id IN",
    )
    mastery_params = params(2, db)
    assert mastery_params["user_id_1"] == USER
    assert sorted(mastery_params["knowledge_point_id_1"]) == [10, 20]


class Boom:
    """Result double whose read raises, for best-effort degradation paths."""

    def scalar_one_or_none(self):
        raise RuntimeError("boom")

    def all(self):
        raise RuntimeError("boom")

    def scalar_one(self):
        raise RuntimeError("boom")


# ── adaptive overview ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("factor", "status"),
    [
        (0.5, "fast_forgetting"),
        (0.89, "fast_forgetting"),
        (0.9, "slightly_fast_forgetting"),
        (0.97, "slightly_fast_forgetting"),
        (0.98, "normal"),
        (1.0, "normal"),
        (1.1, "normal"),
        (1.11, "stable_memory"),
        (1.5, "stable_memory"),
    ],
)
def test_interval_status_thresholds(factor, status):
    assert als._interval_status(factor) == status


@pytest.mark.asyncio
async def test_overview_defaults_without_profile(patched):
    patched.flags(ADAPTIVE_PATH_ENABLED=False, ADAPTIVE_WEIGHT_ENABLED=False)
    db = FakeDb(
        [Result(scalar_one_or_none=None), Result(scalar_one=0), Result(scalar_one=0)]
    )
    assert await als.get_adaptive_overview(db, USER) == {
        "interval_factor": 1.0,
        "interval_status": "normal",
        "target_recall_rate": 0.8,
        "recent_due_recall_rate": 0.0,
        "fast_forgetting_knowledge_count": 0,
        "hard_question_count": 0,
        "path_blocked_knowledge_count": 0,
        "weights_adjusted": False,
        "weight_summary": "",
    }
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_overview_rounding_and_status(patched):
    patched.flags(ADAPTIVE_PATH_ENABLED=False, ADAPTIVE_WEIGHT_ENABLED=False)
    db = FakeDb(
        [
            Result(
                scalar_one_or_none=Row(
                    interval_factor=1.23451,
                    target_recall_rate=0.85,
                    recent_due_count=3,
                    recent_due_correct_count=1,
                )
            ),
            Result(scalar_one=4),
            Result(scalar_one=9),
        ]
    )
    data = await als.get_adaptive_overview(db, USER)
    assert data["interval_factor"] == 1.235
    assert data["recent_due_recall_rate"] == 0.333
    assert data["target_recall_rate"] == 0.85
    assert data["fast_forgetting_knowledge_count"] == 4
    assert data["hard_question_count"] == 9
    assert data["interval_status"] == "stable_memory"


@pytest.mark.asyncio
async def test_overview_weight_summary_uses_field_order_and_top_three(patched):
    patched.flags(ADAPTIVE_PATH_ENABLED=False)
    pref = Row(
        due_weight=1.3,
        weakness_weight=0.7,
        wrong_weight=1.05,
        new_question_weight=1.0,
        diversity_weight=1.0,
        difficulty_weight=1.4,
        path_weight=0.9,
        last_adjusted_at=NOW,
    )
    db = FakeDb(
        [
            Result(scalar_one_or_none=None),
            Result(scalar_one=0),
            Result(scalar_one=0),
            Result(scalar_one_or_none=pref),
        ]
    )
    data = await als.get_adaptive_overview(db, USER)
    assert data["weights_adjusted"] is True
    assert data["weight_summary"] == "due偏重；weakness偏轻；wrong偏重"
    assert len(db.statements) == 4


@pytest.mark.asyncio
async def test_overview_unadjusted_weights_have_empty_summary(patched):
    patched.flags(ADAPTIVE_PATH_ENABLED=False)
    pref = Row(last_adjusted_at=None)
    db = FakeDb(
        [
            Result(scalar_one_or_none=None),
            Result(scalar_one=0),
            Result(scalar_one=0),
            Result(scalar_one_or_none=pref),
        ]
    )
    data = await als.get_adaptive_overview(db, USER)
    assert data["weights_adjusted"] is False
    assert data["weight_summary"] == ""


@pytest.mark.asyncio
async def test_overview_path_and_weight_failures_degrade_to_zero(patched):
    patched.now()
    patched.spy("get_blocked_knowledge_points", error=RuntimeError("blocked failed"))
    db = FakeDb(
        [
            Result(scalar_one_or_none=None),
            Result(scalar_one=0),
            Result(scalar_one=0),
            Result(rows=[IndexRow(1), IndexRow(2)]),
            Boom(),
        ]
    )
    data = await als.get_adaptive_overview(db, USER)
    assert data["path_blocked_knowledge_count"] == 0
    assert data["weights_adjusted"] is False
    assert data["weight_summary"] == ""


@pytest.mark.asyncio
async def test_overview_path_count_uses_spy_result_and_skips_empty_targets(patched):
    patched.flags(ADAPTIVE_WEIGHT_ENABLED=False)
    spy = patched.spy("get_blocked_knowledge_points", result={1: [], 2: []})
    db = FakeDb(
        [
            Result(scalar_one_or_none=None),
            Result(scalar_one=0),
            Result(scalar_one=0),
            Result(rows=[IndexRow(1), IndexRow(2)]),
        ]
    )
    data = await als.get_adaptive_overview(db, USER)
    assert data["path_blocked_knowledge_count"] == 2
    assert len(spy) == 1
    assert spy[0]["args"][1] == [1, 2]
    assert spy[0]["args"][2] == ""

    spy = patched.spy("get_blocked_knowledge_points", result={})
    db = FakeDb(
        [
            Result(scalar_one_or_none=None),
            Result(scalar_one=0),
            Result(scalar_one=0),
            Result(rows=[]),
        ]
    )
    data = await als.get_adaptive_overview(db, USER)
    assert data["path_blocked_knowledge_count"] == 0
    assert spy == []


@pytest.mark.asyncio
async def test_overview_statement_shapes(patched):
    patched.flags(ADAPTIVE_PATH_ENABLED=False)
    db = FakeDb(
        [Result(scalar_one_or_none=None), Result(scalar_one=0), Result(scalar_one=0)]
    )
    await als.get_adaptive_overview(db, USER)
    ordered(
        sql(0, db),
        "FROM user_adaptive_profile",
        "user_adaptive_profile.user_id = ",
    )
    ordered(
        sql(1, db),
        "count(user_knowledge_adaptive_state.id)",
        "user_knowledge_adaptive_state.user_id = ",
        "user_knowledge_adaptive_state.interval_factor < ",
    )
    assert params(1, db)["interval_factor_1"] == 0.9
    ordered(
        sql(2, db),
        "count(user_question_difficulty_state.id)",
        "user_question_difficulty_state.difficulty_label = ",
    )
    assert params(2, db)["difficulty_label_1"] == "hard"


# ── hard questions ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hard_questions_projection_rounding_and_first_kp_wins():
    rows = [
        Row(
            question_id=1,
            personal_difficulty_score=72.04,
            difficulty_label="hard",
            wrong_count=3,
            avg_answer_time_seconds=45.56,
        ),
        Row(
            question_id=2,
            personal_difficulty_score=55.0,
            difficulty_label="hard",
            wrong_count=0,
            avg_answer_time_seconds=0.0,
        ),
    ]
    db = FakeDb(
        [
            Result(rows=rows),
            Result(
                rows=[
                    Row(question_id=1, knowledge_point_id=11, name="first"),
                    Row(question_id=1, knowledge_point_id=12, name="second"),
                ]
            ),
            Result(rows=[Row(question_id=1, next_review_at=NOW)]),
        ]
    )
    data = await als.get_hard_questions(db, USER, limit=13)
    assert data == {
        "total": 2,
        "items": [
            {
                "question_id": 1,
                "knowledge_point_id": 11,
                "knowledge_point_name": "first",
                "personal_difficulty_score": 72.0,
                "difficulty_label": "hard",
                "wrong_count": 3,
                "avg_answer_time_seconds": 45.6,
                "next_review_at": "2026-10-28T03:04:05Z",
            },
            {
                "question_id": 2,
                "knowledge_point_id": None,
                "knowledge_point_name": None,
                "personal_difficulty_score": 55.0,
                "difficulty_label": "hard",
                "wrong_count": 0,
                "avg_answer_time_seconds": None,
                "next_review_at": None,
            },
        ],
    }
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_hard_questions_without_rows_skips_label_queries():
    db = FakeDb([Result(rows=[])])
    assert await als.get_hard_questions(db, USER) == {"total": 0, "items": []}
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_hard_questions_statement_shapes():
    db = FakeDb(
        [Result(rows=[])],
    )
    await als.get_hard_questions(db, USER, limit=7)
    statement = sql(0, db)
    assert statement.split(" FROM ")[0] == (
        "SELECT user_question_difficulty_state.question_id, "
        "user_question_difficulty_state.personal_difficulty_score, "
        "user_question_difficulty_state.difficulty_label, "
        "user_question_difficulty_state.wrong_count, "
        "user_question_difficulty_state.avg_answer_time_seconds"
    )
    ordered(
        statement,
        "user_question_difficulty_state.user_id = ",
        "user_question_difficulty_state.difficulty_label = ",
        "ORDER BY user_question_difficulty_state.personal_difficulty_score DESC",
        "LIMIT ",
    )
    statement_params = params(0, db)
    assert statement_params["user_id_1"] == USER
    assert statement_params["difficulty_label_1"] == "hard"
    assert statement_params["param_1"] == 7


@pytest.mark.asyncio
async def test_hard_questions_labels_query_shapes():
    db = FakeDb(
        [
            Result(
                rows=[
                    Row(
                        question_id=5,
                        personal_difficulty_score=50.0,
                        difficulty_label="hard",
                        wrong_count=0,
                        avg_answer_time_seconds=None,
                    )
                ]
            ),
            Result(rows=[]),
            Result(rows=[]),
        ]
    )
    await als.get_hard_questions(db, USER)
    labels_sql = sql(1, db)
    ordered(
        labels_sql,
        "question_knowledge_points.question_id, "
        "question_knowledge_points.knowledge_point_id, knowledge_points.name",
        "JOIN knowledge_points ON question_knowledge_points.knowledge_point_id "
        "= knowledge_points.id",
        "question_knowledge_points.question_id IN",
        "ORDER BY question_knowledge_points.question_id, question_knowledge_points.id",
    )
    reviews_sql = sql(2, db)
    ordered(
        reviews_sql,
        "user_question_state.question_id, user_question_state.next_review_at",
        "user_question_state.user_id = ",
        "user_question_state.question_id IN",
    )


# ── recommendation weights ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_adjust_recommend_weights_disabled_returns_defaults_without_queries(
    patched,
):
    patched.flags(ADAPTIVE_WEIGHT_ENABLED=False)
    db = FakeDb()
    assert await als.adjust_recommend_weights(db, USER) == als.default_weights()
    assert db.statements == []


@pytest.mark.asyncio
async def test_adjust_recommend_weights_below_five_records_keeps_state(patched):
    patched.now()
    pref = Row(last_adjusted_at=None, **{field: 1.1 for field in als._WEIGHT_FIELDS})
    db = FakeDb([Result(rows=[pref]), Result(one=(4, 3))])
    weights = await als.adjust_recommend_weights(db, USER)
    assert weights == {field: 1.1 for field in als._WEIGHT_FIELDS}
    assert list(weights) == als._WEIGHT_FIELDS
    assert pref.last_adjusted_at is None
    assert "flush" not in db.events
    assert len(db.statements) == 2

    db = FakeDb([Result(rows=[]), Result(one=(0, 0))])
    weights = await als.adjust_recommend_weights(db, USER)
    assert weights == als.default_weights()
    assert "flush" in db.events


@pytest.mark.parametrize(
    ("recent_count", "recent_correct", "due_count", "due_correct", "expected"),
    [
        (5, 0, 0, 0, {"weakness_weight": 1, "new_question_weight": 1}),
        (5, 5, 10, 5, {"due_weight": 1, "new_question_weight": 1}),
        (
            5,
            0,
            10,
            9,
            {"due_weight": -1, "weakness_weight": 1, "new_question_weight": 1},
        ),
        (5, 2, 4, 3, {"weakness_weight": 1, "new_question_weight": 1}),
        (8, 6, 3, 1, {"due_weight": 1, "new_question_weight": 1}),
        (31, 20, 3, 3, {"new_question_weight": -1}),
        (
            31,
            10,
            5,
            5,
            {"due_weight": -1, "weakness_weight": 1, "new_question_weight": -1},
        ),
        (10, 5, 3, 2, {}),
        (30, 10, 2, 2, {"weakness_weight": 1}),
        (5, 5, 4, 4, {"new_question_weight": 1}),
        (9, 5, 5, 1, {"due_weight": 1, "new_question_weight": 1}),
    ],
)
def test_weight_adjustment_matrix(
    recent_count, recent_correct, due_count, due_correct, expected
):
    adjustments = als._weight_adjustments(
        recent_count, recent_correct, due_count, due_correct
    )
    assert list(adjustments) == als._WEIGHT_FIELDS
    assert {key: value for key, value in adjustments.items() if value} == expected


@pytest.mark.asyncio
async def test_adjust_recommend_weights_applies_step_and_clamps(patched):
    patched.now()
    pref = Row(
        due_weight=0.7,
        weakness_weight=1.3,
        wrong_weight=1.0,
        new_question_weight=1.0,
        diversity_weight=1.0,
        difficulty_weight=1.0,
        path_weight=1.0,
        last_adjusted_at=None,
    )
    db = FakeDb([Result(rows=[pref]), Result(one=(6, 1)), Result(one=(5, 5))])
    weights = await als.adjust_recommend_weights(db, USER)
    # due -1 clamps at 0.7, weakness +1 clamps at 1.3, new +0.05 (6 < 10).
    assert weights["due_weight"] == 0.7
    assert weights["weakness_weight"] == 1.3
    assert weights["new_question_weight"] == 1.05
    assert pref.last_adjusted_at == NOW
    assert db.events.count("flush") == 1
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_adjust_recommend_weights_statement_shapes(patched):
    patched.now()
    pref = Row(last_adjusted_at=None, **{field: 1.0 for field in als._WEIGHT_FIELDS})
    db = FakeDb([Result(rows=[pref]), Result(one=(20, 10)), Result(one=(6, 6))])
    await als.adjust_recommend_weights(db, USER)
    ordered(
        sql(0, db),
        "FROM user_recommend_preference",
        "user_recommend_preference.user_id = ",
    )
    practice_sql = sql(1, db)
    ordered(
        practice_sql,
        "count(practice_records.id)",
        "sum(CASE WHEN (practice_records.is_correct = true) THEN",
        "practice_records.user_id = ",
        "practice_records.answered_at >=",
    )
    due_sql = sql(2, db)
    ordered(
        due_sql,
        "count(user_question_state.id)",
        "sum(CASE WHEN (user_question_state.last_is_correct = true) THEN",
        "user_question_state.user_id = ",
        "user_question_state.last_answered_at >=",
    )
    assert params(1, db)["user_id_1"] == USER
    assert params(2, db)["user_id_1"] == USER
    assert params(1, db)["answered_at_1"] == NOW - timedelta(days=14)


def test_preference_weights_preserve_field_order():
    pref = Row(**{field: index / 10 for index, field in enumerate(als._WEIGHT_FIELDS)})
    assert list(als._preference_weights(pref)) == als._WEIGHT_FIELDS


# ── personalized interval ────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("learning", "interval"),
    [(False, True), (True, False)],
)
async def test_apply_personalized_interval_disabled_flags_skip_queries(
    patched, learning, interval
):
    patched.flags(
        ADAPTIVE_LEARNING_ENABLED=learning, ADAPTIVE_INTERVAL_ENABLED=interval
    )
    db = FakeDb()
    assert await als.apply_personalized_interval(db, USER, 5, 10) is None
    assert db.statements == []


@pytest.mark.asyncio
async def test_apply_personalized_interval_averages_knowledge_factors(patched):
    patched.now()
    uqs = Row(next_review_at=None)
    db = FakeDb(
        [
            Result(scalar_one_or_none=Row(interval_factor=1.2)),
            Result(rows=[Row(knowledge_point_id=1), Row(knowledge_point_id=2)]),
            Result(rows=[Row(interval_factor=0.8), Row(interval_factor=1.2)]),
            Result(scalar_one_or_none=Row(difficulty_label="hard")),
            Result(scalar_one_or_none=uqs),
        ]
    )
    assert await als.apply_personalized_interval(db, USER, 5, 10) == 9
    assert uqs.next_review_at == NOW + timedelta(days=9)
    assert db.events.count("flush") == 1
    assert len(db.statements) == 5


@pytest.mark.asyncio
async def test_apply_personalized_interval_without_knowledge_points_skips_factor_query(
    patched,
):
    patched.now()
    db = FakeDb(
        [
            Result(scalar_one_or_none=Row(interval_factor=1.0)),
            Result(rows=[]),
            Result(scalar_one_or_none=None),
            Result(scalar_one_or_none=Row(next_review_at=NOW)),
        ]
    )
    assert await als.apply_personalized_interval(db, USER, 5, 7) == 7
    assert len(db.statements) == 4


@pytest.mark.asyncio
async def test_apply_personalized_interval_without_user_state_returns_days_without_flush(
    patched,
):
    patched.now()
    db = FakeDb(
        [
            Result(scalar_one_or_none=None),
            Result(rows=[]),
            Result(scalar_one_or_none=None),
            Result(scalar_one_or_none=None),
        ]
    )
    assert await als.apply_personalized_interval(db, USER, 5, 3) == 3
    assert "flush" not in db.events


@pytest.mark.asyncio
async def test_apply_personalized_interval_statement_order_and_params(patched):
    patched.now()
    db = FakeDb(
        [
            Result(scalar_one_or_none=None),
            Result(rows=[Row(knowledge_point_id=4)]),
            Result(rows=[]),
            Result(scalar_one_or_none=None),
            Result(scalar_one_or_none=None),
        ]
    )
    await als.apply_personalized_interval(db, USER, 5, 3)
    ordered(
        sql(0, db), "FROM user_adaptive_profile", "user_adaptive_profile.user_id = "
    )
    ordered(
        sql(1, db),
        "SELECT question_knowledge_points.knowledge_point_id",
        "question_knowledge_points.question_id = ",
    )
    ordered(
        sql(2, db),
        "user_knowledge_adaptive_state.knowledge_point_id, "
        "user_knowledge_adaptive_state.interval_factor",
        "user_knowledge_adaptive_state.user_id = ",
        "user_knowledge_adaptive_state.knowledge_point_id IN",
    )
    assert params(2, db)["knowledge_point_id_1"] == [4]
    ordered(sql(3, db), "FROM user_question_difficulty_state")
    ordered(sql(4, db), "FROM user_question_state")


# ── knowledge interval factor ────────────────────────────────────────


def ka_state(kp_id, factor=1.0):
    return Row(
        knowledge_point_id=kp_id,
        interval_factor=factor,
        last_adjusted_at=None,
        due_review_count=0,
        due_review_correct_count=0,
        overdue_wrong_count=0,
    )


@pytest.mark.asyncio
async def test_knowledge_interval_skips_without_ids_or_due_review(patched):
    db = FakeDb()
    await als.update_knowledge_interval_factor(db, USER, [], True, True, False)
    assert db.statements == []
    await als.update_knowledge_interval_factor(db, USER, [1], False, True, False)
    assert db.statements == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("correct", "overdue", "factor", "expected"),
    [
        (False, False, 1.0, 0.92),
        (True, False, 1.0, 1.04),
        (True, True, 1.0, 1.08),
        (False, True, 1.0, 0.92),
        (False, False, 0.6, 0.6),
        (True, False, 1.6, 1.6),
    ],
)
async def test_knowledge_interval_delta_and_clamps(
    patched, correct, overdue, factor, expected
):
    patched.now()
    state = ka_state(1, factor)
    db = FakeDb([Result(rows=[state])])
    await als.update_knowledge_interval_factor(db, USER, [1], True, correct, overdue)
    assert state.interval_factor == expected
    assert state.last_adjusted_at == NOW
    assert state.due_review_count == 1
    assert state.due_review_correct_count == (1 if correct else 0)
    assert state.overdue_wrong_count == (1 if overdue and not correct else 0)
    assert db.events.count("flush") == 1


@pytest.mark.asyncio
async def test_knowledge_interval_reloads_after_unique_conflict(patched):
    patched.now()
    existing = ka_state(1, 1.0)
    winner = ka_state(2, 0.8)
    conflict = IntegrityError("INSERT", {}, Exception("duplicate key"))
    db = FakeDb([Result(rows=[existing]), Result(rows=[winner])], flush_error=conflict)
    await als.update_knowledge_interval_factor(db, USER, [1, 2], True, True, False)
    assert existing.interval_factor == 1.04
    assert winner.interval_factor == 0.832
    assert "begin_nested" in db.events
    assert "add" in db.events
    assert len(db.statements) == 2
    assert db.events.count("flush") == 2


@pytest.mark.asyncio
async def test_knowledge_interval_reload_failure_raises(patched):
    conflict = IntegrityError("INSERT", {}, Exception("duplicate key"))
    db = FakeDb([Result(rows=[]), Result(rows=[])], flush_error=conflict)
    with pytest.raises(RuntimeError, match="disappeared after unique conflict"):
        await als.update_knowledge_interval_factor(db, USER, [1], True, True, False)


@pytest.mark.asyncio
async def test_knowledge_interval_dedups_processing_order(patched):
    patched.now()
    first = ka_state(1, 1.0)
    second = ka_state(2, 1.0)
    db = FakeDb([Result(rows=[first, second])])
    await als.update_knowledge_interval_factor(db, USER, [2, 1, 2], True, False, False)
    assert first.interval_factor == 0.92
    assert second.interval_factor == 0.92
    assert db.events.count("flush") == 1
    assert "begin_nested" not in db.events


# ── question difficulty calibration ──────────────────────────────────


def difficulty_state(score=50.0, label="normal", answer_count=0, avg_time=None):
    return Row(
        personal_difficulty_score=score,
        difficulty_label=label,
        answer_count=answer_count,
        correct_count=0,
        wrong_count=0,
        fast_correct_count=0,
        slow_correct_count=0,
        slow_wrong_count=0,
        overdue_wrong_count=0,
        avg_answer_time_seconds=avg_time,
        last_updated_at=None,
    )


@pytest.mark.parametrize(
    ("is_correct", "answer_time", "expected_time", "overdue", "delta"),
    [
        (True, None, None, False, -4),
        (False, None, None, False, 8),
        (True, 100, 60, False, -1),
        (False, 100, 60, False, 12),
        (True, 30, 60, False, -7),
        (True, 60, 60, False, -4),
        (True, 90, 60, False, -4),
        (True, 35, 60, False, -7),
        (True, 36, 60, False, -4),
        (True, 100, 60, True, -1),
        (False, None, None, True, 13),
        (False, 30, 60, True, 13),
        (True, 100, 0, False, -4),
        (True, 100, None, False, -4),
    ],
)
def test_difficulty_delta_matrix(
    is_correct, answer_time, expected_time, overdue, delta
):
    assert (
        als._difficulty_delta(is_correct, answer_time, expected_time, overdue) == delta
    )


@pytest.mark.parametrize(
    ("score", "label"),
    [
        (0.0, "easy"),
        (29.99, "easy"),
        (30.0, "normal"),
        (69.99, "normal"),
        (70.0, "hard"),
        (100.0, "hard"),
    ],
)
def test_difficulty_label_thresholds(score, label):
    assert als.get_difficulty_label(score) == label


@pytest.mark.parametrize(
    ("is_correct", "answer_time", "expected_time", "counters"),
    [
        (True, 30, 60, {"fast_correct_count": 1}),
        (True, 100, 60, {"slow_correct_count": 1}),
        (False, 100, 60, {"slow_wrong_count": 1}),
        (False, 30, 60, {}),
        (True, 30, 0, {}),
        (True, 30, None, {}),
        (True, None, 60, {}),
        (True, 36, 60, {}),
        (True, 90, 60, {}),
    ],
)
def test_difficulty_counter_updates(is_correct, answer_time, expected_time, counters):
    state = difficulty_state()
    als._apply_difficulty_counters(state, is_correct, answer_time, expected_time)
    for field in (
        "fast_correct_count",
        "slow_correct_count",
        "slow_wrong_count",
    ):
        assert getattr(state, field) == counters.get(field, 0), field


def test_avg_answer_time_first_and_rolling_updates():
    state = difficulty_state(answer_count=1)
    als._update_avg_answer_time(state, 45)
    assert state.avg_answer_time_seconds == 45.0

    state = difficulty_state(answer_count=4, avg_time=100.0)
    als._update_avg_answer_time(state, 40)
    assert state.avg_answer_time_seconds == 85.0

    state = difficulty_state(answer_count=1)
    als._update_avg_answer_time(state, None)
    assert state.avg_answer_time_seconds is None


def test_apply_difficulty_answer_updates_score_label_and_counters():
    state = difficulty_state(score=95.0, label="hard", answer_count=3, avg_time=60.0)
    new_score = als._apply_difficulty_answer(state, True, 100, 60, True)
    assert new_score == 94.0
    assert state.personal_difficulty_score == 94.0
    assert state.difficulty_label == "hard"
    assert state.answer_count == 4
    assert state.correct_count == 1
    assert state.wrong_count == 0
    assert state.slow_correct_count == 1
    assert state.overdue_wrong_count == 0
    assert state.avg_answer_time_seconds == 70.0

    state = difficulty_state(score=0.0, label="easy")
    new_score = als._apply_difficulty_answer(state, False, None, None, True)
    assert new_score == 13.0
    assert state.difficulty_label == "easy"
    assert state.wrong_count == 1
    assert state.overdue_wrong_count == 1
    assert state.answer_count == 1

    state = difficulty_state(score=98.0, label="hard")
    new_score = als._apply_difficulty_answer(state, False, 200, 60, True)
    assert new_score == 100.0
    assert state.personal_difficulty_score == 100.0
    assert state.difficulty_label == "hard"
    assert state.slow_wrong_count == 1


@pytest.mark.asyncio
async def test_update_question_difficulty_state_updates_and_flushes(patched):
    patched.now()
    state = difficulty_state(score=50.0, label="normal")
    db = FakeDb([Result(rows=[state])])
    returned = await als.update_question_difficulty_state(
        db, USER, 5, False, None, None, False
    )
    assert returned is state
    assert state.personal_difficulty_score == 58.0
    assert state.difficulty_label == "normal"
    assert state.answer_count == 1
    assert state.wrong_count == 1
    assert state.last_updated_at == NOW
    assert db.events.count("flush") == 1
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_update_question_difficulty_state_claims_after_unique_conflict(patched):
    patched.now()
    conflict = IntegrityError("INSERT", {}, Exception("duplicate key"))
    db = FakeDb([Result(rows=[]), Result(rows=[])], flush_error=conflict)
    # The re-query after the conflict returns the winner row.
    winner = difficulty_state(score=40.0, label="normal")
    db.responses = [Result(rows=[]), Result(rows=[winner])]
    returned = await als.update_question_difficulty_state(
        db, USER, 5, True, None, None, False
    )
    assert returned is winner
    assert winner.personal_difficulty_score == 36.0
    assert winner.difficulty_label == "normal"
    assert "begin_nested" in db.events
    assert "add" in db.events
    assert len(db.statements) == 2


@pytest.mark.asyncio
async def test_update_question_difficulty_state_statement_shape(patched):
    patched.now()
    db = FakeDb([Result(rows=[difficulty_state()])])
    await als.update_question_difficulty_state(db, USER, 5, True, None, None, False)
    ordered(
        sql(0, db),
        "FROM user_question_difficulty_state",
        "user_question_difficulty_state.user_id = ",
        "user_question_difficulty_state.question_id = ",
    )
    assert params(0, db)["user_id_1"] == USER
    assert params(0, db)["question_id_1"] == 5


# ── answer-level orchestration ───────────────────────────────────────


def test_review_flag_resolution_uses_pre_update_state():
    past = NOW - timedelta(days=3)
    uqs = Row(next_review_at=past)
    assert als._resolve_review_flags(uqs, NOW, None, None) == (True, True)
    assert als._resolve_review_flags(uqs, past, None, None) == (True, False)
    assert als._resolve_review_flags(Row(next_review_at=None), NOW, None, None) == (
        False,
        False,
    )
    assert als._resolve_review_flags(None, NOW, None, None) == (False, False)
    assert als._resolve_review_flags(uqs, NOW, False, False) == (False, False)
    assert als._resolve_review_flags(uqs, past, True, True) == (True, True)
    assert als._resolve_review_flags(uqs, past, None, True) == (True, True)


@pytest.mark.asyncio
async def test_update_adaptive_state_after_answer_disabled_skips_everything(patched):
    patched.flags(ADAPTIVE_LEARNING_ENABLED=False)
    calls = patched.spy("update_user_interval_factor")
    db = FakeDb()
    await als.update_adaptive_state_after_answer(
        db, USER, 5, True, 30, NOW, is_due_review=True, is_overdue_review=False
    )
    assert db.statements == []
    assert calls == []


@pytest.mark.asyncio
async def test_update_adaptive_state_after_answer_call_order_and_kwargs(patched):
    patched.now()
    user_factor = patched.spy("update_user_interval_factor")
    knowledge_factor = patched.spy("update_knowledge_interval_factor")
    difficulty = patched.spy("update_question_difficulty_state")
    interval = patched.spy("apply_personalized_interval")
    uqs = Row(next_review_at=NOW - timedelta(days=2), box_level=4)
    db = FakeDb(
        [
            Result(rows=[uqs]),
            Result(rows=[Row(knowledge_point_id=1), Row(knowledge_point_id=2)]),
            Result(scalar_one_or_none=2),
        ]
    )
    await als.update_adaptive_state_after_answer(db, USER, 5, True, 90, NOW)

    assert [call["args"][0] for call in user_factor] == [USER]
    assert user_factor[0]["kwargs"] == {
        "is_due_review": True,
        "is_correct": True,
        "is_overdue_review": True,
    }
    assert knowledge_factor[0]["args"] == (USER, [1, 2])
    assert knowledge_factor[0]["kwargs"] == {
        "is_due_review": True,
        "is_correct": True,
        "is_overdue_review": True,
    }
    assert difficulty[0]["args"] == (USER, 5)
    assert difficulty[0]["kwargs"] == {
        "is_correct": True,
        "answer_time_seconds": 90,
        "expected_time_seconds": 60,
        "is_overdue_review": True,
    }
    assert interval[0]["args"] == (USER, 5, als_leitner_base_days(4))
    assert len(db.statements) == 3


def als_leitner_base_days(box_level):
    from app.services.question_review_service import LEITNER_INTERVAL_DAYS

    return LEITNER_INTERVAL_DAYS[box_level]


@pytest.mark.asyncio
async def test_update_adaptive_state_after_answer_skips_knowledge_update_without_kp(
    patched,
):
    patched.now()
    user_factor = patched.spy("update_user_interval_factor")
    knowledge_factor = patched.spy("update_knowledge_interval_factor")
    patched.spy("update_question_difficulty_state")
    patched.spy("apply_personalized_interval")
    db = FakeDb(
        [
            Result(rows=[Row(next_review_at=NOW - timedelta(days=2), box_level=1)]),
            Result(rows=[]),
            Result(scalar_one_or_none=None),
        ]
    )
    await als.update_adaptive_state_after_answer(db, USER, 5, True, None, NOW)
    assert len(user_factor) == 1
    assert knowledge_factor == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flags", "expect_factor", "expect_difficulty", "expected_probe_order"),
    [
        ({"ADAPTIVE_INTERVAL_ENABLED": False}, False, True, ["questions.difficulty"]),
        (
            {"ADAPTIVE_DIFFICULTY_ENABLED": False},
            True,
            False,
            ["question_knowledge_points.knowledge_point_id"],
        ),
        (
            {},
            True,
            True,
            [
                "question_knowledge_points.knowledge_point_id",
                "questions.difficulty",
            ],
        ),
    ],
)
async def test_update_adaptive_state_after_answer_flag_matrix(
    patched, flags, expect_factor, expect_difficulty, expected_probe_order
):
    patched.now()
    patched.flags(ADAPTIVE_DRY_RUN=True, **flags)
    user_factor = patched.spy("update_user_interval_factor")
    knowledge_factor = patched.spy("update_knowledge_interval_factor")
    difficulty_spy = patched.spy("update_question_difficulty_state")
    interval_spy = patched.spy("apply_personalized_interval")
    responses = [
        Result(rows=[Row(next_review_at=NOW - timedelta(days=2), box_level=2)])
    ]
    if flags.get("ADAPTIVE_INTERVAL_ENABLED", True):
        responses.append(Result(rows=[Row(knowledge_point_id=3)]))
    if flags.get("ADAPTIVE_DIFFICULTY_ENABLED", True):
        responses.append(Result(scalar_one_or_none=None))
    db = FakeDb(responses)
    await als.update_adaptive_state_after_answer(db, USER, 5, True, None, NOW)
    assert bool(user_factor) == expect_factor
    assert bool(knowledge_factor) == expect_factor
    assert bool(difficulty_spy) == expect_difficulty
    # dry_run keeps the personalized-interval override switched off.
    assert interval_spy == []
    assert len(db.statements) == 1 + len(expected_probe_order)
    probes = [sql(index, db) for index in range(1, len(db.statements))]
    for probe, fragment in zip(probes, expected_probe_order):
        assert fragment in probe, fragment


@pytest.mark.asyncio
async def test_update_adaptive_state_after_answer_without_user_state(patched):
    patched.now()
    difficulty = patched.spy("update_question_difficulty_state")
    interval = patched.spy("apply_personalized_interval")
    db = FakeDb([Result(rows=[]), Result(scalar_one_or_none=None)])
    await als.update_adaptive_state_after_answer(db, USER, 5, False, 45, NOW)
    assert len(difficulty) == 1
    assert difficulty[0]["kwargs"]["expected_time_seconds"] == 75
    assert interval == []


@pytest.mark.asyncio
async def test_update_adaptive_state_after_answer_explicit_flags_win(patched):
    patched.now()
    user_factor = patched.spy("update_user_interval_factor")
    patched.spy("update_question_difficulty_state")
    patched.spy("apply_personalized_interval")
    db = FakeDb(
        [
            Result(rows=[Row(next_review_at=NOW - timedelta(days=9), box_level=1)]),
            Result(scalar_one_or_none=None),
        ]
    )
    await als.update_adaptive_state_after_answer(
        db, USER, 5, True, None, NOW, is_due_review=False, is_overdue_review=False
    )
    assert user_factor == []
    assert len(db.statements) == 2


# ── added coverage: precision, negative adjustments, transaction gates ──


@pytest.mark.asyncio
async def test_graph_context_rounds_mastery_and_confidence_to_declared_precision():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[kp(20, "t", 1), kp(10, "a", 1)]),
            Result(rows=[mastery(10, 30.567, 0.5678)]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=1)
    item = context["prerequisites_by_target"][20][0]
    assert item["mastery_score"] == 30.6
    assert item["mastery_confidence"] == 0.568
    assert item["origin_mastery_score"] == 50.0
    assert item["origin_mastery_confidence"] == 0.0


@pytest.mark.asyncio
async def test_graph_context_blocks_only_one_direct_relation_per_target():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[edge(2, 10, 5)]),
            Result(rows=[kp(20, "t", 1), kp(10, "m", 1), kp(5, "b", 1)]),
            Result(rows=[mastery(10, 30.0, 0.9), mastery(5, 20.0, 0.9)]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=2)
    assert len(context["blocked_targets"][20]) == 1
    assert context["blocked_targets"][20][0]["depth"] == 1


@pytest.mark.asyncio
async def test_hard_questions_rounds_score_to_one_decimal():
    rows = [
        Row(
            question_id=1,
            personal_difficulty_score=72.44,
            difficulty_label="hard",
            wrong_count=0,
            avg_answer_time_seconds=None,
        )
    ]
    db = FakeDb([Result(rows=rows), Result(rows=[]), Result(rows=[])])
    data = await als.get_hard_questions(db, USER)
    assert data["items"][0]["personal_difficulty_score"] == 72.4


@pytest.mark.asyncio
async def test_adjust_recommend_weights_applies_negative_directions(patched):
    patched.now()
    pref = Row(last_adjusted_at=None, **{field: 1.0 for field in als._WEIGHT_FIELDS})
    db = FakeDb([Result(rows=[pref]), Result(one=(10, 10)), Result(one=(5, 5))])
    weights = await als.adjust_recommend_weights(db, USER)
    assert weights["due_weight"] == 0.95
    assert weights["weakness_weight"] == 1.0
    assert weights["new_question_weight"] == 1.0


@pytest.mark.asyncio
async def test_knowledge_interval_transaction_gate_follows_missing_states(patched):
    patched.now()
    transactions = patched.spy("_start_explicit_transaction")
    db = FakeDb([Result(rows=[ka_state(1)])])
    await als.update_knowledge_interval_factor(db, USER, [1], True, True, False)
    assert transactions == []

    db = FakeDb([Result(rows=[])])
    await als.update_knowledge_interval_factor(db, USER, [1], True, True, False)
    assert len(transactions) == 1


@pytest.mark.asyncio
async def test_knowledge_interval_statement_shape(patched):
    patched.now()
    db = FakeDb([Result(rows=[ka_state(1)])])
    await als.update_knowledge_interval_factor(db, USER, [1, 2], True, True, False)
    ordered(
        sql(0, db),
        "FROM user_knowledge_adaptive_state",
        "user_knowledge_adaptive_state.user_id = ",
        "user_knowledge_adaptive_state.knowledge_point_id IN",
    )
    assert params(0, db)["user_id_1"] == USER
    assert sorted(params(0, db)["knowledge_point_id_1"]) == [1, 2]


def test_difficulty_answer_rounds_score_to_one_decimal():
    state = difficulty_state(score=50.57)
    als._apply_difficulty_answer(state, False, None, None, False)
    assert state.personal_difficulty_score == 58.6


@pytest.mark.asyncio
async def test_apply_personalized_interval_defaults_user_factor_to_one(patched):
    patched.now()
    db = FakeDb(
        [
            Result(scalar_one_or_none=None),
            Result(rows=[]),
            Result(scalar_one_or_none=None),
            Result(scalar_one_or_none=None),
        ]
    )
    assert await als.apply_personalized_interval(db, USER, 5, 10) == 10


@pytest.mark.asyncio
async def test_after_answer_uses_leitner_default_for_unknown_box(patched):
    patched.now()
    interval = patched.spy("apply_personalized_interval")
    patched.spy("update_user_interval_factor")
    patched.spy("update_knowledge_interval_factor")
    patched.spy("update_question_difficulty_state")
    db = FakeDb(
        [
            Result(rows=[Row(next_review_at=NOW - timedelta(days=2), box_level=99)]),
            Result(rows=[]),
            Result(scalar_one_or_none=None),
        ]
    )
    await als.update_adaptive_state_after_answer(db, USER, 5, True, None, NOW)
    assert interval[0]["args"] == (USER, 5, 1)


@pytest.mark.asyncio
async def test_graph_context_confidence_equal_to_threshold_is_not_unknown():
    db = FakeDb(
        [
            Result(rows=[edge(1, 20, 10)]),
            Result(rows=[kp(20, "t", 1), kp(10, "a", 1)]),
            Result(rows=[mastery(10, 70.0, 0.3)]),
        ]
    )
    context = await als.get_recommendation_graph_context(db, USER, [20], max_depth=1)
    item = context["prerequisites_by_target"][20][0]
    assert item["unknown_gap"] is False
    assert item["confirmed_gap"] is False
    assert context["prerequisite_candidates"] == {}
    assert context["blocked_targets"] == {}


@pytest.mark.asyncio
async def test_knowledge_interval_rounds_factor_to_four_decimals(patched):
    patched.now()
    state = ka_state(1, 0.9111)
    db = FakeDb([Result(rows=[state])])
    await als.update_knowledge_interval_factor(db, USER, [1], True, False, False)
    assert state.interval_factor == round(0.9111 * 0.92, 4)


def test_difficulty_label_uses_the_new_score():
    state = difficulty_state(score=70.0, label="hard")
    als._apply_difficulty_answer(state, True, None, None, False)
    assert state.personal_difficulty_score == 66.0
    assert state.difficulty_label == "normal"


@pytest.mark.asyncio
async def test_apply_personalized_interval_defaults_knowledge_factor_to_one(patched):
    patched.now()
    db = FakeDb(
        [
            Result(scalar_one_or_none=None),
            Result(rows=[Row(knowledge_point_id=4)]),
            Result(rows=[]),
            Result(scalar_one_or_none=None),
            Result(scalar_one_or_none=None),
        ]
    )
    assert await als.apply_personalized_interval(db, USER, 5, 10) == 10
