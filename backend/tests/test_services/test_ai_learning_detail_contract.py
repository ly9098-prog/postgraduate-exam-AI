"""Contracts for AI learning explain, mistake analysis, and recommendations."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import ai_learning_service as service


class Ports:
    def __init__(self):
        self.calls = []
        self.statements = []
        self.question = SimpleNamespace(
            id=11,
            subject_id=3,
            difficulty=2,
            content={"text": "源题"},
            options={"A": "a"},
            answer="A",
            analysis="解析",
        )
        self.answered_rows = []
        self.candidates = []
        self.subject_rows = []
        self.kp_rows = []
        self.kp_map = {}
        self.vector_result = {"enabled": False, "recommendations": []}
        self.vector_error = None
        self.token_limit = True
        self.ai_result = None
        self.fallback_explain = {"explanation": "讲解回退"}
        self.fallback_mistake = {
            "error_type": "fallback",
            "error_type_label": "回退",
            "analysis": "错因回退",
            "suggestion": "建议回退",
        }


class FakeResult:
    def __init__(self, rows=None, scalars=None):
        self._rows = rows or []
        self._scalars = scalars or []

    def all(self):
        return list(self._rows)

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def scalar_one_or_none(self):
        return self._scalars[0] if self._scalars else None


class FakeDb:
    def __init__(self, ports):
        self.ports = ports

    async def execute(self, statement):
        self.ports.statements.append(statement)
        index = len(self.ports.statements)
        text = str(statement)
        if "admin_ai_configs" in str(statement):
            return FakeResult()
        if "admin_ai_model_configs" in text:
            return FakeResult()
        if "questions.id = :" in text:
            return FakeResult(scalars=[self.ports.question])
        if "practice_records" in text:
            return FakeResult(rows=self.ports.answered_rows)
        if "questions.subject_id IN" in text:
            return FakeResult(scalars=self.ports.candidates)
        if "FROM subjects" in text:
            return FakeResult(rows=self.ports.subject_rows)
        if "knowledge_points" in text:
            return FakeResult(rows=self.ports.kp_rows)
        if index == 1:
            return FakeResult(scalars=[self.ports.question])
        if index == 2:
            return FakeResult(rows=self.ports.answered_rows)
        if index == 3:
            return FakeResult(scalars=self.ports.candidates)
        return FakeResult(rows=self.ports.subject_rows)

    async def get(self, model, subject_id):
        return SimpleNamespace(id=subject_id, parent_id=None)


def question(question_id, difficulty, subject_ref=None, content=None):
    return SimpleNamespace(
        id=question_id,
        subject_id=3,
        difficulty=difficulty,
        content=content if content is not None else {"text": f"题{question_id}"},
        question_type="single_choice",
        subject_ref=subject_ref,
    )


@pytest.fixture
def ports(monkeypatch):
    ports = Ports()

    async def fake_load_question_kps(db, question_ids):
        ports.calls.append(("load_question_kps", tuple(question_ids)))
        return ports.kp_map

    async def fake_check_token_limit(db, user_id, tokens_needed=0):
        ports.calls.append(("check_token_limit", user_id, tokens_needed))
        return ports.token_limit

    async def fake_call_ai(messages, db=None):
        ports.calls.append(("_call_ai", messages))
        return ports.ai_result

    async def fake_record_token_usage(*args):
        ports.calls.append(("record_token_usage", args[1], args[2]))

    async def fake_vector(db, **kwargs):
        ports.calls.append(("vector", kwargs))
        if ports.vector_error is not None:
            raise ports.vector_error
        return ports.vector_result

    async def fake_resolve_subject_ids(db, subject_id, include_descendants=True):
        ports.calls.append(("resolve_subject_ids", subject_id))
        return [subject_id]

    def fake_get_fallback_explain():
        return ports.fallback_explain

    def fake_get_fallback_mistake():
        return ports.fallback_mistake

    monkeypatch.setattr(service, "load_question_kps", fake_load_question_kps)
    monkeypatch.setattr(service, "check_token_limit", fake_check_token_limit)
    monkeypatch.setattr(service, "_call_ai", fake_call_ai)
    monkeypatch.setattr(service, "record_token_usage", fake_record_token_usage)
    monkeypatch.setattr(service, "get_fallback_explain", fake_get_fallback_explain)
    monkeypatch.setattr(
        service, "get_fallback_mistake_analysis", fake_get_fallback_mistake
    )
    monkeypatch.setattr(
        service, "resolve_subject_ids", fake_resolve_subject_ids, raising=False
    )

    import app.services.vector_retrieval_service as vector_service

    monkeypatch.setattr(
        vector_service, "search_similar_questions", fake_vector, raising=False
    )
    return ports


@pytest.mark.asyncio
async def test_explain_success_preserves_prompt_usage_and_payload(ports):
    db = FakeDb(ports)
    ports.ai_result = {
        "content": '{"explanation":"讲解","solution_steps":["步骤"],"key_knowledge_points":["知识点"],"common_mistakes":["错误"]}',
        "tokens_used": 123,
    }
    ports.kp_map = {11: ["知识点"]}

    result = await service.ai_explain(
        db,
        user_id=7,
        question_id=11,
        user_answer="B",
        is_correct=False,
        focus="mistake",
    )

    assert result == {
        "question_id": 11,
        "explanation": "讲解",
        "solution_steps": ["步骤"],
        "key_knowledge_points": ["知识点"],
        "common_mistakes": ["错误"],
        "tokens_used": 123,
        "from_fallback": False,
    }
    assert ports.calls == [
        ("load_question_kps", (11,)),
        ("check_token_limit", 7, 500),
        ("_call_ai", ports.calls[2][1]),
        ("record_token_usage", 7, "ai_explain"),
    ]
    assert "题目：源题" in ports.calls[2][1][1]["content"]


@pytest.mark.asyncio
async def test_explain_limit_and_fallback_keep_knowledge_points(ports):
    db = FakeDb(ports)
    ports.kp_map = {11: ["知识点"]}
    ports.token_limit = False
    ports.statements.clear()

    limited = await service.ai_explain(db, user_id=7, question_id=11)

    assert limited == {
        "question_id": 11,
        "explanation": "今日 AI 调用额度已用尽，请明天再试。",
        "solution_steps": [],
        "key_knowledge_points": ["知识点"],
        "common_mistakes": [],
        "tokens_used": 0,
        "from_fallback": True,
    }

    ports.token_limit = True
    ports.statements.clear()
    fallback = await service.ai_explain(db=FakeDb(ports), user_id=7, question_id=11)
    assert fallback["explanation"] == "讲解回退"
    assert fallback["key_knowledge_points"] == ["知识点"]
    assert fallback["from_fallback"] is True


@pytest.mark.asyncio
async def test_mistake_analysis_success_and_limit_copy(ports):
    db = FakeDb(ports)
    ports.ai_result = {
        "content": '{"error_type":"concept_misunderstanding","analysis":"错因","suggestion":"建议"}',
        "tokens_used": 88,
    }

    result = await service.ai_analyze_mistake(
        db, user_id=7, question_id=11, user_answer="B", correct_answer="A"
    )

    assert result == {
        "error_type": "concept_misunderstanding",
        "error_type_label": "概念理解错误",
        "analysis": "错因",
        "suggestion": "建议",
        "tokens_used": 88,
        "from_fallback": False,
    }
    assert ports.calls == [
        ("check_token_limit", 7, 300),
        ("_call_ai", ports.calls[1][1]),
        ("record_token_usage", 7, "mistake_analysis"),
    ]
    assert "题目：源题" in ports.calls[1][1][1]["content"]

    ports.token_limit = False
    ports.statements.clear()
    limited = await service.ai_analyze_mistake(
        db, user_id=7, question_id=11, user_answer="B", correct_answer="A"
    )
    assert limited == {
        "error_type": "limit_exceeded",
        "error_type_label": "额度用尽",
        "analysis": "今日 AI 调用额度已用尽，请明天再试。",
        "suggestion": "建议自行查看题目解析。",
        "tokens_used": 0,
        "from_fallback": True,
    }


@pytest.mark.asyncio
async def test_vector_recommendation_envelope_is_returned_without_rule_queries(ports):
    db = FakeDb(ports)
    ports.vector_result = {
        "enabled": True,
        "recommendations": [{"question_id": 22}],
    }

    result = await service.recommend_similar_questions(
        db, user_id=7, question_id=11, count=3
    )

    assert result == {
        "source_question_id": 11,
        "recommendations": [{"question_id": 22}],
        "strategy": "vector_plus_rule",
        "tokens_used": 0,
    }
    assert ports.calls == [
        (
            "vector",
            {
                "user_id": 7,
                "question_id": 11,
                "count": 3,
                "exclude_answered": True,
            },
        )
    ]
    assert not ports.statements


@pytest.mark.asyncio
async def test_vector_error_falls_back_to_rule_recommendation(ports, caplog):
    db = FakeDb(ports)
    ports.vector_error = RuntimeError("vector unavailable")
    ports.candidates = [
        question(22, 2, subject_ref=SimpleNamespace(code="408", name="计算机")),
        question(23, 3),
        question(24, 2),
    ]
    ports.kp_map = {
        11: ["A"],
        22: ["A"],
        23: ["A"],
        24: ["B"],
    }

    with caplog.at_level("WARNING", logger="app.services.ai_learning_service"):
        result = await service.recommend_similar_questions(
            db, user_id=7, question_id=11, count=2
        )

    assert result["strategy"] == "rule_based"
    assert result["source_question_id"] == 11
    assert result["tokens_used"] == 0
    assert {item["question_id"] for item in result["recommendations"]} == {22, 23}
    assert {item["stem"] for item in result["recommendations"]} == {"题22", "题23"}
    assert "向量推荐异常，回退到规则推荐" in caplog.text


@pytest.mark.asyncio
async def test_rule_recommendation_queries_and_scoring(ports):
    db = FakeDb(ports)
    ports.candidates = [
        question(22, 2),
        question(23, 3),
        question(24, 3),
    ]
    ports.kp_map = {
        11: ["A"],
        22: ["A"],
        23: ["A"],
        24: ["C"],
    }

    result = await service.recommend_similar_questions(
        db, user_id=7, question_id=11, count=2
    )

    assert {item["question_id"] for item in result["recommendations"]} == {22, 23}
    assert {item["match_reason"] for item in result["recommendations"]} == {
        "同知识点 + 同难度",
        "同知识点",
    }


@pytest.mark.asyncio
async def test_rule_recommendation_scores_filters_and_projects(ports):
    db = FakeDb(ports)
    ports.candidates = [
        question(22, 2),
        question(23, 3),
        question(24, 3),
        question(25, 2),
    ]
    ports.kp_map = {
        11: ["A"],
        22: ["A", "B"],
        23: ["A"],
        24: ["C"],
        25: ["A"],
    }

    result = await service.recommend_similar_questions(
        db, user_id=7, question_id=11, count=2
    )

    assert {item["question_id"] for item in result["recommendations"]} == {22, 25}
    assert all(
        item["match_reason"] == "同知识点 + 同难度"
        for item in result["recommendations"]
    )


def test_same_subject_reason_remains_available(ports):
    candidate = question(23, 3)

    payload = service._similar_recommendation_payload(candidate, ["C"], {"A"}, 2)

    assert payload["match_reason"] == "同科目"
    assert payload["knowledge_points"] == ["C"]
