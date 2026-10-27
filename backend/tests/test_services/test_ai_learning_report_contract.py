"""Contracts for AI learning report generation and its rule-based degradations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import ai_learning_service as service

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


class Ports:
    def __init__(self):
        self.rows: list = []
        self.kp_map: dict = {}
        self.subject = SimpleNamespace(code="408", name="计算机学科专业基础综合")
        self.token_limit = True
        self.ai_result = None
        self.fallback_report = {
            "weak_points": [
                {"knowledge_point": "回退弱项", "accuracy": 0.1, "suggestion": "回顾"}
            ],
            "strong_points": [
                {"knowledge_point": "回退强项", "accuracy": 0.9, "suggestion": "保持"}
            ],
            "learning_suggestions": ["回退建议"],
        }
        self.calls: list[tuple] = []
        self.statements: list = []
        self.executed: list = []
        self.prompt_args = None
        self.token_usage_args = None


class FakeDb:
    def __init__(self, ports):
        self.ports = ports

    async def get(self, model, subject_id):
        self.ports.calls.append(("db.get", subject_id))
        return self.ports.subject

    async def execute(self, statement):
        self.ports.statements.append(statement)
        self.ports.calls.append(("db.execute", len(self.ports.statements)))
        if len(self.ports.statements) == 1:
            return SimpleNamespace(all=lambda: list(self.ports.rows))
        return SimpleNamespace(all=lambda: [])


@pytest.fixture
def ports(monkeypatch):
    ports = Ports()
    monkeypatch.setattr(service, "utcnow", lambda: NOW)

    async def fake_load_question_kps(db, qids):
        ports.calls.append(("load_question_kps", tuple(sorted(qids))))
        return ports.kp_map

    async def fake_check_token_limit(db, user_id, tokens_needed=0):
        ports.calls.append(("check_token_limit", user_id, tokens_needed))
        return ports.token_limit

    async def fake_call_ai(messages, db=None):
        ports.calls.append(("_call_ai", messages))
        return ports.ai_result

    async def fake_record_token_usage(
        db, user_id, session_type, user_message, ai_response, result
    ):
        ports.token_usage_args = (
            db,
            user_id,
            session_type,
            user_message,
            ai_response,
            result,
        )

    def fake_build_report_prompt(subject_code, days, total, accuracy, kp_list):
        ports.prompt_args = (subject_code, days, total, accuracy, kp_list)
        return ["report-prompt"]

    def fake_get_fallback_report():
        ports.calls.append(("get_fallback_report",))
        return ports.fallback_report

    monkeypatch.setattr(service, "load_question_kps", fake_load_question_kps)
    monkeypatch.setattr(service, "check_token_limit", fake_check_token_limit)
    monkeypatch.setattr(service, "_call_ai", fake_call_ai)
    monkeypatch.setattr(service, "record_token_usage", fake_record_token_usage)
    monkeypatch.setattr(service, "build_report_prompt", fake_build_report_prompt)
    monkeypatch.setattr(service, "get_fallback_report", fake_get_fallback_report)
    return ports


def row(question_id, is_correct):
    return SimpleNamespace(question_id=question_id, is_correct=is_correct)


@pytest.mark.asyncio
async def test_empty_records_short_circuit_without_kp_or_ai_work(ports):
    db = FakeDb(ports)
    ports.rows = []

    result = await service.generate_learning_report(db, user_id=7, subject_id=3, days=7)

    assert result == {
        "subject_id": 3,
        "subject_code": "408",
        "subject_name": "计算机学科专业基础综合",
        "period_days": 7,
        "total_answered": 0,
        "accuracy": 0.0,
        "weak_points": [],
        "strong_points": [],
        "learning_suggestions": ["暂无做题记录，建议开始练习。"],
        "tokens_used": 0,
        "from_fallback": True,
    }
    assert ports.calls == [("db.get", 3), ("db.execute", 1)]


@pytest.mark.asyncio
async def test_missing_subject_keeps_empty_subject_fields(ports):
    ports.subject = None
    db = FakeDb(ports)

    result = await service.generate_learning_report(db, user_id=7, subject_id=3)

    assert result["subject_code"] == ""
    assert result["subject_name"] == ""
    assert result["period_days"] == 7


@pytest.mark.asyncio
async def test_records_query_projects_columns_filters_and_order(ports):
    from sqlalchemy.dialects import sqlite

    db = FakeDb(ports)

    await service.generate_learning_report(db, user_id=7, subject_id=3, days=30)

    statement = ports.statements[0]
    compiled = str(statement.compile(dialect=sqlite.dialect()))
    assert "practice_records.question_id" in compiled
    assert "practice_records.is_correct" in compiled
    assert "practice_records.user_id" in compiled
    assert "practice_records.subject_id" in compiled
    assert "practice_records.answered_at >= ?" in compiled
    assert "ORDER BY practice_records.answered_at DESC" in compiled
    assert statement.compile(dialect=sqlite.dialect()).params[
        "answered_at_1"
    ] == NOW - timedelta(days=30)


@pytest.mark.asyncio
async def test_low_volume_report_uses_rule_copy_without_ai(ports):
    db = FakeDb(ports)
    ports.rows = [row(1, True), row(2, True), row(3, False), row(4, True)]
    ports.kp_map = {1: ["导数"], 2: ["导数"], 3: ["积分"], 4: ["积分"]}

    result = await service.generate_learning_report(db, user_id=7, subject_id=3, days=7)

    assert result["total_answered"] == 4
    assert result["accuracy"] == 0.75
    assert result["weak_points"] == [
        {
            "knowledge_point": "积分",
            "accuracy": 0.5,
            "suggestion": "数据不足，继续练习以获取更准确的建议",
        }
    ]
    assert result["strong_points"] == [
        {"knowledge_point": "导数", "accuracy": 1.0, "suggestion": "继续保持"}
    ]
    assert result["learning_suggestions"] == [
        "数据较少，建议积累更多练习记录后再查看 AI 报告。"
    ]
    assert result["from_fallback"] is False
    assert result["tokens_used"] == 0
    assert not [
        call for call in ports.calls if call[0] in {"_call_ai", "check_token_limit"}
    ]


@pytest.mark.asyncio
async def test_low_volume_weak_points_are_capped_at_three(ports):
    db = FakeDb(ports)
    ports.rows = [row(1, False), row(2, False), row(3, False), row(4, False)]
    ports.kp_map = {1: ["甲"], 2: ["乙"], 3: ["丙"], 4: ["丁"]}

    result = await service.generate_learning_report(db, user_id=7, subject_id=3)

    assert [point["knowledge_point"] for point in result["weak_points"]] == [
        "甲",
        "乙",
        "丙",
    ]
    assert result["strong_points"] == []


@pytest.mark.asyncio
async def test_low_volume_strong_points_are_capped_at_three(ports):
    db = FakeDb(ports)
    ports.rows = [row(1, True), row(2, True), row(3, True), row(4, True)]
    ports.kp_map = {1: ["甲"], 2: ["乙"], 3: ["丙"], 4: ["丁"]}

    result = await service.generate_learning_report(db, user_id=7, subject_id=3)

    assert result["weak_points"] == []
    assert [point["knowledge_point"] for point in result["strong_points"]] == [
        "甲",
        "乙",
        "丙",
    ]


@pytest.mark.asyncio
async def test_token_limited_quotas_cap_weak_five_and_strong_three(ports):
    db = FakeDb(ports)
    weak_rows = [row(index, False) for index in range(1, 6)]
    strong_rows = [row(index, True) for index in range(6, 10)]
    ports.rows = [*weak_rows, *strong_rows]
    ports.kp_map = {index: [f"弱点{index}"] for index in range(1, 6)}
    ports.kp_map.update({index: [f"强项{index}"] for index in range(6, 10)})
    ports.token_limit = False

    result = await service.generate_learning_report(db, user_id=7, subject_id=3)

    weak_points = result["weak_points"]
    strong_points = result["strong_points"]
    assert [point["knowledge_point"] for point in weak_points] == [
        "弱点1",
        "弱点2",
        "弱点3",
        "弱点4",
        "弱点5",
    ]
    assert [point["knowledge_point"] for point in strong_points] == [
        "强项6",
        "强项7",
        "强项8",
    ]
    assert {point["suggestion"] for point in weak_points} == {"建议重点复习该知识点"}
    assert {point["suggestion"] for point in strong_points} == {"继续保持"}


@pytest.mark.asyncio
async def test_five_records_crosses_into_ai_path(ports):
    db = FakeDb(ports)
    ports.rows = [row(index, True) for index in range(1, 6)]

    result = await service.generate_learning_report(db, user_id=7, subject_id=3)

    assert result["total_answered"] == 5
    assert ("check_token_limit", 7, 1000) in ports.calls
    assert [call[0] for call in ports.calls].count("_call_ai") == 1


@pytest.mark.asyncio
async def test_token_limit_denied_returns_rule_report(ports):
    db = FakeDb(ports)
    ports.rows = [row(1, True)] * 2 + [row(2, False)] * 4 + [row(3, True)] * 3
    ports.kp_map = {1: ["导数"], 2: ["积分"], 3: ["导数"]}
    ports.token_limit = False

    result = await service.generate_learning_report(db, user_id=7, subject_id=3, days=7)

    assert result["total_answered"] == 9
    assert result["weak_points"] == [
        {
            "knowledge_point": "积分",
            "accuracy": 0.0,
            "suggestion": "建议重点复习该知识点",
        }
    ]
    assert result["strong_points"] == [
        {"knowledge_point": "导数", "accuracy": 1.0, "suggestion": "继续保持"}
    ]
    assert result["learning_suggestions"] == [
        "薄弱知识点有 1 个，建议每天重点练习",
        "尝试做更多同类题目的变体练习",
    ]
    assert result["from_fallback"] is True
    assert not [call for call in ports.calls if call[0] == "_call_ai"]


@pytest.mark.asyncio
async def test_ai_unavailable_returns_global_fallback_report(ports):
    db = FakeDb(ports)
    ports.rows = [row(1, True)] * 6 + [row(2, False)] * 4
    ports.ai_result = None

    result = await service.generate_learning_report(db, user_id=7, subject_id=3, days=7)

    assert result["weak_points"] == ports.fallback_report["weak_points"]
    assert result["strong_points"] == ports.fallback_report["strong_points"]
    assert (
        result["learning_suggestions"] == ports.fallback_report["learning_suggestions"]
    )
    assert result["tokens_used"] == 0
    assert result["from_fallback"] is True
    assert ports.token_usage_args is None


@pytest.mark.asyncio
async def test_ai_success_projects_points_and_records_usage(ports):
    db = FakeDb(ports)
    ports.rows = [row(1, True)] * 7 + [row(2, False)] * 3
    ports.kp_map = {1: ["导数"], 2: ["积分"]}
    ports.ai_result = {
        "content": (
            '{"weak_points": [{"knowledge_point": "积分", "accuracy": 0.4}], '
            '"strong_points": [{"knowledge_point": "导数", "accuracy": 0.9, "suggestion": "保持"}], '
            '"learning_suggestions": ["巩固积分"]}'
        ),
        "tokens_used": 321,
        "model": "deepseek-chat",
        "duration_ms": 800,
    }

    result = await service.generate_learning_report(db, user_id=7, subject_id=3, days=7)

    assert result["weak_points"] == [
        {"knowledge_point": "积分", "accuracy": 0.4, "suggestion": ""}
    ]
    assert result["strong_points"] == [
        {"knowledge_point": "导数", "accuracy": 0.9, "suggestion": "保持"}
    ]
    assert result["learning_suggestions"] == ["巩固积分"]
    assert result["tokens_used"] == 321
    assert result["from_fallback"] is False
    assert ports.prompt_args[0] == "408"
    assert ports.prompt_args[1] == 7
    assert ports.prompt_args[2] == 10
    assert ports.prompt_args[3] == 0.7
    assert ports.token_usage_args[1] == 7
    assert ports.token_usage_args[2] == "learning_report"
    assert ports.token_usage_args[3] == "subject_id=3 days=7"
    assert ports.token_usage_args[4] == ports.ai_result["content"]
    assert ports.token_usage_args[5] is ports.ai_result


@pytest.mark.asyncio
async def test_unparseable_ai_content_becomes_single_suggestion(ports):
    db = FakeDb(ports)
    ports.rows = [row(1, True)] * 10
    ports.ai_result = {
        "content": "不是 JSON，只是一段建议",
        "tokens_used": 42,
        "model": "deepseek-chat",
        "duration_ms": 100,
    }

    result = await service.generate_learning_report(db, user_id=7, subject_id=3)

    assert result["weak_points"] == []
    assert result["strong_points"] == []
    assert result["learning_suggestions"] == ["不是 JSON，只是一段建议"]
    assert result["tokens_used"] == 42
    assert result["from_fallback"] is False
    assert ports.token_usage_args is not None


@pytest.mark.asyncio
async def test_knowledge_point_aggregation_orders_by_ascending_accuracy(ports):
    db = FakeDb(ports)
    ports.rows = [
        row(1, False),
        row(1, False),  # 积分 0/2
        row(2, True),
        row(2, False),  # 导数 1/2
        row(3, True),
        row(3, True),  # 树 2/2
    ]
    ports.kp_map = {1: ["积分"], 2: ["导数"], 3: ["树"]}

    ports.ai_result = {
        "content": '{"weak_points": [], "strong_points": [], "learning_suggestions": []}',
        "tokens_used": 11,
        "model": "deepseek-chat",
        "duration_ms": 50,
    }

    result = await service.generate_learning_report(db, user_id=7, subject_id=3)

    kp_call = next(call for call in ports.calls if call[0] == "load_question_kps")
    assert kp_call[1] == (1, 2, 3)
    prompt_kp_list = ports.prompt_args[4]
    assert prompt_kp_list == [
        {"knowledge_point": "积分", "accuracy": 0.0, "correct": 0, "total": 2},
        {"knowledge_point": "导数", "accuracy": 0.5, "correct": 1, "total": 2},
        {"knowledge_point": "树", "accuracy": 1.0, "correct": 2, "total": 2},
    ]
    assert ports.prompt_args[2] == 6
    assert ports.prompt_args[3] == 0.5
    assert result["weak_points"] == [] and result["strong_points"] == []
