"""Contracts for the study hub recommendation projections."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import study_hub_service as hub

SUBJECTS = [
    SimpleNamespace(id=3, code="data_structure", name="数据结构"),
    SimpleNamespace(id=4, code="computer_network", name="计网"),
]
ANSWERABLE_TYPES = list(hub._ANSWERABLE_TYPES)


class Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalar_one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDb:
    """Records statements and replays one prepared response per execute() call."""

    def __init__(self, responses=()):
        self.responses = list(responses)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        rows = self.responses.pop(0) if self.responses else []
        return Result(rows)


def sql(index=0, db=None):
    return " ".join(str(db.statements[index]).split())


@pytest.mark.asyncio
async def test_subject_mastery_returns_empty_without_query_when_no_core_subjects():
    db = FakeDb()
    assert await hub._build_subject_mastery(db, 7, []) == []
    assert db.statements == []


@pytest.mark.asyncio
async def test_subject_mastery_query_keeps_aggregate_shape():
    db = FakeDb([[]])
    await hub._build_subject_mastery(db, 7, SUBJECTS)
    text = sql(0, db)
    for fragment in (
        "SELECT user_knowledge_states.subject_id",
        "avg(user_knowledge_states.mastery_score)",
        "avg(user_knowledge_states.confidence)",
        "coalesce(sum(user_knowledge_states.attempt_count), ",
        "coalesce(sum(user_knowledge_states.correct_count), ",
        "coalesce(sum(user_knowledge_states.wrong_count), ",
        "count(user_knowledge_states.id)",
        "user_knowledge_states.user_id = ",
        "user_knowledge_states.subject_id IN (",
        "user_knowledge_states.attempt_count > ",
        "GROUP BY user_knowledge_states.subject_id",
    ):
        assert fragment in text, fragment
    assert "ORDER BY" not in text
    params = db.statements[0].compile().params
    assert params["user_id_1"] == 7
    assert params["subject_id_1"] == [3, 4]
    assert params["attempt_count_1"] == 0


@pytest.mark.asyncio
async def test_subject_mastery_projects_present_and_zero_attempt_rows():
    db = FakeDb(
        [
            [
                (3, 41.234, 0.5, 8, 6, 2, 5),
                (4, 0.0, 0.0, 0, 0, 0, 4),
            ]
        ]
    )
    rows = await hub._build_subject_mastery(db, 7, SUBJECTS)
    assert [row["subject_id"] for row in rows] == [3, 4]
    assert rows[0] == {
        "subject_id": 3,
        "subject_code": "data_structure",
        "subject_name": "数据结构",
        "data_available": True,
        "mastery_score": 41.2,
        "confidence": 0.5,
        "attempt_count": 8,
        "accuracy": 0.75,
    }
    assert rows[1]["data_available"] is False
    assert rows[1]["mastery_score"] == 0.0
    assert rows[1]["confidence"] == 0.0
    assert rows[1]["attempt_count"] == 0
    assert rows[1]["accuracy"] is None


@pytest.mark.asyncio
async def test_subject_mastery_falls_back_to_empty_payload_and_coerces_keys():
    missing = SimpleNamespace(id=5, code="operating_system", name="操作系统")
    db = FakeDb([[("3", None, None, None, None, None, None)]])
    rows = await hub._build_subject_mastery(db, 7, [missing, SUBJECTS[0]])
    assert rows[0] == {
        "subject_id": 5,
        "subject_code": "operating_system",
        "subject_name": "操作系统",
        "data_available": False,
        "mastery_score": None,
        "confidence": 0.0,
        "attempt_count": 0,
        "accuracy": None,
    }
    assert rows[1]["subject_id"] == 3
    assert rows[1]["data_available"] is False
    assert rows[1]["mastery_score"] == 0.0
    assert rows[1]["confidence"] == 0.0
    assert rows[1]["attempt_count"] == 0
    assert rows[1]["accuracy"] is None


def practiced(
    subject_id, mastery, confidence, attempts, code="data_structure", name="数据结构"
):
    return {
        "subject_id": subject_id,
        "subject_code": code,
        "subject_name": name,
        "data_available": True,
        "mastery_score": mastery,
        "confidence": confidence,
        "attempt_count": attempts,
        "accuracy": None,
    }


class Diagnosis:
    def __init__(self):
        self.calls = []
        self.responses = {}

    async def __call__(self, db, user_id, subject_id, days=30):
        self.calls.append((subject_id, days))
        return self.responses.get(subject_id)


@pytest.fixture
def diagnosis(monkeypatch):
    recorder = Diagnosis()
    from app.services import knowledge_diagnosis_service

    monkeypatch.setattr(
        knowledge_diagnosis_service, "get_knowledge_diagnosis", recorder
    )
    return recorder


@pytest.fixture
def practice_params(monkeypatch):
    calls = []

    def recorder(**kwargs):
        calls.append(kwargs)
        return {"marker": True, **kwargs}

    monkeypatch.setattr(hub, "_practice_params", recorder)
    return calls


@pytest.mark.asyncio
async def test_chapter_recommendation_returns_none_without_practiced_subjects(
    diagnosis,
):
    db = FakeDb()
    assert await hub._pick_chapter_recommendation(db, 7, []) is None
    assert (
        await hub._pick_chapter_recommendation(
            db,
            7,
            [
                {**practiced(3, None, 0.0, 0), "data_available": False},
                practiced(4, 50.0, 0.1, 0, code="computer_network", name="计网"),
            ],
        )
        is None
    )
    assert diagnosis.calls == []
    assert db.statements == []


@pytest.mark.asyncio
async def test_chapter_recommendation_ranks_two_weakest_and_skips_empty_advice(
    diagnosis,
):
    # Ranking: mastery asc (missing -> 100), confidence asc, -attempts, subject id.
    subjects = [
        practiced(9, 80.0, 0.9, 5),
        practiced(7, 40.0, 0.2, 3),
        practiced(5, 40.0, 0.1, 1),
        practiced(3, 40.0, 0.1, 4),
        practiced(1, 40.0, 0.1, 4),
    ]
    diagnosis.responses = {
        1: {"primary_recommendation": {"knowledge_point_id": 0}},
        3: {"primary_recommendation": "not-a-dict"},
    }
    assert await hub._pick_chapter_recommendation(FakeDb(), 7, subjects) is None
    assert diagnosis.calls == [(1, 30), (3, 30)]


@pytest.mark.asyncio
async def test_chapter_recommendation_probes_the_second_subject_after_empty_advice(
    diagnosis,
):
    subjects = [practiced(3, 40.0, 0.1, 4), practiced(1, 40.0, 0.1, 4)]
    diagnosis.responses = {
        1: {"primary_recommendation": "not-a-dict"},
        3: {"primary_recommendation": {"knowledge_point_id": 21}},
    }
    task = await hub._pick_chapter_recommendation(FakeDb(), 7, subjects)
    assert diagnosis.calls == [(1, 30), (3, 30)]
    assert task["key"] == "chapter:3:21"
    assert task["knowledge_point_id"] == 21


@pytest.mark.asyncio
async def test_chapter_recommendation_ranks_unknown_mastery_last(diagnosis):
    # A practised subject without a mastery score is ranked as 100.0, not as 0.0.
    subjects = [
        practiced(3, None, 0.5, 4),
        practiced(4, 50.0, 0.5, 4, code="computer_network", name="计网"),
    ]
    diagnosis.responses = {4: {"primary_recommendation": {"knowledge_point_id": 41}}}
    task = await hub._pick_chapter_recommendation(FakeDb(), 7, subjects)
    assert diagnosis.calls == [(4, 30)]
    assert task["key"] == "chapter:4:41"


@pytest.mark.asyncio
async def test_chapter_recommendation_builds_task_with_fallbacks_and_quotas(
    diagnosis, practice_params
):
    subjects = [practiced(3, 30.0, 0.2, 4, code="", name="")]
    diagnosis.responses = {
        3: {
            "subject_code": "data_structure",
            "subject_name": "数据结构",
            "primary_recommendation": {
                "knowledge_point_id": 11,
                "trainable_knowledge_points": 25,
            },
        },
    }
    task = await hub._pick_chapter_recommendation(FakeDb(), 7, subjects)
    assert task["key"] == "chapter:3:11"
    assert task["task_type"] == "knowledge_chapter"
    assert task["priority"] == 0
    assert task["title"] == "进行章节专项"
    assert task["reason"] == "根据当前知识覆盖和掌握状态安排章节练习。"
    assert task["action_label"] == "开始章节专项"
    assert task["route"] == "practice"
    assert task["estimated_question_count"] == hub.SMART_TASK_COUNT
    assert task["estimated_minutes"] == hub._minutes_for_questions(hub.SMART_TASK_COUNT)
    assert task["subject_code"] == "data_structure"
    assert task["subject_name"] == "数据结构"
    assert task["knowledge_point_id"] == 11
    assert task["knowledge_point_name"] == ""
    assert task["route_params"] == {"marker": True, **practice_params[0]}
    assert practice_params[0] == {
        "subject_id": 3,
        "mode": "random",
        "count": hub.SMART_TASK_COUNT,
        "knowledge_point_id": 11,
        "include_descendants": True,
        "allow_repeat": True,
    }


@pytest.mark.asyncio
async def test_chapter_recommendation_clamps_trainable_counts(diagnosis):
    subjects = [practiced(3, 30.0, 0.2, 4)]
    for trainable, expected in (
        (1, 3),
        (3, 3),
        (4, 4),
        (25, hub.SMART_TASK_COUNT),
        (None, hub.SMART_TASK_COUNT),
    ):
        recommendation = {"knowledge_point_id": 11}
        if trainable is not None:
            recommendation["trainable_knowledge_points"] = trainable
        diagnosis.responses = {3: {"primary_recommendation": recommendation}}
        task = await hub._pick_chapter_recommendation(FakeDb(), 7, subjects)
        assert task["estimated_question_count"] == expected, (trainable, expected)


@pytest.mark.asyncio
async def test_chapter_recommendation_reuses_diagnosis_subject_labels(diagnosis):
    subjects = [practiced(3, 30.0, 0.2, 4, code="data_structure", name="数据结构")]
    diagnosis.responses = {
        3: {
            "subject_code": "",
            "subject_name": "",
            "primary_recommendation": {
                "knowledge_point_id": 11,
                "title": "自定义标题",
                "reason": "自定义理由",
                "action_label": "自定义动作",
                "knowledge_point_name": "线性表",
            },
        },
    }
    task = await hub._pick_chapter_recommendation(FakeDb(), 7, subjects)
    assert task["title"] == "自定义标题"
    assert task["reason"] == "自定义理由"
    assert task["action_label"] == "自定义动作"
    assert task["knowledge_point_name"] == "线性表"
    assert task["subject_code"] == "data_structure"
    assert task["subject_name"] == "数据结构"


@pytest.mark.asyncio
async def test_chapter_recommendation_prefers_diagnosis_subject_labels(diagnosis):
    subjects = [practiced(3, 30.0, 0.2, 4, code="legacy_code", name="旧科目名")]
    diagnosis.responses = {
        3: {
            "subject_code": "data_structure",
            "subject_name": "数据结构",
            "primary_recommendation": {"knowledge_point_id": 11},
        },
    }
    task = await hub._pick_chapter_recommendation(FakeDb(), 7, subjects)
    assert task["subject_code"] == "data_structure"
    assert task["subject_name"] == "数据结构"


class WeakRow:
    """Row-like accessor for the weak-point projection."""

    def __init__(self, values):
        self._values = list(values)

    def __getitem__(self, index):
        return self._values[index]


@pytest.mark.asyncio
async def test_weak_point_query_keeps_join_filter_ranking_and_limit():
    db = FakeDb([[]])
    assert await hub._pick_weak_point(db, 7, [3, 4]) is None
    text = sql(0, db)
    for fragment in (
        "JOIN knowledge_points ON knowledge_points.id = user_knowledge_states.knowledge_point_id",
        "JOIN subjects ON subjects.id = user_knowledge_states.subject_id",
        "JOIN question_knowledge_points ON",
        "JOIN questions ON questions.id = question_knowledge_points.question_id",
        "JOIN question_versions ON question_versions.id = questions.current_version_id",
        "user_knowledge_states.attempt_count >= ",
        "user_knowledge_states.mastery_score < ",
        "knowledge_points.is_active IS true",
        "knowledge_points.subject_id = user_knowledge_states.subject_id",
        "questions.subject_id = user_knowledge_states.subject_id",
        "questions.is_active IS true",
        "questions.review_status = ",
        "question_versions.question_id = questions.id",
        "question_versions.subject_id = questions.subject_id",
        "question_versions.question_type = questions.question_type",
        "question_versions.is_active IS true",
        "GROUP BY user_knowledge_states.knowledge_point_id",
        "HAVING count(distinct(questions.id)) >= ",
        "ORDER BY CASE WHEN",
        "LIMIT ",
    ):
        assert fragment in text, fragment
    # Join order is part of the contract: a swap changes the rendered statement.
    joins = [
        "JOIN knowledge_points ON",
        "JOIN subjects ON",
        "JOIN question_knowledge_points ON",
        "JOIN questions ON",
        "JOIN question_versions ON",
    ]
    join_indexes = [text.index(fragment) for fragment in joins]
    assert join_indexes == sorted(join_indexes), joins
    group_clause = text.split("GROUP BY", 1)[1].split("HAVING", 1)[0]
    grouped = [
        "user_knowledge_states.knowledge_point_id",
        "knowledge_points.name",
        "user_knowledge_states.subject_id",
        "subjects.code",
        "subjects.name",
        "user_knowledge_states.mastery_score",
        "user_knowledge_states.confidence",
        "user_knowledge_states.attempt_count",
        "user_knowledge_states.wrong_count",
        "user_knowledge_states.recent_wrong_count",
    ]
    group_indexes = [group_clause.index(fragment) for fragment in grouped]
    assert group_indexes == sorted(group_indexes), grouped
    order_clause = text.split("ORDER BY", 1)[1]
    ranked = [
        "user_knowledge_states.recent_wrong_count DESC",
        "user_knowledge_states.mastery_score ASC",
        "user_knowledge_states.wrong_count DESC",
        "user_knowledge_states.knowledge_point_id ASC",
    ]
    rank_indexes = [order_clause.index(fragment) for fragment in ranked]
    assert rank_indexes == sorted(rank_indexes), ranked
    # The answerable question types are bound as a post-compile parameter list.
    params = db.statements[0].compile().params
    assert params["question_type_1"] == ANSWERABLE_TYPES
    assert params["user_id_1"] == 7
    assert params["subject_id_1"] == [3, 4]
    assert params["attempt_count_1"] == 2
    assert params["mastery_score_1"] == 70
    assert params["review_status_1"] == "approved"
    assert params["count_1"] == 3
    assert params["recent_wrong_count_1"] == 2
    assert [params["param_1"], params["param_2"], params["param_3"]] == [0, 1, 1]


@pytest.mark.asyncio
async def test_weak_point_projection_rounds_and_coerces():
    row = WeakRow(
        [11, "线性表", 3, "data_structure", "数据结构", 41.234, 0.4567, 4, 3, 2, 5]
    )
    payload = await hub._pick_weak_point(FakeDb([[row]]), 7, [3])
    assert payload == {
        "knowledge_point_id": 11,
        "knowledge_point_name": "线性表",
        "subject_id": 3,
        "subject_code": "data_structure",
        "subject_name": "数据结构",
        "mastery_score": 41.2,
        "confidence": 0.457,
        "attempt_count": 4,
        "wrong_count": 3,
        "recent_wrong_count": 2,
        "available_question_count": 5,
    }


class Graph:
    def __init__(self):
        self.calls = []
        self.context = {}

    async def __call__(self, db, user_id, target_ids, subject_ids=None):
        self.calls.append((user_id, list(target_ids), list(subject_ids or [])))
        return self.context


@pytest.fixture
def graph(monkeypatch):
    recorder = Graph()
    monkeypatch.setattr(
        hub.adaptive_learning_service, "get_recommendation_graph_context", recorder
    )
    return recorder


def prerequisite(
    subject_id, kp_id, mastery=30.0, path_quality=0.5, origin_name="目标章节"
):
    return {
        "subject_id": subject_id,
        "knowledge_point_id": kp_id,
        "mastery_score": mastery,
        "path_quality": path_quality,
        "origin_name": origin_name,
        "name": f"知识点{kp_id}",
    }


@pytest.mark.asyncio
async def test_path_prerequisite_stops_without_targets_or_blockers(graph):
    db = FakeDb([[]])
    assert await hub._pick_path_prerequisite(db, 7, [3]) is None
    assert graph.calls == []
    assert len(db.statements) == 1
    text = sql(0, db)
    assert "DISTINCT" in text
    assert "knowledge_edges.relation_type = " in text
    assert "ORDER BY knowledge_edges.target_knowledge_point_id ASC" in text
    db = FakeDb([[("3",), ("4",)]])
    graph.context = {"blocked_targets": {}}
    assert await hub._pick_path_prerequisite(db, 7, [3]) is None
    assert graph.calls == [(7, [3, 4], [3])]


@pytest.mark.asyncio
async def test_path_prerequisite_examines_only_the_top_target_and_skips_invalid(
    monkeypatch, graph
):
    db = FakeDb([[(2,), (9,), (5,)]])
    graph.context = {
        "blocked_targets": {
            5: [
                prerequisite(8, 30),  # subject outside the core scope
                prerequisite(3, 0),  # invalid knowledge point id
                prerequisite(3, 31, mastery=20.0, path_quality=0.2),
            ],
            2: [prerequisite(3, 42)],
            9: [prerequisite(3, 21, mastery=10.0, path_quality=0.1)],
        },
    }
    counted = []

    async def fake_count(db, *, knowledge_point_id, subject_id):
        counted.append((knowledge_point_id, subject_id))
        return 0

    monkeypatch.setattr(hub, "_count_trainable_kp_questions", fake_count)
    # Target 5 owns the most blockers, so it is ranked first; when every blocker
    # fails the trainable check the picker returns None instead of trying target 2.
    assert await hub._pick_path_prerequisite(db, 7, [3]) is None
    assert counted == [(31, 3)]
    assert graph.calls == [(7, [2, 9, 5], [3])]
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_path_prerequisite_accepts_first_trainable_blocker_of_top_target(
    monkeypatch, graph
):
    db = FakeDb(
        [
            [(2,), (9,)],
            [SimpleNamespace(id=3, code="data_structure", name="数据结构")],
        ]
    )
    graph.context = {
        "blocked_targets": {
            2: [
                prerequisite(3, 41, mastery=20.0, path_quality=0.2),
                prerequisite(3, 42, mastery=20.0, path_quality=0.9),
            ],
            9: [prerequisite(3, 21, mastery=10.0, path_quality=0.1)],
        },
    }
    counted = []

    async def fake_count(db, *, knowledge_point_id, subject_id):
        counted.append((knowledge_point_id, subject_id))
        return 3 if knowledge_point_id == 42 else 0

    monkeypatch.setattr(hub, "_count_trainable_kp_questions", fake_count)
    payload = await hub._pick_path_prerequisite(db, 7, [3])
    # Blockers sort by mastery asc, then path quality desc, then id asc.
    assert counted == [(42, 3)]
    assert payload == {
        "target_knowledge_point_id": 2,
        "target_knowledge_point_name": "目标章节",
        "knowledge_point_id": 42,
        "knowledge_point_name": "知识点42",
        "subject_id": 3,
        "subject_code": "data_structure",
        "subject_name": "数据结构",
        "mastery_score": 20.0,
        "available_question_count": 3,
    }
    assert graph.calls == [(7, [2, 9], [3])]


@pytest.mark.asyncio
async def test_path_prerequisite_breaks_blocker_count_ties_by_smaller_target_id(
    monkeypatch, graph
):
    db = FakeDb(
        [
            [(7,), (4,)],
            [SimpleNamespace(id=3, code="data_structure", name="数据结构")],
        ]
    )
    graph.context = {
        "blocked_targets": {
            7: [prerequisite(3, 71, mastery=40.0)],
            4: [prerequisite(3, 41, mastery=30.0)],
        },
    }

    async def fake_count(db, *, knowledge_point_id, subject_id):
        return 5

    monkeypatch.setattr(hub, "_count_trainable_kp_questions", fake_count)
    payload = await hub._pick_path_prerequisite(db, 7, [3])
    assert payload["target_knowledge_point_id"] == 4
    assert payload["knowledge_point_id"] == 41
    assert payload["available_question_count"] == 5
    assert payload["mastery_score"] == 30.0


@pytest.mark.asyncio
async def test_path_prerequisite_prefers_the_lowest_mastery_blocker(monkeypatch, graph):
    db = FakeDb(
        [
            [(2,), (9,)],
            [SimpleNamespace(id=3, code="data_structure", name="数据结构")],
        ]
    )
    graph.context = {
        "blocked_targets": {
            2: [
                prerequisite(3, 42, mastery=25.0, path_quality=0.9),
                prerequisite(3, 41, mastery=15.0, path_quality=0.1),
            ],
            9: [prerequisite(3, 21, mastery=5.0, path_quality=0.1)],
        },
    }

    async def fake_count(db, *, knowledge_point_id, subject_id):
        return 4

    monkeypatch.setattr(hub, "_count_trainable_kp_questions", fake_count)
    payload = await hub._pick_path_prerequisite(db, 7, [3])
    # Target 2 owns two blockers, so it is ranked first; blockers sort by mastery asc.
    assert graph.calls == [(7, [2, 9], [3])]
    assert payload["target_knowledge_point_id"] == 2
    assert payload["knowledge_point_id"] == 41
    assert payload["mastery_score"] == 15.0


@pytest.mark.asyncio
async def test_path_prerequisite_returns_none_when_no_candidate_is_trainable(
    monkeypatch, graph
):
    db = FakeDb([[(4,)]])
    graph.context = {
        "blocked_targets": {4: [prerequisite(3, 21), prerequisite(3, 22)]},
    }

    async def fake_count(db, *, knowledge_point_id, subject_id):
        return 2

    monkeypatch.setattr(hub, "_count_trainable_kp_questions", fake_count)
    assert await hub._pick_path_prerequisite(db, 7, [3]) is None
    # No trainable prerequisite reaches the subject lookup.
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_path_prerequisite_returns_none_when_subject_row_is_missing(
    monkeypatch, graph
):
    db = FakeDb(
        [
            [(4,)],
            [],
        ]
    )
    graph.context = {
        "blocked_targets": {4: [prerequisite(3, 21)]},
    }

    async def fake_count(db, *, knowledge_point_id, subject_id):
        return 3

    monkeypatch.setattr(hub, "_count_trainable_kp_questions", fake_count)
    assert await hub._pick_path_prerequisite(db, 7, [3]) is None
    assert len(db.statements) == 2
