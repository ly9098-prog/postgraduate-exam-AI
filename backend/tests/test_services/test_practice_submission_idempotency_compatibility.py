"""Compatibility baseline for practice submission idempotency rules."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.practice_service import (
    PracticeSubmissionConflictError,
    _is_unique_violation,
    _replay_committed_submission,
)
from app.services.practice_service import (
    _practice_submission_fingerprint as fingerprint,
)


def _session_meta(**overrides) -> dict:
    payload = {
        "request_id": "practice_idempotency",
        "subject_id": 7,
        "mode": "random",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:01:00+00:00",
        "duration_sec": 60,
        "question_count": 2,
        "answered_count": 1,
    }
    payload.update(overrides)
    return payload


def _answers(**overrides) -> list[dict]:
    answer = {
        "question_id": 2,
        "user_answer": "A",
        "used_time": 10,
        "request_id": None,
    }
    answer.update(overrides)
    return [answer]


def _fingerprint(**overrides) -> str:
    values = {
        "answers": _answers(),
        "skipped_question_ids": [1],
        "session_meta": _session_meta(),
        "batch_token": "signed-token",
    }
    values.update(overrides)
    return fingerprint(**values)


class TestPracticeSubmissionFingerprint:
    def test_same_semantic_submission_is_stable(self):
        assert _fingerprint() == _fingerprint()

    def test_answer_order_and_alias_do_not_change_semantics(self):
        reordered = [
            {"answer": " A ", "used_time": 10.0, "request_id": "", "question_id": 2}
        ]

        assert _fingerprint(answers=reordered) == _fingerprint()

    def test_answer_semantics_change_hash(self):
        assert _fingerprint(answers=_answers(user_answer="B")) != _fingerprint()
        assert _fingerprint(answers=_answers(used_time=11)) != _fingerprint()
        assert _fingerprint(answers=_answers(question_id=3)) != _fingerprint()

    def test_skipped_order_is_normalized(self):
        assert _fingerprint(skipped_question_ids=[3, 1]) == _fingerprint(
            skipped_question_ids=[1, 3]
        )
        assert _fingerprint(skipped_question_ids=[1, 3]) != _fingerprint()

    def test_session_and_token_semantics_change_hash(self):
        assert _fingerprint(session_meta=_session_meta(mode="smart")) != _fingerprint()
        assert (
            _fingerprint(session_meta=_session_meta(duration_sec=61)) != _fingerprint()
        )
        assert _fingerprint(batch_token="other-token") != _fingerprint()


class TestUniqueViolationDetection:
    def _error(self, original, *, code=None) -> IntegrityError:
        if code is not None:
            original.sqlstate = code
        return IntegrityError("statement", {}, original)

    def test_postgresql_unique_code_is_recognized(self):
        assert _is_unique_violation(self._error(Exception(), code="23505")) is True

    @pytest.mark.parametrize(
        "message",
        [
            "UNIQUE constraint failed: practice_sessions.user_id",
            "duplicate key value violates unique constraint",
        ],
    )
    def test_driver_messages_are_recognized(self, message):
        assert _is_unique_violation(self._error(Exception(message))) is True

    def test_other_integrity_errors_are_not_treated_as_idempotency(self):
        assert (
            _is_unique_violation(self._error(Exception("foreign key violation")))
            is False
        )
        assert _is_unique_violation(IntegrityError("statement", {}, None)) is False


class TestReplayCommittedSubmission:
    def test_matching_hash_replays_canonical_response_copy(self):
        response = {"results": [], "total_correct": 0}
        existing = SimpleNamespace(
            submission_payload_hash=_fingerprint(),
            submission_response=response,
        )

        replayed = _replay_committed_submission(existing, _fingerprint())

        assert replayed == response
        assert replayed is not response

    def test_different_payload_hash_conflicts(self):
        existing = SimpleNamespace(
            submission_payload_hash=_fingerprint(),
            submission_response={"results": []},
        )

        with pytest.raises(PracticeSubmissionConflictError, match="另一组提交"):
            _replay_committed_submission(existing, "different-hash")

    def test_missing_canonical_response_conflicts(self):
        existing = SimpleNamespace(
            submission_payload_hash=_fingerprint(),
            submission_response=None,
        )

        with pytest.raises(PracticeSubmissionConflictError, match="不可恢复"):
            _replay_committed_submission(existing, _fingerprint())
