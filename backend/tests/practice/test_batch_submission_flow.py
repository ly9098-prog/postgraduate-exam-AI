"""Contracts for signed practice-batch submission orchestration."""

from __future__ import annotations

import logging

import pytest

from app.services.practice.batch_submission_flow import (
    BatchSubmissionFlowRequest,
    _validate_protocol,
    _validate_scope_subject,
    submit_practice_batch,
)
from app.services.practice.batch_token import PracticeBatchTokenError


def request(**overrides):
    values = dict(
        db=None,
        user_id=2,
        answers=[{"question_id": 1, "user_answer": "A"}],
        session_meta={
            "request_id": "request",
            "subject_id": 3,
            "mode": "random",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:01:00Z",
            "duration_sec": 60,
            "question_count": 1,
            "answered_count": 1,
        },
        skipped_question_ids=[],
        batch_token="token",
        logger=logging.getLogger("test-batch-flow"),
        replay=lambda *_args: pytest.fail("replay must not run"),
        start_transaction=None,
        is_unique_violation=None,
        create_outbox=None,
    )
    values.update(overrides)
    return BatchSubmissionFlowRequest(**values)


def test_protocol_preserves_rejection_and_fingerprint_order():
    item = request()
    protocol = _validate_protocol(item)
    assert protocol.request_id == "request"
    assert protocol.skipped_ids == []
    assert protocol.all_question_ids == [1]
    assert len(protocol.payload_hash) == 64

    with pytest.raises(PracticeBatchTokenError, match="batch_token"):
        _validate_protocol(request(batch_token=""))
    with pytest.raises(PracticeBatchTokenError, match="skipped_question_ids"):
        _validate_protocol(request(skipped_question_ids=None))
    with pytest.raises(ValueError, match="request_id"):
        _validate_protocol(
            request(
                session_meta={
                    **request().session_meta,
                    "request_id": "",
                }
            )
        )


def test_scope_subject_conflict_uses_signed_batch_error():
    with pytest.raises(PracticeBatchTokenError, match="知识练习范围"):
        _validate_scope_subject({"subject_id": 4}, {"subject_id": 3})
    _validate_scope_subject({"subject_id": 3}, {"subject_id": 3})
    _validate_scope_subject(None, {"subject_id": 3})


@pytest.mark.asyncio
async def test_committed_replay_precedes_token_validation(monkeypatch):
    item = request()

    async def load_replay(_db, **_kwargs):
        return {"replayed": True}

    monkeypatch.setattr(
        "app.services.practice.batch_submission_flow.load_committed_replay",
        load_replay,
    )
    monkeypatch.setattr(
        "app.services.practice.batch_submission_flow._validate_practice_batch_token",
        lambda *_args, **_kwargs: pytest.fail("token must not gate replay"),
    )

    assert await submit_practice_batch(item) == {"replayed": True}
