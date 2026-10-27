"""Issuance wire bytes and revision-read sequencing before extraction."""

import base64
import hashlib
import hmac
import inspect
import json
from types import SimpleNamespace

import pytest

from tests.practice.batch_token_contract_support import NOW

pytest_plugins = ("tests.practice.batch_token_contract_support",)


def issue(module, **overrides):
    values = dict(
        user_id=7,
        subject_id=3,
        mode="random",
        questions=[SimpleNamespace(id=2), SimpleNamespace(id=1)],
        revision_ids={2: 202, 1: 101},
        submission_request_id=" submit-1 ",
    )
    values.update(overrides)
    return module.create_practice_batch_token(**values)


def test_fixed_wire_bytes_contexts_and_live_signing_ports(token_module, monkeypatch):
    monkeypatch.setattr(
        token_module, "settings", SimpleNamespace(APP_SECRET="token-contract-key")
    )
    monkeypatch.setattr(token_module.time, "time", lambda: NOW)
    knowledge = {"root": 8}
    entry = {"source": "practice"}
    token, revisions, request_id = issue(
        token_module,
        recommendation_request_id=" rec-1 ",
        knowledge_context=knowledge,
        entry_context=entry,
        sequential_reservation_request_id=42,
    )
    expected = {
        "v": 2,
        "uid": 7,
        "rid": "submit-1",
        "rec_rid": "rec-1",
        "sid": 3,
        "mode": "random",
        "iat": NOW,
        "exp": NOW + 86400,
        "questions": [[2, 202], [1, 101]],
        "knowledge_context": knowledge,
        "entry_context": entry,
        "seq_reservation_request_id": "42",
    }
    body = (
        base64.urlsafe_b64encode(
            json.dumps(
                expected,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    key = hmac.new(
        b"token-contract-key", b"memograd:practice-batch:v2", hashlib.sha256
    ).digest()
    signature = base64.urlsafe_b64encode(
        hmac.new(key, body.encode(), hashlib.sha256).digest()
    )
    assert token == body + "." + signature.decode().rstrip("=")
    assert revisions == {2: 202, 1: 101} and list(revisions) == [2, 1]
    assert request_id == "submit-1"
    assert token_module._decode_practice_batch_token(token) == expected


@pytest.mark.parametrize("questions", [None, [], ()])
def test_empty_batch_short_circuits_all_later_ports(
    token_module, monkeypatch, questions
):
    def fail():
        raise AssertionError("clock must not be read")

    monkeypatch.setattr(token_module.time, "time", fail)
    assert issue(token_module, questions=questions, mode="invalid") == (None, {}, None)


def test_issue_mode_precedes_question_read(token_module):
    class Question:
        @property
        def id(self):
            raise AssertionError("question must not be read")

    with pytest.raises(token_module.PracticeBatchTokenError, match="^练习模式无效$"):
        issue(token_module, mode="invalid", questions=[Question()])


@pytest.mark.parametrize("revision", [None, 0, "", False])
def test_missing_revision_keeps_second_id_read_in_error(token_module, revision):
    reads = []

    class Question:
        @property
        def id(self):
            reads.append("id")
            return 2

    with pytest.raises(RuntimeError, match="题目 2 缺少可用 question_version"):
        issue(token_module, questions=[Question()], revision_ids={2: revision})
    assert reads == ["id", "id"]


def test_duplicate_precedes_second_revision_lookup_and_clock(token_module, monkeypatch):
    reads = []

    class Revisions(dict):
        def get(self, key):
            reads.append(key)
            return 202

    def fail():
        raise AssertionError("late clock")

    monkeypatch.setattr(token_module.time, "time", fail)
    with pytest.raises(token_module.PracticeBatchTokenError, match="重复题目"):
        issue(
            token_module,
            questions=[SimpleNamespace(id="2"), SimpleNamespace(id=2)],
            revision_ids=Revisions(),
        )
    assert reads == [2]


def test_success_reads_ids_twice_and_does_not_mutate_input(token_module, monkeypatch):
    reads = []

    class Question:
        @property
        def id(self):
            reads.append("id")
            return 2

    monkeypatch.setattr(token_module.time, "time", lambda: reads.append("clock") or NOW)
    source = {2: "202"}
    token, revisions, _ = issue(
        token_module, questions=[Question()], revision_ids=source
    )
    assert reads == ["id", "clock", "id", "id"]
    assert revisions == {2: 202} and source == {2: "202"}
    assert token


@pytest.mark.parametrize("value", [" ", "x" * 129])
def test_invalid_submission_id_keeps_error(token_module, value):
    with pytest.raises(token_module.PracticeBatchTokenError, match="request_id 无效"):
        issue(token_module, submission_request_id=value)


def test_generated_request_id_uses_live_uuid_and_ttl(token_module, monkeypatch):
    monkeypatch.setattr(token_module, "uuid4", lambda: SimpleNamespace(hex="fixed"))
    monkeypatch.setattr(token_module.time, "time", lambda: NOW)
    monkeypatch.setattr(token_module, "PRACTICE_BATCH_TOKEN_TTL_SEC", 13)
    token, _, request_id = issue(token_module, submission_request_id=None)
    assert request_id == "practice_fixed"
    assert token_module._decode_practice_batch_token(token)["exp"] == NOW + 13


def test_revision_conversion_error_is_not_wrapped(token_module):
    error = OverflowError("revision sentinel")

    class Revision:
        def __int__(self):
            raise error

    with pytest.raises(OverflowError) as caught:
        issue(token_module, revision_ids={2: Revision()})
    assert caught.value is error


def test_public_signatures_and_keyword_only_arguments(token_module):
    signature = inspect.signature(token_module.create_practice_batch_token)
    assert list(signature.parameters) == [
        "user_id",
        "subject_id",
        "mode",
        "questions",
        "revision_ids",
        "recommendation_request_id",
        "knowledge_context",
        "entry_context",
        "sequential_reservation_request_id",
        "submission_request_id",
    ]
    assert all(p.kind == p.KEYWORD_ONLY for p in signature.parameters.values())
    signature = inspect.signature(token_module._validate_practice_batch_token)
    assert list(signature.parameters) == [
        "token",
        "user_id",
        "question_ids",
        "session_meta",
        "answers",
    ]
    assert signature.parameters["token"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        p.kind == p.KEYWORD_ONLY for p in list(signature.parameters.values())[1:]
    )
