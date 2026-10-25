"""Compatibility baseline for AI study-advice snapshot helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.advice_snapshot import (
    advice_fallback_response,
    advice_success_response,
    build_advice_snapshot,
    parse_advice_content,
)


def wrong(question_id: int, *, error_type="concept", wrong_answer="B"):
    return SimpleNamespace(
        question_id=question_id,
        error_type=error_type,
        wrong_answer=wrong_answer,
    )


def question(question_id: int, subject_id: int, answer="A"):
    return SimpleNamespace(id=question_id, subject_id=subject_id, answer=answer)


class Rows:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


@pytest.mark.asyncio
async def test_snapshot_joins_wrong_questions_questions_and_kps():
    questions = [question(7, 2), question(8, 3)]

    class Db:
        async def execute(self, _query):
            return Rows(questions)

    async def load_kps(_db, ids):
        assert ids == [7, 8, 99]
        return {7: ["栈"], 8: ["队列"]}

    snapshot = await build_advice_snapshot(
        Db(), [wrong(7), wrong(8), wrong(99)], load_kps=load_kps
    )

    assert snapshot["subject_stats"] == {"2": 1, "3": 1}
    assert snapshot["weak_points"] == ["栈", "队列"]
    assert snapshot["recent_wrong"] == [
        {
            "subject_id": 2,
            "error_type": "concept",
            "wrong_answer": "B",
            "correct_answer": "A",
        },
        {
            "subject_id": 3,
            "error_type": "concept",
            "wrong_answer": "B",
            "correct_answer": "A",
        },
    ]


def test_parse_advice_content_preserves_historical_fallback():
    assert parse_advice_content('{"overall_assessment":"ok"}') == {
        "overall_assessment": "ok"
    }
    assert parse_advice_content("plain advice") == {
        "overall_assessment": "plain advice"
    }
    assert parse_advice_content('["array"]') == {
        "overall_assessment": '["array"]'
    }


def test_advice_response_shapes():
    fallback = advice_fallback_response({"overall_assessment": "fallback"})
    assert fallback == {
        "content": {"overall_assessment": "fallback"},
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "fallback",
        "duration_ms": 0,
    }
    success = advice_success_response(
        {"overall_assessment": "ok"},
        {"tokens_used": 12, "model": "model", "duration_ms": 34},
    )
    assert success["from_fallback"] is False
    assert success["tokens_used"] == 12
