"""Synthetic persistence ports without a provider or real user data."""

from copy import deepcopy
from types import SimpleNamespace

from app.ai import answer_grounding
from app.services.ai import analysis_persistence as persistence


class Database:
    def __init__(self, wrong, *, fail_at=None, error=None):
        self.wrong = wrong
        self.fail_at = fail_at
        self.error = error or RuntimeError("synthetic persistence failure")
        self.trace = []
        self.chats = []
        self.commits = 0
        self.on_commit = lambda count: None

    async def commit(self):
        self.commits += 1
        self.trace.append(
            ("commit", self.commits, self.wrong.ai_analysis, len(self.chats))
        )
        if self.fail_at == f"commit{self.commits}":
            raise self.error
        self.on_commit(self.commits)

    def add(self, chat):
        self.trace.append(("add", chat))
        if self.fail_at == "add":
            raise self.error
        self.chats.append(chat)


def harness(monkeypatch, **db_options):
    wrong = SimpleNamespace(ai_analysis=None)
    safe = {"mistake_diagnosis": "safe", "knowledge_patch": {"nested": []}}
    parsed = {"mistake_diagnosis": "diagnosis", "review_task": {"nested": []}}
    calls = []

    def build(grounding):
        calls.append(("safe", grounding))
        return safe

    def merge(grounding, diagnosis):
        calls.append(("merge", grounding, diagnosis))
        return "merged"

    monkeypatch.setattr(answer_grounding, "build_safe_grounded_analysis", build)
    monkeypatch.setattr(persistence, "merge_grounded_diagnosis", merge)
    args = common_arguments(wrong)
    return SimpleNamespace(
        wrong=wrong,
        safe=safe,
        parsed=parsed,
        calls=calls,
        args=args,
        db=Database(wrong, **db_options),
    )


def common_arguments(wrong):
    return {
        "wrong_question": wrong,
        "user_id": 9,
        "context": {"question": {"stem": "synthetic"}, "nested": {"items": []}},
        "result": {"content": "provider-content", "model": "provider-model"},
        "answer_grounding": {"answer": "B"},
        "visual_evidence": "evidence",
        "visual_ack_retried": True,
        "visual_ack_retry_ms": 12,
        "image_count": 2,
        "input_signature": "input-signature",
        "model_signature": "model-signature",
        "expected_answer_check": ["B"],
        "tokens_used": 31,
        "duration_ms": 51,
        "effective_force": True,
        "runtime": SimpleNamespace(provider="synthetic", model_config_id=7),
    }


async def execute(h, kind):
    if kind == "repair":
        return await persistence.persist_repaired_analysis(
            h.db, **h.args, grounding_guard_reason="mismatch", actual_answer_check=["A"]
        )
    return await persistence.persist_valid_analysis(h.db, **h.args, parsed=h.parsed)


def business_expectation(h, kind):
    payload = h.safe if kind == "repair" else h.parsed
    return deepcopy(payload), {
        key: value for key, value in payload.items() if key != "mistake_diagnosis"
    }


def assert_business_payload(payload, kind, expectation):
    expected, references = expectation
    if kind == "valid":
        expected["mistake_diagnosis"] = "merged"
    assert {key: value for key, value in payload.items() if key != "_meta"} == expected
    assert all(payload[key] is value for key, value in references.items())
